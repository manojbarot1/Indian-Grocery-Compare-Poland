from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Defaults to SQLite so the project runs with zero setup.
    # Point at Postgres for real use:
    #   postgresql+psycopg://desicena:desicena@localhost:5432/desicena
    database_url: str = f"sqlite:///{BACKEND_DIR / 'desicena.db'}"

    shops_file: Path = BACKEND_DIR / "shops.yaml"

    # The country we price for. Drives which shops are eligible and which
    # shipping rules apply.
    market_country: str = "PL"
    display_currency: str = "PLN"

    # Politeness: we are hitting other people's shops.
    http_timeout: float = 20.0
    http_user_agent: str = (
        "DesiPriceBot/0.1 (+https://desiprice.pl/bot; price comparison; "
        "contact: hello@desiprice.pl)"
    )
    request_delay_seconds: float = 1.0

    # Static FX fallback, used only when a shop prices in a foreign currency.
    # Replace with a real rates feed before launch.
    fx_rates_to_pln: dict[str, float] = {"PLN": 1.0, "EUR": 4.27, "USD": 3.95}

    # Tuned against the live PL catalogue. The score blends order-free string
    # similarity with idf-weighted token overlap, so it sits lower than a raw
    # fuzzy ratio would. Raising it loses true merges; lowering it starts
    # merging different flavours of the same product line.
    match_threshold: float = 0.72


settings = Settings()
