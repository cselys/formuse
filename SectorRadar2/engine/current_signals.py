"""Current-only basket policy; canonical historical observations stay untouched."""
import numpy as np
import pandas as pd

from data.freshness import classify_eligibility, current_signal_policy
from data.snapshot_loader import snapshot_from_row
from engine.breadth_engine import compute_breadth
from engine.theme_history import prepare_quotes
from utils.config import get_setting


def current_observation(quotes, symbols, cutoff, settings):
    """Latest valid provider quote at/before the shared cutoff, partial basket."""
    symbols = list(dict.fromkeys(symbols))
    q = prepare_quotes(quotes, symbols)
    q = q.iloc[:0] if cutoff is None else q[q.provider_timestamp <= pd.Timestamp(cutoff).timestamp()]
    stocks = [snapshot_from_row(r, cutoff) for r in q.drop_duplicates('symbol', keep='last').to_dict('records')]
    policy = current_signal_policy(settings)
    result = compute_breadth(stocks, settings, total=len(symbols), policy=policy)
    eligible = [s for s in stocks if classify_eligibility(s, policy).participates_in_current]
    count = result['valid_stocks']
    sufficient = count >= min(2, len(symbols)) and count > 0
    result.update(eligible_stocks=count, eligible_count=count, sufficient=sufficient,
                  total_constituents=len(symbols),
                  no_data_stocks=result['no_data_stocks'] + len(symbols) - len(stocks),
                  status='PASS' if sufficient else 'INSUFFICIENT DATA',
                  constituents=tuple(sorted(s.symbol for s in eligible)))
    if not sufficient:
        for key in ('up_percent', 'down_percent', 'flat_percent', 'strong_up_percent',
                    'strong_down_percent', 'average_return', 'median_return',
                    'average_change_from_open', 'median_change_from_open'):
            result[key] = np.nan
        result.update(valid_stocks=0, missing_stocks=len(symbols))
    return result


def with_current_signals(historical, history, current, settings):
    """Keep extrema and offset breadth intact; substitute only current operands."""
    result = dict(historical)
    value, breadth = current['average_return'], current['up_percent']
    result.update(reversal_from_high=value - result['intraday_high'],
                  recovery_from_low=value - result['intraday_low'], breadth_now=breadth,
                  breadth_change_5m=breadth - result['breadth_5m_ago'],
                  breadth_change_15m=breadth - result['breadth_15m_ago'])
    observed = history[history.avg_return.notna()] if not history.empty else history
    count = observed.observation_id.nunique() if 'observation_id' in observed else len(observed)
    result['has_history'] = bool(count >= get_setting(settings, 'state.min_history_bars', 3)
                                 and np.isfinite(value))
    return result
