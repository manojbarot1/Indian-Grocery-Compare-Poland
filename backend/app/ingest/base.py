from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from ..config import settings


@dataclass
class RawOffer:
    """Platform-neutral offer, before normalisation and matching."""

    external_id: str
    title: str
    url: str
    price: float
    currency: str
    in_stock: bool = True
    image_url: str | None = None
    sku: str | None = None
    brand: str | None = None
    compare_at_price: float | None = None
    weight_grams: int | None = None
    raw: dict = field(default_factory=dict)


class Adapter:
    """Base class for shop adapters.

    Subclasses implement `fetch`. Everything above them — rate limiting, the
    user agent, error handling — lives here so no adapter can accidentally
    hammer a shop.
    """

    platform = "base"

    def __init__(self, shop) -> None:
        self.shop = shop
        self.config = shop.ingest_config or {}

    def client(self) -> httpx.Client:
        """HTTP client for this shop.

        `ingest.user_agent` overrides the default. Some shops run a security
        plugin whose stock rule serves an HTML block page to any User-Agent
        containing the substring "bot" — indiadabazaar.pl does exactly this,
        while its robots.txt permits the endpoint we read. The override lets a
        shop be given a UA that still names DesiPrice and carries a contact URL,
        just without the token that trips a blunt substring filter.

        It is not for pretending to be a browser: keep the override honest, and
        if a shop genuinely does not want to be read, leave it out instead.
        """
        return httpx.Client(
            timeout=settings.http_timeout,
            headers={
                "User-Agent": self.config.get("user_agent", settings.http_user_agent),
                "Accept": "application/json",
            },
            follow_redirects=True,
        )

    def polite_pause(self) -> None:
        time.sleep(settings.request_delay_seconds)

    def fetch(self) -> list[RawOffer]:  # pragma: no cover - interface
        raise NotImplementedError


def to_float(value, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default
