import sqlite3
import pandas as pd
import yaml
import numpy as np
from datetime import datetime
from zoneinfo import ZoneInfo

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

def _up_at_offset(history_up_pcts, minutes):
    """Simulate _up_at_offset from reversal_engine.py."""
    if len(history_up_pcts) < 2:
        return None
    last = len(history_up_pcts) - 1
    target = last - minutes
    if target < 0:
        target = 0
    pos = max(1, min(target, len(history_up_pcts) - 1))
    return history_up_pcts[pos]

# Check what happens with 1 row per symbol (current bug)
print("=== Breadth momentum with 1 row per symbol (current bug) ===")
results = {}
for theme_name in ['Data Center', 'Oil & Gas', 'Financials', 'Semiconductor']:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    
    changes = []
    for sym in tickers:
        q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-07' ORDER BY fetched_at DESC LIMIT 1"
        df = pd.read_sql_query(q, conn)
        if not df.empty:
            row = df.iloc[0]
            change = pct_change(row['price'], row['previous_close'])
            changes.append(change if change is not None else 0.0)
        else:
            changes.append(0.0)
    
    flat = 0.10
    valid_changes = [c for c in changes if c is not None]
    n = len(valid_changes)
    
    if n > 0:
        changes_arr = np.array(valid_changes)
        up = int((changes_arr > flat).sum())
        up_pct = up / n * 100.0
        breadth_now = up_pct
    else:
        up_pct = 0.0
        breadth_now = 0.0
    
    b5 = _up_at_offset(valid_changes, 5) if n >= 1 else None
    b15 = _up_at_offset(valid_changes, 15) if n >= 1 else None
    
    results[theme_name] = {
        'n': n,
        'Up%Now': breadth_now,
        '5mAgo': b5 if b5 is not None else None,
        '15mAgo': b15 if b15 is not None else None,
    }
    
    line = f"{theme_name}: n={n}, Up%Now={breadth_now:.1f}%"
    if b5 is not None:
        line += f", 5mAgo={b5:.4f}"
    else:
        line += ", 5mAgo=None"
    if b15 is not None:
        line += f", 15mAgo={b15:.4f}"
    else:
        line += ", 15mAgo=None"
    print(line)

# Now check with ALL snapshots per symbol (what DB actually has)
print("\n\n=== With ALL snapshots per symbol (2026-10-07) ===")
for theme_name in ['Data Center', 'Oil & Gas', 'Financials']:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    
    all_changes_by_symbol = {}
    for sym in tickers:
        q = f"SELECT fetched_at, price, previous_close FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '2026-10-07' ORDER BY fetched_at"
        df = pd.read_sql_query(q, conn)
        if not df.empty:
            changes = []
            for _, row in df.iterrows():
                change = pct_change(row['price'], row['previous_close'])
                changes.append(change if change is not None else 0.0)
            all_changes_by_symbol[sym] = changes
    
    # Use the LAST symbol's changes
    first_sym = tickers[0]
    changes = all_changes_by_symbol.get(first_sym, [])
    
    n_total = len(changes)
    print(f"\n{theme_name} ({first_sym}): {n_total} total snapshots in DB for 2026-10-07")
    
    # Simulate having different numbers of history rows
    for num_rows in [1, 2, 3, 5, 10, n_total]:
        if num_rows <= n_total and num_rows >= 2:
            history = changes[-num_rows:]  # last num_rows
            b5 = _up_at_offset(history, 5) if len(history) >= 2 else None
            b15 = _up_at_offset(history, 15) if len(history) >= 2 else None
            
            # Compute up_pct from the history
            up_count = int((np.array(history) > flat).sum()) if len(history) > 0 else 0
            up_pct = up_count / len(history) * 100.0 if len(history) > 0 else 0.0
            
            b5_str = str(b5) if b5 is not None else "None/NaN"
            b15_str = str(b15) if b15 is not None else "None/NaN"
            
            print(f"  With {num_rows} history rows: Up%Now={up_pct:.1f}%, 5mAgo={b5_str:>10}, 15mAgo={b15_str:>10}")
        else:
            print(f"  With {num_rows} history rows: Not enough data (have {n_total})")

# Also run the independent Up % Now calculation we did earlier
print("\n\n=== Independent Up % Now from earlier analysis ===")
print("2026-10-07:")
print("  Data Center: 18.2% Up (2/11 eligible)")
print("  Oil & Gas: 41.7% Up (5/12 eligible)")
print("  Financials: 10.0% Up (1/10 eligible)")
print("  Semiconductor: 11.1% Up (2/18 eligible)")

conn.close()
print("\n=== DONE ===")