"""HTML + terminal report rendering for signal quality research (read-only).

Rendered output only — never a source of historical state.
"""
import html as _html
from .observations import STATES, HORIZONS, sample_label


def esc(x):
    return _html.escape(str(x))


def fmt(v, pct=False, nd=2):
    if v is None:
        return "NA"
    try:
        return f"{float(v):.{nd}f}{'%' if pct else ''}"
    except (TypeError, ValueError):
        return esc(v)


def _stats_row(name, st, horizons):
    cells = []
    for h in horizons:
        s = st.get(h, {}) or {}
        n = s.get("n", 0) or 0
        lbl = sample_label(n) if n else "NA"
        cells.append(
            f"<td>{n}<br><small>{lbl}</small></td>"
            f"<td>{fmt(s.get('avg'), pct=True)}</td>"
            f"<td>{fmt(s.get('median'), pct=True)}</td>"
            f"<td>{fmt(s.get('win'), pct=True, nd=1)}</td>"
            f"<td>{fmt(s.get('mfe'), pct=True)}</td>"
            f"<td>{fmt(s.get('mae'), pct=True)}</td>"
            f"<td>{fmt(s.get('best'), pct=True)}</td>"
            f"<td>{fmt(s.get('worst'), pct=True)}</td>"
        )
    return f"<tr><td><b>{esc(name)}</b></td>{''.join(cells)}</tr>"


def _stats_table(st_groups, horizons=(1, 3, 5, 10, 20), order=None):
    heads = "".join(f"<th colspan=8>+{h}D</th>" for h in horizons)
    sub = "<tr><th>Group</th>" + "".join(
        "<th>N</th><th>Avg</th><th>Med</th><th>Win%</th><th>MFE</th><th>MAE</th><th>Best</th><th>Worst</th>"
        for _ in horizons) + "</tr>"
    keys = order if order else list(st_groups.keys())
    rows = "".join(_stats_row(g, st_groups[g], horizons) for g in keys if g in st_groups)
    return (f"<table border=1 style='border-collapse:collapse;font-size:11px'>"
            f"<tr><th></th>{heads}</tr>{sub}{rows}</table>")


def generate_html(*, period, obs_count, cov, definitions_html, st_stats, bstats,
                  mono, trans_summary, ev_stats, rcat_rows, rcat_cmp, vol,
                  regime_res, cat_res, fail, limit_html, conclusions_html):
    s = []
    A = s.append
    A("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Signal Quality Research</title></head>")
    A("<style>body{font-family:Segoe UI,Arial;margin:24px;max-width:1500px}"
      "table{margin:8px 0}td,th{padding:3px 6px;vertical-align:top}"
      "h2{border-bottom:2px solid #888}h3{margin-top:18px}"
      ".note{color:#555;font-size:12px}.limit{background:#fff3cd;padding:8px;border:1px solid #ddd}</style>")
    A("<h1>Signal Quality Research Report</h1>")
    A(f"<p class=note>Observation period {esc(period)} &middot; {obs_count} recorded observations &middot; "
      "descriptive research only — no trading recommendations. Signals/states/scores from recorded scan JSON; "
      "future prices used only for outcome calculation (point-in-time safe).</p>")

    A("<h2>1. Executive Summary</h2>")
    A(conclusions_html)

    # 2. Data Coverage
    A("<h2>2. Data Coverage</h2>")
    A("<table border=1 style='border-collapse:collapse;font-size:12px'>"
      "<tr><th>Field</th><th>Value</th></tr>"
      f"<tr><td>Earliest observation</td><td>{esc(cov['earliest'])}</td></tr>"
      f"<tr><td>Latest observation</td><td>{esc(cov['latest'])}</td></tr>"
      f"<tr><td>Trading sessions (recorded scan dates)</td><td>{cov['sessions']}</td></tr>"
      f"<tr><td>Symbols</td><td>{cov['symbols']}</td></tr>"
      f"<tr><td>Observations</td><td>{cov['observations']}</td></tr>"
      f"<tr><td>Obs/symbol (min/median/max)</td><td>{cov['obs_per_symbol_min']} / {cov['obs_per_symbol_median']} / {cov['obs_per_symbol_max']}</td></tr>"
      f"<tr><td>Scanner versions</td><td>{esc(cov['versions'])}</td></tr>"
      f"<tr><td>Result source</td><td>RECORDED scan JSON (data/reports), with per-record history_context / history_result_fingerprint</td></tr>"
      f"<tr><td>Calculation policy (recorded)</td><td>w-fri-live-partial-v1 (as recorded at scan time)</td></tr>"
      "</table>")
    A("<h3>Observations by state</h3>")
    A("<table border=1 style='border-collapse:collapse;font-size:12px'><tr><th>State</th><th>N</th></tr>")
    for st in STATES:
        if st in cov["by_state"]:
            A(f"<tr><td>{esc(st)}</td><td>{cov['by_state'][st]}</td></tr>")
    A("</table>")
    A("<h3>Observations by Candidate Score range</h3>")
    A("<table border=1 style='border-collapse:collapse;font-size:12px'><tr><th>Bucket</th><th>N</th></tr>")
    for b in ["0-19", "20-39", "40-59", "60-69", "70-79", "80-89", "90-100"]:
        A(f"<tr><td>{esc(b)}</td><td>{cov['by_bucket'].get(b, 0)}</td></tr>")
    A("</table>")
    A("<h3>Forward outcome coverage (trading sessions strictly after observation)</h3>")
    A("<table border=1 style='border-collapse:collapse;font-size:12px'><tr><th>Horizon</th><th>Available</th><th>Missing/Unavailable</th></tr>")
    for h in HORIZONS:
        A(f"<tr><td>+{h}D</td><td>{cov['horizon_coverage'][f'+{h}D']}</td>"
          f"<td>{cov['missing_outcomes'][f'+{h}D']} (insufficient future cache bars — not filled)</td></tr>")
    A("</table>")
    A(f"<p class=note>{cov['missing_close_count']} observations had no recorded close. "
      "No observations were silently filled; unavailable horizons are marked NA with reason.</p>")

    # 3. Signal Definitions
    A("<h2>3. Signal Definitions (actual V1.2/V1.3 conditions)</h2>")
    A(definitions_html)

    # 4. State Performance
    A("<h2>4. State Performance (forward after observation date)</h2>")
    A(_stats_table(st_stats, order=[s for s in STATES if s in st_stats]))
    A("<p class=note>Descriptive only — states are not ranked. N is the available sample at each horizon.</p>")

    # 5. Candidate Score Calibration
    A("<h2>5. Candidate Score Calibration (existing V1.2 score, unchanged)</h2>")
    order = ["0-19", "20-39", "40-59", "60-69", "70-79", "80-89", "90-100"]
    A(_stats_table(bstats, order=order))
    rows = "".join(f"<tr><td>{esc(b)}</td><td>{n}</td><td>{fmt(v, pct=True)}</td></tr>"
                   for b, n, v in mono[0])
    A("<p><b>Average +20D return by bucket (monotonic check)</b></p>")
    A("<table border=1 style='border-collapse:collapse;font-size:12px'><tr><th>Bucket</th><th>N</th><th>Avg +20D</th></tr>" + rows + "</table>")
    A(f"<p class=note>Strictly increasing across usable buckets (N&ge;10): "
      f"<b>{'yes' if mono[1] else 'no'}</b> ({mono[2]} usable buckets). "
      "Small sample sizes are explicitly noted. Calibration description, not predictive-validity proof.</p>")

    # 6. State Transition Analysis
    A("<h2>6. State Transition Analysis</h2>")
    A("<p class=note>Event level: consecutive recorded sessions per symbol (Fri&ndash;Mon included; gaps break the chain). "
      "Observation-level stats are in sections 4/5; this section counts each state-change event once.</p>")
    total_ev = sum(trans_summary.values()) if trans_summary else 0
    A(f"<p>Total consecutive-session events: {total_ev}</p>")
    A("<table border=1 style='border-collapse:collapse;font-size:11px'><tr><th>Transition</th><th>Events</th><th>%</th></tr>")
    for name, n in sorted(trans_summary.items(), key=lambda kv: -kv[1]):
        A(f"<tr><td>{esc(name)}</td><td>{n}</td><td>{n/total_ev*100:.1f}%</td></tr>")
    A("</table>")
    A("<h3>Focal path: DOWNTREND &rarr; BOTTOM_FORMING / BOTTOM_BREAKOUT (enter / on-path / off-path)</h3>")
    A(_stats_table(ev_stats, horizons=(5, 10, 20)))

    # 7. RCAT Case Study
    A("<h2>7. RCAT Case Study (2026-09-08 through 2026-09-21 + context)</h2>")
    A("<table border=1 style='border-collapse:collapse;font-size:11px'>"
      "<tr><th>Date</th><th>State</th><th>Cand</th><th>Trend</th><th>Entry</th><th>Bottom</th>"
      "<th>Reversal</th><th>+1D</th><th>+3D</th><th>+5D</th><th>+10D</th><th>+20D</th><th>DayChg</th><th>Regime</th><th>Close</th></tr>")
    for r in rcat_rows:
        A("<tr>" + "".join(f"<td>{esc(x)}</td>" for x in r) + "</tr>")
    A("</table>")
    A(rcat_cmp["explanation_html"])
    A(rcat_cmp["comparison_html"])

    # 8. Volume Analysis
    A("<h2>8. Volume Analysis (current behavior measured, not changed)</h2>")
    hv = vol["high_vol"]; nv = vol["normal_vol"]
    A(f"<p>High volume (ratio &ge; 1.2): N={hv['n']} | Normal volume: N={nv['n']}. "
      "Volume ratio in the existing system is direction-agnostic in Trend Score (any ratio &ge; 1.2 scores full 10), "
      "Bottom Score (any &ge;1.2 scores full 10) and Reversal Score (any &ge;1.2 scores full 5); "
      "Entry Quality credits elevated volume only when a <code>recent_breakout</code> structure is also present. "
      "It does not require directional confirmation of the high-volume bar itself.</p>")
    A("<h3>High volume (ratio &ge; 1.2) forward returns</h3>")
    A(_stats_table(vol["high_vol_stats"]))
    A("<h3>Normal volume (ratio &lt; 1.2) forward returns</h3>")
    A(_stats_table(vol["normal_vol_stats"]))

    # 9. Market Regime Analysis
    A("<h2>9. Market Regime Analysis</h2>")
    A(_stats_table(regime_res, order=[r for r in ("MARKET_UPTREND", "MARKET_NEUTRAL", "MARKET_DOWNTREND") if r in regime_res]))

    # 10. Category Analysis
    A("<h2>10. Category Analysis</h2>")
    A(_stats_table(cat_res))
    A("<p class=note>No conclusions drawn from tiny samples; see N per group.</p>")

    # 11. Failure Analysis
    A("<h2>11. Failure Analysis (patterns, not stock labels)</h2>")
    A(fail["html"] if isinstance(fail, dict) and "html" in fail else _failures_html(fail))

    # 12. Data Limitations
    A("<h2>12. Data Limitations</h2>")
    A(f"<div class=limit>{limit_html}</div>")

    # 13. Research Conclusions
    A("<h2>13. Research Conclusions</h2>")
    A(conclusions_html)

    A("</body></html>")
    return "\n".join(s)


def _failures_html(fail):
    out = []
    for k, v in fail.items():
        if not isinstance(v, dict):
            continue
        n = v.get("n_events", v.get("n", 0))
        s5 = v.get("stats_5d", {}) or {}
        s20 = v.get("stats_20d", {}) or {}
        out.append(
            f"<p><b>{esc(k)}</b>: N={n}; "
            f"+5D avg={fmt(s5.get('avg'), pct=True)} (N={s5.get('n', 0)}); "
            f"+20D avg={fmt(s20.get('avg'), pct=True)} (N={s20.get('n', 0)})"
            + (f"; share={fmt(v.get('share_of_70plus'), pct=True, nd=1)}" if "share_of_70plus" in v else "")
            + "</p>")
    return "".join(out)


def terminal_summary(cov, out_counts, st_stats, bstats, rcat_rows, report_path):
    L = []
    A = L.append
    A("SIGNAL QUALITY RESEARCH")
    A("=" * 70)
    A(f"Observation period: {cov['earliest']} .. {cov['latest']}")
    A(f"Symbols: {cov['symbols']}")
    A(f"Sessions: {cov['sessions']}")
    A(f"Observations: {cov['observations']}")
    A("")
    A("State observations:")
    for st in STATES:
        if st in cov["by_state"]:
            A(f"  {st}: {cov['by_state'][st]}")
    A("")
    A("Candidate Score coverage:")
    for b in ["0-19", "20-39", "40-59", "60-69", "70-79", "80-89", "90-100"]:
        A(f"  {b}: {cov['by_bucket'].get(b, 0)}")
    A("")
    A("Forward outcome coverage:")
    for h in HORIZONS:
        A(f"  +{h}D: {cov['horizon_coverage'][f'+{h}D']} available, {cov['missing_outcomes'][f'+{h}D']} unavailable")
    A("")
    for st in ("BOTTOM_FORMING", "BOTTOM_BREAKOUT"):
        s20 = st_stats.get(st, {}).get(20, {}) or {}
        A(f"{st}: N(20D)={s20.get('n', 0)}, avg +20D={fmt(s20.get('avg'), pct=True)}, win={fmt(s20.get('win'), pct=True, nd=1)}")
    for b in ("40-59", "60-69", "70-79", "80-89", "90-100"):
        s20 = bstats.get(b, {}).get(20, {}) or {}
        A(f"Candidate {b}: N(20D)={s20.get('n', 0)}, avg +20D={fmt(s20.get('avg'), pct=True)}")
    if rcat_rows:
        A("")
        A("RCAT (window):")
        for r in rcat_rows:
            A(f"  {r[0]}: {r[1]}, cand={r[2]}, bottom={r[5]}, regime={r[13]}")
    A("")
    A(f"HTML report: {report_path}")
    return "\n".join(L)
