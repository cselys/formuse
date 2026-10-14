import sqlite3
import pandas as pd
import yaml
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
conn = sqlite3.connect(db_path)

# Read the themes.yaml to find theme configurations
with open(r'C:\Git\AI\Claude\SectorRadar\config\themes.yaml', 'r') as f:
    themes_config = yaml.safe_load(f)

print("=== Theme configurations ===")
for name, cfg in themes_config.items():
    tickers = cfg.get('tickers', [])
    etfs = cfg.get('etf', [])
    print(f"{name}: {len(tickers)} tickers, {len(etfs)} ETFs")
    if len(tickers) > 0:
        print(f"  Tickers: {tickers[:5]}...")  # first 5
    if len(etfs) > 0:
        print(f"  ETFs: {etfs}")

# Now let's independently calculate breadth for a few themes from raw SQLite
def get_latest_snapshot(symbol, session_date='2026-10-07'):
    """Get the latest snapshot for a symbol from SQLite for the given session date."""
    q = f"SELECT * FROM quote_snapshots WHERE symbol = '{symbol}' AND session_date = '{session_date}' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, conn)
    return df.iloc[0] if not df.empty else None

# Use 2026-10-07 as the latest session
latest_session = '2026-10-07'

# List of themes to audit
themes_to_audit = ['Data Center', 'Oil & Gas', 'Financials', 'Semiconductor', 'AI / Compute', 'Nuclear']

for theme_name in themes_to_audit:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    if not tickers:
        print(f"\n{theme_name}: no tickers configured")
        continue
    
    up_count = 0
    down_count = 0
    flat_count = 0
    eligible_count = 0
    total_with_data = 0
    
    for sym in tickers:
        snap = get_latest_snapshot(sym, latest_session)
        if snap is None:
            print(f"  {sym}: no data for {latest_session}")
            continue
        
        change = snap.get('change_vs_previous_close')
        if change is None:
            continue
        
        total_with_data += 1
        eligible_count += 1
        
        flat_threshold = 0.10
        if change > flat_threshold:
            up_count += 1
        elif change < -flat_threshold:
            down_count += 1
        else:
            flat_count += 1
    
    if eligible_count > 0:
        up_pct = up_count / eligible_count * 100
        down_pct = down_count / eligible_count * 100
        flat_pct = flat_count / eligible_count * 100
        print(f"\n{theme_name} (session {latest_session}):")
        print(f"  Eligible: {eligible_count}, Up: {up_count} ({up_pct:.1f}%), Down: {down_count} ({down_pct:.1f}%), Flat: {flat_count} ({flat_pct:.1f}%)")
    else:
        print(f"\n{theme_name}: no eligible stocks with change_vs_previous_close in {latest_session}")

# Also check 2026-10-05 (first session, likely only 1 snapshot per symbol)
print(f"\n\n=== Checking session 2026-10-05 (first run, likely 1 snapshot per symbol) ===")
for theme_name in ['Data Center', 'Financials', 'Technology']:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    if not tickers:
        print(f"\n{theme_name}: no tickers configured")
        continue
    
    has_data = 0
    no_data = 0
    up_count = 0
    down_count = 0
    eligible_count = 0
    
    for sym in tickers:
        snap = get_latest_snapshot(sym, '2026-10-05')
        if snap is None:
            no_data += 1
            continue
        
        has_data += 1
        change = snap.get('change_vs_previous_close')
        if change is None:
            continue
        
        eligible_count += 1
        flat_threshold = 0.10
        if change > flat_threshold:
            up_count += 1
        elif change < -flat_threshold:
            down_count += 1
        else:
            flat_count += 1
    
    print(f"\n{theme_name} (session 2026-10-05):")
    print(f"  Data: {has_data}, No data: {no_data}, Eligible: {eligible_count}")
    if eligible_count > 0:
        up_pct = up_count / eligible_count * 100
        down_pct = down_count / eligible_count * 100
        print(f"  Up: {up_count} ({up_pct:.1f}%), Down: {down_count} ({down_pct:.1f}%)")

conn.close()