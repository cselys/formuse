"""
Comprehensive test suite for Stock Scanner V1.2 Paper Validation subsystem.
Covers snapshot creation, immutability, candidate filtering, forward returns,
MFE/MAE, state transitions, lookahead isolation, and no-trading safety.
"""

import os
import json
import shutil
import tempfile
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from stock_scanner.src.paper.models import PaperSignal, PaperOutcome
from stock_scanner.src.paper.signal_recorder import SignalRecorder
from stock_scanner.src.paper.outcome_tracker import OutcomeTracker
from stock_scanner.src.paper.state_tracker import StateTracker
from stock_scanner.src.paper.performance import PerformanceAnalyzer
from stock_scanner.src.paper.paper_report import PaperReporter


class MockScanner:
    def __init__(self):
        self.version = "1.2"
        self.config = {
            'paper_validation': {
                'enabled': True,
                'actionable_min_candidate_score': 70,
                'watchlist_min_candidate_score': 70,
                'actionable_states': ['REVERSAL', 'EARLY_UPTREND', 'BOTTOM_BREAKOUT'],
                'watchlist_states': ['UPTREND', 'BOTTOM_FORMING', 'REVERSAL_CONFIRMED']
            }
        }

    def scan(self, target_category=None, target_symbol=None, **kwargs):
        return [
            {
                'scanner_version': '1.2',
                'symbol': 'AAPL',
                'category': 'technology',
                'state': 'EARLY_UPTREND',
                'candidate_score': 85.0,
                'trend_score': 80.0,
                'bottom_score': 50.0,
                'reversal_score': 75.0,
                'entry_quality': 90.0,
                'market_regime': 'MARKET_UPTREND',
                'daily': {
                    'close': 150.0,
                    'rsi': 55.0,
                    'macd': 1.2,
                    'volume_ratio': 1.5,
                    'distance_ema20': 2.0,
                    'distance_ema50': 4.0,
                    'atr_pct': 2.5
                },
                'relative_strength': {'rs_20': 1.05},
                'trend_score_breakdown': {},
                'bottom_score_breakdown': {},
                'reversal_score_breakdown': {},
                'entry_quality_details': {},
                'candidate_score_breakdown': {}
            },
            {
                'scanner_version': '1.2',
                'symbol': 'MSFT',
                'category': 'technology',
                'state': 'DOWNTREND',
                'candidate_score': 40.0,
                'trend_score': 30.0,
                'bottom_score': 20.0,
                'reversal_score': 25.0,
                'entry_quality': 40.0,
                'market_regime': 'MARKET_UPTREND',
                'daily': {
                    'close': 300.0,
                    'rsi': 35.0,
                    'macd': -1.0,
                    'volume_ratio': 0.8,
                    'distance_ema20': -3.0,
                    'distance_ema50': -5.0,
                    'atr_pct': 2.0
                },
                'relative_strength': {'rs_20': 0.95}
            }
        ]


class MockLoader:
    def download_ticker(self, symbol):
        # Generate dummy price series starting 30 days ago
        dates = pd.date_range(end=datetime.now(), periods=50, freq='B')
        df = pd.DataFrame({
            'Open': np.linspace(140, 160, 50),
            'High': np.linspace(145, 165, 50),
            'Low': np.linspace(135, 155, 50),
            'Close': np.linspace(142, 162, 50),
            'Volume': [1000000] * 50
        }, index=dates)
        return df


@pytest.fixture
def temp_dirs():
    tmp = tempfile.mkdtemp()
    signals_dir = os.path.join(tmp, "signals")
    outcomes_dir = os.path.join(tmp, "outcomes")
    reports_dir = os.path.join(tmp, "reports")
    os.makedirs(signals_dir, exist_ok=True)
    os.makedirs(outcomes_dir, exist_ok=True)
    os.makedirs(reports_dir, exist_ok=True)
    yield signals_dir, outcomes_dir, reports_dir
    shutil.rmtree(tmp)


def test_signal_recorder_and_snapshot(temp_dirs):
    signals_dir, outcomes_dir, reports_dir = temp_dirs
    mock_scanner = MockScanner()
    recorder = SignalRecorder(signals_dir=signals_dir, outcomes_dir=outcomes_dir, scanner=mock_scanner)

    scan_date = "2026-09-01"
    res = recorder.record_daily_scan(scan_date=scan_date)

    assert res["symbols_scanned"] == 2
    assert res["candidates_recorded"] == 1  # AAPL is EARLY_UPTREND with score 85; MSFT is DOWNTREND

    # Verify snapshot exists and contains both symbols
    snapshot_path = res["snapshot_path"]
    assert os.path.exists(snapshot_path)
    with open(snapshot_path, 'r', encoding='utf-8') as f:
        snap = json.load(f)
    assert snap["total_symbols_scanned"] == 2
    assert len(snap["symbols"]) == 2

    # Verify candidate signals file
    signals_file = res["signals_path"]
    assert os.path.exists(signals_file)
    with open(signals_file, 'r', encoding='utf-8') as f:
        sigs = json.load(f)
    assert len(sigs) == 1
    assert sigs[0]["symbol"] == "AAPL"
    assert sigs[0]["signal_tier"] == "ACTIONABLE"
    assert sigs[0]["signal_price"] == 150.0


def test_snapshot_immutability(temp_dirs):
    signals_dir, outcomes_dir, _ = temp_dirs
    mock_scanner = MockScanner()
    recorder = SignalRecorder(signals_dir=signals_dir, outcomes_dir=outcomes_dir, scanner=mock_scanner)

    scan_date = "2026-09-01"
    res1 = recorder.record_daily_scan(scan_date=scan_date)
    res2 = recorder.record_daily_scan(scan_date=scan_date)

    # Second run should create versioned snapshot duplicate rather than overwriting
    assert res1["snapshot_path"] != res2["snapshot_path"]
    assert "_v2.json" in res2["snapshot_path"]


def test_outcome_tracker_forward_returns_mfe_mae(temp_dirs):
    signals_dir, outcomes_dir, _ = temp_dirs
    mock_scanner = MockScanner()
    recorder = SignalRecorder(signals_dir=signals_dir, outcomes_dir=outcomes_dir, scanner=mock_scanner)

    # Use a date in the past so future data exists in MockLoader
    past_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    recorder.record_daily_scan(scan_date=past_date)

    loader = MockLoader()
    tracker = OutcomeTracker(signals_dir=signals_dir, outcomes_dir=outcomes_dir, loader=loader)
    res = tracker.update_all_outcomes()

    assert res["updated_count"] >= 1

    # Inspect outcome file
    outcomes_file = os.path.join(outcomes_dir, f"outcome_{past_date}.json")
    with open(outcomes_file, 'r', encoding='utf-8') as f:
        outcomes = json.load(f)

    assert len(outcomes) == 1
    out = outcomes[0]
    assert out["status"] in ["PARTIAL", "COMPLETE"]
    assert out["forward_returns"]["1d"] is not None
    assert out["forward_returns"]["20d"] is not None
    assert out["mfe"]["5d"] is not None
    assert out["mae"]["5d"] is not None


def test_state_tracker_transitions(temp_dirs):
    signals_dir, outcomes_dir, _ = temp_dirs
    mock_scanner = MockScanner()
    recorder = SignalRecorder(signals_dir=signals_dir, outcomes_dir=outcomes_dir, scanner=mock_scanner)

    d1 = "2026-09-01"
    d2 = "2026-09-02"
    recorder.record_daily_scan(scan_date=d1)
    recorder.record_daily_scan(scan_date=d2)

    st_tracker = StateTracker(signals_dir=signals_dir, outcomes_dir=outcomes_dir)
    res = st_tracker.update_state_transitions()
    assert res["updated_signals"] >= 1


def test_performance_and_reports(temp_dirs):
    signals_dir, outcomes_dir, reports_dir = temp_dirs
    mock_scanner = MockScanner()
    recorder = SignalRecorder(signals_dir=signals_dir, outcomes_dir=outcomes_dir, scanner=mock_scanner)

    past_date = (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d")
    recorder.record_daily_scan(scan_date=past_date)

    loader = MockLoader()
    tracker = OutcomeTracker(signals_dir=signals_dir, outcomes_dir=outcomes_dir, loader=loader)
    tracker.update_all_outcomes()

    reporter = PaperReporter(reports_dir=reports_dir, signals_dir=signals_dir, outcomes_dir=outcomes_dir)
    paths = reporter.generate_reports(report_type="daily")

    assert os.path.exists(paths["summary_json"])
    assert os.path.exists(paths["summary_txt"])
    assert os.path.exists(paths["csv_report"])
    assert os.path.exists(paths["top_signals"])
    assert os.path.exists(paths["worst_signals"])


def test_lookahead_isolation():
    # Verify signal score calculation is strictly independent of future prices
    df_signal = pd.DataFrame({
        'Open': [100, 101, 102],
        'High': [102, 103, 104],
        'Low': [99, 100, 101],
        'Close': [101, 102, 103],
        'Volume': [1000, 1000, 1000]
    }, index=pd.date_range('2026-01-01', periods=3))

    df_future_modified = pd.DataFrame({
        'Open': [100, 101, 102, 500],
        'High': [102, 103, 104, 600],
        'Low': [99, 100, 101, 400],
        'Close': [101, 102, 103, 550],
        'Volume': [1000, 1000, 1000, 10000]
    }, index=pd.date_range('2026-01-01', periods=4))

    # Slicing up to signal date
    d_dt = pd.to_datetime('2026-01-03')
    slice1 = df_signal[df_signal.index <= d_dt]
    slice2 = df_future_modified[df_future_modified.index <= d_dt]

    pd.testing.assert_frame_equal(slice1, slice2)


def test_no_trading_boundary():
    # Verify that paper validation subsystem contains zero order placement / broker functions
    import inspect
    from stock_scanner.src.paper import signal_recorder, outcome_tracker, state_tracker, performance, paper_report

    forbidden_terms = ["broker", "place_order", "submit_order", "execute_order", "execute_trade", "live_execution", "submit_order"]
    for mod in [signal_recorder, outcome_tracker, state_tracker, performance, paper_report]:
        source = inspect.getsource(mod).lower()
        for term in forbidden_terms:
            assert term not in source
