"""What the landing page puts in front of a first-time visitor.

The default listing used to be sorted by lowest price across the whole
catalogue, which is the one ordering guaranteed to show the worst of it: the
cheapest rows in a grocery catalogue are sold-out incense sticks and single
sachets, and they are stocked by one shop, so a price comparison site opened
on sixty products with nothing to compare and the prices struck through.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app

from .conftest import make_offer, make_product, make_shop


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def names(payload):
    return [r["name"] for r in payload["results"]]


def test_savings_sort_leads_with_the_biggest_gap(client, session):
    a = make_shop(session, "alpha")
    b = make_shop(session, "beta")

    small = make_product(session, "Small Gap Dal")
    make_offer(session, a, small, 10.0)
    make_offer(session, b, small, 12.0)

    big = make_product(session, "Big Gap Rice")
    make_offer(session, a, big, 20.0)
    make_offer(session, b, big, 70.0)
    session.commit()

    assert names(client.get("/api/search").json()) == ["Big Gap Rice", "Small Gap Dal"]


def test_saving_is_measured_between_shops_not_within_one(client, session):
    """A shop listing the same product twice is not a saving.

    Ranking on the raw maximum in-stock price let a 2 zl cross-shop gap
    outrank a 50 zl one, because one shop also stocked a much dearer case.
    """
    a = make_shop(session, "alpha")
    b = make_shop(session, "beta")

    # One shop, two listings 60 zl apart -- a shopper cannot switch to save it.
    within = make_product(session, "Within Shop Ghee")
    make_offer(session, a, within, 10.0)
    make_offer(session, a, within, 70.0)
    make_offer(session, b, within, 11.0)

    across = make_product(session, "Across Shop Atta")
    make_offer(session, a, across, 10.0)
    make_offer(session, b, across, 40.0)
    session.commit()

    assert names(client.get("/api/search").json()) == [
        "Across Shop Atta",
        "Within Shop Ghee",
    ]


def test_unbuyable_products_rank_last_under_every_sort(client, session):
    a = make_shop(session, "alpha")

    sold_out = make_product(session, "Aaa Sold Out Cheap")
    make_offer(session, a, sold_out, 1.0, in_stock=False)

    buyable = make_product(session, "Zzz In Stock Dear")
    make_offer(session, a, buyable, 50.0)
    session.commit()

    # Cheapest-first and alphabetical would both otherwise lead with the
    # sold-out one.
    for sort in ("savings", "price", "unit", "name", "offers"):
        assert names(client.get(f"/api/search?sort={sort}").json()) == [
            "Zzz In Stock Dear",
            "Aaa Sold Out Cheap",
        ], sort


def test_sold_out_products_are_still_returned(client, session):
    """Demoted, not hidden: someone searching a specific item wants to learn
    that it exists and is sold out, rather than that we have never heard of
    it."""
    a = make_shop(session, "alpha")
    gone = make_product(session, "Discontinued Pickle")
    make_offer(session, a, gone, 9.0, in_stock=False)
    session.commit()

    payload = client.get("/api/search?q=pickle").json()
    assert names(payload) == ["Discontinued Pickle"]
    assert payload["total"] == 1
