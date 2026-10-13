"""
Main Stock Scanner orchestrator for stock_scanner V1.2.
Coordinates configuration, data download, analysis, scoring, classification, reporting, and Gemini AI.
"""

import os
import logging
import yaml
import pandas as pd
from typing import Dict, List, Optional, Any

from stock_scanner.src.data.yfinance_loader import YFinanceLoader, DataValidationError
from stock_scanner.src.data.historical_cache import update_symbol_cache, update_universe_cache, load_cached_data
from stock_scanner.src.ai.gemini import GeminiExplainer
from stock_scanner.src.reporting.console import display_console_report
from stock_scanner.src.reporting.csv_report import save_csv_report
from stock_scanner.src.reporting.json_report import save_json_report
from stock_scanner.src.reporting.yaml_watchlist import save_watchlist_yaml
from stock_scanner.src.data.market_calendar import (
    cutoff_timestamp, completed_daily, completed_weekly, week_context, uses_completed_weeks,
)
from stock_scanner.src.analysis.weekly_diagnostics import weekly_diagnostics
from stock_scanner.src.analysis.snapshot import analyze_snapshot
from stock_scanner.src.reporting.weekly_report import build_weekly_records
from stock_scanner.src.data.scanner_history import calculation_signature, history_context, weekly_policy, result_fingerprint
from stock_scanner.src.validation.universe_validator import validate_universe_yaml

logger = logging.getLogger("stock_scanner")


class StockScanner:
    """Orchestrator for the stock_scanner V1.2 system."""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.config = self._load_yaml(os.path.join(config_dir, "scanner.yaml"))
        self.universe = self._load_yaml(os.path.join(config_dir, "universe.yaml"))
        self.version = self.config.get('scanner_version', '1.2')
        self.loader = YFinanceLoader()
        self.explainer = GeminiExplainer()
        # Validate universe configuration early, rather than silently
        # filtering invalid entries downstream.
        self._universe_path = os.path.join(config_dir, "universe.yaml")
        validate_universe_yaml(self.universe, file_path=self._universe_path)

    def _load_yaml(self, path: str) -> dict:
        if not os.path.exists(path):
            logger.warning(f"Config file not found at {path}, using empty dict.")
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def scan(
        self,
        target_category: Optional[str] = None,
        target_symbol: Optional[str] = None,
        target_state: Optional[str] = None,
        enable_ai: bool = False,
        top_n: Optional[int] = None,
        report_period: str = 'auto',
        as_of=None,
        offline_frames=None,
        write_outputs=True,
    ) -> List[dict]:
        """
        Run scan across universe or filtered subset.
        """
        if report_period not in ('auto', 'daily', 'weekly', 'both'):
            raise ValueError('report_period must be auto, daily, weekly, or both')
        cutoff = cutoff_timestamp(as_of)
        weekly_context = week_context(cutoff)
        generate_weekly = report_period in ('weekly', 'both') or (
            report_period == 'auto' and weekly_context['auto_weekly'])
        categories = self.universe.get('categories', {})
        market_benchmarks = self.universe.get('market_benchmarks', ['SPY', 'QQQ'])
        sector_indexes_cfg = self.universe.get('sector_indexes', {})

        symbols_to_category = {}
        category_benchmarks = {}

        for cat_name, cat_data in categories.items():
            if target_category and cat_name.lower() != target_category.lower():
                continue
            bench = cat_data.get('benchmark', 'QQQ')
            category_benchmarks[cat_name] = bench
            for sym in cat_data.get('symbols', []):
                if not isinstance(sym, str):
                    logger.warning(f"Expected string symbol, got {type(sym)} in category {cat_name}")
                    continue
                sym_upper = sym.strip().upper()
                if target_symbol and sym_upper != target_symbol.upper():
                    continue
                symbols_to_category[sym_upper] = cat_name

        if target_symbol and not symbols_to_category:
            sym_upper = target_symbol.strip().upper()
            symbols_to_category[sym_upper] = target_category or 'custom'
            category_benchmarks[target_category or 'custom'] = 'SPY'

        if not symbols_to_category:
            logger.warning("No symbols found matching criteria.")
            return []

        all_symbols = set(symbols_to_category.keys())
        for bench in market_benchmarks:
            all_symbols.add(bench)
        for bench in category_benchmarks.values():
            all_symbols.add(bench)
        for idx_sym in sector_indexes_cfg.values():
            all_symbols.add(idx_sym.strip().upper())

        if offline_frames is not None:
            if as_of is None or write_outputs or enable_ai:
                raise ValueError('Offline scan requires explicit as_of, write_outputs=False and AI disabled')
            missing = all_symbols - set(offline_frames)
            if missing:
                raise ValueError(f'Missing offline stock/benchmark inputs: {sorted(missing)}')
            raw_data = {symbol: offline_frames[symbol].copy(deep=True) for symbol in all_symbols}
            raw_data = {symbol: completed_daily(frame, cutoff) for symbol, frame in raw_data.items()}
            if any(frame.empty or str(frame.index[-1].date()) != weekly_context['latest_session']
                   for frame in raw_data.values()):
                raise ValueError('Offline inputs must include the exact completed session for every stock/benchmark')
        else:
            logger.info(f"Downloading historical data for {len(all_symbols)} symbols...")
            # Step 1: Perform cache-aware incremental updates
            # This updates the persistent parquet cache on disk
            update_universe_cache(
                list(all_symbols),
                fetch_recent_days=5,
            )

            # Step 2: Load cached data for all symbols from persistent cache
            raw_data = {}
            for sym in all_symbols:
                df = load_cached_data(sym)
                if df is not None and not df.empty:
                    raw_data[sym] = df
                    logger.debug(f"Loaded {len(df)} cached bars for {sym}")
                else:
                    # Fallback: download fresh if no cache exists (first run)
                    try:
                        df = self.loader.download_ticker(sym)
                        raw_data[sym] = df
                        logger.info(f"Fresh download for {sym} ({len(df)} bars)")
                    except Exception as e:
                        logger.warning(f"Could not fetch data for {sym}: {e}")
        # V1.3 only consumes closed daily sessions and completed weekly candles.
        if uses_completed_weeks(self.config):
            raw_data = {s: completed_daily(df, cutoff) for s, df in raw_data.items()}
            raw_data = {s: df for s, df in raw_data.items() if not df.empty}
        completed_week_data = {}
        for s, df in raw_data.items():
            try:
                completed_week_data[s] = completed_weekly(df, cutoff)
            except (ValueError, TypeError, KeyError):
                logger.exception('Unable to build completed weekly candles for %s', s)
                completed_week_data[s] = pd.DataFrame(columns=['Open', 'High', 'Low', 'Close', 'Volume'], index=pd.DatetimeIndex([]))

        # and sector breadth. These are never part of symbols_to_category.
        index_symbols = {s.strip().upper() for s in self.universe.get('etf_symbols', [])}
        for bench in market_benchmarks:
            index_symbols.add(bench.strip().upper())
        for bench in category_benchmarks.values():
            index_symbols.add(bench.strip().upper())
        for idx_sym in sector_indexes_cfg.values():
            index_symbols.add(idx_sym.strip().upper())
        # A category explicitly typed as an index/ETF contributes index symbols.
        for cat_name, cat_data in categories.items():
            if cat_data.get('instrument_type', '').lower() in ('index', 'etf'):
                for sym in cat_data.get('symbols', []):
                    index_symbols.add(sym.strip().upper())

        # Compute daily change for each configured sector index/ETF so the report
        # can rank sector index performance without adding them to scan results.
        sector_index_data = {}
        for sector_name, idx_sym in sector_indexes_cfg.items():
            idx_sym_upper = idx_sym.strip().upper()
            idx_df = raw_data.get(idx_sym_upper)
            change = self._compute_daily_change(idx_df) if idx_df is not None else None
            if change is None:
                logger.warning(f"Unable to calculate daily change for sector index {idx_sym_upper}")
            sector_index_data[sector_name] = {
                'symbol': idx_sym_upper,
                'sector': sector_name,
                'change_pct': change.get('change_pct') if change else None,
                'close': (float(idx_df['Close'].iloc[-1]) if idx_df is not None and 'Close' in idx_df.columns and not idx_df['Close'].dropna().empty else None),
                'data_date': change.get('data_date') if change else None,
            }

        report_context = {
            'sector_indexes_cfg': sector_indexes_cfg,
            'index_symbols': index_symbols,
            'sector_index_data': sector_index_data,
            'weekly_context': weekly_context,
            'generate_weekly': generate_weekly,
            'scope': 'filtered subset' if target_category or target_symbol or target_state else 'full universe',
        }

        if generate_weekly:
            weekly_symbols = dict(symbols_to_category)
            for sector, symbol in sector_indexes_cfg.items():
                weekly_symbols.setdefault(symbol.upper(), sector)
            report_context['weekly_records'] = build_weekly_records(
                raw_data, weekly_symbols, category_benchmarks, index_symbols, self.config, weekly_context)
            # Apply state filters to the week's own state, not the live daily state.
            if target_state:
                report_context['weekly_records'] = [r for r in report_context['weekly_records']
                    if r.get('is_index_etf') or r.get('state', '').lower() == target_state.lower()]

        spy_df = raw_data.get('SPY') if 'SPY' in raw_data else raw_data.get('QQQ')
        if spy_df is None and raw_data:
            spy_df = list(raw_data.values())[0]

        results = []
        history_calculation_signature = calculation_signature(self.config)

        for symbol, cat_name in symbols_to_category.items():
            if symbol not in raw_data:
                logger.warning(f"Skipping {symbol}: No data downloaded.")
                continue

            df_daily = raw_data[symbol]
            bench_sym = category_benchmarks.get(cat_name, 'SPY')
            df_bench = raw_data.get(bench_sym) if bench_sym in raw_data else spy_df

            try:
                # Compute daily change from the loaded yfinance daily data
                # (point-in-time, previous available trading session).
                daily_change = self._compute_daily_change(df_daily)
                if daily_change is None:
                    logger.warning(f"Unable to calculate daily change for {symbol}")

                # The same deterministic formulas serve live and week-end snapshots.
                df_weekly = (completed_week_data[symbol] if uses_completed_weeks(self.config)
                             else self.loader.resample_to_weekly(df_daily))
                snapshot = analyze_snapshot(df_daily, df_weekly, df_bench, spy_df, self.config)
                state = snapshot['state']

                if target_state and state.lower() != target_state.lower():
                    continue

                record = {
                    'scanner_version': self.version,
                    'symbol': symbol,
                    'category': cat_name,
                    'is_index_etf': symbol in index_symbols,
                    'is_sector_index': symbol in index_symbols and symbol not in market_benchmarks and symbol not in category_benchmarks.values(),
                    'daily_change_pct': (daily_change.get('change_pct') if daily_change else None),
                    'previous_close': (daily_change.get('previous_close') if daily_change else None),
                    'data_date': (daily_change.get('data_date') if daily_change else None),
                    **snapshot,
                }
                record['data_status'] = ('OK' if record['data_date'] == weekly_context['latest_session'] else 'STALE')
                record['as_of'] = cutoff.isoformat()
                # Reporting provenance only; all calculation inputs and scores are unchanged.
                market_symbol = ('SPY' if 'SPY' in raw_data else 'QQQ' if 'QQQ' in raw_data
                                 else next(iter(raw_data), None))
                effective_benchmark = bench_sym if bench_sym in raw_data else market_symbol
                record['history_context'] = history_context(
                    history_calculation_signature, symbol, cat_name, effective_benchmark, market_symbol,
                    df_daily, df_weekly, df_bench, spy_df,
                    calculation_policy=weekly_policy(self.config, historical=False))
                record['history_result_fingerprint'] = result_fingerprint(snapshot)
                record['weekly_diagnostics'] = weekly_diagnostics(
                    completed_week_data[symbol], snapshot['daily'], self.config, weekly_context,
                    completed_week_data.get('SPY', completed_week_data.get('QQQ')),
                    completed_week_data.get(bench_sym))

                if enable_ai and self.explainer.client:
                    logger.info(f"Generating Gemini AI explanation for {symbol}...")
                    explanation = self.explainer.explain_symbol(symbol, cat_name, state, record, record)
                    if explanation:
                        record['ai_explanation'] = explanation.model_dump()

                results.append(record)
                logger.info('Scanned %s: State=%s, Candidate=%s, Trend=%s, EntryQ=%s',
                            symbol, state, snapshot['candidate_score'], snapshot['trend_score'], snapshot['entry_quality'])

            except Exception as e:
                logger.error(f"Error processing symbol {symbol}: {e}")

        # Automatically generate CALL and PUT watchlist YAML outputs
        if results and write_outputs:
            try:
                save_watchlist_yaml(results, output_dir="output", config=self.config)
            except Exception as e:
                logger.error(f"Failed to save YAML watchlists: {e}")

        if self._has_report_context(results) or generate_weekly:
            return results, report_context
        return results

    @staticmethod
    def _compute_daily_change(df_daily: pd.DataFrame) -> Optional[Dict[str, Any]]:
        """
        Compute the point-in-time daily percentage change using the last two
        available trading sessions:
            (today_close / previous_trading_day_close - 1) * 100
        Returns None if the data is insufficient, missing, or invalid.
        """
        if df_daily is None or df_daily.empty or 'Close' not in df_daily.columns:
            return None
        valid = df_daily[['Close']].dropna()
        if len(valid) < 2:
            return None
        try:
            today_close = float(valid['Close'].iloc[-1])
            prev_close = float(valid['Close'].iloc[-2])
            if prev_close <= 0 or today_close <= 0:
                return None
            change_pct = (today_close / prev_close - 1.0) * 100.0
            return {
                'change_pct': change_pct,
                'previous_close': prev_close,
                'data_date': str(valid.index[-1].date()),
            }
        except Exception:
            return None

    @staticmethod
    def _has_report_context(results: List[dict]) -> bool:
        """A full-universe scan (no category/symbol filter) can produce a daily report."""
        return bool(results) and any(
            r.get('symbol') not in ('SPY', 'QQQ') and not r.get('is_index_etf', False)
            for r in results
        )
