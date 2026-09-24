"""Given a shopping list, find the cheapest way to actually buy it.

This is the feature a plain price-comparison site cannot give you. Buying each
item from whichever shop is cheapest looks optimal until you pay shipping four
times. Buying everything from one shop pays shipping once but overpays on items.
The real answer is usually a split across two shops, and it is not obvious.

We solve it exactly by enumerating subsets of candidate shops. With the handful
of shops that serve any one market this is instant, and exactness matters: a
greedy answer that is 4 PLN worse undermines the whole premise of the site.
Above `EXACT_MAX_SHOPS` we fall back to greedy descent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..config import settings
from ..models import Offer, Product, Shop
from ..shipping import engine as shipping_engine

EXACT_MAX_SHOPS = 16


def to_pln(amount: float, currency: str) -> float:
    return round(amount * settings.fx_rates_to_pln.get(currency, 1.0), 2)


@dataclass
class LineItem:
    product_id: int
    product_name: str
    quantity: int
    shop_slug: str
    shop_name: str
    offer_id: int
    offer_title: str
    offer_url: str
    unit_price_pln: float
    line_total_pln: float


@dataclass
class ShopParcel:
    shop_slug: str
    shop_name: str
    items: list[LineItem] = field(default_factory=list)
    subtotal_pln: float = 0.0
    shipping_pln: float = 0.0
    shipping_method: str = ""
    shipping_estimated: bool = True
    shipping_confidence: str = "low"
    free_shipping_applied: bool = False
    amount_to_free_shipping: float | None = None
    weight_grams: int = 0
    min_days: int = 0
    max_days: int = 0
    warnings: list[str] = field(default_factory=list)
    # A real field, not a property: dataclasses.asdict() drops properties, and
    # this has to survive serialisation into the API response.
    total_pln: float = 0.0


@dataclass
class BasketPlan:
    strategy: str
    parcels: list[ShopParcel]
    goods_pln: float
    shipping_pln: float
    total_pln: float
    max_days: int
    missing_product_ids: list[int] = field(default_factory=list)
    any_estimated_shipping: bool = False


def _eligible_offers(
    session: Session, product_ids: list[int], country: str
) -> dict[int, list[Offer]]:
    """Cheapest in-stock offer per (product, shop) for shops serving `country`."""
    rows = list(
        session.scalars(
            select(Offer)
            .options(selectinload(Offer.shop))
            .where(
                Offer.product_id.in_(product_ids),
                Offer.in_stock.is_(True),
            )
            .order_by(Offer.price_pln)
        )
    )
    best: dict[tuple[int, int], Offer] = {}
    for offer in rows:
        shop = offer.shop
        if not shop.active or country not in (shop.ships_to or []):
            continue
        key = (offer.product_id, shop.id)
        if key not in best:  # ordered by price, so first wins
            best[key] = offer

    by_product: dict[int, list[Offer]] = {pid: [] for pid in product_ids}
    for (product_id, _), offer in best.items():
        by_product[product_id].append(offer)
    return by_product


def _build_parcels(
    assignment: dict[int, Offer],
    quantities: dict[int, int],
    products: dict[int, Product],
) -> list[ShopParcel]:
    parcels: dict[str, ShopParcel] = {}
    weights: dict[str, list[tuple[int | None, int]]] = {}

    for product_id, offer in assignment.items():
        shop = offer.shop
        parcel = parcels.setdefault(
            shop.slug, ShopParcel(shop_slug=shop.slug, shop_name=shop.name)
        )
        weights.setdefault(shop.slug, [])
        qty = quantities[product_id]
        line_total = round(offer.price_pln * qty, 2)
        parcel.items.append(
            LineItem(
                product_id=product_id,
                product_name=products[product_id].name,
                quantity=qty,
                shop_slug=shop.slug,
                shop_name=shop.name,
                offer_id=offer.id,
                offer_title=offer.title,
                offer_url=offer.url,
                unit_price_pln=offer.price_pln,
                line_total_pln=line_total,
            )
        )
        parcel.subtotal_pln = round(parcel.subtotal_pln + line_total, 2)
        weights[shop.slug].append((offer.weight_grams, qty))

    for slug, parcel in parcels.items():
        shop = assignment[
            next(pid for pid, o in assignment.items() if o.shop.slug == slug)
        ].shop
        parcel.weight_grams = shipping_engine.basket_weight(weights[slug])
        # Thresholds are denominated in the shop's own currency.
        rate = settings.fx_rates_to_pln.get(shop.currency, 1.0)
        subtotal_native = parcel.subtotal_pln / rate if rate else parcel.subtotal_pln

        quote = shipping_engine.quote(
            shop.slug, shop.shipping_rules, subtotal_native,
            parcel.weight_grams, shop.currency,
        )
        if quote:
            parcel.shipping_pln = to_pln(quote.cost, quote.currency)
            parcel.shipping_method = quote.method
            parcel.shipping_estimated = quote.estimated
            parcel.shipping_confidence = quote.confidence
            parcel.free_shipping_applied = quote.free_applied
            parcel.min_days, parcel.max_days = quote.min_days, quote.max_days
            parcel.warnings = list(quote.notes)
            if quote.over_weight_limit:
                parcel.warnings.append("Basket exceeds this shop's parcel limit.")
        else:
            parcel.warnings.append("No shipping rule on file — cost not included.")

        gap = shipping_engine.amount_to_free_shipping(
            shop.shipping_rules, subtotal_native
        )
        parcel.amount_to_free_shipping = to_pln(gap, shop.currency) if gap else gap
        parcel.total_pln = round(parcel.subtotal_pln + parcel.shipping_pln, 2)

    return list(parcels.values())


def _plan_from_assignment(
    strategy: str,
    assignment: dict[int, Offer],
    quantities: dict[int, int],
    products: dict[int, Product],
    missing: list[int],
) -> BasketPlan:
    parcels = _build_parcels(assignment, quantities, products)
    goods = round(sum(p.subtotal_pln for p in parcels), 2)
    shipping = round(sum(p.shipping_pln for p in parcels), 2)
    return BasketPlan(
        strategy=strategy,
        parcels=sorted(parcels, key=lambda p: -p.total_pln),
        goods_pln=goods,
        shipping_pln=shipping,
        total_pln=round(goods + shipping, 2),
        max_days=max((p.max_days for p in parcels), default=0),
        missing_product_ids=missing,
        any_estimated_shipping=any(
            p.shipping_estimated and p.shipping_pln > 0 for p in parcels
        ),
    )


def _cost_of_subset(
    shop_ids: frozenset[int],
    offers_by_product: dict[int, list[Offer]],
    quantities: dict[int, int],
) -> tuple[float, dict[int, Offer]] | None:
    """Goods+shipping for restricting the basket to `shop_ids`. None if the
    subset cannot supply every item."""
    assignment: dict[int, Offer] = {}
    per_shop_subtotal: dict[int, float] = {}
    per_shop_weight: dict[int, list[tuple[int | None, int]]] = {}

    for product_id, offers in offers_by_product.items():
        usable = [o for o in offers if o.shop_id in shop_ids]
        if not usable:
            return None
        offer = min(usable, key=lambda o: o.price_pln)
        assignment[product_id] = offer
        qty = quantities[product_id]
        per_shop_subtotal[offer.shop_id] = (
            per_shop_subtotal.get(offer.shop_id, 0.0) + offer.price_pln * qty
        )
        per_shop_weight.setdefault(offer.shop_id, []).append((offer.weight_grams, qty))

    total = sum(per_shop_subtotal.values())
    for shop_id, subtotal_pln in per_shop_subtotal.items():
        shop = next(
            o.shop for o in assignment.values() if o.shop_id == shop_id
        )
        rate = settings.fx_rates_to_pln.get(shop.currency, 1.0)
        quote = shipping_engine.quote(
            shop.slug,
            shop.shipping_rules,
            subtotal_pln / rate if rate else subtotal_pln,
            shipping_engine.basket_weight(per_shop_weight[shop_id]),
            shop.currency,
        )
        if quote:
            total += to_pln(quote.cost, quote.currency)
    return round(total, 2), assignment


def optimize_basket(
    session: Session,
    wanted: dict[int, int],
    country: str | None = None,
) -> dict:
    """`wanted` maps product_id -> quantity. Returns the optimal plan plus the
    baselines it should be judged against."""
    country = country or settings.market_country
    product_ids = list(wanted)
    products = {
        p.id: p for p in session.scalars(select(Product).where(Product.id.in_(product_ids)))
    }
    offers_by_product = _eligible_offers(session, product_ids, country)

    missing = [pid for pid, offers in offers_by_product.items() if not offers]
    available = {pid: o for pid, o in offers_by_product.items() if o}
    if not available:
        return {
            "best": None, "single_shop": None, "naive": None,
            "missing_product_ids": missing, "savings_vs_naive_pln": 0.0,
            "savings_vs_single_shop_pln": 0.0,
        }

    quantities = {pid: max(1, int(wanted[pid])) for pid in available}
    shop_ids = sorted({o.shop_id for offers in available.values() for o in offers})

    # --- optimal split -----------------------------------------------------
    best_cost: float | None = None
    best_assignment: dict[int, Offer] | None = None

    if len(shop_ids) <= EXACT_MAX_SHOPS:
        for size in range(1, len(shop_ids) + 1):
            for subset in combinations(shop_ids, size):
                result = _cost_of_subset(frozenset(subset), available, quantities)
                if result and (best_cost is None or result[0] < best_cost):
                    best_cost, best_assignment = result
    else:  # greedy descent: start from all shops, drop the least useful
        current = set(shop_ids)
        result = _cost_of_subset(frozenset(current), available, quantities)
        best_cost, best_assignment = result if result else (None, None)
        improved = True
        while improved and len(current) > 1:
            improved = False
            for shop_id in sorted(current):
                trial = _cost_of_subset(frozenset(current - {shop_id}), available, quantities)
                if trial and (best_cost is None or trial[0] < best_cost):
                    best_cost, best_assignment = trial
                    current.discard(shop_id)
                    improved = True
                    break

    # --- baselines ---------------------------------------------------------
    single_best: tuple[float, dict[int, Offer]] | None = None
    for shop_id in shop_ids:
        result = _cost_of_subset(frozenset({shop_id}), available, quantities)
        if result and (single_best is None or result[0] < single_best[0]):
            single_best = result

    naive_assignment = {
        pid: min(offers, key=lambda o: o.price_pln) for pid, offers in available.items()
    }

    best_plan = (
        _plan_from_assignment("optimal_split", best_assignment, quantities, products, missing)
        if best_assignment
        else None
    )
    single_plan = (
        _plan_from_assignment("single_shop", single_best[1], quantities, products, missing)
        if single_best
        else None
    )
    naive_plan = _plan_from_assignment(
        "cheapest_price_ignoring_shipping", naive_assignment, quantities, products, missing
    )

    return {
        "best": best_plan,
        "single_shop": single_plan,
        "naive": naive_plan,
        "missing_product_ids": missing,
        "savings_vs_naive_pln": (
            round(naive_plan.total_pln - best_plan.total_pln, 2) if best_plan else 0.0
        ),
        "savings_vs_single_shop_pln": (
            round(single_plan.total_pln - best_plan.total_pln, 2)
            if best_plan and single_plan
            else 0.0
        ),
    }
