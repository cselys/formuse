"""Load recorded scanner observations (read-only) and compute forward outcomes.

Signals/states/scores come ONLY from recorded scan JSON (data/reports/*.json).
Future prices from the existing local parquet cache are used ONLY for outcomes.
"""
import json, os
import pandas as pd

STATES = ["STRONG_UPTREND", "UPTREND", "EARLY_UPTREND", "REVERSAL",
          "REVERSAL_CONFIRMED", "BOTTOM_FORMING", "BOTTOM_BREAKOUT",
          "NEUTRAL", "DOWNTREND", "STRONG_DOWNTREND", "AVOID"]

HORIZONS = [1, 3, 5, 10, 20]


def load_observations(reports_dir):
    """Load all recorded scan JSON into a flat list of observations."""
    obs = []
    files = sorted(f for f in os.listdir(reports_dir) if f.endswith(".json"))
    for fn in files:
        path = os.path.join(reports_dir, fn)
        try:
            with open(path) as f:
                doc = json.load(f)
        except Exception:
            continue
        scan_date = doc.get("scan_date") or fn.replace(".json", "")
        version = doc.get("scanner_version", "unknown")
        for r in doc.get("results", []):
            d = r.get("daily") or {}
            obs.append({
                "date": scan_date,
                "symbol": r.get("symbol"),
                "category": r.get("category"),
                "daily_change_pct": r.get("daily_change_pct"),
                "state": r.get("state"),
                "candidate_score": r.get("candidate_score"),
                "trend_score": r.get("trend_score"),
                "entry_quality": r.get("entry_quality"),
                "bottom_score": r.get("bottom_score"),
                "reversal_score": r.get("reversal_score"),
                "market_regime": r.get("market_regime"),
                "rsi": d.get("rsi"),
                "volume_ratio": d.get("volume_ratio"),
                "volume": d.get("volume"),
                "close": d.get("close"),
                "distance_ema20": d.get("distance_ema20"),
                "distance_ema50": d.get("distance_ema50"),
                "rs_20d": (r.get("relative_strength") or {}).get("rs_20d"),
                "rs_60d": (r.get("relative_strength") or {}).get("rs_60d"),
                "higher_low": (r.get("structure") or {}).get("higher_low"),
                "recent_breakout": (r.get("structure") or {}).get("recent_breakout"),
                "base_formation": (r.get("structure") or {}).get("base_formation"),
                "scanner_version": version,
                "result_source": "RECORDED",
            })
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values(["date", "symbol"]).reset_index(drop=True)


def _cache_path(cache_dir, symbol):
    return os.path.join(cache_dir, f"{symbol}.parquet")


def compute_outcomes(obs, cache_dir):
    """Attach forward returns / MFE / MAE using the local parquet price cache.

    Horizon = N trading sessions strictly after the observation date.
    Missing/insufficient future data -> NaN (never filled).
    """
    price_cache = {}
    rets = {h: [] for h in HORIZONS}
    mfe = {h: [] for h in HORIZONS}
    mae = {h: [] for h in HORIZONS}
    for _, row in obs.iterrows():
        sym, date, px = row["symbol"], row["date"], row["close"]
        path = _cache_path(cache_dir, sym)
        if px is None or not os.path.exists(path):
            for h in HORIZONS:
                rets[h].append(None); mfe[h].append(None); mae[h].append(None)
            continue
        if sym not in price_cache:
            try:
                price_cache[sym] = pd.read_parquet(path)
            except Exception:
                price_cache[sym] = None
        df = price_cache[sym]
        if df is None or df.empty:
            for h in HORIZONS:
                rets[h].append(None); mfe[h].append(None); mae[h].append(None)
            continue
        idx = df.index
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        future = df[idx > date]
        for h in HORIZONS:
            if len(future) >= h:
                sub = future.iloc[:h]
                rets[h].append((sub["Close"].iloc[-1] / px) - 1.0)
                mfe[h].append((sub["High"].max() / px) - 1.0)
                mae[h].append((sub["Low"].min() / px) - 1.0)
            else:
                rets[h].append(None); mfe[h].append(None); mae[h].append(None)
    out = obs.copy()
    for h in HORIZONS:
        out[f"fwd_{h}d"] = rets[h]
        out[f"mfe_{h}d"] = mfe[h]
        out[f"mae_{h}d"] = mae[h]
    return out


def score_bucket(s):
    if s is None or pd.isna(s):
        return None
    for lo, hi in [(0, 19), (20, 39), (40, 59), (60, 69), (70, 79), (80, 89), (90, 100)]:
        if lo <= s <= hi:
            return f"{lo}-{hi}"
    return None


def sample_label(n):
    if n < 10:
        return "INSUFFICIENT SAMPLE"
    if n < 30:
        return "SMALL SAMPLE"
    return "DESCRIPTIVE SAMPLE"
