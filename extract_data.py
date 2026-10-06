#!/usr/bin/env python
"""Signal validation data extraction"""

import sqlite3
import pandas as pd
import numpy as np
import yaml

# Load themes
with open('config/themes.yaml', 'r') as f:
    themes = yaml.safe_load(f)

# Load DB
db = sqlite3.connect('data/sector_radar.db')
cur = db.cursor()

# Get latest quote per symbol
cur.execute(
    "SELECT symbol, fetched_at, data_age_seconds, is_valid, provider_timestamp "
    "FROM quote_snapshots "
    "WHERE data_age_seconds IS NOT NULL "
    "ORDER BY fetched_at DESC "
    "LIMIT 5"
)
rows = cur.fetchall()
print("Sample DB rows:", rows)

# Check schema
cur.execute('PRAGMA table_info(quote_snapshots)')
print("quote_snapshots schema:", cur.fetchall())

# Get latest quote per symbol
cur.execute(
    "SELECT symbol, fetched_at, data_age_seconds, is_valid, provider_timestamp "
    "FROM quote_snapshots "
    "WHERE data_age_seconds IS NOT NULL "
    "ORDER BY fetched_at DESC"
)
rows = cur.fetchall()
df = pd.DataFrame(rows, columns=['symbol', 'fetched_at', 'data_age_seconds', 'is_valid', 'provider_timestamp'])
df['fetched_at_ts'] = pd.to_datetime(df['fetched_at'])
latest = df.sort_values('fetched_at_ts').groupby('symbol').last().reset_index()

print(f"Total distinct symbols: {len(latest)}")
print(f"Age range: {latest['data_age_seconds'].min():.0f} to {latest['data_age_seconds'].max():.0f} seconds")

db.close()