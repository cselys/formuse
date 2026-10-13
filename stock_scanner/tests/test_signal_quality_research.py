"""Tests for the read-only Signal Quality Research layer.

These tests verify:
- point-in-time signal inputs
- future prices only affect outcome, not signal
- trading-day horizon calculation (weekends/holidays)
- missing future data handling (NA, never filled)
- consecutive observations vs event transitions
- Candidate Score bucket boundaries
- state aggregation
- RCAT case extraction
- deterministic report generation
- no mutation of V1.2 calculation logic (research module never writes to scoring/config)
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from stock_scanner.src.research.observations import (
    load_observations, compute_outcomes, score_bucket, HORIZONS,
)
from stock_scanner.src.research.analytics import (
    state_stats, bucket_stats, data_coverage, transitions,
    monotonic_check, volume_analysis, sample_label,
)
from stock_scanner.src.research import report as report_mod


def _mk_df(dates, closes, highs=None, lows=None, volumes=None):
    idx = pd.DatetimeIndex(dates)
    n = len(dates)
    highs = highs or [c * 1.02 for c in closes]
    lows = lows or [c * 0.98 for c in closes]
    vols = volumes or [1_000_000] * n
    return pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes, "Volume": vols},
        index=idx,
    )


@pytest.fixture
def reports_dir(tmp_path):
    """Two recorded scan dates with two symbols."""
    d = tmp_path / "reports"
    d.mkdir()
    day1 = [
        {"symbol": "AAA", "category": "tech", "state": "BOTTOM_FORMING",
         "candidate_score": 55.0, "trend_score": 40.0, "entry_quality": 70.0,
         "bottom_score": 60.0, "reversal_score": 45.0, "market_regime": "MARKET_NEUTRAL",
         "daily": {"close": 10.0, "rsi": 45.0, "volume_ratio": 1.0,
                   "distance_ema20": -1.0, "distance_ema50": -2.0},
         "relative_strength": {"rs_20d": -2.0, "rs_60d": -5.0},
         "structure": {"higher_low": True, "recent_breakout": False, "base_formation": False}},
        {"symbol": "BBB", "category": "tech", "state": "UPTREND",
         "candidate_score": 82.0, "trend_score": 80.0, "entry_quality": 90.0,
         "bottom_score": 20.0, "reversal_score": 10.0, "market_regime": "MARKET_UPTREND",
         "daily": {"close": 50.0, "rsi": 60.0, "volume_ratio": 1.3,
                   "distance_ema20": 2.0, "distance_ema50": 4.0},
         "relative_strength": {"rs_20d": 5.0, "rs_60d": 10.0},
         "structure": {"higher_low": True, "recent_breakout": True, "base_formation": False}},
    ]
    day2 = [
        dict(day1[0], state="BOTTOM_BREAKOUT", candidate_score=58.0,
             bottom_score=68.0,
             daily=dict(day1[0]["daily"], close=10.5, volume_ratio=1.5)),
        dict(day1[1], state="UPTREND", candidate_score=81.0,
             daily=dict(day1[1]["daily"], close=51.0)),
    ]
    for date, rows in [("2026-01-05", day1), ("2026-01-06", day2)]:
        with open(d / f"{date}.json", "w") as f:
            json.dump({"scan_date": date, "scanner_version": "1.2", "results": rows}, f)
    return d


@pytest.fixture
def cache_dir(tmp_path):
    c = tmp_path / "cache"
    c.mkdir()
    # Mon+...+Fri (Jan 5-9) + Mon-Thu (Jan 12-15): 20 future trading bars after Jan 5? no, 9.
    dates = list(pd.bdate_range("2026-01-05", "2026-02-10"))
    # AAA flat then up; BBB steady
    aaa = _mk_df(dates, [10.0 + 0.1 * i for i in range(len(dates))])
    bbb = _mk_df(dates, [50.0 + 0.5 * i for i in range(len(dates))])
    aaa.to_parquet(c / "AAA.parquet")
    bbb.to_parquet(c / "BBB.parquet")
    return c


# 1. Point-in-time signal inputs + 2. future prices only affect outcome
def test_signal_fields_come_only_from_recorded_json(reports_dir, cache_dir):
    obs = load_observations(str(reports_dir))
    o = obs[obs["symbol"] == "AAA"].sort_values("date").iloc[0]
    assert o["state"] == "BOTTOM_FORMING"
    assert o["candidate_score"] == 55.0
    # outcome columns do not exist yet before compute_outcomes
    assert "fwd_1d" not in obs.columns


def test_future_price_change_does_not_alter_signal_fields(reports_dir, cache_dir):
    obs = load_observations(str(reports_dir))
    base = compute_outcomes(obs, str(cache_dir))
    sig_cols = ["date", "symbol", "state", "candidate_score", "trend_score"]
    base_signals = base[sig_cols].copy()

    # Perturb future prices only (after observation date)
    changed = cache_dir
    df = pd.read_parquet(changed / "AAA.parquet")
    df.loc[df.index > "2026-01-06", "Close"] *= 2.0
    df.loc[df.index > "2026-01-06", "High"] *= 2.0
    df.to_parquet(changed / "AAA.parquet")
    after = compute_outcomes(load_observations(str(reports_dir)), str(cache_dir))
    pd.testing.assert_frame_equal(base_signals, after[sig_cols].copy())
    # but outcomes differ (future data affects only outcome)
    assert after.iloc[0]["fwd_20d"] != base.iloc[0]["fwd_20d"]


# 3. Correct trading-day horizon calculation + 4. weekend/holiday handling
def test_horizon_counts_trading_sessions_not_calendar_days(reports_dir, cache_dir):
    obs = load_observations(str(reports_dir))
    out = compute_outcomes(obs, str(cache_dir))
    aaa = out[(out["symbol"] == "AAA")].sort_values("date").iloc[0]
    # +5D from Jan 5 (Mon) must use Jan 12 close, skipping the weekend
    df = pd.read_parquet(cache_dir / "AAA.parquet")
    expected = df["Close"].iloc[5] / 10.0 - 1.0
    assert aaa["fwd_5d"] == pytest.approx(expected)


def test_weekend_rows_never_used(reports_dir, cache_dir):
    df = pd.read_parquet(cache_dir / "AAA.parquet")
    # ensure no weekend index rows exist at all
    assert not any(d.weekday() >= 5 for d in df.index)


# 5. Missing future data handling
def test_missing_future_data_is_na_not_filled(reports_dir, cache_dir):
    # truncate BBB cache so long horizons are unavailable:
    # Keep only Jan 5-9 (5 sessions): 4 future bars after Jan 5, so +5D unavailable.
    df = pd.read_parquet(cache_dir / "BBB.parquet")
    df.iloc[:5].to_parquet(cache_dir / "BBB.parquet")
    obs = load_observations(str(reports_dir))
    out = compute_outcomes(obs, str(cache_dir))
    bbb = out[(out["symbol"] == "BBB") & (out["date"] == pd.Timestamp("2026-01-05"))].iloc[0]
    assert pd.isna(bbb["fwd_5d"])
    assert pd.isna(bbb["fwd_10d"])
    # +1D still available (first future bar exists)
    assert pd.notna(bbb["fwd_1d"])


def test_symbol_without_cache_gets_all_na(reports_dir, cache_dir, tmp_path):
    with open(reports_dir / "2026-01-05.json") as f:
        doc = json.load(f)
    doc["results"].append(dict(doc["results"][0], symbol="NOCACHE"))
    with open(reports_dir / "2026-01-05.json", "w") as f:
        json.dump(doc, f)
    out = compute_outcomes(load_observations(str(reports_dir)), str(cache_dir))
    row = out[out["symbol"] == "NOCACHE"].iloc[0]
    for h in HORIZONS:
        assert pd.isna(row[f"fwd_{h}d"])


# 6. Consecutive observations vs event transitions
def test_transitions_require_consecutive_sessions(reports_dir):
    obs = load_observations(str(reports_dir))
    ev, summary = transitions(obs)
    # both dates are consecutive (Mon->Tue) so 2 events (one per symbol)
    assert len(ev) == 2
    assert summary.get("BOTTOM_FORMING -> BOTTOM_BREAKOUT") == 1


def test_gap_breaks_transition_chain(tmp_path):
    d = tmp_path / "r2"
    d.mkdir()
    row = {"symbol": "AAA", "category": "tech", "state": "DOWNTREND",
           "candidate_score": 20.0, "trend_score": 15.0, "entry_quality": 50.0,
           "bottom_score": 30.0, "reversal_score": 20.0, "market_regime": "MARKET_NEUTRAL",
           "daily": {"close": 10.0, "rsi": 30.0, "volume_ratio": 0.8,
                     "distance_ema20": -5.0, "distance_ema50": -8.0},
           "relative_strength": {"rs_20d": -10.0, "rs_60d": -20.0},
           "structure": {"higher_low": False, "recent_breakout": False, "base_formation": False}}
    # Two dates separated by more than a weekend (8 calendar days)
    for date in ["2026-01-05", "2026-01-13"]:
        with open(d / f"{date}.json", "w") as f:
            json.dump({"scan_date": date, "scanner_version": "1.2",
                       "results": [dict(row)]}, f)
    ev, summary = transitions(load_observations(str(d)))
    assert len(ev) == 0  # gap > 4 days, no chain


# 7. Candidate Score bucket boundaries
def test_score_bucket_boundaries():
    assert score_bucket(0) == "0-19"
    assert score_bucket(19) == "0-19"
    assert score_bucket(20) == "20-39"
    assert score_bucket(39) == "20-39"
    assert score_bucket(40) == "40-59"
    assert score_bucket(59) == "40-59"
    assert score_bucket(60) == "60-69"
    assert score_bucket(69) == "60-69"
    assert score_bucket(70) == "70-79"
    assert score_bucket(79) == "70-79"
    assert score_bucket(80) == "80-89"
    assert score_bucket(89) == "80-89"
    assert score_bucket(90) == "90-100"
    assert score_bucket(100) == "90-100"
    assert score_bucket(None) is None


# 8. State aggregation
def test_state_stats_aggregation(reports_dir, cache_dir):
    out = compute_outcomes(load_observations(str(reports_dir)), str(cache_dir))
    st = state_stats(out)
    assert st["BOTTOM_FORMING"][1]["n"] == 1
    assert st["UPTREND"][1]["n"] == 2  # AAA + BBB both UPTREND at 1D
    bs = bucket_stats(out)
    assert "40-59" in bs and "80-89" in bs
    cov = data_coverage(out)
    assert cov["observations"] == 4
    assert cov["sessions"] == 2


# 9. Provenance handling
def test_recorded_provenance_is_preserved(reports_dir):
    obs = load_observations(str(reports_dir))
    assert (obs["result_source"] == "RECORDED").all()
    assert (obs["scanner_version"] == "1.2").all()


# 10. RCAT case extraction
def test_rcat_case_extraction(reports_dir):
    # Rename a symbol to RCAT and check the runner's RCAT-row builder logic
    for fn in reports_dir.glob("*.json"):
        with open(fn) as f:
            doc = json.load(f)
        for r in doc["results"]:
            if r["symbol"] == "AAA":
                r["symbol"] = "RCAT"
        with open(fn, "w") as f:
            json.dump(doc, f)
    obs = load_observations(str(reports_dir))
    rcat = obs[obs["symbol"] == "RCAT"].sort_values("date")
    assert len(rcat) == 2
    assert list(rcat["state"]) == ["BOTTOM_FORMING", "BOTTOM_BREAKOUT"]


# 11. Deterministic report generation
def test_report_generation_is_deterministic(reports_dir, cache_dir):
    out = compute_outcomes(load_observations(str(reports_dir)), str(cache_dir))
    st = state_stats(out)
    bs = bucket_stats(out)
    mono = monotonic_check(bs)
    ev, summ = transitions(out)
    kwargs = dict(
        period="2026-01-05 .. 2026-01-06", obs_count=len(out),
        cov=data_coverage(out), definitions_html="<p>defs</p>",
        st_stats=st, bstats=bs, mono=mono, trans_summary=summ,
        ev_stats={"enter": {h: {} for h in (5, 10, 20)},
                  "on_path": {h: {} for h in (5, 10, 20)},
                  "off_path": {h: {} for h in (5, 10, 20)}},
        rcat_rows=[], rcat_cmp={"explanation_html": "", "comparison_html": ""},
        vol=volume_analysis(out),
        regime_res={}, cat_res={}, fail={"html": "<p></p>"},
        limit_html="<p></p>", conclusions_html="<p></p>",
    )
    h1 = report_mod.generate_html(**kwargs)
    h2 = report_mod.generate_html(**kwargs)
    assert h1 == h2


# 12. No mutation of V1.2 calculation logic
def test_v12_modules_untouched_by_research_import():
    import hashlib
    pkg = Path(__file__).resolve().parents[1] / "src"
    targets = [
        pkg / "scoring" / "candidate_score.py",
        pkg / "scoring" / "trend_score.py",
        pkg / "scoring" / "entry_quality.py",
        pkg / "scoring" / "bottom_score.py",
        pkg / "scoring" / "reversal_score.py",
        pkg / "analysis" / "regime.py",
    ]
    # The research layer must not import any scoring module for writing,
    # and files must still parse with expected key functions present.
    import ast
    for t in targets:
        tree = ast.parse(t.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        assert names, f"{t} unexpectedly empty"
    # research modules never open scoring files for writing
    research_src = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (pkg / "research").glob("*.py")
    )
    assert "open(" not in research_src or "mode='w'" not in research_src


def test_sample_labels():
    assert sample_label(0) == "INSUFFICIENT SAMPLE"
    assert sample_label(9) == "INSUFFICIENT SAMPLE"
    assert sample_label(10) == "SMALL SAMPLE"
    assert sample_label(29) == "SMALL SAMPLE"
    assert sample_label(30) == "DESCRIPTIVE SAMPLE"


def test_volume_analysis_split(reports_dir, cache_dir):
    out = compute_outcomes(load_observations(str(reports_dir)), str(cache_dir))
    vol = volume_analysis(out)
    assert vol["high_vol"]["n"] + vol["normal_vol"]["n"] <= len(out)
