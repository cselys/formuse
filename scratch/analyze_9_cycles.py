import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/sector_radar.db')

print("=== QUOTE SNAPSHOTS 9 BATCHES (Batches 2..10) ===")
df_q = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, price, previous_close, today_open, volume FROM quote_snapshots ORDER BY fetched_at', conn)
df_q['ts'] = pd.to_datetime(df_q['fetched_at'])
df_q['diff'] = (df_q['ts'] - df_q['ts'].shift(1)).dt.total_seconds()
df_q['batch_id'] = (df_q['diff'] > 120).cumsum()

for bid in range(2, 11):
    g = df_q[df_q['batch_id'] == bid]
    ages = g['data_age_seconds']
    fresh = (ages <= 60).sum()
    aging = ((ages > 60) & (ages <= 300)).sum()
    stale = (ages > 300).sum()
    null_ages = ages.isna().sum()
    print(f"Cycle {bid-1} (Batch {bid}): start={g['ts'].min()}, end={g['ts'].max()}, count={len(g)}, valid={g['is_valid'].sum()}, invalid={(g['is_valid']==0).sum()}, fresh={fresh}, aging={aging}, stale={stale}")

print("\n=== STOCK SNAPSHOTS RECENT 9 TIMESTAMPS ===")
stk_ts = pd.read_sql('SELECT DISTINCT timestamp FROM stock_snapshots ORDER BY timestamp DESC LIMIT 9', conn)['timestamp'].tolist()
for i, ts in enumerate(stk_ts):
    df_s = pd.read_sql('SELECT symbol, price, previous_close, today_open FROM stock_snapshots WHERE timestamp = ?', conn, params=(ts,))
    print(f"Stock Snapshot {i+1}: timestamp={ts}, count={len(df_s)}")
