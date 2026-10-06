import sqlite3
import pandas as pd

conn = sqlite3.connect('data/sector_radar.db')

print("=== QUOTE SNAPSHOTS BATCH DETAILS ===")
df_q = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, price, previous_close, today_open, intraday_high, intraday_low, volume FROM quote_snapshots ORDER BY fetched_at', conn)
df_q['ts'] = pd.to_datetime(df_q['fetched_at'])
df_q['diff'] = (df_q['ts'] - df_q['ts'].shift(1)).dt.total_seconds()
df_q['batch_id'] = (df_q['diff'] > 120).cumsum()

batches = df_q.groupby('batch_id').agg(
    start_ts=('ts', 'min'),
    end_ts=('ts', 'max'),
    symbol_count=('symbol', 'count'),
    valid_count=('is_valid', 'sum'),
    invalid_count=('is_valid', lambda x: (x == 0).sum())
).reset_index()

print(batches)

print("\n=== RECENT 9 TIMESTAMPS IN SECTOR SNAPSHOTS ===")
df_sec = pd.read_sql('SELECT DISTINCT timestamp FROM sector_snapshots ORDER BY timestamp DESC LIMIT 15', conn)
print(df_sec)

print("\n=== RECENT 9 TIMESTAMPS IN STOCK SNAPSHOTS ===")
df_stk = pd.read_sql('SELECT DISTINCT timestamp FROM stock_snapshots ORDER BY timestamp DESC LIMIT 15', conn)
print(df_stk)
