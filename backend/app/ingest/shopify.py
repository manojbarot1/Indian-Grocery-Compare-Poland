"""Shopify adapter.

Shopify stores expose a public, paginated `/products.json` containing exactly
what we need — title, vendor, variant price, availability and `grams`. That last
field is why Shopify shops give us accurate shipping: we know real parcel weight
rather than guessing from the pack size in the title.

Each variant becomes its own offer, because a 1 kg and a 5 kg bag are different
products at different prices.
"""

from __future__ import annotations

from .base import Adapter, RawOffer, to_float


class ShopifyAdapter(Adapter):
    platform = "shopify"

    def fetch(self) -> list[RawOffer]:
        path = self.config.get("path", "/products.json")
        page_size = int(self.config.get("page_size", 250))
        max_pages = int(self.config.get("max_pages", 40))

        offers: list[RawOffer] = []
        with self.client() as client:
            for page in range(1, max_pages + 1):
                url = f"{self.shop.url.rstrip('/')}{path}"
                response = client.get(url, params={"limit": page_size, "page": page})
                response.raise_for_status()
                try:
                    products = response.json().get("products", [])
                except ValueError:
                    # A 200 that is not JSON means a challenge or error page.
                    break
                if not products:
                    break
                for product in products:
                    offers.extend(self._parse_product(product))
                if len(products) < page_size:
                    break
                self.polite_pause()
        return offers

    def _parse_product(self, product: dict) -> list[RawOffer]:
        handle = product.get("handle", "")
        base_url = f"{self.shop.url.rstrip('/')}/products/{handle}"
        images = product.get("images") or []
        default_image = images[0].get("src") if images else None
        vendor = product.get("vendor")
        title = (product.get("title") or "").strip()

        results: list[RawOffer] = []
        for variant in product.get("variants") or []:
            price = to_float(variant.get("price"))
            if price is None:
                continue

            variant_title = (variant.get("title") or "").strip()
            # "Default Title" is Shopify's placeholder for single-variant products.
            full_title = (
                f"{title} {variant_title}"
                if variant_title and variant_title.lower() != "default title"
                else title
            )

            variant_image = (variant.get("featured_image") or {}).get("src")
            grams = variant.get("grams")

            results.append(
                RawOffer(
                    external_id=str(variant.get("id")),
                    title=full_title,
                    url=f"{base_url}?variant={variant.get('id')}",
                    price=price,
                    currency=self.shop.currency,
                    in_stock=bool(variant.get("available", True)),
                    image_url=variant_image or default_image,
                    sku=variant.get("sku") or None,
                    brand=vendor,
                    compare_at_price=to_float(variant.get("compare_at_price")),
                    weight_grams=int(grams) if grams else None,
                    raw={
                        "product_id": product.get("id"),
                        "product_type": product.get("product_type"),
                        "tags": product.get("tags"),
                        "vendor": vendor,
                    },
                )
            )
        return results
