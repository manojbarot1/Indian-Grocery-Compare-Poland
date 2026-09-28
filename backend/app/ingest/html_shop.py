"""Generic sitemap + HTML adapter for shops with no catalogue API.

Most Indian grocers in Poland do not run Shopify or WooCommerce. They run
SOTESHOP, Shoper, or a bespoke Laravel storefront, and none of those expose a
public product feed. But nearly all of them publish a sitemap, because they want
Google to index them.

So: read the sitemap, filter to product URLs, and parse each page. Extraction
tries schema.org JSON-LD first — many platforms emit it for Google Shopping and
it is far more stable than CSS — then falls back to per-shop selectors declared
in shops.yaml. That keeps a new shop a config change rather than a new module.

This is inherently more fragile than a JSON API and much slower (one request per
product), so it is the fallback, not the default. Shops are polled politely and
a failed page is skipped rather than failing the whole run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import Adapter, RawOffer

log = logging.getLogger(__name__)

# "12.00zł", "12,00 zł", "1 234,56 PLN"
PRICE_RE = re.compile(r"(\d{1,3}(?:[  ]\d{3})*(?:[.,]\d{1,2})?)\s*(?:zł|pln)", re.I)

# Pack size written in a URL slug, e.g. ".../trs-coarse-semolina-500g-0tPyR7"
SLUG_SIZE_RE = re.compile(r"[-/](\d+(?:[.,]\d+)?)\s*(kg|g|ml|l|szt|pcs?)(?=[-/.]|$)", re.I)


def parse_price(text: str | None) -> float | None:
    """Parse a Polish-formatted price. Returns None rather than guessing."""
    if not text:
        return None
    match = PRICE_RE.search(text)
    if not match:
        # A bare number in a price-only element, e.g. "12.00"
        bare = re.fullmatch(r"\s*(\d+(?:[.,]\d{1,2})?)\s*", text)
        if not bare:
            return None
        raw = bare.group(1)
    else:
        raw = match.group(1)
    raw = raw.replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


class HtmlShopAdapter(Adapter):
    platform = "html"

    # ---------------------------------------------------------------- discovery
    def _sitemap_urls(self, client: httpx.Client, url: str, depth: int = 0) -> list[str]:
        """Collect <loc> entries, following sitemap indexes one level down."""
        if depth > 2:
            return []
        try:
            response = client.get(url)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("sitemap %s failed: %s", url, exc)
            return []

        soup = BeautifulSoup(response.text, "xml")
        if soup.find("sitemapindex"):
            nested: list[str] = []
            for loc in soup.find_all("loc"):
                self.polite_pause()
                nested.extend(self._sitemap_urls(client, loc.get_text(strip=True), depth + 1))
            return nested
        return [loc.get_text(strip=True) for loc in soup.find_all("loc")]

    def filter_product_urls(self, found: list[str]) -> list[str]:
        """Reduce raw sitemap entries to de-duplicated product URLs."""
        base = self.shop.url.rstrip("/")
        include = self.config.get("include_pattern")
        excludes = self.config.get("exclude_patterns", [])
        limit = int(self.config.get("max_products", 800))

        seen: set[str] = set()
        urls: list[str] = []
        for url in found:
            # Normalise to the shop's own scheme/host: sitemaps often list http://
            url = urljoin(base + "/", urlparse(url).path)
            if url in seen or url.rstrip("/") == base:
                continue
            if include and not re.search(include, url):
                continue
            if any(re.search(pattern, url) for pattern in excludes):
                continue
            seen.add(url)
            urls.append(url)
        return urls[:limit]

    def _category_urls(self, client: httpx.Client) -> list[str]:
        """Discover products by walking category listings.

        The fallback-to-the-fallback, for shops with no sitemap at all (Shoper).
        Pagination stops as soon as a page yields no product link we have not
        already seen, which handles both unpaginated categories and the common
        pattern of a last page that silently repeats the first.
        """
        base = self.shop.url.rstrip("/")
        category_re = re.compile(self.config.get("category_pattern", "/c/"))
        product_re = re.compile(self.config.get("product_pattern", "/p/"))
        page_param = self.config.get("page_param", "page")
        max_pages = int(self.config.get("max_pages_per_category", 30))
        link_re = re.compile(r'href="([^"]+)"')

        def links(html: str, pattern: re.Pattern) -> set[str]:
            out = set()
            for href in link_re.findall(html):
                url = urljoin(base + "/", href)
                if url.startswith(base) and pattern.search(url):
                    out.add(url.split("?")[0].split("#")[0])
            return out

        try:
            home = client.get(base + "/")
            home.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("%s: homepage fetch failed: %s", self.shop.slug, exc)
            return []

        categories = sorted(links(home.text, category_re))
        seeds = self.config.get("category_seeds")
        if seeds:
            categories = [urljoin(base + "/", s.lstrip("/")) for s in seeds]
        log.info("%s: %d categories to walk", self.shop.slug, len(categories))

        products: set[str] = set()
        for category in categories:
            seen_here: set[str] = set()
            for page in range(1, max_pages + 1):
                url = category if page == 1 else f"{category}?{page_param}={page}"
                self.polite_pause()
                try:
                    response = client.get(url)
                    response.raise_for_status()
                except Exception:  # noqa: BLE001
                    break
                hits = links(response.text, product_re)
                if not hits - seen_here:
                    break
                seen_here |= hits
            products |= seen_here
        return sorted(products)

    def _product_urls(self, client: httpx.Client) -> list[str]:
        base = self.shop.url.rstrip("/")
        if self.config.get("discovery") == "categories":
            return self.filter_product_urls(self._category_urls(client))

        found: list[str] = []
        for path in self.config.get("sitemaps", ["/sitemap.xml"]):
            found.extend(self._sitemap_urls(client, urljoin(base + "/", path.lstrip("/"))))
        return self.filter_product_urls(found)

    # --------------------------------------------------------------- extraction
    @staticmethod
    def _merge(dst: dict, src: dict) -> None:
        """Deep-merge `src` into `dst`, preferring richer values.

        Lists win over dicts: Shoper emits shipping first as a single dict and
        later as the full list of couriers, and the list is the one we want.
        """
        for key, value in src.items():
            if key == "@context":
                continue
            current = dst.get(key)
            if isinstance(value, dict) and isinstance(current, dict):
                HtmlShopAdapter._merge(current, value)
            elif isinstance(value, list) and isinstance(current, dict):
                dst[key] = value
            elif key not in dst or current in (None, {}, [], ""):
                dst[key] = value

    def _from_jsonld(self, soup: BeautifulSoup) -> dict | None:
        """schema.org Product, if the platform emits it.

        Some platforms (Shoper) split one product across a dozen <script> tags
        that each carry a fragment — name in one, price in another, availability
        in a third — all sharing the same "@id". Read individually every one of
        them looks empty, so fragments are merged by @id before extraction.
        """

        def walk(node):
            if isinstance(node, dict):
                types = node.get("@type")
                types = types if isinstance(types, list) else [types]
                # "@type" may be a full IRI, e.g. "http://schema.org/Product".
                if any(str(t).rsplit("/", 1)[-1] == "Product" for t in types):
                    yield node
                for value in node.values():
                    yield from walk(value)
            elif isinstance(node, list):
                for value in node:
                    yield from walk(value)

        parsed_blocks: list[dict] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            parsed_blocks.append(data)

        # Pass 1: stitch fragments together by @id.
        by_id: dict[str, dict] = {}
        for data in parsed_blocks:
            if isinstance(data, dict) and data.get("@id"):
                self._merge(by_id.setdefault(str(data["@id"]), {}), data)

        candidates: list[dict] = []
        for merged in by_id.values():
            if merged.get("name") and merged.get("offers"):
                candidates.append(merged)
        for data in parsed_blocks:
            candidates.extend(walk(data))

        for product in candidates:
                offers = product.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                price = parse_price(str(offers.get("price"))) if offers.get("price") else None
                if not price:
                    continue
                brand = product.get("brand")
                if isinstance(brand, dict):
                    brand = brand.get("name")
                image = product.get("image")
                if isinstance(image, list):
                    image = image[0] if image else None
                return {
                    "title": product.get("name"),
                    "price": price,
                    "currency": offers.get("priceCurrency") or self.shop.currency,
                    "image": image,
                    "sku": product.get("sku"),
                    "brand": brand if isinstance(brand, str) else None,
                    "in_stock": "outofstock"
                    not in str(offers.get("availability", "")).lower().replace("_", ""),
                }
        return None

    def _select_text(self, soup: BeautifulSoup, selectors: list[str]) -> str | None:
        for selector in selectors:
            for node in soup.select(selector):
                text = (
                    node.get("content")
                    if node.name == "meta"
                    else node.get_text(" ", strip=True)
                )
                if text and text.strip():
                    return text.strip()
        return None

    def _select_attr(
        self, soup: BeautifulSoup, selectors: list[str], attr: str
    ) -> str | None:
        for selector in selectors:
            for node in soup.select(selector):
                value = node.get("content") if node.name == "meta" else node.get(attr)
                if value:
                    return value
        return None

    def _from_selectors(self, soup: BeautifulSoup) -> dict | None:
        rules = self.config.get("selectors", {})
        title = self._select_text(soup, rules.get("title", ["h1", "title"]))
        price = parse_price(self._select_text(soup, rules.get("price", [])))
        if not title or not price:
            return None

        image = self._select_attr(soup, rules.get("image", []), "src") or self._select_attr(
            soup, ["meta[property='og:image']"], "content"
        )

        # Stock defaults to available. Scanning the page text for "brak w
        # magazynie" was tried and is wrong: these storefronts ship a hidden
        # out-of-stock modal on every page, which marked the entire catalogue
        # unavailable. Only an explicit, shop-specific selector is trustworthy.
        out_of_stock_selector = rules.get("out_of_stock")
        in_stock = not (out_of_stock_selector and soup.select_one(out_of_stock_selector))

        return {
            "title": title,
            "price": price,
            "currency": self.shop.currency,
            "image": image,
            "sku": self._select_text(soup, rules.get("sku", [])),
            "brand": self._select_text(soup, rules.get("brand", [])),
            "in_stock": in_stock,
        }

    # The column is bounded and some shops use very long descriptive slugs —
    # Little India's Polish product paths run past 128 characters, which failed
    # the insert outright. Keep the readable head, then a digest of the whole
    # path so two products sharing a prefix can never collide.
    MAX_EXTERNAL_ID = 110

    @classmethod
    def _external_id(cls, url: str) -> str:
        path = urlparse(url).path.strip("/") or url
        if len(path) <= cls.MAX_EXTERNAL_ID:
            return path
        digest = hashlib.sha1(path.encode("utf-8")).hexdigest()[:16]
        return f"{path[: cls.MAX_EXTERNAL_ID - 17]}#{digest}"

    @staticmethod
    def _title_with_size(title: str, url: str) -> str:
        """Recover a pack size the page title dropped but the URL slug kept.

        Real case: the page title is "TRS Gruba semolina" while the URL is
        ".../trs-coarse-semolina-500g-0tPyR7". Without the size the offer has no
        price-per-kg and cannot be matched against the same product elsewhere,
        since pack size is part of product identity.
        """
        if re.search(r"\d+(?:[.,]\d+)?\s*(kg|g|ml|l|szt|pcs?)\b", title, re.I):
            return title
        match = SLUG_SIZE_RE.search(urlparse(url).path)
        return f"{title} {match.group(1)}{match.group(2).lower()}" if match else title

    # -------------------------------------------------------------------- fetch
    def fetch(self) -> list[RawOffer]:
        offers: list[RawOffer] = []
        headers = {"Accept": "text/html,application/xhtml+xml,application/xml"}

        with self.client() as client:
            urls = self._product_urls(client)
            log.info("%s: %d product URLs from sitemap", self.shop.slug, len(urls))

            failures = 0
            for url in urls:
                self.polite_pause()
                try:
                    response = client.get(url, headers=headers)
                    response.raise_for_status()
                except Exception as exc:  # noqa: BLE001
                    failures += 1
                    # One dead page must not kill the run, but a wholesale
                    # failure means the site changed and we should stop early.
                    if failures > 25 and failures > len(offers):
                        raise RuntimeError(
                            f"{self.shop.slug}: {failures} consecutive page failures "
                            f"({exc}); aborting"
                        ) from exc
                    continue

                soup = BeautifulSoup(response.text, "html.parser")
                data = self._from_jsonld(soup) or self._from_selectors(soup)
                if not data or not data.get("title"):
                    continue

                offers.append(
                    RawOffer(
                        external_id=self._external_id(url),
                        title=self._title_with_size(str(data["title"]).strip(), url),
                        url=url,
                        price=float(data["price"]),
                        currency=data.get("currency") or self.shop.currency,
                        in_stock=bool(data.get("in_stock", True)),
                        image_url=data.get("image"),
                        sku=data.get("sku"),
                        brand=data.get("brand"),
                        # These platforms publish no shipping weight; the
                        # shipping engine falls back to its default per item.
                        weight_grams=None,
                        raw={"source": "html"},
                    )
                )
        return offers
