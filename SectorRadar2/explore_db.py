#!/usr/bin/env python
"""Explore database structure"""

import sqlite3
import pandas as pd

db = sqlite3.connect('data/sector_radar.db')
cur = db.cursor()

# Check latest quotes
cur.execute('''
    SELECT symbol, fetched_at, data_age_seconds, is_valid, provider_timestamp, price, previous_close, today_open, intraday_high, intraday_low, volume
    FROM quote_snapshots
    WHERE data_age_seconds IS NOT NULL
    ORDER BY fetched_at DESC
    LIMIT 10
''')
rows = cur.fetchall()
df = pd.DataFrame(rows, columns=['symbol', 'fetched_at', 'data_age_seconds', 'is_valid', 'provider_timestamp', 'price', 'previous_close', 'today_open', 'intraday_high', 'intraday_low', 'volume'])
print('Latest 10 quotes:')
print(df.to_string())
print()

# Check distinct symbols
cur.execute('SELECT COUNT(DISTINCT symbol) FROM quote_snapshots WHERE data_age_seconds IS NOT NULL')
print('Distinct symbols:', cur.fetchone()[0])

# Check sector_snapshots
cur.execute('SELECT COUNT(*) FROM sector_snapshots')
print('sector_snapshots count:', cur.fetchone()[0])

cur.execute('PRAGMA table_info(sector_snapshots)')
for row in cur.fetchall():
    print(row)

# Check stock_snapshots
cur.execute('SELECT COUNT(*) FROM stock_snapshots')
print('stock_snapshots count:', cur.fetchone()[0])

cur.execute('PRAGMA table_info(stock_snapshots)')
for row in cur.fetchall():
    print(row)