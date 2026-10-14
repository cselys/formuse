"""Configuration loading: config/themes.yaml + config/settings.yaml + env vars.

The theme universe lives in YAML on purpose — edit tickers without touching
Python code (spec section 34).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

import yaml
from dotenv import load_dotenv
from data.provider_base import MarketDataProvider

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_THEMES_PATH = PROJECT_ROOT / "config" / "themes.yaml"


def load_yaml(path: os.PathLike | str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(path: os.PathLike | str | None = None) -> Dict[str, Any]:
    """Load application settings (config/settings.yaml)."""
    path = path or os.environ.get("SECTOR_RADAR_SETTINGS", str(DEFAULT_SETTINGS_PATH))
    return load_yaml(path)


def load_themes(path: os.PathLike | str | None = None) -> Dict[str, Dict[str, List[str]]]:
    """Load the theme universe (config/themes.yaml).

    Returns ``{theme_name: {"tickers": [...], "etf": [...]}}``.
    Tickers are upper-cased and de-duplicated (order preserved).
    ETFs must not duplicate the theme's own tickers.
    """
    path = path or os.environ.get("SECTOR_RADAR_THEMES", str(DEFAULT_THEMES_PATH))
    raw = load_yaml(path)
    themes: Dict[str, Dict[str, List[str]]] = {}
    for name, body in raw.items():
        if not isinstance(body, dict):
            continue
        tickers: List[str] = []
        for t in body.get("tickers") or []:
            t = str(t).strip().upper()
            if t and t not in tickers:
                tickers.append(t)
        etf: List[str] = []
        for e in body.get("etf") or []:
            e = str(e).strip().upper()
            if e and e not in etf and e not in tickers:
                etf.append(e)
        themes[str(name)] = {"tickers": tickers, "etf": etf}
    return themes


def all_symbols(themes: Dict[str, Dict[str, List[str]]]) -> List[str]:
    """All distinct tickers + ETFs across themes (for batched downloads)."""
    seen = set()
    out: List[str] = []
    for body in themes.values():
        for s in list(body["tickers"]) + list(body["etf"]):
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


def get_setting(settings: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    """Fetch a nested setting by dotted key, e.g. ``'classification.flat_threshold'``."""
    cur: Any = settings
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def get_factory(provider_name: str) -> MarketDataProvider:
    """Factory function that creates a provider instance by name.

    Parameters
    ----------
    provider_name : str
        Provider name: ``"finnhub"`` or ``"yfinance"``.

    Returns
    -------
    MarketDataProvider
        A provider instance with a ``name`` attribute.

    Raises
    ------
    ValueError
        If the provider name is unknown.
    """
    from data.provider_factory import create_provider
    from utils.config import load_settings

    settings = load_settings()
    return create_provider(settings, provider_name=provider_name)
