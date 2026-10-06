import sys
sys.path.insert(0, '.')
import sqlite3
import pandas as pd
import numpy as np
import yaml
from datetime import datetime, timezone

# Load themes config
with open('config/themes.yaml', 'r') as f:
    themes_cfg = yaml.safe_load(f)

from data.freshness import FreshnessPolicy, compute_eligibility_metadata, classify_eligibility, get_current_eligible_snapshots
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
cycles_data = []

for bid in range(2, 11):
    g = df_q[df_q['batch_id'] == bid]
    cycle_ts = g['fetched_at'].max()
    cycles_data.append({
        'cycle_index': bid - 1,
        'batch_id': bid,
        'timestamp': cycle_ts,
        'quotes': g
    })

print(f"Loaded {len(cycles_data)} collection cycles.")
for c in cycles_data:
    q = c['quotes']
    ages = q['data_age_seconds']
    print(f"Cycle {c['cycle_index']}: ts={c['timestamp']} count={len(q)} valid={q['is_valid'].sum()} fresh={(ages<=60).sum()} aging={((ages>60)&(ages<=300)).sum()} stale={(ages>300).sum()}")
