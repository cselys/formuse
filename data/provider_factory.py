"""Provider selection / factory (Finnhub migration, Phase 1).

Reads ``data.provider`` from the application settings and constructs the
corresponding ``MarketDataProvider`` implementation. This is the single point
where the primary provider (FinHub today) is chosen — adding a future provider
(Polygon, Alpaca, ...) is a one-line addition here.

Usage
-----
    from data.provider_factory import create_provider
    from utils.config import load_settings

    settings = load_settings()
    provider = create_provider(settings)     # -> FinnhubProvider if "finnhub"
"""
from __future__ import annotations

import os

from data.finnhub_provider import FinnhubProvider
from data.provider_base import MarketDataProvider
from data.yfinance_provider import YFinanceProvider


def create_provider(settings: dict,
                    provider_name: str | None = None) -> MarketDataProvider:
    """Construct the primary market-data provider from settings.

    Parameters
    ----------
    settings : dict
        Application settings (from ``config/settings.yaml``).
    provider_name : str | None
        Optional override of ``data.provider``.

    Returns
    -------
    MarketDataProvider
        A FinnhubProvider, YFinanceProvider, or a fallback.

    Raises
    ------
    ValueError
        If ``data.provider`` is set to an unknown value.
    """
    name = (provider_name or settings.get("data", {}).get("provider", "finnhub")).lower()

    if name == "finnhub":
        finnhub = settings.get("data", {}).get("finnhub", {})
        return FinnhubProvider(
            api_key=os.environ.get(finnhub.get("api_key_env", "FINNHUB_API_KEY")),
            base_url=finnhub.get("base_url", "https://finnhub.io/api/v1"),
            timeout=finnhub.get("timeout_seconds", 15.0),
            retry_count=finnhub.get("retry_count", 3),
            retry_backoff_base=finnhub.get("retry_backoff_base_seconds", 2.0),
            rate_limit_per_minute=finnhub.get("rate_limit_per_minute", 60),
            rate_safety_factor=finnhub.get("rate_safety_factor", 0.80),
        )

    if name == "yfinance":
        return YFinanceProvider(
            retry_count=settings.get("data", {}).get("retry_count", 3),
            retry_backoff_seconds=settings.get("data", {}).get(
                "retry_backoff_seconds", 2.0),
        )

    raise ValueError(
        f"Unknown provider {name!r} for data.provider; "
        "choose 'finnhub' or 'yfinance' (or add a branch in create_provider)."
    )
