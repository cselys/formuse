"""Theme-level orchestration (spec sections 9-17).

Combines per-stock metrics, breadth, the session return series,
reversal/recovery, state, and ETF comparison into one ThemeMetrics object.
The theme universe comes from config/themes.yaml — nothing is hardcoded.
"""
from __future__ import annotations

from typing import Dict, List

from data.freshness import (
    FreshnessPolicy,
    classify_eligibility,
    compute_eligibility_metadata,
    get_current_eligible_snapshots,
    get_history_eligible_symbols,
)
from data.provider_base import MarketData
from engine.breadth_engine import compute_breadth
from engine.reversal_engine import analyze_history, classify_state, theme_return_series
from models.schemas import ETFComparison, StockSnapshot, ThemeMetrics
from utils.config import get_setting
from utils.logging import get_logger

logger = get_logger(__name__)


def _create_freshness_policy(settings: dict) -> FreshnessPolicy:
    """Create FreshnessPolicy from settings."""
    freshness_settings = get_setting(settings, "data.freshness", {})
    return FreshnessPolicy(
        fresh_max_seconds=freshness_settings.get("fresh_max_seconds", 60),
        stale_threshold_seconds=freshness_settings.get("stale_threshold_seconds", 300),
        include_aging_in_current=freshness_settings.get("include_aging_in_current", False),
    )


def build_theme_metrics(theme: str,
                        theme_cfg: dict,
                        stock_metrics: Dict[str, StockSnapshot],
                        md: MarketData,
                        settings: dict) -> ThemeMetrics:
    """Compute full ThemeMetrics for one configured theme."""
    tickers: List[str] = theme_cfg.get("tickers", [])
    etfs: List[str] = theme_cfg.get("etf", [])

    stocks = [stock_metrics[t] for t in tickers if t in stock_metrics]
    unknown = [t for t in tickers if t not in stock_metrics]
    if unknown:
        logger.warning("theme %s: no data for configured tickers: %s",
                       theme, ", ".join(unknown))

    # Create freshness policy
    policy = _create_freshness_policy(settings)

    # Get eligibility metadata for all stocks in this theme
    meta = compute_eligibility_metadata(stocks, _create_freshness_policy(settings))

    # Only eligible stocks participate in breadth
    eligible_stocks = get_current_eligible_snapshots(stocks, _create_freshness_policy(settings))
    breadth = compute_breadth(eligible_stocks, settings, total=len(tickers))

    # Theme history from valid constituents' intraday bars (spec 13).
    # Only FRESH stocks participate in history
    fresh_symbols = get_history_eligible_symbols(stocks, _create_freshness_policy(settings))
    prev_close_map = {s.symbol: s.previous_close
                      for s in stocks if s.previous_close is not None}
    flat = get_setting(settings, "classification.flat_threshold", 0.10)
    history = theme_return_series(md.bars, prev_close_map, list(fresh_symbols), flat)
    hist = analyze_history(history, settings)

    state = classify_state(
        avg_return=breadth["average_return"],
        avg_change_from_open=breadth["average_change_from_open"],
        up_percent=breadth["up_percent"],
        down_percent=breadth["down_percent"],
        reversal_from_high=hist["reversal_from_high"],
        recovery_from_low=hist["recovery_from_low"],
        settings=settings,
        has_history=hist["has_history"],
    )

    # ETF comparison — ETFs are NEVER counted as constituent stocks (spec 17).
    etf_rows: List[ETFComparison] = []
    for etf in etfs:
        sm = stock_metrics.get(etf)
        # Check ETF eligibility
        etf_eligibility = classify_eligibility(sm, _create_freshness_policy(settings)) if sm else None
        if sm is None or not sm.is_valid or sm.change_vs_previous_close is None:
            etf_rows.append(ETFComparison(etf=etf, etf_return=None,
                                          basket_return=breadth["average_return"],
                                          divergence=None, note="no data"))
        elif etf_eligibility and not etf_eligibility.participates_in_current:
            etf_rows.append(ETFComparison(etf=etf, etf_return=None,
                                          basket_return=breadth["average_return"],
                                          divergence=None, note="stale quote excluded"))
        else:
            etf_ret = sm.change_vs_previous_close
            etf_rows.append(ETFComparison(
                etf=etf, etf_return=etf_ret,
                basket_return=breadth["average_return"],
                divergence=etf_ret - breadth["average_return"],
                note=""))

    ts = md.asof.isoformat() if md.asof is not None else (
        md.fetched_at.isoformat() if md.fetched_at is not None else "")

    return ThemeMetrics(
        theme=theme,
        timestamp=ts,
        total_stocks=breadth["total_stocks"],
        valid_stocks=breadth["valid_stocks"],
        missing_stocks=breadth["missing_stocks"],
        up_stocks=breadth["up_stocks"],
        down_stocks=breadth["down_stocks"],
        flat_stocks=breadth["flat_stocks"],
        up_percent=breadth["up_percent"],
        down_percent=breadth["down_percent"],
        flat_percent=breadth["flat_percent"],
        strong_up_percent=breadth["strong_up_percent"],
        strong_down_percent=breadth["strong_down_percent"],
        average_return=breadth["average_return"],
        median_return=breadth["median_return"],
        average_change_from_open=breadth["average_change_from_open"],
        median_change_from_open=breadth["median_change_from_open"],
        total_volume=breadth["total_volume"],
        intraday_high=hist["intraday_high"],
        intraday_low=hist["intraday_low"],
        reversal_from_high=hist["reversal_from_high"],
        recovery_from_low=hist["recovery_from_low"],
        breadth_now=hist["breadth_now"],
        breadth_5m_ago=hist["breadth_5m_ago"],
        breadth_15m_ago=hist["breadth_15m_ago"],
        breadth_change_5m=hist["breadth_change_5m"],
        breadth_change_15m=hist["breadth_change_15m"],
        state=state,
        small_sample=breadth["valid_stocks"] < 5,
        etf=etf_rows,
        history=history,
        # Eligibility metadata
        eligible_stocks=meta["eligible_stocks"],
        aging_stocks=meta["aging_stocks"],
        stale_stocks=meta["stale_stocks"],
        no_data_stocks=meta["no_data_stocks"],
        oldest_quote_age=meta["oldest_quote_age"],
        newest_quote_age=meta["newest_quote_age"],
    )


def run_sector_engine(themes_cfg: Dict[str, dict],
                      stock_metrics: Dict[str, StockSnapshot],
                      md: MarketData,
                      settings: dict) -> List[ThemeMetrics]:
    """Run all configured themes. One bad theme never breaks the others."""
    out: List[ThemeMetrics] = []
    for name, cfg in themes_cfg.items():
        try:
            out.append(build_theme_metrics(name, cfg, stock_metrics, md, settings))
        except Exception:
            logger.exception("theme calculation failed for %s", name)
    return out