from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.orm import Session, selectinload

from ..basket.optimizer import optimize_basket, to_pln
from ..config import settings
from ..db import get_session
from ..matching.categories import LABELS as CATEGORY_LABELS
from ..matching.categories import SUBCATEGORY_RULES
from ..matching.categories import SUB_LABELS
from ..matching.normalize import basic_clean
from ..models import Offer, PricePoint, Product, Shop
from ..schemas import (
    BasketRequest,
    OfferOut,
    ProductDetail,
    ProductSummary,
    SearchResponse,
    ShopOut,
    ShopPrice,
)
from ..shipping import engine as shipping_engine

router = APIRouter(prefix="/api")

SORTS = {
    "price": "lowest price",
    "unit": "cheapest per kg/l",
    "name": "name",
    "offers": "most shops",
}


def _serialise(value):
    if is_dataclass(value):
        return {k: _serialise(v) for k, v in asdict(value).items()}
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    return value


def _offer_out(offer: Offer, quantity: int = 1) -> OfferOut:
    """An offer priced the way a shopper experiences it: with delivery."""
    shop = offer.shop
    rate = settings.fx_rates_to_pln.get(shop.currency, 1.0)
    subtotal_native = offer.price * quantity
    weight = shipping_engine.basket_weight([(offer.weight_grams, quantity)])

    quote = shipping_engine.quote(
        shop.slug, shop.shipping_rules, subtotal_native, weight, shop.currency
    )
    gap = shipping_engine.amount_to_free_shipping(shop.shipping_rules, subtotal_native)

    shipping_pln = to_pln(quote.cost, quote.currency) if quote else None
    return OfferOut(
        id=offer.id,
        shop_slug=shop.slug,
        shop_name=shop.name,
        title=offer.title,
        url=offer.url,
        price_pln=offer.price_pln,
        price=offer.price,
        currency=offer.currency,
        unit_price_pln=offer.unit_price_pln,
        base_unit=offer.base_unit,
        in_stock=offer.in_stock,
        weight_grams=offer.weight_grams,
        shipping_pln=shipping_pln,
        shipping_method=quote.method if quote else None,
        shipping_estimated=quote.estimated if quote else True,
        free_shipping_applied=quote.free_applied if quote else False,
        amount_to_free_shipping=to_pln(gap, shop.currency) if gap else gap,
        landed_total_pln=(
            round(offer.price_pln * quantity + shipping_pln, 2)
            if shipping_pln is not None
            else None
        ),
        min_days=quote.min_days if quote else None,
        max_days=quote.max_days if quote else None,
        warnings=list(quote.notes) if quote else ["No shipping rule on file."],
    )


def _shop_prices(offers: list[Offer]) -> list[ShopPrice]:
    """Cheapest offer per shop, priced as delivered, cheapest first.

    One row per shop, not per offer: a shop listing the same tin twice is noise
    to a shopper comparing shops.
    """
    best_per_shop: dict[str, tuple[OfferOut, Offer]] = {}
    for offer in offers:
        out = _offer_out(offer)
        current = best_per_shop.get(out.shop_slug)
        key = out.landed_total_pln or out.price_pln
        if current is None or key < (
            current[0].landed_total_pln or current[0].price_pln
        ):
            best_per_shop[out.shop_slug] = (out, offer)

    rows = []
    for out, offer in best_per_shop.values():
        rules = offer.shop.shipping_rules or {}
        free_over = rules.get("free_over")
        rows.append(
            ShopPrice(
                shop_slug=out.shop_slug,
                shop_name=out.shop_name,
                price_pln=out.price_pln,
                shipping_pln=out.shipping_pln,
                landed_total_pln=out.landed_total_pln,
                shipping_estimated=out.shipping_estimated,
                free_shipping_applied=out.free_shipping_applied,
                in_stock=out.in_stock,
                min_days=out.min_days,
                max_days=out.max_days,
                url=out.url,
                free_over_pln=(
                    to_pln(float(free_over), offer.shop.currency)
                    if free_over is not None
                    else None
                ),
                amount_to_free_shipping=out.amount_to_free_shipping,
            )
        )
    rows.sort(
        key=lambda r: (not r.in_stock, r.landed_total_pln or r.price_pln)
    )
    return rows


def _summarise(product: Product, offers: list[Offer]) -> ProductSummary:
    live = [o for o in offers if o.in_stock] or offers
    prices = [o.price_pln for o in live]
    landed = [o.landed_total_pln for o in (_offer_out(o) for o in live) if o.landed_total_pln]

    # Take the price and its unit from the same offer. The product's own
    # base_unit can be unset while a merged offer still has one, which rendered
    # as a unit price with no unit after it.
    priced = [o for o in live if o.unit_price_pln and o.base_unit]
    best_unit_offer = min(priced, key=lambda o: o.unit_price_pln) if priced else None

    min_price = min(prices) if prices else None
    max_price = max(prices) if prices else None
    spread = (
        round((max_price - min_price) / min_price * 100, 1)
        if min_price and max_price and min_price > 0
        else None
    )

    return ProductSummary(
        id=product.id,
        slug=product.slug,
        name=product.name,
        brand=product.brand,
        image_url=product.image_url,
        size_value=product.size_value,
        size_unit=product.size_unit,
        base_unit=best_unit_offer.base_unit if best_unit_offer else product.base_unit,
        offer_count=len(live),
        shop_count=len({o.shop_id for o in live}),
        min_price_pln=min_price,
        max_price_pln=max_price,
        best_unit_price_pln=best_unit_offer.unit_price_pln if best_unit_offer else None,
        shop_prices=_shop_prices(live),
        best_landed_pln=min(landed) if landed else None,
        spread_pct=spread,
    )


@router.get("/shops", response_model=list[ShopOut])
def list_shops(session: Session = Depends(get_session)):
    counts = dict(
        session.execute(
            select(Offer.shop_id, func.count(Offer.id)).group_by(Offer.shop_id)
        ).all()
    )
    out = []
    # Disabled shops stay in the database for their price history but must
    # not appear in the UI or the counts.
    for shop in session.scalars(
        select(Shop).where(Shop.active.is_(True)).order_by(Shop.name)
    ):
        rules = shop.shipping_rules or {}
        out.append(
            ShopOut(
                slug=shop.slug,
                name=shop.name,
                url=shop.url,
                country=shop.country,
                currency=shop.currency,
                ships_to=shop.ships_to or [],
                offer_count=counts.get(shop.id, 0),
                shipping_confidence=rules.get("confidence", "low"),
                free_over=rules.get("free_over"),
                last_ingest_at=(
                    shop.last_ingest_at.isoformat() if shop.last_ingest_at else None
                ),
                last_ingest_status=shop.last_ingest_status,
            )
        )
    return out


@router.get("/categories")
def list_categories(
    multi_shop_only: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    """Categories with product counts, for the sidebar.

    Counts respect `multi_shop_only` so the sidebar never advertises 400
    products in an aisle that then shows 12 under the active filter.
    """
    stmt = select(Product.category, func.count(Product.id)).where(
        Product.offers.any()
    )
    if multi_shop_only:
        # Count in-stock offers only, exactly as search does when it decides
        # whether a product is comparable. Counting all offers here made the
        # sidebar advertise 71 products in an aisle that then showed 58.
        comparable = (
            select(Offer.product_id)
            .where(Offer.in_stock.is_(True))
            .group_by(Offer.product_id)
            .having(func.count(func.distinct(Offer.shop_id)) > 1)
            .subquery()
        )
        stmt = stmt.where(Product.id.in_(select(comparable.c.product_id)))

    rows = session.execute(stmt.group_by(Product.category)).all()

    # Sub-counts in the same pass, so the child numbers can never disagree with
    # the parent the way the sidebar once disagreed with the results.
    sub_rows = session.execute(
        stmt.with_only_columns(
            Product.category, Product.subcategory, func.count(Product.id)
        ).group_by(Product.category, Product.subcategory)
    ).all()
    children: dict[str, list[dict]] = {}
    for parent, sub, count in sub_rows:
        if not sub:
            continue
        children.setdefault(parent, []).append(
            {"slug": sub, "label": SUB_LABELS.get(sub, sub), "count": count}
        )
    for group in children.values():
        group.sort(key=lambda c: -c["count"])

    out = [
        {
            "slug": slug or "other",
            "label": CATEGORY_LABELS.get(slug or "other", "Other"),
            "count": count,
            "children": children.get(slug, []),
        }
        for slug, count in rows
    ]
    out.sort(key=lambda c: (c["slug"] == "other", -c["count"]))
    return {"categories": out, "total": sum(c["count"] for c in out)}


@router.get("/search", response_model=SearchResponse)
def search(
    q: str | None = Query(default=None, description="Free-text query"),
    brand: str | None = None,
    shop: str | None = None,
    category: str | None = Query(default=None, description="Category slug"),
    subcategory: str | None = Query(default=None, description="Sub-category slug"),
    sort: str = Query(default="price", pattern="^(price|unit|name|offers)$"),
    multi_shop_only: bool = Query(
        default=False, description="Only products actually sold by 2+ shops"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=48, ge=1, le=200),
    session: Session = Depends(get_session),
):
    # Collected as a list and applied straight to the ranking query. Wrapping
    # them in `Product.id IN (subquery)` cost 4s on an unfiltered listing.
    conditions = []

    if q:
        # Match every word independently rather than the phrase as typed.
        # "deep paratha" must find "Deep Aloo Paratha" — the words are rarely
        # adjacent in a shop title, and a single LIKE on the whole phrase found
        # almost nothing.
        #
        # Each word is also matched against the normalised form, so a Polish
        # query reaches English listings (mąka -> flour) and vice versa.
        words = [w for w in re.split(r"\s+", q.strip().lower()) if w]
        for word in words[:6]:
            like = f"%{word}%"
            normalised = f"%{basic_clean(word)}%"
            conditions.append(
                or_(
                    func.lower(Product.name).like(like),
                    func.lower(Product.brand).like(like),
                    Product.match_key.like(normalised),
                    Product.match_core.like(normalised),
                    Product.offers.any(func.lower(Offer.title).like(like)),
                )
            )
    if category:
        conditions.append(Product.category == category)
    if subcategory:
        conditions.append(Product.subcategory == subcategory)
    if brand:
        conditions.append(func.lower(Product.brand) == brand.lower())
    if shop:
        conditions.append(Product.offers.any(Offer.shop.has(Shop.slug == shop)))

    # Rank in SQL, hydrate only the page.
    #
    # Loading every product and its offers into Python to sort them took 57s
    # (and 5s even after summarising only the page). The ranking keys —
    # cheapest price, cheapest per unit, how many shops — are all aggregates the
    # database can compute without shipping any rows.
    in_stock_price = func.min(
        case((Offer.in_stock.is_(True), Offer.price_pln))
    )
    in_stock_unit = func.min(
        case((Offer.in_stock.is_(True), Offer.unit_price_pln))
    )
    agg = (
        select(
            Offer.product_id.label("product_id"),
            # Prefer in-stock prices, falling back to any, which is what the
            # summary does when a product is sold out everywhere.
            func.coalesce(in_stock_price, func.min(Offer.price_pln)).label("min_price"),
            func.coalesce(in_stock_unit, func.min(Offer.unit_price_pln)).label("min_unit"),
            func.count(distinct(case((Offer.in_stock.is_(True), Offer.shop_id))))
            .label("shops_in_stock"),
            func.count(Offer.id).label("offer_count"),
        )
        .where(Offer.product_id.isnot(None))
        .group_by(Offer.product_id)
        .subquery()
    )

    ranked_stmt = (
        select(Product.id)
        .join(agg, agg.c.product_id == Product.id)
        .where(*conditions)
    )

    hidden_single_shop = 0
    if multi_shop_only:
        # Counted, not silently dropped: the UI offers to show these, otherwise
        # a search for a product only one shop stocks looks like the site has
        # never heard of it.
        hidden_single_shop = (
            session.scalar(
                select(func.count()).select_from(
                    ranked_stmt.where(agg.c.shops_in_stock < 2).subquery()
                )
            )
            or 0
        )
        ranked_stmt = ranked_stmt.where(agg.c.shops_in_stock >= 2)

    order = {
        "price": (agg.c.min_price.is_(None), agg.c.min_price),
        "unit": (agg.c.min_unit.is_(None), agg.c.min_unit),
        "name": (func.lower(Product.name),),
        "offers": (agg.c.shops_in_stock.desc(), agg.c.offer_count.desc()),
    }[sort]

    total = session.scalar(
        select(func.count()).select_from(ranked_stmt.subquery())
    ) or 0

    page_ids = list(
        session.scalars(
            ranked_stmt.order_by(*order, Product.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )

    by_id = {
        product.id: product
        for product in session.scalars(
            select(Product)
            .where(Product.id.in_(page_ids))
            .options(selectinload(Product.offers).selectinload(Offer.shop))
        )
    }

    return SearchResponse(
        query=q,
        total=total,
        page=page,
        page_size=page_size,
        # page_ids preserves the ranking; the dict lookup does not.
        results=[
            _summarise(by_id[pid], list(by_id[pid].offers))
            for pid in page_ids
            if pid in by_id
        ],
        hidden_single_shop=hidden_single_shop,
    )


@router.get("/products/{slug}", response_model=ProductDetail)
def product_detail(
    slug: str,
    quantity: int = Query(default=1, ge=1, le=99),
    session: Session = Depends(get_session),
):
    product = session.scalar(
        select(Product)
        .where(Product.slug == slug)
        .options(selectinload(Product.offers).selectinload(Offer.shop))
    )
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    offers = sorted(
        (_offer_out(o, quantity) for o in product.offers),
        key=lambda o: (not o.in_stock, o.landed_total_pln or o.price_pln * quantity),
    )
    summary = _summarise(product, list(product.offers))
    return ProductDetail(**summary.model_dump(), offers=offers)


@router.get("/products/{slug}/history")
def price_history(slug: str, session: Session = Depends(get_session)):
    product = session.scalar(select(Product).where(Product.slug == slug))
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    rows = session.execute(
        select(PricePoint, Shop.slug)
        .join(Offer, Offer.id == PricePoint.offer_id)
        .join(Shop, Shop.id == Offer.shop_id)
        .where(Offer.product_id == product.id)
        .order_by(PricePoint.observed_at)
    ).all()

    series: dict[str, list[dict]] = {}
    for point, shop_slug in rows:
        series.setdefault(shop_slug, []).append(
            {
                "price_pln": point.price_pln,
                "in_stock": point.in_stock,
                "observed_at": point.observed_at.isoformat(),
            }
        )
    return {"product": product.slug, "series": series}


@router.post("/basket/optimize")
def basket_optimize(payload: BasketRequest, session: Session = Depends(get_session)):
    if not payload.items:
        raise HTTPException(status_code=400, detail="Basket is empty")

    wanted: dict[int, int] = {}
    for item in payload.items:
        wanted[item.product_id] = wanted.get(item.product_id, 0) + item.quantity

    return _serialise(optimize_basket(session, wanted, payload.country))


@router.get("/stats")
def stats(session: Session = Depends(get_session)):
    multi_shop = session.scalar(
        select(func.count()).select_from(
            select(Offer.product_id)
            .group_by(Offer.product_id)
            .having(func.count(func.distinct(Offer.shop_id)) > 1)
            .subquery()
        )
    )
    return {
        "shops": session.scalar(
            select(func.count(Shop.id)).where(Shop.active.is_(True))
        ),
        "offers": session.scalar(select(func.count(Offer.id))),
        "products": session.scalar(select(func.count(Product.id))),
        "products_in_multiple_shops": multi_shop or 0,
        "market": settings.market_country,
        "currency": settings.display_currency,
        "sorts": SORTS,
    }
