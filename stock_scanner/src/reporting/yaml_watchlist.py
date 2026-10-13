"""
YAML Watchlist reporting for stock_scanner V1.2.
Automatically generates configurable shortlist and full list CALL and PUT watchlist YAML files from scan results.
"""

import os
import logging
import yaml
from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("stock_scanner.reporting")


def save_watchlist_yaml(
    results: List[Dict[str, Any]],
    output_dir: str = "output",
    scan_date: str = None,
    config: Optional[Dict[str, Any]] = None
) -> Dict[str, str]:
    """
    Generate and save CALL and PUT watchlist YAML files based on scanner state classifications,
    scores, and configuration output settings (shortlist and full list).
    """
    os.makedirs(output_dir, exist_ok=True)
    if not scan_date:
        scan_date = datetime.now().strftime("%Y-%m-%d")

    scanner_version = results[0].get('scanner_version', '1.2') if results else '1.2'

    # Extract and validate configuration output settings
    config = config or {}
    output_cfg = config.get('output', {})
    shortlist_cfg = output_cfg.get('shortlist', {})

    shortlist_enabled = shortlist_cfg.get('enabled', True)
    shortlist_size = shortlist_cfg.get('size', 5)
    sort_by = shortlist_cfg.get('sort_by', 'candidate_score')
    save_full_list = output_cfg.get('save_full_list', True)

    # Validate config types and ranges
    if not isinstance(shortlist_enabled, bool):
        raise ValueError(f"Invalid shortlist.enabled value: {shortlist_enabled}. Must be a boolean.")
    if not isinstance(save_full_list, bool):
        raise ValueError(f"Invalid save_full_list value: {save_full_list}. Must be a boolean.")
    if not isinstance(shortlist_size, int) or shortlist_size <= 0:
        raise ValueError(f"Invalid shortlist.size value: {shortlist_size}. Must be a positive integer.")

    # Define state categories
    call_states = {
        'STRONG_UPTREND',
        'UPTREND',
        'EARLY_UPTREND',
        'BOTTOM_FORMING',
        'BOTTOM_BREAKOUT',
        'REVERSAL',
        'REVERSAL_CONFIRMED'
    }
    put_states = {
        'DOWNTREND',
        'STRONG_DOWNTREND'
    }

    call_candidates = []
    put_candidates = []

    for r in results:
        state = r.get('state', '')
        c_score = r.get('candidate_score', 0.0)
        symbol = r.get('symbol')

        if not symbol:
            continue

        if state in call_states and c_score >= 50.0:
            call_candidates.append(r)
        elif state in put_states:
            put_candidates.append(r)

    # Sort CALL candidates by candidate_score descending (best first)
    call_candidates = sorted(call_candidates, key=lambda x: x.get('candidate_score', 0.0), reverse=True)

    # Sort PUT candidates by candidate_score ascending (lowest score / strongest downtrend first)
    put_candidates = sorted(put_candidates, key=lambda x: x.get('candidate_score', 0.0))

    # Build full lists with original sequential priorities
    call_full_stocks = []
    for idx, r in enumerate(call_candidates, 1):
        call_full_stocks.append({
            'symbol': r.get('symbol'),
            'candidate_score': round(float(r.get('candidate_score', 0.0)), 1),
            'signal': r.get('state'),
            'priority': idx,
            'category': r.get('category'),
            'trend_score': round(float(r.get('trend_score', 0.0)), 1),
            'entry_quality': round(float(r.get('entry_quality', 0.0)), 1)
        })

    put_full_stocks = []
    for idx, r in enumerate(put_candidates, 1):
        put_full_stocks.append({
            'symbol': r.get('symbol'),
            'candidate_score': round(float(r.get('candidate_score', 0.0)), 1),
            'signal': r.get('state'),
            'priority': idx,
            'category': r.get('category'),
            'trend_score': round(float(r.get('trend_score', 0.0)), 1),
            'entry_quality': round(float(r.get('entry_quality', 0.0)), 1)
        })

    generated_files = {}

    # 1. Save Full List if enabled
    if save_full_list:
        call_full_payload = {
            'generated_date': scan_date,
            'scanner_version': scanner_version,
            'watchlist_type': 'CALL_FULL',
            'stocks': call_full_stocks
        }
        put_full_payload = {
            'generated_date': scan_date,
            'scanner_version': scanner_version,
            'watchlist_type': 'PUT_FULL',
            'stocks': put_full_stocks
        }

        call_full_path = os.path.join(output_dir, "call_stocks_full.yaml")
        put_full_path = os.path.join(output_dir, "put_stocks_full.yaml")

        with open(call_full_path, 'w', encoding='utf-8') as f:
            yaml.dump(call_full_payload, f, sort_keys=False, default_flow_style=False)
        with open(put_full_path, 'w', encoding='utf-8') as f:
            yaml.dump(put_full_payload, f, sort_keys=False, default_flow_style=False)

        generated_files['call_full'] = call_full_path
        generated_files['put_full'] = put_full_path
        logger.info(f"Generated full CALL watchlist YAML: {call_full_path} ({len(call_full_stocks)} stocks)")
        logger.info(f"Generated full PUT watchlist YAML: {put_full_path} ({len(put_full_stocks)} stocks)")

    # 2. Save Shortlist if enabled
    if shortlist_enabled:
        call_shortlist_stocks = []
        for idx, r in enumerate(call_candidates[:shortlist_size], 1):
            item = dict(call_full_stocks[idx - 1]) if idx <= len(call_full_stocks) else {}
            item['priority'] = idx  # Renumbered sequentially starting at 1
            call_shortlist_stocks.append(item)

        put_shortlist_stocks = []
        for idx, r in enumerate(put_candidates[:shortlist_size], 1):
            item = dict(put_full_stocks[idx - 1]) if idx <= len(put_full_stocks) else {}
            item['priority'] = idx  # Renumbered sequentially starting at 1
            put_shortlist_stocks.append(item)

        call_payload = {
            'generated_date': scan_date,
            'scanner_version': scanner_version,
            'watchlist_type': 'CALL',
            'stocks': call_shortlist_stocks
        }
        put_payload = {
            'generated_date': scan_date,
            'scanner_version': scanner_version,
            'watchlist_type': 'PUT',
            'stocks': put_shortlist_stocks
        }

        call_path = os.path.join(output_dir, "call_stocks.yaml")
        put_path = os.path.join(output_dir, "put_stocks.yaml")

        with open(call_path, 'w', encoding='utf-8') as f:
            yaml.dump(call_payload, f, sort_keys=False, default_flow_style=False)
        with open(put_path, 'w', encoding='utf-8') as f:
            yaml.dump(put_payload, f, sort_keys=False, default_flow_style=False)

        generated_files['call'] = call_path
        generated_files['put'] = put_path
        logger.info(f"Generated shortlist CALL YAML: {call_path} ({len(call_shortlist_stocks)} stocks)")
        logger.info(f"Generated shortlist PUT YAML: {put_path} ({len(put_shortlist_stocks)} stocks)")

    return generated_files
