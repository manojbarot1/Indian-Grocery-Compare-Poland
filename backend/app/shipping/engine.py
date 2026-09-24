"""Work out what a basket actually costs to get to your door.

Grocery comparison is different from electronics comparison: a 5 kg sack of atta
and a 50 g packet of cardamom cost the same to list but wildly different to ship,
and almost every Indian grocer prices shipping in weight bands with a
free-over-X threshold. Comparing sticker prices alone is close to useless.

Every quote carries `estimated` and `confidence`, which the UI must show. We
never present a guessed shipping cost as a quoted one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DEFAULT_ITEM_WEIGHT_G = 500
"""Fallback when a shop publishes no weight. Deliberately generous: better to
over-estimate shipping than to promise a total the shopper cannot get."""


@dataclass
class ShippingQuote:
    shop_slug: str
    method: str
    cost: float
    currency: str
    min_days: int
    max_days: int
    free_applied: bool = False
    estimated: bool = True
    confidence: str = "low"
    over_weight_limit: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def eta_label(self) -> str:
        if self.min_days == self.max_days:
            return f"{self.min_days} d"
        return f"{self.min_days}-{self.max_days} d"


def _band_price(bands: list[dict], weight_kg: float) -> tuple[float | None, bool]:
    """Cheapest band that can carry this weight. Returns (price, over_limit)."""
    if not bands:
        return None, False
    eligible = [b for b in bands if weight_kg <= float(b.get("max_kg", 0))]
    if not eligible:
        # Heavier than anything the shop offers — quote the top band and flag it,
        # because in reality the shop will split it into multiple parcels.
        heaviest = max(bands, key=lambda b: float(b.get("max_kg", 0)))
        top_kg = float(heaviest.get("max_kg") or 1.0)
        parcels = max(1, int(weight_kg // top_kg) + (1 if weight_kg % top_kg else 0))
        return float(heaviest["price"]) * parcels, True
    return float(min(eligible, key=lambda b: float(b["price"]))["price"]), False


def quote(
    shop_slug: str,
    rules: dict,
    subtotal: float,
    weight_grams: int,
    currency: str = "PLN",
) -> ShippingQuote | None:
    """Cheapest shipping option for this basket at this shop.

    `subtotal` and the returned cost are both in the shop's own currency, so the
    free-shipping threshold is compared against the right number.
    """
    if not rules:
        return None

    weight_kg = max(weight_grams, 0) / 1000.0
    confidence = rules.get("confidence", "low")
    notes: list[str] = []
    if rules.get("note"):
        notes.append(str(rules["note"]))

    max_order_kg = rules.get("max_order_kg")
    over_limit = bool(max_order_kg and weight_kg > float(max_order_kg))
    if over_limit:
        notes.append(
            f"Shop caps orders at {max_order_kg} kg; this basket is "
            f"{weight_kg:.1f} kg and would ship as multiple orders."
        )

    best: ShippingQuote | None = None
    for method in rules.get("methods", []):
        price, band_over = _band_price(method.get("bands", []), weight_kg)
        if price is None:
            continue
        transit = method.get("transit_days", [3, 7])
        handling = rules.get("handling_days", [0, 0])
        candidate = ShippingQuote(
            shop_slug=shop_slug,
            method=str(method.get("name", "Shipping")),
            cost=round(price, 2),
            currency=currency,
            min_days=int(transit[0]) + int(handling[0]),
            max_days=int(transit[-1]) + int(handling[-1]),
            estimated=bool(method.get("estimated", confidence != "high")),
            confidence=confidence,
            over_weight_limit=over_limit or band_over,
            notes=list(notes),
        )
        if best is None or candidate.cost < best.cost:
            best = candidate

    if best is None:
        return None

    free_over = rules.get("free_over")
    if free_over is not None and subtotal >= float(free_over):
        best.cost = 0.0
        best.free_applied = True
        if rules.get("free_over_note"):
            best.notes.append(
                f"Free shipping applies to {rules['free_over_note']} only — "
                "verify at checkout."
            )
    return best


def basket_weight(items: list[tuple[int | None, int]]) -> int:
    """Total grams for [(weight_grams_or_None, qty), ...], applying the fallback
    weight to anything the shop did not publish."""
    return sum((w or DEFAULT_ITEM_WEIGHT_G) * qty for w, qty in items)


def amount_to_free_shipping(rules: dict, subtotal: float) -> float | None:
    """How much more to spend to unlock free delivery, or None if N/A."""
    free_over = rules.get("free_over")
    if free_over is None:
        return None
    gap = float(free_over) - subtotal
    return round(gap, 2) if gap > 0 else 0.0
