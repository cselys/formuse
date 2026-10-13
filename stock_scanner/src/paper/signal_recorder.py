"""
Signal recorder module for Paper Validation subsystem.
Creates immutable daily scan snapshots and paper signal records for candidates.
"""

import os
import json
import logging
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional

from stock_scanner.src.scanner import StockScanner
from stock_scanner.src.paper.models import PaperSignal, PaperOutcome

logger = logging.getLogger("stock_scanner.paper.recorder")


class SignalRecorder:
    """Records immutable daily snapshots and generates paper signals for candidates."""

    def __init__(self, signals_dir: str = "data/paper_validation/signals", outcomes_dir: str = "data/paper_validation/outcomes", scanner: Optional[StockScanner] = None):
        self.signals_dir = signals_dir
        self.outcomes_dir = outcomes_dir
        self.scanner = scanner or StockScanner()
        os.makedirs(self.signals_dir, exist_ok=True)
        os.makedirs(self.outcomes_dir, exist_ok=True)

    def record_daily_scan(self, scan_date: Optional[str] = None, target_category: Optional[str] = None) -> Dict[str, Any]:
        """
        Run the scanner, save an immutable daily snapshot of all scanned symbols,
        identify paper candidates, create paper signal records and initialize outcome records.
        """
        if not scan_date:
            scan_date = datetime.now().strftime("%Y-%m-%d")

        logger.info(f"Running daily scan for paper validation on date: {scan_date}")
        results = self.scanner.scan(target_category=target_category)
        if isinstance(results, tuple):
            results, _ = results

        if not results:
            logger.warning("No scan results generated.")
            return {"scan_date": scan_date, "symbols_scanned": 0, "candidates_recorded": 0}

        # 1. Save immutable snapshot of all scanned symbols
        snapshot_filename = f"{scan_date}.json"
        snapshot_path = os.path.join(self.signals_dir, snapshot_filename)

        # Immutability check: if snapshot exists, version it
        if os.path.exists(snapshot_path):
            counter = 2
            while True:
                versioned_filename = f"{scan_date}_v{counter}.json"
                versioned_path = os.path.join(self.signals_dir, versioned_filename)
                if not os.path.exists(versioned_path):
                    snapshot_path = versioned_path
                    snapshot_filename = versioned_filename
                    break
                counter += 1
            logger.warning(f"Snapshot for {scan_date} already exists. Saving as versioned duplicate: {snapshot_filename}")

        snapshot_data = {
            "scan_date": scan_date,
            "scanner_version": self.scanner.version,
            "created_at": datetime.now().isoformat(),
            "total_symbols_scanned": len(results),
            "symbols": []
        }

        # Simplify results for snapshot storage (remove bulky dataframes if any, keep indicators & breakdown)
        cleaned_results = []
        for r in results:
            cleaned = {
                "scan_date": scan_date,
                "scanner_version": r.get('scanner_version'),
                "symbol": r.get('symbol'),
                "category": r.get('category'),
                "state": r.get('state'),
                "candidate_score": r.get('candidate_score'),
                "trend_score": r.get('trend_score'),
                "bottom_score": r.get('bottom_score'),
                "reversal_score": r.get('reversal_score'),
                "entry_quality": r.get('entry_quality'),
                "market_regime": r.get('market_regime'),
                "price": r.get('daily', {}).get('close', 0.0),
                "rsi": r.get('daily', {}).get('rsi', 0.0),
                "macd": r.get('daily', {}).get('macd', 0.0),
                "volume_ratio": r.get('daily', {}).get('volume_ratio', 0.0),
                "distance_ema20": r.get('daily', {}).get('distance_ema20', 0.0),
                "distance_ema50": r.get('daily', {}).get('distance_ema50', 0.0),
                "atr_pct": r.get('daily', {}).get('atr_pct', 0.0),
                "relative_strength": r.get('relative_strength', {}),
                "trend_score_breakdown": r.get('trend_score_breakdown', {}),
                "bottom_score_breakdown": r.get('bottom_score_breakdown', {}),
                "reversal_score_breakdown": r.get('reversal_score_breakdown', {}),
                "entry_quality_details": r.get('entry_quality_details', {}),
                "candidate_score_breakdown": r.get('candidate_score_breakdown', {})
            }
            snapshot_data["symbols"].append(cleaned)
            cleaned_results.append((r, cleaned))

        with open(snapshot_path, 'w', encoding='utf-8') as f:
            json.dump(snapshot_data, f, indent=2)
        logger.info(f"Saved immutable scan snapshot to {snapshot_path}")

        # 2. Identify candidates and create paper signals
        pv_config = self.scanner.config.get('paper_validation', {})
        actionable_states = pv_config.get('actionable_states', ['REVERSAL', 'EARLY_UPTREND', 'BOTTOM_BREAKOUT'])
        watchlist_states = pv_config.get('watchlist_states', ['UPTREND', 'BOTTOM_FORMING', 'REVERSAL_CONFIRMED'])
        act_min_score = pv_config.get('actionable_min_candidate_score', 70)
        watch_min_score = pv_config.get('watchlist_min_candidate_score', 70)

        paper_signals = []
        paper_outcomes = []

        for r, cleaned in cleaned_results:
            state = r.get('state')
            c_score = r.get('candidate_score', 0.0)

            signal_tier = None
            if state in actionable_states and c_score >= act_min_score:
                signal_tier = "ACTIONABLE"
            elif state in watchlist_states and c_score >= watch_min_score:
                signal_tier = "WATCHLIST"

            if not signal_tier:
                continue

            symbol = r.get('symbol')
            signal_id = f"sig_{symbol}_{scan_date}_{uuid.uuid4().hex[:6]}"
            signal_price = cleaned['price']
            signal_timestamp = f"{scan_date} 23:59:59"

            paper_sig = PaperSignal(
                signal_id=signal_id,
                scanner_version=r.get('scanner_version', '1.2'),
                signal_date=scan_date,
                symbol=symbol,
                category=r.get('category', 'general'),
                signal_type=state,
                signal_tier=signal_tier,
                signal_price=signal_price,
                signal_timestamp=signal_timestamp,
                price_source="close",
                trend_score=r.get('trend_score', 0.0),
                bottom_score=r.get('bottom_score', 0.0),
                reversal_score=r.get('reversal_score', 0.0),
                entry_quality=r.get('entry_quality', 0.0),
                candidate_score=c_score,
                market_regime=r.get('market_regime', 'UNKNOWN'),
                relative_strength=r.get('relative_strength', {}),
                indicators_snapshot={
                    "rsi": cleaned['rsi'],
                    "macd": cleaned['macd'],
                    "volume_ratio": cleaned['volume_ratio'],
                    "distance_ema20": cleaned['distance_ema20'],
                    "distance_ema50": cleaned['distance_ema50'],
                    "atr_pct": cleaned['atr_pct']
                }
            )

            paper_outcome = PaperOutcome(
                signal_id=signal_id,
                symbol=symbol,
                signal_date=scan_date,
                signal_price=signal_price,
                status="OPEN",
                state_transitions=[{"date": scan_date, "state": state}]
            )

            paper_signals.append(paper_sig.to_dict())
            paper_outcomes.append(paper_outcome.to_dict())

        # Save signals and outcomes JSON files for the day
        signals_file = os.path.join(self.signals_dir, f"signals_{scan_date}.json")
        outcomes_file = os.path.join(self.outcomes_dir, f"outcome_{scan_date}.json")

        with open(signals_file, 'w', encoding='utf-8') as f:
            json.dump(paper_signals, f, indent=2)

        with open(outcomes_file, 'w', encoding='utf-8') as f:
            json.dump(paper_outcomes, f, indent=2)

        logger.info(f"Recorded {len(paper_signals)} paper signals for {scan_date}. Saved to {signals_file} and {outcomes_file}.")

        return {
            "scan_date": scan_date,
            "snapshot_path": snapshot_path,
            "signals_path": signals_file,
            "outcomes_path": outcomes_file,
            "symbols_scanned": len(results),
            "candidates_recorded": len(paper_signals)
        }
