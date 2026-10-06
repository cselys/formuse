import sqlite3
import pandas as pd

conn = sqlite3.connect('data/sector_radar.db')

print("=== QUOTE SNAPSHOTS FETCHED_AT MIN/MAX FOR EACH BATCH ===")
df_q = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, price, previous_close, today_open FROM quote_snapshots ORDER BY fetched_at', conn)
df_q['ts'] = pd.to_datetime(df_q['fetched_at'])
df_q['diff'] = (df_q['ts'] - df_q['ts'].shift(1)).dt.total_seconds()
df_q['batch_id'] = (df_q['diff'] > 120).cumsum()

for bid, g in df_q.groupby('batch_id'):
    print(f"Batch {bid}: min_ts={g['fetched_at'].min()} max_ts={g['fetched_at'].max()} count={len(g)}")

print("\n=== STOCK SNAPSHOTS TIMESTAMPS ===")
df_s = pd.read_sql('SELECT DISTINCT timestamp FROM stock_snapshots ORDER BY timestamp DESC', conn)
print(df_s.to_string())

print("\n=== SECTOR SNAPSHOTS TIMESTAMPS ===")
df_sec = pd.read_sql('SELECT DISTINCT timestamp FROM sector_snapshots ORDER BY timestamp DESC', conn)
print(df_sec.to_string())
