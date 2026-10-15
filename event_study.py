#!/usr/bin/env python3
"""
Daily state-tape event study for stock_scanner (cselys/formuse).

Replays the scanner's OWN scoring + state classification on EVERY historical
trading day (point-in-time, no lookahead), then answers three questions:

  1. Do states like REVERSAL / BOTTOM_BREAKOUT predict forward returns?
     -> state_stats.csv  (per state: n, avg fwd +5/+10/+20d, win rate)
  2. Do CONSECUTIVE signals (streaks) beat one-off signals?
     -> streak_stats.csv (per state x streak bucket: 1 day / 2 days / 3+ days)
  3. Does a HIGHER score actually mean better forward returns? (score calibration)
     -> score_calibration.csv (reversal/bottom score deciles -> avg fwd returns)
  4. Which STATE PATHS predict? e.g. DOWNTREND>REVERSAL>UPTREND vs one-off labels
     -> path_stats_2d.csv / path_stats_3d.csv (every 2-gram / 3-gram of states)
     -> transitions.csv (P(next_state | current_state) matrix)

All indicator / scoring / state logic is IMPORTED from the repo itself --
this script only adds the daily replay loop, streak tracking, and statistics.
No strategy logic is duplicated here.

Entry realism: signal generated on day t's close -> entered at next trading
day's OPEN (no lookahead). Forward returns are measured vs that entry price.

Usage:
    # full universe, config auto-resolved (./config or <repo>/stock_scanner/config)
    python event_study.py --start 2022-01-01 --end 2026-10-01 --out ./event_out

    # one category only
    python event_study.py --categories semiconductors --start 2024-01-01 \
        --end 2024-12-31 --out ./event_semi

    # explicit symbol override / config dir
    python event_study.py --config-dir /path/to/config \
        --symbols NVDA,AAPL,MSFT --start 2022-01-01 --end 2026-10-01

Requires: yfinance, pandas, numpy, PyYAML, and the stock_scanner package
          importable (it lives next to this script).
"""

import os
import sys
import argparse
import warnings
from datetime import timedelta

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

# Make stock_scanner importable (it lives next to this script).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import types as _types
import importlib as _importlib


def _stub_missing_src_data():
    """The GitHub repo does not commit stock_scanner/src/data/ (yfinance_loader,
    market_calendar, historical_cache, scanner_history), so a fresh clone cannot
    even `import stock_scanner`. This provides the names needed at IMPORT time
    only. This script never calls them (it uses yfinance directly).
    Fix properly with: git add stock_scanner/src/data
    """
    def _dummy(*a, **k):
        raise RuntimeError("stubbed stock_scanner.src.data member called")

    pkg = _types.ModuleType("stock_scanner.src.data")
    pkg.__path__ = []
    sys.modules["stock_scanner.src.data"] = pkg

    def _mod(name, members):
        m = _types.ModuleType(f"stock_scanner.src.data.{name}")
        for mem in members:
            setattr(m, mem, type(mem, (), {"__init__": lambda s, *a, **k: None})
                    if mem[0].isupper() else _dummy)
        sys.modules[f"stock_scanner.src.data.{name}"] = m

    _mod("market_calendar", ["cutoff_timestamp", "completed_daily",
                             "completed_weekly", "week_context",
                             "uses_completed_weeks", "session_dates", "schedule"])
    _mod("yfinance_loader", ["YFinanceLoader", "DataValidationError"])
    _mod("historical_cache", ["update_symbol_cache", "update_universe_cache",
                              "load_cached_data"])
    _mod("scanner_history", ["calculation_signature", "history_context",
                             "weekly_policy", "result_fingerprint"])


def _load_scanner():
    # Pre-register a lightweight `stock_scanner.src` package pointing at the real
    # directory, so its __init__ (which imports scanner.py -> pydantic, reporting,
    # and the missing src/data tree) is never executed. We only need the pure
    # leaf modules: analysis.daily/weekly/relative_strength/regime + scoring.*.
    import stock_scanner  # noqa: F401  (top-level __init__ is docstring-only)
    src_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "stock_scanner", "src")
    _stub_missing_src_data()
    stub = _types.ModuleType("stock_scanner.src")
    stub.__path__ = [src_dir]
    sys.modules["stock_scanner.src"] = stub

    from stock_scanner.src.analysis.daily import run_daily_analysis
    from stock_scanner.src.analysis.weekly import run_weekly_analysis
    from stock_scanner.src.analysis.relative_strength import calculate_relative_strength
    from stock_scanner.src.analysis.regime import classify_state
    from stock_scanner.src.scoring.trend_score import calculate_trend_score
    from stock_scanner.src.scoring.bottom_score import calculate_bottom_score
    from stock_scanner.src.scoring.reversal_score import calculate_reversal_score
    return (run_daily_analysis, run_weekly_analysis, calculate_relative_strength,
            classify_state, calculate_trend_score, calculate_bottom_score,
            calculate_reversal_score)


(run_daily_analysis, run_weekly_analysis, calculate_relative_strength,
 classify_state, calculate_trend_score, calculate_bottom_score,
 calculate_reversal_score) = _load_scanner()

WARMUP_DAYS = 500          # history needed before `start` (EMA200 / 52w high-low)
FWD_HORIZONS = (5, 10, 20)  # forward-return horizons in trading days
BENCHMARK = "SPY"


# ---------------------------------------------------------------- data ---

def load_bars(symbols, start, end, cache_dir=None):
    """Download daily OHLCV (adjusted) for symbols + benchmark (batched).

    If cache_dir is given, per-symbol parquet cache is used: cached bars are
    reused, missing ones are downloaded and then cached. Survives restarts.
    """
    import yfinance as yf

    warm_start = (pd.to_datetime(start) - timedelta(days=WARMUP_DAYS)).strftime("%Y-%m-%d")
    bars, need = {}, []
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        for sym in symbols:
            p = os.path.join(cache_dir, f"{sym}.csv")
            if os.path.isfile(p):
                try:
                    bars[sym] = pd.read_csv(p, index_col=0, parse_dates=True)
                    continue
                except Exception:
                    pass
            need.append(sym)
    else:
        need = list(symbols)
    if need:
        print(f"  downloading {len(need)} symbols...")
    else:
        print("  all bars from cache")
    if need:
        try:
            df_all = yf.download(need, start=warm_start, end=end, auto_adjust=True,
                                 progress=False, threads=True, group_by="ticker")
            batched = isinstance(df_all.columns, pd.MultiIndex)
        except Exception as e:
            print(f"  [warn] batch download failed ({e}), falling back to serial")
            df_all, batched = None, False

        def _clean(df):
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
            df = df[cols].dropna()
            df.index = pd.to_datetime(df.index).tz_localize(None)
            return df

        fresh = {}
        if batched:
            for sym in need:
                try:
                    df = _clean(df_all[sym].copy())
                except (KeyError, AttributeError):
                    print(f"  [warn] no data for {sym}, skipped")
                    continue
                if df.empty:
                    print(f"  [warn] no data for {sym}, skipped")
                    continue
                fresh[sym] = df
        else:
            for sym in need:  # serial fallback
                df = yf.download(sym, start=warm_start, end=end, auto_adjust=True,
                                 progress=False, threads=False)
                if df is None or df.empty:
                    print(f"  [warn] no data for {sym}, skipped")
                    continue
                fresh[sym] = _clean(df)
        if cache_dir:
            for sym, df in fresh.items():
                try:
                    df.to_csv(os.path.join(cache_dir, f"{sym}.csv"))
                except Exception as e:
                    print(f"  [warn] cache write failed for {sym}: {e}")
        bars.update(fresh)
    print(f"  bars ready: {len(bars)} symbols")
    return bars


# --------------------------------------------------------------- tape ---

def classify_one_day(df_slice, spy_slice, config, state_history=None, trend_history=None):
    """Run the scanner's full pipeline on data up to (and including) one day.

    state_history / trend_history are causal (days strictly before today);
    they enable the 2026-10-15 state gates (BOTTOM washout, REVERSAL express).
    """
    # Weekly bars resampled point-in-time
    df_w = df_slice.resample("W-FRI").agg(
        {"Open": "first", "High": "max", "Low": "min",
         "Close": "last", "Volume": "sum"}).dropna()

    _, daily_ind = run_daily_analysis(df_slice, config)
    weekly_ind = run_weekly_analysis(df_w, config)
    rs = calculate_relative_strength(df_slice, spy_slice)
    struct = daily_ind.get("structure", {})

    trend, _ = calculate_trend_score(weekly_ind, daily_ind, struct, rs, config)
    bottom, _ = calculate_bottom_score(daily_ind, struct, rs, df_slice, config)
    reversal, _ = calculate_reversal_score(daily_ind, weekly_ind, struct, rs, config)
    state = classify_state(trend, bottom, reversal, daily_ind, weekly_ind,
                           struct, rs, config,
                           state_history=state_history, trend_history=trend_history)
    return state, trend, bottom, reversal


def build_tape(bars, config, start, end, ckpt_dir=None):
    """Replay every trading day in [start, end] -> one row per (date, symbol).

    If ckpt_dir is given, each symbol's tape is checkpointed to parquet as it
    completes; reruns skip symbols that already have a checkpoint.
    """
    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    spy = bars.get(BENCHMARK)
    if ckpt_dir:
        os.makedirs(ckpt_dir, exist_ok=True)
    rows = []

    for sym, df in bars.items():
        if sym == BENCHMARK:
            continue
        ckpt = os.path.join(ckpt_dir, f"{sym}.csv") if ckpt_dir else None
        if ckpt and os.path.isfile(ckpt):
            try:
                done = pd.read_csv(ckpt, parse_dates=["date"])
                rows.append(done)
                print(f"  tape {sym}: resumed {len(done)} rows from checkpoint")
                continue
            except Exception:
                pass
        dates = df.index[(df.index >= start_dt) & (df.index <= end_dt)]
        sym_rows, n = [], 0
        hist_states, hist_trends = [], []  # causal history for 2026-10-15 gates
        for i, day in enumerate(dates):
            df_slice = df.loc[:day]
            if len(df_slice) < 300:      # not enough history for EMA200/52w
                continue
            spy_slice = spy.loc[:day] if spy is not None else pd.DataFrame()
            try:
                state, trend, bottom, reversal = classify_one_day(
                    df_slice, spy_slice, config,
                    state_history=hist_states, trend_history=hist_trends)
            except Exception as e:       # one bad day must not kill the run
                print(f"  [warn] {sym} {day.date()}: {e}")
                continue
            sym_rows.append({
                "date": day, "symbol": sym, "state": state,
                "trend_score": trend, "bottom_score": bottom,
                "reversal_score": reversal,
                "close": float(df_slice["Close"].iloc[-1]),
            })
            hist_states.append(state)
            hist_trends.append(float(trend))
            n += 1
        print(f"  tape {sym}: {n} classified days")
        if sym_rows and ckpt:
            pd.DataFrame(sym_rows).to_csv(ckpt, index=False)
        rows.append(pd.DataFrame(sym_rows))
    tape = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    if not tape.empty:
        tape = tape.sort_values(["symbol", "date"]).reset_index(drop=True)
    return tape


# ----------------------------------------------- forwards & streaks ---

def add_forwards(tape, bars):
    """Entry = next trading day's open; fwd returns vs entry."""
    if tape.empty:
        return tape
    tape = tape.copy()
    for h in FWD_HORIZONS:
        tape[f"fwd_{h}d"] = np.nan

    idx_of = {sym: df.index for sym, df in bars.items()}
    for i, row in tape.iterrows():
        df = bars[row["symbol"]]
        idx = idx_of[row["symbol"]]
        pos = idx.get_loc(row["date"])
        if isinstance(pos, slice):
            pos = pos.stop - 1
        entry_pos, closes = pos + 1, {}
        if entry_pos >= len(idx):
            continue
        entry = float(df["Open"].iloc[entry_pos])
        if entry <= 0:
            continue
        for h in FWD_HORIZONS:
            cpos = entry_pos + h - 1
            if cpos < len(idx):
                tape.at[i, f"fwd_{h}d"] = float(df["Close"].iloc[cpos]) / entry - 1.0
    return tape


def add_streaks(tape):
    """streak = consecutive days ending today with the same state (per symbol)."""
    if tape.empty:
        return tape
    tape = tape.copy()
    tape["streak"] = 1
    for sym, g in tape.groupby("symbol", sort=False):
        streak, prev = 1, None
        for ix in g.index:
            st = tape.at[ix, "state"]
            streak = streak + 1 if st == prev else 1
            prev = st
            tape.at[ix, "streak"] = streak
    tape["streak_bucket"] = pd.cut(
        tape["streak"], bins=[0, 1, 2, 100], labels=["1d", "2d", "3d+"])
    return tape


# ----------------------------------------------- paths (state sequences) ---

def add_paths(tape, max_k=3):
    """Trailing state paths ending today: path_2d='A>B', path_3d='A>B>C'.

    This captures what the user means by "consecutive": not just streaks of
    the SAME state, but sequences like DOWNTREND>REVERSAL>UPTREND.
    """
    if tape.empty:
        return tape
    tape = tape.copy()
    for k in (2, 3):
        col = f"path_{k}d"
        tape[col] = None
        for _sym, g in tape.groupby("symbol", sort=False):
            states = tape.loc[g.index, "state"]
            shifted = [states.shift(i) for i in range(k - 1, -1, -1)]
            path = shifted[0].astype(str)
            for s in shifted[1:]:
                path = path + ">" + s.astype(str)
            valid = pd.concat(shifted, axis=1).notna().all(axis=1)
            tape.loc[g.index, col] = path.where(valid)
    return tape


# ---------------------------------------------------------------- stats ---

def summarize(tape):
    """Per-state, per-streak, and score-calibration tables."""
    t = tape.dropna(subset=["fwd_10d"]).copy()
    out = {}

    g = t.groupby("state")
    out["state"] = pd.DataFrame({
        "n": g.size(),
        **{f"avg_fwd_{h}d": g[f"fwd_{h}d"].mean() for h in FWD_HORIZONS},
        "win_rate_10d": g["fwd_10d"].apply(lambda s: (s > 0).mean()),
        "avg_reversal_score": g["reversal_score"].mean(),
        "avg_bottom_score": g["bottom_score"].mean(),
    }).reset_index().sort_values("n", ascending=False)

    g2 = t.groupby(["state", "streak_bucket"], observed=True)
    out["streak"] = pd.DataFrame({
        "n": g2.size(),
        "avg_fwd_10d": g2["fwd_10d"].mean(),
        "win_rate_10d": g2["fwd_10d"].apply(lambda s: (s > 0).mean()),
    }).reset_index().sort_values(["state", "streak_bucket"])

    cal = []
    for score_col in ("reversal_score", "bottom_score"):
        s = t[score_col]
        if s.nunique() < 10:
            continue
        t["_dec"] = pd.qcut(s, 10, labels=False, duplicates="drop")
        g3 = t.groupby("_dec", observed=True)
        d = pd.DataFrame({
            "score_decile": g3.size().index,
            "n": g3.size().values,
            "avg_score": g3[score_col].mean().values,
            "avg_fwd_10d": g3["fwd_10d"].mean().values,
            "win_rate_10d": g3["fwd_10d"].apply(lambda x: (x > 0).mean()).values,
        })
        d.insert(0, "score", score_col)
        cal.append(d)
    out["calibration"] = pd.concat(cal, ignore_index=True) if cal else pd.DataFrame()

    # --- state paths (2-grams / 3-grams): which sequences predict? ---
    for k in (2, 3):
        col = f"path_{k}d"
        if col not in t.columns:
            continue
        g4 = t.dropna(subset=[col]).groupby(col, observed=True)
        out[f"path{k}"] = pd.DataFrame({
            "n": g4.size(),
            **{f"avg_fwd_{h}d": g4[f"fwd_{h}d"].mean() for h in FWD_HORIZONS},
            "win_rate_10d": g4["fwd_10d"].apply(lambda s: (s > 0).mean()),
        }).reset_index().sort_values("n", ascending=False)

    # --- transition matrix P(next | current) ---
    if "path_2d" in t.columns:
        tt = t.dropna(subset=["path_2d"]).copy()
        parts = tt["path_2d"].str.split(">", expand=True)
        tt["from_state"], tt["to_state"] = parts[0], parts[1]
        g5 = tt.groupby(["from_state", "to_state"], observed=True)
        tr = g5.size().reset_index(name="n")
        tr["prob"] = tr["n"] / tr.groupby("from_state")["n"].transform("sum")
        out["transitions"] = tr.sort_values(["from_state", "prob"],
                                            ascending=[True, False]).reset_index(drop=True)
    # --- per-year breakdowns (regimes change; recent years are what matter) ---
    t["year"] = t["date"].dt.year
    gy = t.groupby(["year", "state"], observed=True)
    out["state_by_year"] = pd.DataFrame({
        "n": gy.size(),
        **{f"avg_fwd_{h}d": gy[f"fwd_{h}d"].mean() for h in FWD_HORIZONS},
        "win_rate_10d": gy["fwd_10d"].apply(lambda s: (s > 0).mean()),
    }).reset_index().sort_values(["year", "n"], ascending=[True, False])

    if "path_3d" in t.columns:
        gp = t.dropna(subset=["path_3d"]).groupby(["year", "path_3d"],
                                                  observed=True)
        out["path3_by_year"] = pd.DataFrame({
            "n": gp.size(),
            **{f"avg_fwd_{h}d": gp[f"fwd_{h}d"].mean() for h in FWD_HORIZONS},
            "win_rate_10d": gp["fwd_10d"].apply(lambda s: (s > 0).mean()),
        }).reset_index().sort_values(["year", "n"], ascending=[True, False])
    return out


# ------------------------------------------------------------------ cli ---

def _default_config_dir():
    # Same convention as stock_scanner/run_scanner.py:
    # ./config if it has scanner.yaml, else <repo>/config relative to this file.
    from pathlib import Path
    if Path("config/scanner.yaml").is_file():
        return Path("config")
    return Path(__file__).resolve().parent / "stock_scanner" / "config"


def main():
    ap = argparse.ArgumentParser(description="Daily state-tape event study")
    ap.add_argument("--config-dir", default=_default_config_dir(),
                    help="dir with scanner.yaml + universe.yaml "
                         "(default: ./config or <repo>/stock_scanner/config)")
    ap.add_argument("--symbols",
                    help="comma-separated override; default: all universe.yaml symbols")
    ap.add_argument("--categories",
                    help="comma-separated universe categories to include "
                         "(e.g. semiconductors,technology)")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="./event_study_out")
    a = ap.parse_args()

    from pathlib import Path
    config_dir = Path(a.config_dir)
    with open(config_dir / "scanner.yaml", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if a.symbols:
        symbols = [s.strip().upper() for s in a.symbols.split(",") if s.strip()]
    else:
        with open(config_dir / "universe.yaml", encoding="utf-8") as f:
            u = yaml.safe_load(f)
        cats = ([c.strip() for c in a.categories.split(",")]
                if a.categories else None)
        symbols = []
        for cat, v in (u.get("categories") or {}).items():
            if cats and cat not in cats:
                continue
            symbols += [s for s in (v.get("symbols") or []) if isinstance(s, str)]
        symbols = list(dict.fromkeys(symbols))  # de-dup, keep order
    if BENCHMARK not in symbols:
        symbols = symbols + [BENCHMARK]
    print(f"config: {config_dir} | symbols: {len(symbols)}")

    os.makedirs(a.out, exist_ok=True)
    cache_dir = os.path.join(a.out, "_bars_cache")
    ckpt_dir = os.path.join(a.out, "_tape_parts")
    print("downloading bars...")
    bars = load_bars(symbols, a.start, a.end, cache_dir=cache_dir)
    print("replaying state tape (point-in-time, no lookahead)...")
    tape = build_tape(bars, config, a.start, a.end, ckpt_dir=ckpt_dir)
    tape.to_csv(os.path.join(a.out, "tape.csv"), index=False)
    print(f"tape rows: {len(tape)}")

    print("forward returns + streaks + paths...")
    tape = add_paths(add_streaks(add_forwards(tape, bars)))
    tape.to_csv(os.path.join(a.out, "tape_with_stats.csv"), index=False)

    print("summarizing...")
    csv_names = {"state": "state_stats.csv", "streak": "streak_stats.csv",
                 "calibration": "score_calibration.csv",
                 "path2": "path_stats_2d.csv", "path3": "path_stats_3d.csv",
                 "transitions": "transitions.csv",
                 "state_by_year": "state_stats_by_year.csv",
                 "path3_by_year": "path_stats_3d_by_year.csv"}
    results = summarize(tape)
    for name, df in results.items():
        p = os.path.join(a.out, csv_names[name])
        df.to_csv(p, index=False)
        print(f"  wrote {p} ({len(df)} rows)")

    # console peek: the money tables
    st = results["state"]
    focus = st[st["state"].isin(
        ["REVERSAL", "REVERSAL_CONFIRMED", "BOTTOM_FORMING", "BOTTOM_BREAKOUT"])]
    print("\n=== reversal/bottom states vs forward returns ===")
    print(focus[["state", "n", "avg_fwd_5d", "avg_fwd_10d",
                 "avg_fwd_20d", "win_rate_10d"]].to_string(index=False,
                 float_format=lambda x: f"{x:.3%}"))

    p3 = results.get("path3", pd.DataFrame())
    if not p3.empty:
        rev = p3[p3["path_3d"].str.contains("REVERSAL|BOTTOM", na=False)]
        rev = rev[rev["n"] >= 5].sort_values("avg_fwd_10d", ascending=False)
        print("\n=== top reversal/bottom 3-day paths (n>=5) by avg fwd 10d ===")
        if rev.empty:
            print("(none with n>=5)")
        else:
            print(rev.head(10)[["path_3d", "n", "avg_fwd_10d",
                                "win_rate_10d"]].to_string(index=False))

    # certainty per probability: top paths by WIN RATE across ALL states
    pall = results.get("path3", pd.DataFrame())
    if not pall.empty:
        top = pall[pall["n"] >= 30].sort_values("win_rate_10d", ascending=False)
        print("\n=== top 3-day paths by win rate (n>=30, all states) ===")
        if top.empty:
            print("(none with n>=30)")
        else:
            print(top.head(12)[["path_3d", "n", "avg_fwd_10d",
                                "win_rate_10d"]].to_string(index=False))

    # per-year: recent years matter more (regimes change)
    py = results.get("path3_by_year", pd.DataFrame())
    if not py.empty:
        for yr in sorted(py["year"].unique())[-2:]:
            sub = py[(py["year"] == yr)
                     & py["path_3d"].str.contains("REVERSAL|BOTTOM", na=False)]
            sub = sub[sub["n"] >= 5].sort_values("win_rate_10d", ascending=False)
            print(f"\n=== {yr}: reversal/bottom paths by win rate (n>=5) ===")
            if sub.empty:
                print("(none)")
            else:
                print(sub.head(8)[["path_3d", "n", "avg_fwd_10d",
                                   "win_rate_10d"]].to_string(index=False))


if __name__ == "__main__":
    main()
