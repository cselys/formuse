"""Descriptive aggregation for signal quality research (no recommendations)."""
import pandas as pd
from .observations import STATES, HORIZONS, score_bucket, sample_label


def _stats(sub, h):
    """Return stats dict for one group at one horizon."""
    s = sub[f"fwd_{h}d"].dropna()
    n = len(s)
    if n == 0:
        return {"n": 0, "avg": None, "median": None, "win": None,
                "mfe": None, "mae": None, "best": None, "worst": None}
    mfe = sub[f"mfe_{h}d"].dropna()
    mae = sub[f"mae_{h}d"].dropna()
    return {
        "n": n,
        "avg": s.mean() * 100,
        "median": s.median() * 100,
        "win": (s > 0).mean() * 100,
        "mfe": mfe.mean() * 100 if len(mfe) else None,
        "mae": mae.mean() * 100 if len(mae) else None,
        "best": s.max() * 100,
        "worst": s.min() * 100,
    }


def group_stats(df, key):
    """Stats per group across all horizons."""
    out = {}
    for g, sub in df.groupby(key):
        out[g] = {h: _stats(sub, h) for h in HORIZONS}
    return out


def state_stats(df):
    return group_stats(df, "state")


def bucket_stats(df):
    d = df.copy()
    d["bucket"] = d["candidate_score"].map(score_bucket)
    return group_stats(d.dropna(subset=["bucket"]), "bucket")


def regime_stats(df):
    return group_stats(df.dropna(subset=["market_regime"]), "market_regime")


def category_stats(df):
    return group_stats(df.dropna(subset=["category"]), "category")


def data_coverage(df):
    """Coverage summary."""
    cov = {
        "earliest": df["date"].min().date().isoformat() if len(df) else None,
        "latest": df["date"].max().date().isoformat() if len(df) else None,
        "sessions": df["date"].nunique(),
        "symbols": df["symbol"].nunique(),
        "observations": len(df),
        "by_state": df["state"].value_counts().to_dict(),
        "by_bucket": df["candidate_score"].map(score_bucket).value_counts().to_dict(),
        "versions": df["scanner_version"].value_counts().to_dict(),
    }
    cov["horizon_coverage"] = {
        f"+{h}D": int(df[f"fwd_{h}d"].notna().sum()) for h in HORIZONS
    }
    cov["missing_outcomes"] = {
        f"+{h}D": int(df[f"fwd_{h}d"].isna().sum()) for h in HORIZONS
    }
    per_sym = df.groupby("symbol").size()
    cov["obs_per_symbol_min"] = int(per_sym.min())
    cov["obs_per_symbol_median"] = float(per_sym.median())
    cov["obs_per_symbol_max"] = int(per_sym.max())
    no_close = int(df["close"].isna().sum())
    cov["missing_close_count"] = no_close
    return cov


def monotonic_check(bstats):
    """Check whether avg +20D return rises with bucket. Descriptive only."""
    order = ["0-19", "20-39", "40-59", "60-69", "70-79", "80-89", "90-100"]
    vals = []
    for b in order:
        st = bstats.get(b, {}).get("20d", {})
        vals.append((b, st.get("n", 0), st.get("avg")))
    usable = [(b, n, v) for b, n, v in vals if v is not None and n >= 10]
    strictly_up = all(
        usable[i][2] < usable[i + 1][2] for i in range(len(usable) - 1)
    ) if len(usable) > 1 else False
    return vals, strictly_up, len(usable)


# ---- Transition / event analysis ----

def _event_outcome(events, df, h):
    """Stats over events at horizon h."""
    rows = []
    for ev in events:
        sub = df[(df["symbol"] == ev["symbol"]) & (df["date"] == ev["date"])]
        if len(sub) == 1:
            v = sub.iloc[0][f"fwd_{h}d"]
            if pd.notna(v):
                rows.append(v)
    if not rows:
        return {"n": 0, "avg": None, "win": None, "mfe": None, "mae": None}
    s = pd.Series(rows)
    # MFE/MAE from matching event rows
    mfes, maes = [], []
    for ev in events:
        sub = df[(df["symbol"] == ev["symbol"]) & (df["date"] == ev["date"])]
        if len(sub) == 1:
            v = sub.iloc[0][f"mfe_{h}d"]
            if pd.notna(v):
                mfes.append(v)
            v = sub.iloc[0][f"mae_{h}d"]
            if pd.notna(v):
                maes.append(v)
    return {
        "n": len(s), "avg": s.mean() * 100,
        "win": (s > 0).mean() * 100,
        "mfe": (pd.Series(mfes).mean() * 100) if mfes else None,
        "mae": (pd.Series(maes).mean() * 100) if maes else None,
    }


def transitions(df):
    """Event-level transitions between consecutive recorded observations per symbol.

    A transition requires consecutive recorded sessions (no gap) so that
    every consecutive pair is a real day-over-day state change.
    Returns (events, summary) where events are (prev_state, state) pairs.
    """
    events = []
    for sym, sub in df.groupby("symbol"):
        sub = sub.sort_values("date")
        dates = list(sub["date"])
        states = list(sub["state"])
        for i in range(1, len(dates)):
            # consecutive sessions only (1 trading day apart)
            gap_days = (dates[i] - dates[i - 1]).days
            if gap_days <= 4:  # Fri->Mon and midweek pairs
                events.append({
                    "symbol": sym,
                    "date": dates[i],
                    "prev_state": states[i - 1],
                    "state": states[i],
                    "prev_score": sub.iloc[i - 1]["candidate_score"],
                    "score": sub.iloc[i]["candidate_score"],
                })
    ev = pd.DataFrame(events)
    summary = {}
    if len(ev):
        pairs = ev.groupby(["prev_state", "state"]).size()
        for (p, s), n in pairs.items():
            summary[f"{p} -> {s}"] = int(n)
    return ev, summary


def focal_path_stats(df, path_steps, ev):
    """Stats for events entering the first state of a path whose following
    transitions stay on the path (or for failure paths, leave it)."""
    from_state, to_states = path_steps[0], path_steps[1]
    out = {}
    for name, keep in [("enter", None), ("on_path", to_states), ("off_path", to_states)]:
        sel = []
        for sym, sub in df.groupby("symbol"):
            sub = sub.sort_values("date").reset_index(drop=True)
            for i in range(len(sub) - 1):
                if sub.iloc[i]["state"] != from_state:
                    continue
                nxt = sub.iloc[i + 1]["state"]
                if name == "enter":
                    sel.append((sub.iloc[i]["symbol"], sub.iloc[i]["date"]))
                elif name == "on_path" and nxt in keep:
                    sel.append((sub.iloc[i]["symbol"], sub.iloc[i]["date"]))
                elif name == "off_path" and nxt not in keep:
                    sel.append((sub.iloc[i]["symbol"], sub.iloc[i]["date"]))
        sub_df = df.merge(pd.DataFrame(sel, columns=["symbol", "date"]),
                          on=["symbol", "date"], how="inner") if sel else df.iloc[0:0]
        out[name] = {h: _stats(sub_df, h) for h in (5, 10, 20)}
    return out


def volume_analysis(df):
    """Distinguish high-volume observations by direction, using recorded fields only."""
    d = df.dropna(subset=["volume_ratio"]).copy()
    hi = d[d["volume_ratio"] >= 1.2]
    lo = d[d["volume_ratio"] < 1.2]
    def direction_split(sub):
        known = sub["fwd_5d"].dropna()
        return {
            "n": len(sub),
            "up_5d": int((known > 0).sum()),
            "down_5d": int((known < 0).sum()),
            "unavailable_5d": int(len(sub) - len(known)),
        }
    # same-day direction: sign of distance moved vs EMA20 is recorded;
    # day direction itself is not recorded per-observation, so use fwd split only.
    return {
        "high_vol": direction_split(hi),
        "normal_vol": direction_split(lo),
        "high_vol_stats": {h: _stats(hi, h) for h in (1, 3, 5, 10, 20)},
        "normal_vol_stats": {h: _stats(lo, h) for h in (1, 3, 5, 10, 20)},
    }


def failures(df):
    """Failed-signal patterns (descriptive)."""
    res = {}
    def pat(mask, name):
        sub = df[mask]
        res[name] = {
            "n": len(sub),
            "stats_5d": _stats(sub, 5),
            "stats_20d": _stats(sub, 20),
        }
    # BOTTOM_FORMING followed by further weakness within 5 sessions
    weak_next = set()
    for sym, sub in df.groupby("symbol"):
        sub = sub.sort_values("date").reset_index(drop=True)
        for i in range(len(sub) - 1):
            if sub.iloc[i]["state"] == "BOTTOM_FORMING" and \
               sub.iloc[i + 1]["state"] in ("DOWNTREND", "STRONG_DOWNTREND"):
                weak_next.add((sub.iloc[i]["symbol"], sub.iloc[i]["date"]))
    sel = df.merge(pd.DataFrame(list(weak_next), columns=["symbol", "date"]),
                   on=["symbol", "date"], how="inner") if weak_next else df.iloc[0:0]
    res["BOTTOM_FORMING -> DOWNTREND/STRONG_DOWNTREND next session"] = {
        "n_events": len(weak_next),
        "stats_5d": _stats(sel, 5),
        "stats_20d": _stats(sel, 20),
    }
    # high candidate score but negative 20D
    hi_neg = df[(df["candidate_score"] >= 70) & (df["fwd_20d"] < 0)]
    res["Candidate>=70 with negative +20D"] = {
        "n": len(hi_neg),
        "share_of_70plus": (len(hi_neg) / max(1, len(df[df["candidate_score"] >= 70]))) * 100,
        "avg_20d": (hi_neg["fwd_20d"].mean() * 100) if len(hi_neg) else None,
    }
    res["html"] = (
        f"<p><b>BOTTOM_FORMING followed by DOWNTREND/STRONG_DOWNTREND next session</b>: "
        f"N events={res['BOTTOM_FORMING -> DOWNTREND/STRONG_DOWNTREND next session']['n_events']}, "
        f"avg +5D={res['BOTTOM_FORMING -> DOWNTREND/STRONG_DOWNTREND next session']['stats_5d'].get('avg') if res['BOTTOM_FORMING -> DOWNTREND/STRONG_DOWNTREND next session']['stats_5d']['n'] else 'NA'}%"
        f"</p>"
        f"<p><b>Candidate Score &ge; 70 with negative +20D outcome</b>: "
        f"N={res['Candidate>=70 with negative +20D']['n']} "
        f"({res['Candidate>=70 with negative +20D']['share_of_70plus']:.1f}% of all N&ge;70 observations)</p>"
    )
    return res
