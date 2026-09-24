from __future__ import annotations

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Shop
from .base import Adapter
from .html_shop import HtmlShopAdapter
from .shopify import ShopifyAdapter
from .woocommerce import WooCommerceAdapter

ADAPTERS: dict[str, type[Adapter]] = {
    ShopifyAdapter.platform: ShopifyAdapter,
    WooCommerceAdapter.platform: WooCommerceAdapter,
    HtmlShopAdapter.platform: HtmlShopAdapter,
}


def adapter_for(shop: Shop) -> Adapter:
    try:
        return ADAPTERS[shop.platform](shop)
    except KeyError:
        raise ValueError(
            f"No adapter for platform {shop.platform!r} (shop {shop.slug}). "
            f"Known: {', '.join(sorted(ADAPTERS))}"
        ) from None


def load_shops(session: Session, path=None) -> list[Shop]:
    """Sync shops.yaml into the database. Idempotent — safe to run on boot."""
    path = path or settings.shops_file
    with open(path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    shops: list[Shop] = []
    for entry in data.get("shops", []):
        shop = session.scalar(select(Shop).where(Shop.slug == entry["slug"]))
        if shop is None:
            shop = Shop(slug=entry["slug"])
            session.add(shop)

        shop.name = entry["name"]
        shop.url = entry["url"]
        shop.platform = entry["platform"]
        shop.country = entry.get("country", "PL")
        shop.currency = entry.get("currency", "PLN")
        shop.ships_to = entry.get("ships_to", [entry.get("country", "PL")])
        shop.active = entry.get("active", True)
        shop.ingest_config = entry.get("ingest", {})
        shop.shipping_rules = entry.get("shipping", {})
        shop.weight_unit = entry.get("weight_unit", "g")
        shops.append(shop)

    session.commit()
    return shops
