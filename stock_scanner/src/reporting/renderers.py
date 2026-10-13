"""
Rendering for the daily report.

All renderers consume the same DailyReport data model so that terminal, TXT,
and HTML output share a single set of calculations. TXT is derived from the
terminal rendering; HTML uses the same structured data.
"""

import html as html_lib
from stock_scanner.src.reporting.state_breakdown import render_state_section, render_state_terminal
from typing import List, Dict, Any

_SEP = "=" * 110
_LINE = "-" * 110


def _fmt(value: Any, default: str = "N/A", fmt: str = None) -> str:
    if value is None:
        return default
    try:
        float(value)
    except (TypeError, ValueError):
        return str(value)
    if fmt:
        try:
            return fmt.format(value)
        except (ValueError, TypeError):
            return str(value)
    return str(value)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):+.2f}%"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_num(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def _fmt_pct_plain(value: Any) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def _stock_row(r: Dict[str, Any]) -> List[str]:
    return [
        r.get('symbol', ''),
        r.get('category', ''),
        _fmt_num(r.get('close')),
        _fmt_pct(r.get('change_pct')),
        r.get('state', ''),
        _fmt_num(r.get('candidate_score')),
        _fmt_num(r.get('entry_quality')),
        _fmt_pct(r.get('rs_20d')),
        r.get('rs_trend', 'N/A'),
    ]


# --------------------------------------------------------------------------- #
# Terminal / TXT rendering
# --------------------------------------------------------------------------- #

def _render_header(rep) -> str:
    out = []
    out.append(_SEP)
    out.append(" " * 34 + "STOCK SCANNER DAILY REPORT")
    out.append(_SEP)
    out.append(f"Date: {rep.scan_date}")
    out.append("Data source: yfinance")
    out.append(f"Universe: {rep.universe_size} stocks")
    out.append(f"Market Regime: {rep.market_regime}")
    out.append(_SEP)
    return "\n".join(out)


def _render_stock_table(title: str, rows: List[Dict[str, Any]]) -> str:
    out = []
    out.append("")
    out.append(title)
    out.append(_LINE)
    out.append(f"{'Rank':<5} {'Symbol':<8} {'Category':<15} {'Close':<9} {'Change %':<10} {'State':<18} {'Score':<8} {'EntryQ':<8} {'RS(20d)':<10} {'RS Trend':<12}")
    out.append(_LINE)
    for idx, r in enumerate(rows, 1):
        cols = _stock_row(r)
        sym, cat, close, chg, state, cand, entry, rs, rs_trend = cols
        out.append(
            f"{idx:<5} {sym:<8} {cat:<15} {close:<9} {chg:<10} {state:<18} {cand:<8} {entry:<8} {rs:<10} {rs_trend:<12}"
        )
    return "\n".join(out)


def _render_sector_breadth_table(title: str, rows: List[Dict[str, Any]], ratio_key: str, count_key: str, avg_key: str) -> str:
    out = []
    out.append("")
    out.append(title)
    out.append(_LINE)
    out.append(f"{'Rank':<5} {'Sector':<20} {'Up':<6} {'Down':<6} {'Flat':<6} {'Total':<8} {'Up %':<8} {'Down %':<8} {'Avg Change':<10}")
    out.append(_LINE)
    for idx, s in enumerate(rows, 1):
        out.append(
            f"{idx:<5} {s['sector']:<20} {s['sector_up_count']:<6} {s['sector_down_count']:<6} {s['sector_flat_count']:<6} "
            f"{s['total_stock_count']:<8} {_fmt_pct_plain(s['up_ratio'] * 100):<8} {_fmt_pct_plain(s['down_ratio'] * 100):<8} "
            f"{_fmt_pct(s['avg_change_pct']):<10}"
        )
    return "\n".join(out)


def _index_display_label(rep, r: Dict[str, Any]) -> str:
    display = rep.sector_index_label(r.get('symbol', ''))
    return display or (r.get('sector') or '')


def _render_sector_index_table(title: str, rows: List[Dict[str, Any]], rep) -> str:
    out = []
    out.append("")
    out.append(title)
    out.append(_LINE)
    out.append(f"{'Rank':<5} {'Index':<8} {'Sector':<26} {'Close':<10} {'Change %':<10}")
    out.append(_LINE)
    for idx, r in enumerate(rows, 1):
        sector_label = _index_display_label(rep, r)
        out.append(
            f"{idx:<5} {r.get('symbol', ''):<8} {sector_label:<26} {_fmt_num(r.get('close')):<10} {_fmt_pct(r.get('change_pct')):<10}"
        )
    return "\n".join(out)


def render_terminal_report(rep) -> str:
    """Render the full daily report for terminal / TXT output."""
    parts = []
    parts.append(_render_header(rep))
    parts.append(_render_stock_table("TOP 10 STOCKS UP", rep.top_stocks_up))
    parts.append(_render_stock_table("TOP 10 STOCKS DOWN", rep.top_stocks_down))
    parts.append(_render_sector_breadth_table(
        "TOP 3 SECTORS UP - STOCK BREADTH", rep.top_sectors_up, 'up_ratio', 'sector_up_count', 'avg_change_pct'))
    parts.append(_render_sector_breadth_table(
        "TOP 3 SECTORS DOWN - STOCK BREADTH", rep.top_sectors_down, 'down_ratio', 'sector_down_count', 'avg_change_pct'))
    parts.append(_render_sector_index_table("TOP 3 SECTOR INDEXES UP", rep.sector_indexes_up, rep))
    parts.append(_render_sector_index_table("TOP 3 SECTOR INDEXES DOWN", rep.sector_indexes_down, rep))
    body = "\n".join(parts)
    if rep.has_scan_results:
        body += '\n' + render_state_terminal(rep.state_breakdown)
    return body


def render_txt_report(rep) -> str:
    """TXT report mirrors the terminal report for readability."""
    return render_terminal_report(rep)


# --------------------------------------------------------------------------- #
# CSV rendering
# --------------------------------------------------------------------------- #

def _csv_quote(value: Any) -> str:
    s = "" if value is None else str(value)
    if any(c in s for c in (',', '"', '\n')):
        s = '"' + s.replace('"', '""') + '"'
    return s


def _rows_to_csv(header: List[str], rows: List[List[Any]]) -> str:
    lines = [_csv_quote(h) for h in header]
    lines = [",".join(lines)]
    for row in rows:
        lines.append(",".join(_csv_quote(c) for c in row))
    return "\n".join(lines)


def render_stocks_up_csv(rep) -> str:
    header = ["Rank", "Symbol", "Category", "Close", "Change %", "State", "Candidate Score", "Entry Quality", "RS(20d)", "RS Trend"]
    rows = []
    for idx, r in enumerate(rep.top_stocks_up, 1):
        rows.append([idx, r.get('symbol'), r.get('category'), r.get('close'),
                     _fmt_pct(r.get('change_pct')), r.get('state'), r.get('candidate_score'),
                     r.get('entry_quality'), _fmt_pct(r.get('rs_20d')), r.get('rs_trend')])
    return _rows_to_csv(header, rows)


def render_stocks_down_csv(rep) -> str:
    header = ["Rank", "Symbol", "Category", "Close", "Change %", "State", "Candidate Score", "Entry Quality", "RS(20d)", "RS Trend"]
    rows = []
    for idx, r in enumerate(rep.top_stocks_down, 1):
        rows.append([idx, r.get('symbol'), r.get('category'), r.get('close'),
                     _fmt_pct(r.get('change_pct')), r.get('state'), r.get('candidate_score'),
                     r.get('entry_quality'), _fmt_pct(r.get('rs_20d')), r.get('rs_trend')])
    return _rows_to_csv(header, rows)


def render_sectors_csv(rep) -> str:
    header = ["Sector", "Up", "Down", "Flat", "Total", "Up %", "Down %", "Avg Change %"]
    rows = []
    for s in rep.sector_breadth:
        rows.append([s['sector'], s['sector_up_count'], s['sector_down_count'], s['sector_flat_count'],
                     s['total_stock_count'], _fmt_pct_plain(s['up_ratio'] * 100), _fmt_pct_plain(s['down_ratio'] * 100),
                     _fmt_pct(s['avg_change_pct'])])
    return _rows_to_csv(header, rows)


def render_sector_indexes_csv(rep) -> str:
    header = ["Symbol", "Sector", "Close", "Change %"]
    rows = []
    for r in rep.sector_indexes_up + rep.sector_indexes_down:
        rows.append([r.get('symbol'), _index_display_label(rep, r),
                     r.get('close'), _fmt_pct(r.get('change_pct'))])
    return _rows_to_csv(header, rows)


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #

def _e(value: Any) -> str:
    return html_lib.escape("" if value is None else str(value))


def _html_stock_table(rows: List[Dict[str, Any]]) -> str:
    rows_html = []
    for idx, r in enumerate(rows, 1):
        rows_html.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{_e(r.get('symbol'))}</td>"
            f"<td>{_e(r.get('category'))}</td>"
            f"<td>{_e(_fmt_num(r.get('close')))}</td>"
            f"<td>{_e(_fmt_pct(r.get('change_pct')))}</td>"
            f"<td>{_e(r.get('state'))}</td>"
            f"<td>{_e(_fmt_num(r.get('candidate_score')))}</td>"
            f"<td>{_e(_fmt_num(r.get('entry_quality')))}</td>"
            f"<td>{_e(_fmt_pct(r.get('rs_20d')))}</td>"
            f"<td>{_e(r.get('rs_trend'))}</td>"
            "</tr>"
        )
    return "\n".join(rows_html)


def _html_sector_breadth_table(rows: List[Dict[str, Any]]) -> str:
    rows_html = []
    for idx, s in enumerate(rows, 1):
        rows_html.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{_e(s['sector'])}</td>"
            f"<td>{s['sector_up_count']}</td>"
            f"<td>{s['sector_down_count']}</td>"
            f"<td>{s['sector_flat_count']}</td>"
            f"<td>{s['total_stock_count']}</td>"
            f"<td>{_e(_fmt_pct_plain(s['up_ratio'] * 100))}</td>"
            f"<td>{_e(_fmt_pct_plain(s['down_ratio'] * 100))}</td>"
            f"<td>{_e(_fmt_pct(s['avg_change_pct']))}</td>"
            "</tr>"
        )
    return "\n".join(rows_html)


def _html_sector_index_table(rows: List[Dict[str, Any]], rep) -> str:
    rows_html = []
    for idx, r in enumerate(rows, 1):
        sector_label = _index_display_label(rep, r)
        rows_html.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{_e(r.get('symbol'))}</td>"
            f"<td>{_e(sector_label)}</td>"
            f"<td>{_e(_fmt_num(r.get('close')))}</td>"
            f"<td>{_e(_fmt_pct(r.get('change_pct')))}</td>"
            "</tr>"
        )
    return "\n".join(rows_html)


def render_html_report(rep) -> str:
    def section(title: str, table_html: str) -> str:
        return f"<h2>{_e(title)}</h2><table>{table_html}</table>"

    stock_up = _html_stock_table(rep.top_stocks_up)
    stock_down = _html_stock_table(rep.top_stocks_down)
    sectors_up = _html_sector_breadth_table(rep.top_sectors_up)
    sectors_down = _html_sector_breadth_table(rep.top_sectors_down)
    idx_up = _html_sector_index_table(rep.sector_indexes_up, rep)
    idx_down = _html_sector_index_table(rep.sector_indexes_down, rep)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Stock Scanner Daily Report — {_e(rep.scan_date)}</title>
<style>
body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 24px; color: #222; background: #f7f7f7; }}
h1 {{ color: #1a1a2e; }}
h2 {{ color: #16213e; border-bottom: 2px solid #e0e0e0; padding-bottom: 4px; margin-top: 28px; }}
.meta {{ color: #555; margin-bottom: 6px; }}
table {{ border-collapse: collapse; width: 100%; max-width: 1200px; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 14px; }}
th {{ background: #16213e; color: #fff; }}
tr:nth-child(even) {{ background: #f2f2f2; }}
</style>
</head>
<body>
<h1>Stock Scanner Daily Report</h1>
<div class="meta">Date: {_e(rep.scan_date)}</div>
<div class="meta">Data source: yfinance</div>
<div class="meta">Universe: {rep.universe_size} stocks</div>
<div class="meta">Market Regime: {_e(rep.market_regime)}</div>
{section("TOP 10 STOCKS UP", stock_up)}
{section("TOP 10 STOCKS DOWN", stock_down)}
{section("TOP 3 SECTORS UP - STOCK BREADTH", sectors_up)}
{section("TOP 3 SECTORS DOWN - STOCK BREADTH", sectors_down)}
{section("TOP 3 SECTOR INDEXES UP", idx_up)}
{section("TOP 3 SECTOR INDEXES DOWN", idx_down)}
{render_state_section(rep.state_breakdown)}
</body>
</html>
"""
