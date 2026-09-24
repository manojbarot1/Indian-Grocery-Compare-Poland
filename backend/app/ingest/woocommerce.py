"""WooCommerce adapter, via the public Store API (`/wp-json/wc/store/v1`).

Two traps this handles:

1. Prices arrive as integer strings in minor units with a separate
   `currency_minor_unit` — "7500" with minor_unit 2 is 75.00 PLN, not 7500.
2. `weight` is a bare number in whatever unit the shop configured in WooCommerce,
   which the API never tells you. The shop entry declares `weight_unit`.
"""

from __future__ import annotations

import html
import logging

from .base import Adapter, RawOffer, to_float

log = logging.getLogger(__name__)

WEIGHT_TO_GRAMS = {"g": 1.0, "kg": 1000.0, "lbs": 453.592, "oz": 28.3495}


class WooCommerceAdapter(Adapter):
    platform = "woocommerce"

    def fetch(self) -> list[RawOffer]:
        path = self.config.get("path", "/wp-json/wc/store/v1/products")
        page_size = int(self.config.get("page_size", 100))
        max_pages = int(self.config.get("max_pages", 40))

        offers: list[RawOffer] = []
        with self.client() as client:
            for page in range(1, max_pages + 1):
                url = f"{self.shop.url.rstrip('/')}{path}"
                response = client.get(url, params={"per_page": page_size, "page": page})
                if response.status_code == 400:
                    break  # Woo returns 400 once you page past the end
                response.raise_for_status()
                try:
                    products = response.json()
                except ValueError:
                    # Some installs answer 200 with an HTML error/challenge page
                    # once you page past the end, or when a plugin intercepts
                    # the request. Stop cleanly instead of failing the shop.
                    log.warning(
                        "%s: non-JSON response at page %d; stopping",
                        self.shop.slug, page,
                    )
                    break
                if not isinstance(products, list) or not products:
                    break
                for product in products:
                    offer = self._parse_product(product)
                    if offer:
                        offers.append(offer)

                total_pages = response.headers.get("X-WP-TotalPages")
                if total_pages and page >= int(total_pages):
                    break
                if len(products) < page_size:
                    break
                self.polite_pause()
        return offers

    def _price(self, prices: dict, key: str) -> float | None:
        raw = prices.get(key)
        if raw in (None, ""):
            return None
        value = to_float(raw)
        if value is None:
            return None
        return round(value / (10 ** int(prices.get("currency_minor_unit", 2))), 2)

    def _weight_grams(self, product: dict) -> int | None:
        weight = to_float(product.get("weight"))
        if not weight:
            return None
        unit = (self.shop.weight_unit or "g").lower()
        return int(round(weight * WEIGHT_TO_GRAMS.get(unit, 1.0)))

    def _parse_product(self, product: dict) -> RawOffer | None:
        prices = product.get("prices") or {}
        price = self._price(prices, "price")
        if price is None:
            return None

        images = product.get("images") or []
        brands = product.get("brands") or []

        return RawOffer(
            external_id=str(product.get("id")),
            title=html.unescape(product.get("name") or "").strip(),
            url=product.get("permalink") or self.shop.url,
            price=price,
            currency=prices.get("currency_code") or self.shop.currency,
            in_stock=bool(product.get("is_in_stock", True)),
            image_url=images[0].get("src") if images else None,
            sku=product.get("sku") or None,
            brand=html.unescape(brands[0].get("name")) if brands else None,
            compare_at_price=self._price(prices, "regular_price"),
            weight_grams=self._weight_grams(product),
            raw={
                "categories": [
                    html.unescape(c.get("name", "")) for c in product.get("categories", [])
                ],
                "slug": product.get("slug"),
            },
        )
