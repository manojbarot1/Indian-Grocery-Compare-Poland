"""Price audit: what the shop charges today vs what we stored.

Fetches each sampled product straight from its shop using the platform's own
endpoint — deliberately not through our adapter, so an adapter bug shows up as
a disagreement rather than being reproduced on both sides.

    docker compose exec api python verify_prices.py [per_shop] [seed]
"""

import random
import re
import sys
import time
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Offer, Shop

UA = "DesiPrice/0.1 (+https://desiprice.pl; price check; contact: hello@desiprice.pl)"
PER_SHOP = int(sys.argv[1]) if len(sys.argv) > 1 else 3
random.seed(int(sys.argv[2]) if len(sys.argv) > 2 else 42)

client = httpx.Client(timeout=30, follow_redirects=True, headers={"User-Agent": UA})


def shopify_price(shop, offer):
    """Single-product JSON, matched on the variant id we stored."""
    handle = urlparse(offer.url).path.rsplit("/", 1)[-1]
    r = client.get(f"{shop.url.rstrip('/')}/products/{handle}.json")
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    variants = r.json().get("product", {}).get("variants", [])
    for v in variants:
        if str(v.get("id")) == str(offer.external_id):
            return float(v["price"]), "variant matched"
    return (float(variants[0]["price"]), "FIRST VARIANT (id not found)") if variants else (None, "no variants")


def woo_price(shop, offer):
    ua = offer.shop.ingest_config.get("user_agent", UA)
    r = client.get(
        f"{shop.url.rstrip('/')}/wp-json/wc/store/v1/products/{offer.external_id}",
        headers={"User-Agent": ua},
    )
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    try:
        p = r.json()
    except ValueError:
        return None, "non-JSON"
    pr = p.get("prices") or {}
    if pr.get("price") in (None, ""):
        return None, "no price"
    return round(float(pr["price"]) / (10 ** int(pr.get("currency_minor_unit", 2))), 2), "store api"


PRICE_RE = re.compile(r"(\d{1,3}(?:[  ]\d{3})*(?:[.,]\d{1,2})?)\s*(?:zł|pln)", re.I)


def html_price(shop, offer):
    """Read the page and report every price-looking number, so a wrong pick is visible."""
    r = client.get(offer.url)
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}"
    soup = BeautifulSoup(r.text, "html.parser")
    # JSON-LD first: it states whether VAT is included, and these pages render
    # net and gross side by side so a CSS guess can silently pick the wrong one.
    for script in soup.find_all("script", type="application/ld+json"):
        m = re.search(r'"price"\s*:\s*"?([\d.]+)"?', script.string or "")
        if m:
            return float(m.group(1)), "json-ld (gross)"
    sels = (shop.ingest_config.get("selectors") or {}).get("price", [])
    for sel in sels:
        node = soup.select_one(sel)
        if node:
            m = PRICE_RE.search(node.get_text(" ", strip=True)) or re.search(
                r"(\d+(?:[.,]\d{1,2})?)", node.get_text(" ", strip=True)
            )
            if m:
                return float(m.group(1).replace(",", ".").replace(" ", "")), f"selector {sel}"
    # JSON-LD fallback (Shoper splits it across fragments)
    for script in soup.find_all("script", type="application/ld+json"):
        m = re.search(r'"price"\s*:\s*"?([\d.]+)"?', script.string or "")
        if m:
            return float(m.group(1)), "json-ld"
    return None, "not found"


FETCH = {"shopify": shopify_price, "woocommerce": woo_price, "html": html_price}

with SessionLocal() as s:
    shops = {sh.id: sh for sh in s.scalars(select(Shop).where(Shop.active.is_(True)))}
    sample = []
    for sid, sh in shops.items():
        offers = list(
            s.scalars(
                select(Offer).where(Offer.shop_id == sid, Offer.price_pln > 0).limit(400)
            )
        )
        sample += random.sample(offers, min(PER_SHOP, len(offers)))
    # detach what we need before the session closes
    rows = [
        (shops[o.shop_id], o.id, o.external_id, o.url, o.price, o.price_pln, o.currency, o.title)
        for o in sample
    ]

print(f"checking {len(rows)} offers across {len(shops)} shops\n")
print(f"{'SHOP':<20}{'STORED':>9}{'LIVE':>9}  {'VERDICT':<10} PRODUCT")
print("-" * 104)

ok = drift = bad = err = 0
problems = []

for shop, oid, ext, url, price, price_pln, cur, title in rows:
    fn = FETCH.get(shop.platform)
    try:
        live, how = fn(shop, type("O", (), {"external_id": ext, "url": url, "shop": shop})())
    except Exception as exc:
        live, how = None, f"{type(exc).__name__}"
    time.sleep(1.0)

    if live is None:
        verdict, err = "UNREACHABLE", err + 1
        problems.append((shop.name, title, price, live, how, url))
    elif abs(live - price) < 0.011:
        verdict, ok = "match", ok + 1
    elif abs(live - price) / max(live, price) <= 0.35:
        verdict, drift = "changed", drift + 1
        problems.append((shop.name, title, price, live, how, url))
    else:
        verdict, bad = "** CHECK **", bad + 1
        problems.append((shop.name, title, price, live, how, url))

    print(f"{shop.name:<20}{price:>9.2f}{(live if live is not None else float('nan')):>9.2f}  {verdict:<10} {title[:44]}")

total = len(rows)
print("\n" + "=" * 60)
print(f"exact match      {ok}/{total}")
print(f"price changed    {drift}/{total}   (catalogue is 6 days old)")
print(f"needs checking   {bad}/{total}")
print(f"unreachable      {err}/{total}")

if problems:
    print("\nDETAIL")
    for name, title, stored, live, how, url in problems:
        shown = f"{live:.2f}" if live is not None else "—"
        print(f"  [{name}] {title[:56]}")
        print(f"      stored {stored:.2f}  live {shown}  ({how})")
        print(f"      {url[:96]}")
