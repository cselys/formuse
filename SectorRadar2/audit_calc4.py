import sqlite3
import pandas as pd
import yaml
import numpy as np

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
conn = sqlite3.connect(db_path)

def pct_change(new, old):
    try:
        if new is None or old is None:
            return None
        n, o = float(new), float(old)
        if not (np.isfinite(n) and np.isfinite(o)) or o == 0:
            return None
        return (n - o) / o * 100.0
    except (TypeError, ValueError):
        return None

with open(r'C:\Git\AI\Claude\SectorRadar\config\themes.yaml', 'r') as f:
    themes_config = yaml.safe_load(f)

# Check what "Up % Now" actually is - it's computed from the CURRENT snapshot's change_vs_previous_close
# Let's verify by checking a few symbols

# For session 2026-10-07 (latest)
print("=== change_vs_previous_close for symbols in Data Center theme (2026-10-07) ===")
dc_tickers = themes_config.get('Data Center', {}).get('tickers', [])
for sym in dc_tickers[:5]:  # first 5
    q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-07' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, conn)
    if not df.empty:
        row = df.iloc[0]
        change = pct_change(row['price'], row['previous_close'])
        print(f"  {sym}: price={row['price']}, prev_close={row['previous_close']}, change_vs_previous_close={change}")

# Now let's check what the dashboard actually computes
# The "Up % Now" = number of eligible stocks with change_vs_previous_close > 0.10 / total eligible * 100
# Let's compute this for all themes

print("\n=== Independently computed Up % Now from latest snapshot (2026-10-07) ===")
for theme_name, cfg in themes_config.items():
    tickers = cfg.get('tickers', [])
    if not tickers:
        continue
    
    up_count = 0
    eligible_count = 0
    
    for sym in tickers:
        q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-07' ORDER BY fetched_at DESC LIMIT 1"
        df = pd.read_sql_query(q, conn)
        if df.empty:
            continue
        row = df.iloc[0]
        change = pct_change(row['price'], row['previous_close'])
        if change is not None:
            eligible_count += 1
            if change > 0.10:
                up_count += 1
    
    if eligible_count > 0:
        up_pct = up_count / eligible_count * 100
        print(f"  {theme_name}: {eligible_count} eligible, {up_count} up, Up%Now={up_pct:.1f}%")
    else:
        print(f"  {theme_name}: 0 eligible")

# Now check what the dashboard shows - it uses md.bars which only has latest snapshot
# Let me also check 2026-10-05
print("\n=== Independently computed Up % Now from 2026-10-05 ===")
for theme_name, cfg in themes_config.items():
    tickers = cfg.get('tickers', [])
    if not tickers:
        continue
    
    up_count = 0
    eligible_count = 0
    
    for sym in tickers:
        q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-05' ORDER BY fetched_at DESC LIMIT 1"
        df = pd.read_sql_query(q, conn)
        if df.empty:
            continue
        row = df.iloc[0]
        change = pct_change(row['price'], row['previous_close'])
        if change is not None:
            eligible_count += 1
            if change > 0.10:
                up_count += 1
    
    if eligible_count > 0:
        up_pct = up_count / eligible_count * 100
        print(f"  {theme_name}: {eligible_count} eligible, {up_count} up, Up%Now={up_pct:.1f}%")
    else:
        print(f"  {theme_name}: 0 eligible")

conn.close()