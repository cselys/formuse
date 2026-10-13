"""
File writer for the daily report.

Writes the daily report data model to output/reports/ in TXT, CSV, and HTML
formats. This is the existing output/ convention used by the YAML watchlists,
extended with a reports/ subdirectory.
"""

import os
import logging
from stock_scanner.src.reporting.state_breakdown import save_state_breakdown
from datetime import datetime
from typing import List, Dict, Any, Optional

from stock_scanner.src.reporting.renderers import (
    render_txt_report,
    render_html_report,
    render_stocks_up_csv,
    render_stocks_down_csv,
    render_sectors_csv,
    render_sector_indexes_csv,
)

logger = logging.getLogger("stock_scanner.reporting")


def _write_file(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def save_daily_report(
    report,
    output_dir: str = "output/reports",
    scan_date: Optional[str] = None,
) -> Dict[str, str]:
    """
    Write the daily report to files. Returns a dict of format -> file path.
    """
    os.makedirs(output_dir, exist_ok=True)
    if not scan_date:
        scan_date = report.scan_date or datetime.now().strftime("%Y-%m-%d")

    base = os.path.join(output_dir, f"daily_report_{scan_date}")

    paths = {}

    txt_path = base + ".txt"
    _write_file(txt_path, render_txt_report(report))
    paths['txt'] = txt_path

    csv_path = base + ".csv"
    _write_file(csv_path, _render_combined_csv(report, scan_date))
    paths['csv'] = csv_path

    html_path = base + ".html"
    _write_file(html_path, render_html_report(report))
    paths['html'] = html_path
    paths['state_breakdown'] = save_state_breakdown(report.state_breakdown, scan_date, output_dir)

    # Separate machine-readable CSV files (one per report section).
    separate = {}
    separate['stocks_up'] = _write_section_csv(output_dir, f"stocks_up_{scan_date}.csv", render_stocks_up_csv(report))
    separate['stocks_down'] = _write_section_csv(output_dir, f"stocks_down_{scan_date}.csv", render_stocks_down_csv(report))
    separate['sectors'] = _write_section_csv(output_dir, f"sectors_{scan_date}.csv", render_sectors_csv(report))
    separate['sector_indexes'] = _write_section_csv(output_dir, f"sector_indexes_{scan_date}.csv", render_sector_indexes_csv(report))

    paths['separate_csv'] = separate
    return paths


def _render_combined_csv(report, scan_date: str) -> str:
    """A single CSV that concatenates all report sections with header markers."""
    parts = [f"STOCK_SCANNER_DAILY_REPORT,{scan_date}", f"market_regime,{report.market_regime}"]
    parts.append(render_stocks_up_csv(report))
    parts.append(render_stocks_down_csv(report))
    parts.append(render_sectors_csv(report))
    parts.append(render_sector_indexes_csv(report))
    return "\n\n".join(parts)


def _write_section_csv(output_dir: str, filename: str, content: str) -> str:
    path = os.path.join(output_dir, filename)
    _write_file(path, content)
    return path
