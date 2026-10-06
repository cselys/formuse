import sqlite3
import pandas as pd

conn = sqlite3.connect('data/sector_radar.db')

print("=== QUOTE SNAPSHOTS RECENT BATCHES ===")
df_q = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, price, previous_close, today_open, volume FROM quote_snapshots ORDER BY fetched_at', conn)
df_q['ts'] = pd.to_datetime(df_q['fetched_at'])
df_q['diff'] = (df_q['ts'] - df_q['ts'].shift(1)).dt.total_seconds()
df_q['batch_id'] = (df_q['diff'] > 120).cumsum()

for bid, group in df_q.groupby('batch_id'):
    print(f"Batch {bid}: start={group['ts'].min()}, end={group['ts'].max()}, count={len(group)}, valid={group['is_valid'].sum()}, invalid={(group['is_valid']==0).sum()}")

print("\n=== STOCK SNAPSHOTS RECENT TIMESTAMPS ===")
df_s = pd.read_sql('SELECT timestamp, session_date, count(symbol) as cnt FROM stock_snapshots GROUP BY timestamp ORDER BY timestamp DESC', conn)
print(df_s)

print("\n=== SECTOR SNAPSHOTS RECENT TIMESTAMPS ===")
df_sec = pd.read_sql('SELECT timestamp, session_date, count(theme) as cnt FROM sector_snapshots GROUP BY timestamp ORDER BY timestamp DESC', conn)
print(df_sec)
