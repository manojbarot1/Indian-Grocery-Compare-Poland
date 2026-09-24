"""The optimiser is the product's core claim, so these tests encode the
situations that claim depends on."""

from __future__ import annotations

from app.basket.optimizer import optimize_basket

from .conftest import make_offer, make_product, make_shop


def test_one_shop_wins_when_shipping_dominates(session):
    """Item B is 2 PLN cheaper at shop B, but a second parcel costs 10 PLN.
    Buying everything from shop A must win."""
    a = make_shop(session, "alpha", band_price=10.0)
    b = make_shop(session, "beta", band_price=10.0)
    rice = make_product(session, "Daawat Rice")
    dal = make_product(session, "Heera Dal")

    make_offer(session, a, rice, 20.0)
    make_offer(session, a, dal, 20.0)
    make_offer(session, b, dal, 18.0)
    session.commit()

    result = optimize_basket(session, {rice.id: 1, dal.id: 1})
    best = result["best"]

    assert len(best.parcels) == 1
    assert best.parcels[0].shop_slug == "alpha"
    assert best.total_pln == 50.0  # 20 + 20 + 10 shipping
    # The naive "cheapest price" pick pays shipping twice.
    assert result["naive"].total_pln == 58.0
    assert result["savings_vs_naive_pln"] == 8.0


def test_splitting_wins_when_the_discount_beats_the_extra_shipping(session):
    """Item B is 30 PLN cheaper at shop B — worth paying a second 10 PLN parcel."""
    a = make_shop(session, "alpha", band_price=10.0)
    b = make_shop(session, "beta", band_price=10.0)
    rice = make_product(session, "Daawat Rice")
    dal = make_product(session, "Heera Dal")

    make_offer(session, a, rice, 20.0)
    make_offer(session, a, dal, 50.0)
    make_offer(session, b, dal, 20.0)
    session.commit()

    result = optimize_basket(session, {rice.id: 1, dal.id: 1})
    best = result["best"]

    assert {p.shop_slug for p in best.parcels} == {"alpha", "beta"}
    assert best.total_pln == 60.0  # (20+10) + (20+10)
    assert result["savings_vs_single_shop_pln"] == 20.0  # single shop = 80


def test_free_shipping_threshold_changes_the_answer(session):
    """Shop A is pricier per item but ships free over 100 PLN. Consolidating
    there must beat splitting, and the optimiser has to notice."""
    a = make_shop(session, "alpha", band_price=15.0, free_over=100.0)
    b = make_shop(session, "beta", band_price=15.0)
    rice = make_product(session, "Daawat Rice")
    dal = make_product(session, "Heera Dal")

    make_offer(session, a, rice, 55.0)
    make_offer(session, a, dal, 55.0)
    make_offer(session, b, dal, 50.0)
    session.commit()

    best = optimize_basket(session, {rice.id: 1, dal.id: 1})["best"]

    assert len(best.parcels) == 1
    assert best.parcels[0].free_shipping_applied is True
    assert best.total_pln == 110.0  # vs 55+15 + 50+15 = 135 split


def test_quantities_are_respected_in_price_and_weight(session):
    a = make_shop(session, "alpha", band_price=10.0)
    rice = make_product(session, "Daawat Rice")
    make_offer(session, a, rice, 20.0, weight_grams=1000)
    session.commit()

    best = optimize_basket(session, {rice.id: 3})["best"]

    assert best.goods_pln == 60.0
    assert best.parcels[0].weight_grams == 3000
    assert best.parcels[0].items[0].quantity == 3


def test_out_of_stock_offers_are_ignored(session):
    a = make_shop(session, "alpha", band_price=10.0)
    b = make_shop(session, "beta", band_price=10.0)
    rice = make_product(session, "Daawat Rice")
    make_offer(session, a, rice, 10.0, in_stock=False)
    make_offer(session, b, rice, 25.0)
    session.commit()

    best = optimize_basket(session, {rice.id: 1})["best"]
    assert best.parcels[0].shop_slug == "beta"


def test_shops_that_do_not_deliver_here_are_excluded(session):
    a = make_shop(session, "alpha", band_price=10.0, ships_to=("DE",))
    b = make_shop(session, "beta", band_price=10.0, ships_to=("PL",))
    rice = make_product(session, "Daawat Rice")
    make_offer(session, a, rice, 5.0)
    make_offer(session, b, rice, 25.0)
    session.commit()

    best = optimize_basket(session, {rice.id: 1}, country="PL")["best"]
    assert best.parcels[0].shop_slug == "beta"


def test_unavailable_items_are_reported_not_silently_dropped(session):
    a = make_shop(session, "alpha", band_price=10.0)
    rice = make_product(session, "Daawat Rice")
    ghost = make_product(session, "Nonexistent Thing")
    make_offer(session, a, rice, 20.0)
    session.commit()

    result = optimize_basket(session, {rice.id: 1, ghost.id: 1})
    assert result["missing_product_ids"] == [ghost.id]
    assert result["best"].total_pln == 30.0


def test_foreign_currency_offers_are_converted_for_comparison(session):
    """A EUR shop must be compared in PLN, including its shipping."""
    from app.config import settings

    eur = make_shop(session, "euroshop", band_price=5.0, currency="EUR")
    pln = make_shop(session, "plshop", band_price=10.0, currency="PLN")
    rice = make_product(session, "Daawat Rice")

    # 10 EUR of goods + 5 EUR shipping, converted at the configured rate.
    offer = make_offer(session, eur, rice, 10.0)
    offer.price_pln = round(10.0 * settings.fx_rates_to_pln["EUR"], 2)
    make_offer(session, pln, rice, 100.0)
    session.commit()

    best = optimize_basket(session, {rice.id: 1})["best"]
    expected = round(15.0 * settings.fx_rates_to_pln["EUR"], 2)
    assert best.parcels[0].shop_slug == "euroshop"
    assert best.total_pln == expected
