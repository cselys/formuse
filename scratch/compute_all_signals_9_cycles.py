import sys
sys.path.insert(0, '.')
import sqlite3
import pandas as pd
import numpy as np
import yaml
from collections import Counter
from scipy.stats import spearmanr

# Load themes config
with open('config/themes.yaml', 'r') as f:
    themes_cfg = yaml.safe_load(f)

from data.freshness import FreshnessPolicy, compute_eligibility_metadata, get_current_eligible_snapshots
from models.schemas import StockSnapshot, ThemeMetrics, ETFComparison, UP, DOWN, FLAT
from utils.config import load_settings

settings = load_settings()
policy = FreshnessPolicy()

conn = sqlite3.connect('data/sector_radar.db')

# Extract quote batches
df_q = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, provider_timestamp, price, previous_close, today_open, intraday_high, intraday_low, volume, issue FROM quote_snapshots ORDER BY fetched_at', conn)
df_q['ts'] = pd.to_datetime(df_q['fetched_at'])
df_q['diff'] = (df_q['ts'] - df_q['ts'].shift(1)).dt.total_seconds()
df_q['batch_id'] = (df_q['diff'] > 120).cumsum()

# Batches 2..10 are the 9 RTH cycles on 2026-10-06
cycles = []
for bid in range(2, 11):
    g = df_q[df_q['batch_id'] == bid]
    cycle_ts = g['fetched_at'].max()
    cycles.append({
        'cycle_index': bid - 1,
        'batch_id': bid,
        'timestamp': cycle_ts,
        'quotes': g
    })

# Compute ThemeMetrics for each cycle
theme_history_avg_ret = {theme: [] for theme in themes_cfg}
theme_history_up_pct = {theme: [] for theme in themes_cfg}

all_cycles_metrics = []

for c in cycles:
    c_idx = c['cycle_index']
    q_df = c['quotes']
    
    # Build stock snapshot dict
    stock_snaps = {}
    for _, r in q_df.iterrows():
        sym = r['symbol']
        p = r['price']
        pc = r['previous_close']
        o = r['today_open']
        
        chg_close = (p - pc) / pc * 100.0 if (p is not None and pc is not None and pc > 0) else None
        chg_open = (p - o) / o * 100.0 if (p is not None and o is not None and o > 0) else None
        
        snap = StockSnapshot(
            symbol=sym,
            timestamp=r['fetched_at'],
            previous_close=pc,
            today_open=o,
            current_price=p,
            intraday_high=r['intraday_high'],
            intraday_low=r['intraday_low'],
            change_vs_previous_close=chg_close,
            change_vs_open=chg_open,
            distance_from_intraday_high=(p - r['intraday_high'])/r['intraday_high']*100.0 if (p and r['intraday_high']) else None,
            distance_from_intraday_low=(p - r['intraday_low'])/r['intraday_low']*100.0 if (p and r['intraday_low']) else None,
            volume=int(r['volume']) if r['volume'] is not None else 0,
            is_valid=bool(r['is_valid']),
            issue=r['issue'] or "",
            direction=UP if (chg_close or 0) > 0.1 else (DOWN if (chg_close or 0) < -0.1 else FLAT),
            provider_timestamp=r['provider_timestamp'],
            fetched_at=r['fetched_at'],
            data_age_seconds=r['data_age_seconds']
        )
        stock_snaps[sym] = snap
        
    # Build ThemeMetrics for each theme
    cycle_theme_metrics = []
    
    for theme_name, t_cfg in themes_cfg.items():
        tickers = [t.strip().upper() for t in t_cfg.get('tickers', [])]
        etfs = [e.strip().upper() for e in t_cfg.get('etf', [])]
        
        snaps = [stock_snaps[t] for t in tickers if t in stock_snaps]
        meta = compute_eligibility_metadata(snaps, policy)
        eligible = get_current_eligible_snapshots(snaps, policy)
        
        valid_cnt = len(eligible)
        total_cnt = len(tickers)
        
        if valid_cnt > 0:
            returns = [s.change_vs_previous_close for s in eligible if s.change_vs_previous_close is not None]
            open_changes = [s.change_vs_open for s in eligible if s.change_vs_open is not None]
            
            avg_ret = float(np.mean(returns)) if returns else 0.0
            med_ret = float(np.median(returns)) if returns else 0.0
            avg_open_chg = float(np.mean(open_changes)) if open_changes else 0.0
            
            up_cnt = sum(1 for r in returns if r > 0.1)
            down_cnt = sum(1 for r in returns if r < -0.1)
            flat_cnt = len(returns) - up_cnt - down_cnt
            
            up_pct = (up_cnt / total_cnt) * 100.0
            down_pct = (down_cnt / total_cnt) * 100.0
            flat_pct = (flat_cnt / total_cnt) * 100.0
        else:
            avg_ret = 0.0
            med_ret = 0.0
            avg_open_chg = 0.0
            up_cnt = down_cnt = flat_cnt = 0
            up_pct = down_pct = flat_pct = 0.0
            
        theme_history_avg_ret[theme_name].append(avg_ret)
        theme_history_up_pct[theme_name].append(up_pct)
        
        # Intraday high / low across history up to current cycle
        hist_returns = theme_history_avg_ret[theme_name]
        intra_high = max(hist_returns)
        intra_low = min(hist_returns)
        reversal_from_high = avg_ret - intra_high # <= 0
        recovery_from_low = avg_ret - intra_low   # >= 0
        
        # Breadth momentum (15m: 2 cycles ago, ~15 min)
        if len(theme_history_up_pct[theme_name]) >= 3:
            breadth_momentum_15m = up_pct - theme_history_up_pct[theme_name][-3]
        elif len(theme_history_up_pct[theme_name]) == 2:
            breadth_momentum_15m = up_pct - theme_history_up_pct[theme_name][-2]
        else:
            breadth_momentum_15m = 0.0
            
        # ETF comparison
        etf_comps = []
        max_abs_div = 0.0
        primary_div = None
        
        for etf_sym in etfs:
            if etf_sym in stock_snaps and stock_snaps[etf_sym].is_valid and stock_snaps[etf_sym].change_vs_previous_close is not None:
                etf_ret = stock_snaps[etf_sym].change_vs_previous_close
                div = etf_ret - avg_ret
                etf_comps.append(ETFComparison(etf=etf_sym, etf_return=etf_ret, basket_return=avg_ret, divergence=div))
                if abs(div) > max_abs_div:
                    max_abs_div = abs(div)
                    primary_div = div
            else:
                etf_comps.append(ETFComparison(etf=etf_sym, etf_return=None, basket_return=avg_ret, divergence=None, note="no data"))
                
        tm = ThemeMetrics(
            theme=theme_name,
            timestamp=c['timestamp'],
            total_stocks=total_cnt,
            valid_stocks=valid_cnt,
            missing_stocks=total_cnt - valid_cnt,
            up_stocks=up_cnt,
            down_stocks=down_cnt,
            flat_stocks=flat_cnt,
            up_percent=up_pct,
            down_percent=down_pct,
            flat_percent=flat_pct,
            strong_up_percent=0.0,
            strong_down_percent=0.0,
            average_return=avg_ret,
            median_return=med_ret,
            average_change_from_open=avg_open_chg,
            median_change_from_open=0.0,
            total_volume=sum(s.volume for s in snaps if s.volume),
            intraday_high=intra_high,
            intraday_low=intra_low,
            reversal_from_high=reversal_from_high,
            recovery_from_low=recovery_from_low,
            breadth_now=up_pct,
            breadth_5m_ago=None,
            breadth_15m_ago=None,
            breadth_change_5m=None,
            breadth_change_15m=breadth_momentum_15m,
            state="MIXED",
            small_sample=(valid_cnt < 5),
            etf=etf_comps,
            eligible_stocks=meta['eligible_stocks'],
            aging_stocks=meta['aging_stocks'],
            stale_stocks=meta['stale_stocks'],
            no_data_stocks=meta['no_data_stocks'],
            oldest_quote_age=meta['oldest_quote_age'],
            newest_quote_age=meta['newest_quote_age']
        )
        # Store custom attribute for ETF max div
        setattr(tm, 'etf_max_div', max_abs_div)
        cycle_theme_metrics.append(tm)
        
    all_cycles_metrics.append(cycle_theme_metrics)

print(f"Computed metrics for {len(all_cycles_metrics)} cycles.")
