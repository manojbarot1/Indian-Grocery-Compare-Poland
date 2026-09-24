from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Shop(Base):
    """A merchant we ingest from. Shipping rules live in `shipping_rules` as the
    declarative structure defined in shops.yaml, interpreted by shipping.engine."""

    __tablename__ = "shops"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    url: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(32))
    country: Mapped[str] = mapped_column(String(2))
    currency: Mapped[str] = mapped_column(String(3))
    ships_to: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    ingest_config: Mapped[dict] = mapped_column(JSON, default=dict)
    shipping_rules: Mapped[dict] = mapped_column(JSON, default=dict)
    weight_unit: Mapped[str] = mapped_column(String(8), default="g")

    last_ingest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ingest_status: Mapped[str | None] = mapped_column(String(255))

    offers: Mapped[list["Offer"]] = relationship(back_populates="shop")


class Product(Base):
    """A canonical product — the thing a shopper actually wants. Many shop
    offers collapse into one of these."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(128), index=True)
    category: Mapped[str | None] = mapped_column(String(128), index=True)
    # One level below category, e.g. atta-flour -> besan. Nullable:
    # plenty of products only resolve to the parent aisle.
    subcategory: Mapped[str | None] = mapped_column(String(128), index=True)
    image_url: Mapped[str | None] = mapped_column(Text)

    # Pack size, normalised. base_unit is one of kg | l | pc.
    size_value: Mapped[float | None] = mapped_column(Float)
    size_unit: Mapped[str | None] = mapped_column(String(8))
    base_unit: Mapped[str | None] = mapped_column(String(4))

    # The blocking key used by the matcher; products with the same key are
    # compared against each other.
    match_key: Mapped[str] = mapped_column(String(255), index=True)
    # Canonical tokens only (no brand, no size) — what similarity is scored
    # against, so scoring never re-compares text the key already pinned.
    match_core: Mapped[str] = mapped_column(String(512), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    offers: Mapped[list["Offer"]] = relationship(back_populates="product")


class Offer(Base):
    """One buyable listing at one shop. Price is stored in the shop's own
    currency; `price_pln` is the normalised comparison value."""

    __tablename__ = "offers"
    __table_args__ = (
        UniqueConstraint("shop_id", "external_id", name="uq_offer_shop_external"),
        Index("ix_offers_product_price", "product_id", "price_pln"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shop_id: Mapped[int] = mapped_column(ForeignKey("shops.id"), index=True)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id"), index=True, nullable=True
    )

    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512))
    url: Mapped[str] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(128), index=True)

    price: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    price_pln: Mapped[float] = mapped_column(Float, index=True)
    compare_at_price: Mapped[float | None] = mapped_column(Float)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)

    weight_grams: Mapped[int | None] = mapped_column(Integer)

    # Parsed from the title, e.g. "Daawat Basmati Rice 1kg" -> 1.0 / kg
    brand: Mapped[str | None] = mapped_column(String(128))
    size_value: Mapped[float | None] = mapped_column(Float)
    size_unit: Mapped[str | None] = mapped_column(String(8))
    base_unit: Mapped[str | None] = mapped_column(String(4))
    # Price per kg / litre / piece — the only honest way to compare groceries.
    unit_price_pln: Mapped[float | None] = mapped_column(Float, index=True)

    match_key: Mapped[str | None] = mapped_column(String(255), index=True)
    match_score: Mapped[float | None] = mapped_column(Float)
    match_locked: Mapped[bool] = mapped_column(Boolean, default=False)

    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )

    shop: Mapped["Shop"] = relationship(back_populates="offers")
    product: Mapped["Product | None"] = relationship(back_populates="offers")


class PricePoint(Base):
    """Append-only price history. Written only when a price actually changes,
    so the table stays small and the chart stays meaningful."""

    __tablename__ = "price_points"
    __table_args__ = (Index("ix_price_points_offer_ts", "offer_id", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    offer_id: Mapped[int] = mapped_column(ForeignKey("offers.id"), index=True)
    price_pln: Mapped[float] = mapped_column(Float)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
