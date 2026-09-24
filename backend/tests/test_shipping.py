from __future__ import annotations

from app.shipping.engine import (
    DEFAULT_ITEM_WEIGHT_G,
    amount_to_free_shipping,
    basket_weight,
    quote,
)

RULES = {
    "confidence": "high",
    "free_over": 199.99,
    "handling_days": [1, 2],
    "max_order_kg": 30.0,
    "methods": [
        {
            "name": "Kurier",
            "transit_days": [1, 2],
            "bands": [
                {"max_kg": 30.0, "price": 9.99},
                {"max_kg": 60.0, "price": 19.99},
            ],
        }
    ],
}


def test_cheapest_eligible_band_wins():
    q = quote("s", RULES, subtotal=50.0, weight_grams=2000)
    assert q.cost == 9.99


def test_handling_days_are_added_to_transit():
    q = quote("s", RULES, subtotal=50.0, weight_grams=2000)
    assert (q.min_days, q.max_days) == (2, 4)
    assert q.eta_label == "2-4 d"


def test_free_shipping_threshold_applies():
    q = quote("s", RULES, subtotal=250.0, weight_grams=2000)
    assert q.cost == 0.0
    assert q.free_applied is True


def test_threshold_is_exclusive_below_the_limit():
    assert quote("s", RULES, subtotal=199.98, weight_grams=1000).cost == 9.99
    assert quote("s", RULES, subtotal=199.99, weight_grams=1000).cost == 0.0


def test_overweight_basket_is_flagged_and_priced_as_multiple_parcels():
    q = quote("s", RULES, subtotal=50.0, weight_grams=70_000)
    assert q.over_weight_limit is True
    assert q.cost > 19.99
    assert any("multiple orders" in n for n in q.notes)


def test_high_confidence_rules_are_not_marked_estimated():
    assert quote("s", RULES, subtotal=10.0, weight_grams=500).estimated is False


def test_low_confidence_rules_are_marked_estimated():
    rules = {**RULES, "confidence": "low"}
    assert quote("s", rules, subtotal=10.0, weight_grams=500).estimated is True


def test_no_rules_yields_no_quote():
    assert quote("s", {}, subtotal=10.0, weight_grams=500) is None


def test_missing_weights_fall_back_to_a_conservative_default():
    assert basket_weight([(None, 2), (300, 1)]) == DEFAULT_ITEM_WEIGHT_G * 2 + 300


def test_amount_to_free_shipping():
    assert amount_to_free_shipping(RULES, 150.0) == 49.99
    assert amount_to_free_shipping(RULES, 250.0) == 0.0
    assert amount_to_free_shipping({}, 10.0) is None
