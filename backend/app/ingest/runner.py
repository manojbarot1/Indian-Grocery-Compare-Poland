"""Pull a shop's catalogue and persist it.

Upserts on (shop, external_id) so re-running is cheap and price history stays
continuous. A `PricePoint` is written only when the price or stock state
actually changes, which keeps the history table small enough to chart.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..matching.normalize import apply_size, parse_title
from ..models import Offer, PricePoint, Shop, utcnow
from .base import RawOffer
from .registry import adapter_for

log = logging.getLogger(__name__)


@dataclass
class IngestResult:
    shop_slug: str
    fetched: int = 0
    created: int = 0
    updated: int = 0
    price_changes: int = 0
    delisted: int = 0
    skipped_placeholder: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _to_pln(amount: float, currency: str) -> float:
    return round(amount * settings.fx_rates_to_pln.get(currency, 1.0), 2)


PLACEHOLDER_MAX_PRICE = 2.0
"""A price at or below this is a candidate for being a placeholder, not a price."""

PLACEHOLDER_MIN_SHARE = 0.05
"""...but only if it repeats across this share of the shop's catalogue."""


def detect_placeholder_prices(raw_offers: list[RawOffer]) -> set[float]:
    """Find prices a shop uses to mean "not priced yet".

    Little Asia Grocery lists 78 different products at exactly 1.00 zł — mango,
    moong dal, whole black pepper. Their API reports it faithfully, so this is
    their data, not our parsing. Ingested as-is, that shop wins every comparison
    it appears in with a price nobody can actually buy at.

    Detected rather than hard-coded: a *specific* low value repeated across a
    meaningful share of one shop's catalogue is a placeholder. A shop that
    genuinely sells many things for 1.00 would spread across 0.99, 1.00, 1.20;
    it would not stack 78 unrelated products on one value.
    """
    if not raw_offers:
        return set()

    counts = Counter(
        o.price for o in raw_offers if o.price and o.price <= PLACEHOLDER_MAX_PRICE
    )
    threshold = max(5, int(len(raw_offers) * PLACEHOLDER_MIN_SHARE))
    return {price for price, n in counts.items() if n >= threshold}


def _apply_normalisation(offer: Offer, raw: RawOffer) -> None:
    """First-pass normalisation. The matcher redoes this later with the
    corpus-wide brand vocabulary, which it cannot know at ingest time."""
    parsed = parse_title(raw.title, raw.brand)
    offer.brand = parsed.brand
    offer.match_key = parsed.match_key
    apply_size(offer, parsed)


def ingest_shop(session: Session, shop: Shop, dry_run: bool = False) -> IngestResult:
    result = IngestResult(shop_slug=shop.slug)
    try:
        raw_offers = adapter_for(shop).fetch()
    except Exception as exc:  # noqa: BLE001 - one bad shop must not stop the run
        log.warning("ingest failed for %s: %s", shop.slug, exc)
        result.error = f"{type(exc).__name__}: {exc}"
        shop.last_ingest_at = utcnow()
        shop.last_ingest_status = result.error[:255]
        session.commit()
        return result

    result.fetched = len(raw_offers)
    if dry_run:
        return result

    placeholders = detect_placeholder_prices(raw_offers)
    if placeholders:
        log.warning(
            "%s: treating %s as placeholder price(s), not real offers",
            shop.slug,
            ", ".join(f"{p:.2f}" for p in sorted(placeholders)),
        )

    existing = {
        offer.external_id: offer
        for offer in session.scalars(select(Offer).where(Offer.shop_id == shop.id))
    }
    seen: set[str] = set()

    for raw in raw_offers:
        # A zero price is never a real grocery price — it marks placeholder
        # variants, "price on request" items and hidden bundle components.
        # Listing them would put a bogus 0.00 at the top of every comparison.
        if not raw.title or not raw.price or raw.price <= 0:
            continue
        # A placeholder price is not a price. Listing it would hand this shop
        # the top spot on every product it touches.
        if raw.price in placeholders:
            result.skipped_placeholder += 1
            continue
        seen.add(raw.external_id)
        price_pln = _to_pln(raw.price, raw.currency)
        offer = existing.get(raw.external_id)

        if offer is None:
            offer = Offer(shop_id=shop.id, external_id=raw.external_id)
            session.add(offer)
            result.created += 1
            price_changed = True
        else:
            price_changed = (
                abs(offer.price_pln - price_pln) > 0.001
                or offer.in_stock != raw.in_stock
            )
            result.updated += 1

        offer.title = raw.title[:512]
        offer.url = raw.url
        offer.image_url = raw.image_url
        # Bounded columns: a shop can put anything in these fields.
        offer.sku = raw.sku[:128] if raw.sku else None
        offer.price = raw.price
        offer.currency = raw.currency
        offer.price_pln = price_pln
        offer.compare_at_price = raw.compare_at_price
        offer.in_stock = raw.in_stock
        offer.weight_grams = raw.weight_grams
        offer.raw = raw.raw
        offer.last_seen_at = utcnow()

        _apply_normalisation(offer, raw)

        if price_changed:
            session.flush()
            session.add(
                PricePoint(
                    offer_id=offer.id, price_pln=price_pln, in_stock=raw.in_stock
                )
            )
            result.price_changes += 1

    # Anything the shop stopped listing is out of stock, not deleted: keeping the
    # row preserves its price history and any manual match corrections.
    for external_id, offer in existing.items():
        if external_id not in seen and offer.in_stock:
            offer.in_stock = False
            result.delisted += 1

    shop.last_ingest_at = utcnow()
    shop.last_ingest_status = (
        f"ok: {result.fetched} fetched, {result.created} new, {result.delisted} delisted"
    )
    session.commit()
    return result


def ingest_all(
    session: Session, only: list[str] | None = None, dry_run: bool = False
) -> list[IngestResult]:
    stmt = select(Shop).where(Shop.active.is_(True))
    if only:
        stmt = stmt.where(Shop.slug.in_(only))
    return [ingest_shop(session, shop, dry_run) for shop in session.scalars(stmt)]
