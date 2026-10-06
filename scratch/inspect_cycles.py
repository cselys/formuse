import sqlite3
import pandas as pd
import numpy as np
import yaml

conn = sqlite3.connect('data/sector_radar.db')

print("=== QUOTE SNAPSHOTS BATCHES ===")
df_q = pd.read_sql('SELECT fetched_at, symbol, data_age_seconds, is_valid, price, previous_close, today_open, intraday_high, intraday_low, volume, issue FROM quote_snapshots ORDER BY fetched_at', conn)
df_q['ts'] = pd.to_datetime(df_q['fetched_at'])
df_q['diff'] = (df_q['ts'] - df_q['ts'].shift(1)).dt.total_seconds()
df_q['batch_id'] = (df_q['diff'] > 120).cumsum()

batch_summary = df_q.groupby('batch_id').agg(
    start_ts=('ts', 'min'),
    end_ts=('ts', 'max'),
    symbol_count=('symbol', 'count'),
    valid_count=('is_valid', 'sum'),
    invalid_count=('is_valid', lambda x: (x == 0).sum()),
    avg_data_age=('data_age_seconds', 'mean'),
    max_data_age=('data_age_seconds', 'max'),
    min_data_age=('data_age_seconds', 'min')
).reset_index()

print(batch_summary.to_string())

print("\n=== STOCK SNAPSHOTS TIMESTAMPS ===")
df_stk = pd.read_sql('SELECT timestamp, session_date, symbol, price, previous_close, today_open, change_vs_close, change_vs_open, volume, intraday_high, intraday_low FROM stock_snapshots ORDER BY timestamp', conn)
print("Stock snapshots count per timestamp:")
print(df_stk.groupby('timestamp').size())

print("\n=== SECTOR SNAPSHOTS TIMESTAMPS ===")
df_sec = pd.read_sql('SELECT timestamp, session_date, theme, total_stocks, up_stocks, down_stocks, flat_stocks, up_percent, down_percent, average_return, median_return, average_change_from_open, intraday_high, intraday_low, breadth, state FROM sector_snapshots ORDER BY timestamp', conn)
print("Sector snapshots count per timestamp:")
print(df_sec.groupby('timestamp').size())
