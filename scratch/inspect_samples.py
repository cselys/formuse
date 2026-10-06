import sqlite3
import pandas as pd
import numpy as np

conn = sqlite3.connect('data/sector_radar.db')

print("=== QUOTE SNAPSHOTS SAMPLE FOR BATCH 2 ===")
df_q2 = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, price, previous_close, today_open, intraday_high, intraday_low, volume FROM quote_snapshots ORDER BY fetched_at', conn)
df_q2['ts'] = pd.to_datetime(df_q2['fetched_at'])
df_q2['diff'] = (df_q2['ts'] - df_q2['ts'].shift(1)).dt.total_seconds()
df_q2['batch_id'] = (df_q2['diff'] > 120).cumsum()

batch2 = df_q2[df_q2['batch_id'] == 2]
print(batch2.head(10))

print("\n=== STOCK SNAPSHOTS SAMPLE ===")
df_stk = pd.read_sql('SELECT * FROM stock_snapshots LIMIT 10', conn)
print(df_stk)

print("\n=== SECTOR SNAPSHOTS SAMPLE ===")
df_sec = pd.read_sql('SELECT * FROM sector_snapshots LIMIT 10', conn)
print(df_sec)
