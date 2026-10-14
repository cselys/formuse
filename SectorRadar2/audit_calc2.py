import sqlite3
import pandas as pd
import yaml

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
conn = sqlite3.connect(db_path)

with open(r'C:\Git\AI\Claude\SectorRadar\config\themes.yaml', 'r') as f:
    themes_config = yaml.safe_load(f)

# Check change_vs_previous_close for some symbols
test_symbols = ['NVDA', 'AMD', 'JPM', 'XOM', 'AAL', 'AAOI']

print("=== change_vs_previous_close values from latest snapshot (2026-10-07) ===")
for sym in test_symbols:
    q = f"SELECT symbol, session_date, change_vs_previous_close, is_valid, issue FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-07' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        row = df.iloc[0]
        print(f"  {sym}: change_vs_previous_close={row['change_vs_previous_close']}, is_valid={row['is_valid']}, issue={row['issue']}")
    else:
        print(f"  {sym}: no data for 2026-10-07")

print("\n=== change_vs_previous_close values from session 2026-10-05 ===")
for sym in test_symbols:
    q = f"SELECT symbol, session_date, change_vs_previous_close, is_valid, issue FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-05' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        row = df.iloc[0]
        print(f"  {sym}: change_vs_previous_close={row['change_vs_previous_close']}, is_valid={row['is_valid']}, issue={row['issue']}")
    else:
        print(f"  {sym}: no data for 2026-10-05")

# Check how many symbols have change_vs_previous_close != None in 2026-10-07
print("\n=== Symbols with change_vs_previous_close != None in 2026-10-07 ===")
q = "SELECT symbol, change_vs_previous_close FROM quote_snapshots WHERE session_date = '2026-10-07' AND change_vs_previous_close IS NOT NULL ORDER BY symbol LIMIT 20"
df = pd.read_sql_query(q, conn)
print(f"  Count: {len(df)}")
print(f"  Examples:")
for _, row in df.iterrows():
    print(f"    {row['symbol']}: {row['change_vs_previous_close']}")

print("\n=== Symbols with change_vs_previous_close IS NULL in 2026-10-07 ===")
q = "SELECT symbol, COUNT(*) as cnt FROM quote_snapshots WHERE session_date = '2026-10-07' AND change_vs_previous_close IS NULL GROUP BY symbol ORDER BY cnt DESC LIMIT 10"
df = pd.read_sql_query(q, conn)
print(f"  Count: {len(df)}")
for _, row in df.iterrows():
    print(f"  {row['symbol']}: {row['cnt']} snapshots with NULL change_vs_previous_close")

# Check the first few columns of a snapshot
print("\n=== Full snapshot for NVDA on 2026-10-07 ===")
q = f"SELECT * FROM quote_snapshots WHERE symbol = 'NVDA' AND session_date = '2026-10-07' ORDER BY fetched_at DESC LIMIT 1"
df = pd.read_sql_query(q, conn)
print(df)

conn.close()