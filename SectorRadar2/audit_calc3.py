import sqlite3
import pandas as pd
import yaml
import numpy as np

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
conn = sqlite3.connect(db_path)

def pct_change(new, old):
    """Mirror price_engine._pct."""
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

# Compute change_vs_previous_close from price and previous_close
def get_latest_snapshot_metrics(symbol, session_date='2026-10-07'):
    """Get latest snapshot and compute change_vs_previous_close."""
    q = f"SELECT * FROM quote_snapshots WHERE symbol = '{symbol}' AND session_date = '{session_date}' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, conn)
    if df.empty:
        return None
    row = df.iloc[0]
    change = pct_change(row['price'], row['previous_close'])
    return {
        'symbol': symbol,
        'price': row['price'],
        'previous_close': row['previous_close'],
        'change_vs_previous_close': change,
        'is_valid': row['is_valid'],
        'issue': row['issue']
    }

latest_session = '2026-10-07'

# Check some themes
test_themes = ['Data Center', 'Oil & Gas', 'Financials', 'Semiconductor', 'AI / Compute', 'Nuclear']

for theme_name in test_themes:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    if not tickers:
        print(f"\n{theme_name}: no tickers configured")
        continue
    
    up_count = 0
    down_count = 0
    flat_count = 0
    eligible_count = 0
    
    for sym in tickers:
        metrics = get_latest_snapshot_metrics(sym, latest_session)
        if metrics is None:
            print(f"  {sym}: no data for {latest_session}")
            continue
        
        change = metrics['change_vs_previous_close']
        if change is None:
            print(f"  {sym}: change_vs_previous_close is None (price={metrics['price']}, prev_close={metrics['previous_close']})")
            continue
        
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

# Also check session 2026-10-05
print(f"\n\n=== Session 2026-10-05 ===")
for theme_name in ['Data Center', 'Financials']:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    if not tickers:
        print(f"\n{theme_name}: no tickers configured")
        continue
    
    up_count = 0
    down_count = 0
    flat_count = 0
    eligible_count = 0
    
    for sym in tickers:
        metrics = get_latest_snapshot_metrics(sym, '2026-10-05')
        if metrics is None:
            print(f"  {sym}: no data for 2026-10-05")
            continue
        
        change = metrics['change_vs_previous_close']
        if change is None:
            print(f"  {sym}: change_vs_previous_close is None")
            continue
        
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
        print(f"\n{theme_name} (session 2026-10-05):")
        print(f"  Eligible: {eligible_count}, Up: {up_count} ({up_pct:.1f}%), Down: {down_count} ({down_pct:.1f}%), Flat: {flat_count}")
    else:
        print(f"\n{theme_name}: no eligible stocks with change_vs_previous_close in 2026-10-05")

conn.close()