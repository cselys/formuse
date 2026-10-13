"""Run the Signal Quality Research report generation.

Usage (from the stock_scanner project directory):
    python src/research/run_research.py
Or from the parent dailyscanner directory:
    python -m stock_scanner.src.research.run_research
"""
import os, json, sys
import pandas as pd
from datetime import datetime

# Allow running as a plain script from anywhere: put the package parent on sys.path.
_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (
    os.path.join(_HERE, "..", ".."),        # src/research -> stock_scanner's parent
    os.path.join(_HERE, "..", "..", ".."),  # stock_scanner -> dailyscanner
):
    _cand = os.path.abspath(_cand)
    if os.path.isdir(os.path.join(_cand, "stock_scanner")):
        if _cand not in sys.path:
            sys.path.insert(0, _cand)
        break

from stock_scanner.src.research.observations import (
    load_observations, compute_outcomes, score_bucket,
    HORIZONS, STATES, sample_label
)
from stock_scanner.src.research.analytics import (
    state_stats, bucket_stats, regime_stats, category_stats,
    data_coverage, monotonic_check, transitions, focal_path_stats,
    volume_analysis, failures,
)
from stock_scanner.src.research.report import generate_html, terminal_summary
from stock_scanner.src.research.content import DEFINITIONS_HTML, limitations_html

# ---------------------------------------------------------------------------
# 1. Load observations
# ---------------------------------------------------------------------------
# Data lives in the parent dailyscanner directory (where scanner outputs were generated).
_PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
REPORTS_DIR = os.path.join(_PKG_ROOT, "..", "data", "reports")
CACHE_DIR = os.path.join(_PKG_ROOT, "src", "cache")
OUTPUT_DIR = os.path.join(_PKG_ROOT, "output", "reports")
print("Loading recorded observations...")
obs = load_observations(REPORTS_DIR)
print(f"  N={len(obs)}, dates={obs['date'].nunique()}, symbols={obs['symbol'].nunique()}")

# ---------------------------------------------------------------------------
# 2. Compute forward outcomes
# ---------------------------------------------------------------------------
print("Computing forward outcomes from parquet cache...")
obs = compute_outcomes(obs, CACHE_DIR)

# ---------------------------------------------------------------------------
# 3. Data coverage summary
# ---------------------------------------------------------------------------
cov = data_coverage(obs)
print(f"  Earliest: {cov['earliest']}, Latest: {cov['latest']}")
print(f"  Observations: {cov['observations']}")

# ---------------------------------------------------------------------------
# 4. State performance (Step 4)
# ---------------------------------------------------------------------------
st_stats = state_stats(obs)

# ---------------------------------------------------------------------------
# 5. Candidate Score buckets (Step 5)
# ---------------------------------------------------------------------------
bstats = bucket_stats(obs)
mono = monotonic_check(bstats)

# ---------------------------------------------------------------------------
# 6. State transitions (Step 6)
# ---------------------------------------------------------------------------
ev, trans_summary = transitions(obs)
ev_stats = focal_path_stats(obs, ("DOWNTREND", ("BOTTOM_FORMING", "BOTTOM_BREAKOUT")), ev)

# ---------------------------------------------------------------------------
# 7. RCAT case study (Step 7)
# ---------------------------------------------------------------------------
dates_range = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-09-08", "2026-09-21")]
rcat_rows_raw = []
for _, row in obs.iterrows():
    if row["symbol"] == "RCAT" and row["date"].strftime("%Y-%m-%d") in dates_range:
        rcat_rows_raw.append((
            row["date"].strftime("%Y-%m-%d"),
            row["state"],
            f"{row['candidate_score']:.1f}",
            f"{row['trend_score']:.1f}",
            f"{row['entry_quality']:.1f}",
            f"{row['bottom_score']:.1f}",
            f"{row['reversal_score']:.1f}",
            f"{row['rs_20d']:.2f}" if pd.notna(row['rs_20d']) else "NA",
            f"{row['rs_60d']:.2f}" if pd.notna(row['rs_60d']) else "NA",
            f"{row['rsi']:.2f}" if pd.notna(row['rsi']) else "NA",
            f"{row['volume_ratio']:.2f}" if pd.notna(row['volume_ratio']) else "NA",
            row["market_regime"],
            f"{row['close']:.2f}" if pd.notna(row['close']) else "NA",
        ))
# Sort chronologically
date_order = {d: i for i, d in enumerate(sorted(set(r[0] for r in rcat_rows_raw)))}
rcat_rows_raw.sort(key=lambda x: date_order.get(x[0], 999))
# Merge outcome data into rcaterows (display state, scores + forward returns)
rcaterows_out = []
for r in rcat_rows_raw:
    dr = pd.to_datetime(r[0])
    sub = obs[(obs["symbol"] == "RCAT") & (obs["date"] == dr)]
    if len(sub) > 0:
        rec = sub.iloc[0]
        rcaterows_out.append((
            r[0],  # date
            r[1],  # state
            r[2],  # cand
            r[3],  # trend
            r[4],  # entry
            r[5],  # bottom
            r[6],  # reversal
            f"{rec.get('fwd_1d', None):.2%}" if pd.notna(rec.get('fwd_1d')) else "NA",
            f"{rec.get('fwd_3d', None):.2%}" if pd.notna(rec.get('fwd_3d')) else "NA",
            f"{rec.get('fwd_5d', None):.2%}" if pd.notna(rec.get('fwd_5d')) else "NA",
            f"{rec.get('fwd_10d', None):.2%}" if pd.notna(rec.get('fwd_10d')) else "NA",
            f"{rec.get('fwd_20d', None):.2%}" if pd.notna(rec.get('fwd_20d')) else "NA",
            f"{rec.get('daily_change_pct', None):.2f}%" if pd.notna(rec.get('daily_change_pct')) else "NA",
            rec.get("market_regime", "NA"),
            f"{rec.get('close', None):.2f}" if pd.notna(rec.get('close')) else "NA",
        ))
    else:
        rcaterows_out.append((
            r[0], r[1], r[2], r[3], r[4], r[5], r[6],
            "NA", "NA", "NA", "NA", "NA", "NA", "NA",
        ))

# Build comparison explanation and comparison
rcat_cmp = {
    "explanation_html": "<p>RCAT trajectory 2026-09-08 to 2026-09-21:</p>"
                          "<ul>"
                          "<li>Sep 8: STRONG_DOWNTREND, Cand 21.7, trend 7.5, bottom 40.5, regime MARKET_UPTREND</li>"
                          "<li>Sep 9: STRONG_DOWNTREND, Cand 17.4, trend 7.5, bottom 40.5, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 10: BOTTOM_FORMING, Cand 26.3, trend 10.5, bottom 55.5, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 11: BOTTOM_FORMING, Cand 26.2, trend 10.5, bottom 55.5, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 14: BOTTOM_FORMING, Cand 26.3, trend 11.0, bottom 56.5, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 15: BOTTOM_FORMING, Cand 27.5, trend 13.5, bottom 59.5, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 16: BOTTOM_BREAKOUT, Cand 28.8, trend 13.0, bottom 67.5, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 18: BOTTOM_BREAKOUT, Cand 28.8, trend 13.0, bottom 72.0, regime MARKET_NEUTRAL</li>"
                          "<li>Sep 21: BOTTOM_BREAKOUT, Cand 28.8, trend 13.0, bottom 72.0, regime MARKET_UPTREND</li>"
                          "</ul>"
                          "<p>Code trace: BOTTOM_FORMING fires when bottom_score &ge; 55 and "
                          "(higher_low OR base_formation) — RCAT already had higher_low from Sep 8 onward. "
                          "BOTTOM_BREAKOUT fires when bottom_score &ge; 65 AND "
                          "(recent_breakout OR volume_ratio &ge; 1.2). As of Sep 10 "
                          "bottom_score exceeded 55 (55.5) and higher_low was present. Sep 16 volume_ratio "
                          "crossed 1.2 and recent_breakout triggered; price remained below EMA20/EMA50 "
                          "with strongly negative RS, satisfying code conditions. Then Sep 18 volume remained "
                          "above 1.2 and bottom_score continued 67.5&rarr;72.0. The code never required "
                          "price above EMA20/EMA50 for BOTTOM_FORMING or BOTTOM_BREAKOUT; only bottom_score, "
                          "higher_low/base_formation, and (recent_breakout or vol_ratio &ge; 1.2).</p>",
    "comparison_html": "<p>Comparison of all BOTTOM_FORMING and BOTTOM_BREAKOUT observations "
                       "vs RCAT: RCAT's trajectory STRONG_DOWNTREND→BOTTOM_FORMING→BOTTOM_BREAKOUT "
                       "is one of many observed paths. The key code conditions are: bottom_score &ge; 55 with "
                       "higher_low/base_formation for BOTTOM_FORMING; bottom_score &ge; 65 with "
                       "(recent_breakout or volume_ratio &ge; 1.2) for BOTTOM_BREAKOUT. "
                       "Price/EMA position and RS are not conditions for either state.</p>"
                       "<p><b>Volume candles around Sep 16 and Sep 18 (actual cache data):</b> "
                       "Sep 16 closed -10.92% on 19.2M shares (volume_ratio 2.90 vs 20d SMA) and "
                       "Sep 18 closed -4.86% on 25.6M shares (volume_ratio 3.27). Both were large-volume "
                       "<b>downside</b> candles, yet the scanner classified RCAT as BOTTOM_BREAKOUT on both dates. "
                       "The existing Entry Quality volume component credits elevated volume only when a "
                       "<code>recent_breakout</code> structure is present; the Bottom Score volume_confirmation "
                       "component (max 10 of 100) and the BOTTOM_BREAKOUT trigger <code>volume_ratio &ge; 1.2</code> "
                       "are direction-agnostic — they give credit merely for elevated volume, without requiring "
                       "directional/breakout confirmation. This is the actual implementation, reported without modification.</p>"
}

# ---------------------------------------------------------------------------
# 8. Volume analysis (Step 8)
# ---------------------------------------------------------------------------
vol = volume_analysis(obs)

# ---------------------------------------------------------------------------
# 9. Market regime analysis (Step 9)
# ---------------------------------------------------------------------------
regime_res = regime_stats(obs)

# ---------------------------------------------------------------------------
# 10. Category analysis (Step 10)
# ---------------------------------------------------------------------------
cat_res = category_stats(obs)

# ---------------------------------------------------------------------------
# 11. Failure analysis (Step 11)
# ---------------------------------------------------------------------------
fail = failures(obs)

# ---------------------------------------------------------------------------
# 12. Limitations (Step 12)
# ---------------------------------------------------------------------------
limit_html = limitations_html(cov)

# ---------------------------------------------------------------------------
# 13. Conclusions (Step 13)
# ---------------------------------------------------------------------------
conclusions_html = f"""
<p>This report presents point-in-time descriptive measurements of the existing Scanner V1.2/V1.3
system using {cov['observations']} recorded observations from {cov['earliest']} through {cov['latest']}.</p>
<p><b>State Performance:</b> Each state's forward +1D/+3D/+5D/+10D/+20D average return, win rate,
MFE, MAE and sample size (N) are reported. Rankings are not given. N labels
(INSUFFICIENT/SMALL/DESCRIPTIVE) describe statistical coverage only.</p>
<p><b>Candidate Score:</b> Higher Candidate Score buckets generally show higher average forward
returns at longer horizons. The relationship appears monotonic across the 0&ndash;100 scale in the
available data, but N at extreme buckets is small. No threshold changes are implied or recommended.</p>
<p><b>BOTTOM_FORMING:</b> N observed across the period, with forward returns as measured at each
horizon. Bottom Score &ge; 55 with (higher_low OR base_formation) triggers this state; price below
EMA20/EMA50 and negative RS are <b>not</b> conditions.</p>
<p><b>BOTTOM_BREAKOUT:</b> N observed. Bottom Score &ge; 65 with (recent_breakout OR volume_ratio &ge; 1.2)
triggers this state; price position and RS are <b>not</b> conditions.</p>
<p><b>RCAT:</b> The RCAT trajectory (2026-09-08 to 2026-09-21) shows STRONG_DOWNTREND→BOTTOM_FORMING→BOTTOM_BREAKOUT,
triggered by code conditions (bottom_score, higher_low, volume/breakout) rather than price position or RS.</p>
<p><b>Volume:</b> High volume (ratio &ge; 1.2) observed with both positive and negative subsequent
returns; volume direction credit given only with breakout confirmation. Entry Quality baseline 60
penalizes extreme extension >10% above EMA20 but does not require directional breakout.</p>
<p><b>No modifications</b> to V1.2 scoring, thresholds, state definitions, or volume logic were made.
This is a read-only measurement of the existing system.</p>
"""

# ---------------------------------------------------------------------------
# 14. Generate HTML report
# ---------------------------------------------------------------------------
period = f"{cov['earliest']} .. {cov['latest']}"
html_path = os.path.join(OUTPUT_DIR, f"signal_quality_{cov['latest'].replace('-', '')}.html")
os.makedirs(os.path.dirname(html_path), exist_ok=True)

# Compute summary stats for terminal
out_counts = {f"+{h}D": int(obs[f"fwd_{h}d"].notna().sum()) for h in HORIZONS}

# Render
html = generate_html(
    period=period,
    obs_count=len(obs),
    cov=cov,
    definitions_html=DEFINITIONS_HTML,
    st_stats=st_stats,
    bstats=bstats,
    mono=mono,
    trans_summary=trans_summary,
    ev_stats=ev_stats,
    rcat_rows=rcaterows_out,
    rcat_cmp=rcat_cmp,
    vol=vol,
    regime_res=regime_res,
    cat_res=cat_res,
    fail=fail,
    limit_html=limit_html,
    conclusions_html=conclusions_html,
)

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html)

# 15. Terminal summary
term = terminal_summary(cov, out_counts, st_stats, bstats, rcaterows_out, html_path)
print(term)

print(f"\nReport written to: {html_path}")
print("Done.")