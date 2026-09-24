from __future__ import annotations

from pydantic import BaseModel, Field


class ShopOut(BaseModel):
    slug: str
    name: str
    url: str
    country: str
    currency: str
    ships_to: list[str]
    offer_count: int = 0
    shipping_confidence: str = "low"
    free_over: float | None = None
    last_ingest_at: str | None = None
    last_ingest_status: str | None = None


class OfferOut(BaseModel):
    id: int
    shop_slug: str
    shop_name: str
    title: str
    url: str
    price_pln: float
    price: float
    currency: str
    unit_price_pln: float | None = None
    base_unit: str | None = None
    in_stock: bool
    weight_grams: int | None = None

    # Landed cost = price + shipping for buying this one item alone.
    shipping_pln: float | None = None
    shipping_method: str | None = None
    shipping_estimated: bool = True
    free_shipping_applied: bool = False
    amount_to_free_shipping: float | None = None
    landed_total_pln: float | None = None
    min_days: int | None = None
    max_days: int | None = None
    warnings: list[str] = Field(default_factory=list)


class ShopPrice(BaseModel):
    """One shop's price for a product, compact enough to show on a search card.

    Carrying this in search results is what lets the grid show every shop's
    price inline instead of hiding it behind a click — the comparison is the
    product, so it should not need a second request to see.
    """

    shop_slug: str
    shop_name: str
    price_pln: float
    shipping_pln: float | None = None
    landed_total_pln: float | None = None
    shipping_estimated: bool = True
    free_shipping_applied: bool = False
    in_stock: bool = True
    min_days: int | None = None
    max_days: int | None = None
    url: str
    # The shop's free-delivery threshold, in PLN. A shop with a high threshold
    # looks expensive on a single item but can be the cheapest on a full basket,
    # so the card has to show the threshold, not just today's shipping cost.
    free_over_pln: float | None = None
    amount_to_free_shipping: float | None = None


class ProductSummary(BaseModel):
    id: int
    slug: str
    name: str
    brand: str | None = None
    image_url: str | None = None
    size_value: float | None = None
    size_unit: str | None = None
    base_unit: str | None = None
    offer_count: int
    shop_count: int
    min_price_pln: float | None = None
    max_price_pln: float | None = None
    best_unit_price_pln: float | None = None
    best_landed_pln: float | None = None
    spread_pct: float | None = None
    # Cheapest offer per shop, cheapest-delivered first.
    shop_prices: list[ShopPrice] = Field(default_factory=list)


class ProductDetail(ProductSummary):
    offers: list[OfferOut] = Field(default_factory=list)


class SearchResponse(BaseModel):
    query: str | None = None
    total: int
    page: int
    page_size: int
    results: list[ProductSummary]
    # How many matches the "comparable only" filter removed, so the UI can
    # offer them rather than pretending they do not exist.
    hidden_single_shop: int = 0


class BasketItemIn(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1, le=99)


class BasketRequest(BaseModel):
    items: list[BasketItemIn]
    country: str | None = None


class PricePointOut(BaseModel):
    price_pln: float
    in_stock: bool
    observed_at: str
