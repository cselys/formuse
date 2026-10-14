import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Check symbols per session date
cur.execute("SELECT session_date, COUNT(DISTINCT symbol) FROM quote_snapshots GROUP BY session_date ORDER BY session_date")
per_date = cur.fetchall()
print(f"Symbols per session_date: {per_date}")

# Total symbols across all dates
cur.execute("SELECT COUNT(DISTINCT symbol) FROM quote_snapshots")
total_symbols = cur.fetchone()[0]
print(f"Total distinct symbols: {total_symbols}")

# Look at a few specific themes - let's find symbols from different sectors
# First, let's look at all session dates and their data
for date_row in per_date:
    date = date_row[0]
    count = date_row[1]
    cur.execute(f"SELECT symbol, COUNT(*) as cnt, MIN(fetched_at) as earliest, MAX(fetched_at) as latest FROM quote_snapshots WHERE session_date = '{date}' GROUP BY symbol ORDER BY cnt ASC LIMIT 5")
    few = cur.fetchall()
    cur.execute(f"SELECT symbol, COUNT(*) as cnt, MIN(fetched_at) as earliest, MAX(fetched_at) as latest FROM quote_snapshots WHERE session_date = '{date}' GROUP BY symbol ORDER BY cnt DESC LIMIT 5")
    many = cur.fetchall()
    print(f"\n=== Session {date} ({count} symbols) ===")
    print(f"  Lowest count symbols:")
    for row in few:
        print(f"    {row[0]}: {row[1]} snapshots, {row[2]}-{row[3]}")
    print(f"  Highest count symbols:")
    for row in many:
        print(f"    {row[0]}: {row[1]} snapshots, {row[2]}-{row[3]}")

# Let's find some key theme symbols
# Technology/AI/Compute symbols
tech_keywords = ['NVDA', 'AMD', 'AVGO', 'MU', 'QCOM', 'INTC', 'TSLA', 'AAPL', 'MSFT', 'GOOGL']
for sym in tech_keywords:
    cur.execute(f"SELECT COUNT(*) FROM quote_snapshots WHERE symbol = '{sym}'")
    cnt = cur.fetchone()[0]
    if cnt > 0:
        cur.execute(f"SELECT MIN(fetched_at), MAX(fetched_at), MIN(provider_timestamp), MAX(provider_timestamp) FROM quote_snapshots WHERE symbol = '{sym}'")
        ts = cur.fetchone()
        print(f"\n{sym}: {cnt} snapshots, fetchedat range: {ts[0]}-{ts[1]}, pt range: {ts[2]}-{ts[3]}")

# Financials
fin_keywords = ['JPM', 'BAC', 'GS', 'MS', 'WFC', 'C', 'BLK', 'AXP', 'BRK.B']
for sym in fin_keywords:
    cur.execute(f"SELECT COUNT(*) FROM quote_snapshots WHERE symbol = '{sym}'")
    cnt = cur.fetchone()[0]
    if cnt > 0:
        cur.execute(f"SELECT MIN(fetched_at), MAX(fetched_at) FROM quote_snapshots WHERE symbol = '{sym}'")
        ts = cur.fetchone()
        print(f"{sym}: {cnt} snapshots, fetchedat range: {ts[0]}-{ts[1]}")

# Data Center / Energy
dc_keywords = ['NEE', 'DUK', 'SO', 'XEL', 'NSC', 'PCG', 'EIX', 'D', 'SO', 'EVA']
for sym in dc_keywords:
    cur.execute(f"SELECT COUNT(*) FROM quote_snapshots WHERE symbol = '{sym}'")
    cnt = cur.fetchone()[0]
    if cnt > 0:
        cur.execute(f"SELECT MIN(fetched_at), MAX(fetched_at) FROM quote_snapshots WHERE symbol = '{sym}'")
        ts = cur.fetchone()
        print(f"{sym}: {cnt} snapshots, fetchedat range: {ts[0]}-{ts[1]}")

# Look at snapshot density over time
cur.execute("SELECT session_date, COUNT(*) as total_rows, COUNT(DISTINCT symbol) as symbols, MIN(fetched_at) as first_fetch, MAX(fetched_at) as last_fetch FROM quote_snapshots GROUP BY session_date ORDER BY session_date")
summary = cur.fetchall()
print(f"\n=== Summary by session_date ===")
for row in summary:
    print(f"  {row[0]}: {row[1]} rows, {row[2]} symbols, fetched {row[3]}-{row[4]}")

conn.close()