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

# Simulate the _up_at_offset function from reversal_engine.py
def _up_at_offset(history_up_pcts, minutes):
    """
    Simulate _up_at_offset(history, minutes) from reversal_engine.py.
    history_up_pcts: list of up_percent values, one per bar
    Returns the up_percent at minutes before the last bar, or None.
    """
    if len(history_up_pcts) < 2:
        return None
    last = len(history_up_pcts) - 1  # last bar index
    target = last - minutes
    if target < 0:
        target = 0
    pos = int(np.searchsorted(range(len(history_up_pcts)), target)) if hasattr(np, 'searchsorted') else 0
    # Simpler version: find the bar closest to 'minutes' before last
    pos = max(1, min(last - minutes, len(history_up_pcts) - 1))
    return history_up_pcts[pos]

# Also simulate theme_return_series - but with 1 row per symbol (current bug)
# If md.bars has 1 row per symbol, theme_return_series produces 1-row history

# Let's check what happens with 1 row per symbol (the current bug)
print("=== Breadth momentum with 1 row per symbol (current bug) ===")
for theme_name in ['Data Center', 'Oil & Gas', 'Financials', 'Semiconductor']:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    
    # Get change_vs_previous_close for each ticker from 2026-10-07
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
    # Current valid stocks: those with change_vs_previous_close is not None
    # and is_valid and participates_in_current
    # For simplicity, let's just use changes that are not None
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
    
    # _up_at_offset with 1 row: returns None
    b5 = _up_at_offset(valid_changes, 5) if n >= 1 else None
    b15 = _up_at_offset(valid_changes, 15) if n >= 1 else None
    
    print(f"\n{theme_name}: {n} valid stocks")
    print(f"  Up % Now: {breadth_now:.1f}%")
    print(f"  5m Ago: {b5 if b5 is not None else 'None/NaN'}")
    print(f"  15m Ago: {b15 if b15 is not None else 'None/NaN'}")
    print(f"  Δ 5m: { (breadth_now - b5) if b5 is not None else 'None' } pp")
    print(f"  Δ 15m: { (breadth_now - b15) if b15 is not None else 'None' } pp")

# Now check what happens if we have MULTIPLE rows per symbol (as in the DB after several cycles)
print("\n\n=== Breadth momentum with MULTIPLE rows per symbol (what DB has) ===")
# The DB has ~13 rows per symbol for 2026-10-06, ~12 for 2026-10-07
# But app.py only uses the LAST row, so effectively 1 row

# Let's simulate having 5 rows (like the test uses)
for theme_name in ['Data Center', 'Oil & Gas', 'Financials']:
    cfg = themes_config.get(theme_name, {})
    tickers = cfg.get('tickers', [])
    
    # Get ALL change_vs_previous_close for 2026-10-07 (all snapshots)
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
    
    # Use the LAST 5 changes per symbol (simulating 5 historical bars)
    # But theme_return_series combines all symbols, so we need a combined history
    # Let's just use the last symbol's changes as an example
    first_sym = tickers[0]
    changes = all_changes_by_symbol.get(first_sym, [])
    
    if len(changes) >= 5:
        # Use last 5 changes as the history
        history_changes = changes[-5:]  # last 5
        flat = 0.10
        
        # Current breadth now (from last bar)
        valid_count = 1  # simplified
        up_count = int((np.array(history_changes) > flat).sum())
        up_pct = valid_count > 0 and up_count / valid_count * 100.0 or 0.0
        breadth_now = up_pct
        
        # 5m ago and 15m ago using _up_at_offset
        b5 = _up_at_offset(history_changes, 5)
        b15 = _up_at_offset(history_changes, 15)
        
        print(f"\n{theme_name} ({first_sym}): {len(changes)} total snapshots, using last 5")
        print(f"  History (last 5): {history_changes}")
        print(f"  Up % Now: {breadth_now:.1f}%")
        print(f"  5m Ago: {b5 if b5 is not None else 'None/NaN'}")
        print(f"  15m Ago: {b15 if b15 is not None else 'None/NaN'}")
        print(f"  Δ 5m: { (breadth_now - b5) if b5 is not None else 'None' } pp")
        print(f"  Δ 15m: { (breadth_now - b15) if b15 is not None else 'None' } pp")
    else:
        print(f"\n{theme_name} ({first_sym}): only {len(changes)} snapshots, need 5 for history")

conn.close()