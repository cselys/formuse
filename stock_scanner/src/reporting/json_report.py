"""
JSON reporting for stock_scanner V1.2.
Saves complete machine-readable scan records including Candidate Score, Entry Quality, and Market Regime.
"""

import os
import json
from datetime import datetime


def save_json_report(results: list[dict], output_dir: str = "data/reports", scan_date: str = None) -> str:
    """
    Save complete scan results to JSON file by scan date.
    """
    os.makedirs(output_dir, exist_ok=True)
    if not scan_date:
        scan_date = datetime.now().strftime("%Y-%m-%d")

    report_payload = {
        'scan_date': scan_date,
        'scanner_version': results[0].get('scanner_version', '1.2') if results else '1.2',
        'total_symbols_scanned': len(results),
        'results': results
    }

    filename = f"{scan_date}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(report_payload, f, indent=2, default=str)

    return filepath
