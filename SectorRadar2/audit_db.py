import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Check table structure
cur.execute("PRAGMA table_info(quote_snapshots)")
cols = cur.fetchall()
print("=== quote_snapshots columns ===")
for c in cols:
    print(c)

# Check row count
cur.execute("SELECT COUNT(*) FROM quote_snapshots")
total = cur.fetchone()[0]
print(f"\nTotal rows: {total}")

# Check distinct session_dates
cur.execute("SELECT DISTINCT session_date FROM quote_snapshots ORDER BY session_date")
dates = cur.fetchall()
print(f"\nDistinct session_dates: {dates}")

# Check symbols
cur.execute("SELECT DISTINCT symbol FROM quote_snapshots ORDER BY symbol LIMIT 30")
symbols = cur.fetchall()
print(f"\nFirst 30 symbols: {symbols}")

# Get a few representative symbols from different themes
# Let's check what themes exist and find symbols
cur.execute("SELECT DISTINCT source FROM quote_snapshots")
sources = cur.fetchall()
print(f"\nDistinct sources: {sources}")

# Check for any non-Finnhub sources
cur.execute("SELECT DISTINCT source FROM quote_snapshots WHERE source != 'finnhub'")
non_finnhub = cur.fetchall()
print(f"Non-Finnhub sources: {non_finnhub}")

# Look at snapshot count per symbol
cur.execute("SELECT symbol, COUNT(*) as cnt, MIN(fetched_at) as earliest, MAX(fetched_at) as latest, MIN(provider_timestamp) as min_pt, MAX(provider_timestamp) as max_pt FROM quote_snapshots GROUP BY symbol ORDER BY cnt DESC LIMIT 10")
per_symbol = cur.fetchall()
print(f"\nTop 10 symbols by snapshot count in the order DESC LIMIT 10:")
for row in per_symbol:
    print(f"  {row[0]}: {row[1]} snapshots, earliest={row[2]}, latest={row[3]}, pt_range={row[4]}-{row[5]}")

conn.close()