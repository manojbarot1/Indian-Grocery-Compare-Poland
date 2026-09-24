from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Offer, Product, Shop


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


def make_shop(session, slug, *, free_over=None, band_price=10.0, currency="PLN",
              transit=(2, 3), confidence="high", ships_to=("PL",)) -> Shop:
    shop = Shop(
        slug=slug,
        name=slug.title(),
        url=f"https://{slug}.example",
        platform="shopify",
        country="PL",
        currency=currency,
        ships_to=list(ships_to),
        active=True,
        ingest_config={},
        shipping_rules={
            "confidence": confidence,
            "free_over": free_over,
            "handling_days": [0, 0],
            "methods": [
                {
                    "name": "Kurier",
                    "transit_days": list(transit),
                    "bands": [{"max_kg": 30.0, "price": band_price}],
                }
            ],
        },
    )
    session.add(shop)
    session.flush()
    return shop


def make_product(session, name, *, size_value=1.0, base_unit="kg") -> Product:
    product = Product(
        slug=name.lower().replace(" ", "-"),
        name=name,
        brand=name.split()[0].lower(),
        size_value=size_value,
        size_unit=base_unit,
        base_unit=base_unit,
        match_key=f"{name.split()[0].lower()}|x|{size_value}{base_unit}",
        match_core=name.lower(),
    )
    session.add(product)
    session.flush()
    return product


def make_offer(session, shop, product, price, *, weight_grams=1000, in_stock=True) -> Offer:
    offer = Offer(
        shop_id=shop.id,
        product_id=product.id,
        external_id=f"{shop.slug}-{product.id}-{price}",
        title=product.name,
        url=f"{shop.url}/p/{product.slug}",
        price=price,
        currency=shop.currency,
        price_pln=price,
        in_stock=in_stock,
        weight_grams=weight_grams,
        raw={},
    )
    session.add(offer)
    session.flush()
    return offer
