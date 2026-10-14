from utils.config import load_settings
from engine.sector_engine import run_sector_engine
from data.cache import SnapshotStore
import sqlite3
import yaml
import pandas as pd
import numpy as np

db_path = r'C:\Git\AI\Claude\SectorRadar\data\sector_radar.db'
db = sqlite3.connect(db_path)

with open(r'C:\Git\AI\Claude\SectorRadar\config\themes.yaml', 'r') as f:
    themes_config = yaml.safe_load(f)

settings = load_settings()
latest_session = '2026-10-07'

# Load snapshots the same way app.py does
def load_finnhub_snapshots(store, session_date):
    from models.schemas import StockSnapshot
    from engine.price_engine import _pct
    from utils.logging import get_logger
    import logging
    logger = logging.getLogger(__name__)
    
    df = store.latest_quote_snapshots(session_date=session_date)
    stock_metrics = {}
    for _, row in df.iterrows():
        current_price = row["price"]
        previous_close = row["previous_close"]
        today_open = row["today_open"]
        
        change_vs_previous_close = _pct(current_price, previous_close)
        change_vs_open = _pct(current_price, today_open)
        
        direction = 'FLAT'
        if change_vs_previous_close is not None:
            if change_vs_previous_close > 0.10:
                direction = 'UP'
            elif change_vs_previous_close < -0.10:
                direction = 'DOWN'
            else:
                direction = 'FLAT'
        
        from zoneinfo import ZoneInfo
        from datetime import datetime
        provider_timestamp = row["provider_timestamp"]
        if provider_timestamp is not None:
            ts_utc = datetime.fromtimestamp(provider_timestamp, tz=None)
            ts_et = ts_utc.astimezone(ZoneInfo("America/New_York"))
            timestamp_iso = ts_et.isoformat()
        else:
            timestamp_iso = ""
        
        snapshot = StockSnapshot(
            symbol=row["symbol"],
            timestamp=timestamp_iso,
            previous_close=previous_close,
            today_open=today_open,
            current_price=current_price,
            intraday_high=row["intraday_high"],
            intraday_low=row["intraday_low"],
            change_vs_previous_close=change_vs_previous_close,
            change_vs_open=change_vs_open,
            distance_from_intraday_high=_pct(current_price, row["intraday_high"]),
            distance_from_intraday_low=_pct(current_price, row["intraday_low"]),
            volume=int(row["volume"]) if row["volume"] is not None else 0,
            is_valid=bool(row["is_valid"]),
            issue=row["issue"] or "",
            direction=direction,
            provider_timestamp=row["provider_timestamp"],
            fetched_at=row["fetched_at"],
            data_age_seconds=row["data_age_seconds"],
        )
        stock_metrics[row["symbol"]] = snapshot
    return stock_metrics

store = SnapshotStore(db_path)
stock_metrics = load_finnhub_snapshots(store, latest_session)

# Check eligibility for Data Center theme
cfg = themes_config['Data Center']
tickers = cfg.get('tickers', [])

from data.freshness import FreshnessPolicy, classify_eligibility, get_current_eligible_snapshots

policy = FreshnessPolicy()

# Build the stocks list like sector_engine does
stocks_list = [stock_metrics[t] for t in tickers if t in stock_metrics]
print(f'Stocks in Data Center: {len(stocks_list)}')
for s in stocks_list:
    print(f'  {s.symbol}: is_valid={s.is_valid}, change_vs_previous_close={s.change_vs_previous_close}, data_age_seconds={s.data_age_seconds}')

# Get eligible stocks
eligible_stocks = get_current_eligible_snapshots(stocks_list, policy)
print(f'\\nEligible stocks: {len(eligible_stocks)}')
for s in eligible_stocks:
    print(f'  {s.symbol}: is_valid={s.is_valid}, change_vs_previous_close={s.change_vs_previous_close}, data_age_seconds={s.data_age_seconds}')

# Now compute breadth
from engine.breadth_engine import compute_breadth
result = compute_breadth(eligible_stocks, settings, total=len(tickers))
print(f'\\ncompute_breadth result:')
print(f'  up_percent: {result["up_percent"]}')
print(f'  valid_stocks: {result["valid_stocks"]}')
print(f'  total_stocks: {result["total_stocks"]}')
print(f'  up_stocks: {result["up_stocks"]}')
print(f'  down_stocks: {result["down_stocks"]}')
print(f'  flat_stocks: {result["flat_stocks"]}')

# Also compute without freshness filter - just use all valid stocks with change
print(f'\\n=== Without freshness filter ===')
valid_count = 0
up_count = 0
for s in stocks_list:
    if s.is_valid and s.change_vs_previous_close is not None:
        valid_count += 1
        if s.change_vs_previous_close > 0.10:
            up_count += 1

print(f'Valid: {valid_count}, Up: {up_count}, Up%={up_count/valid_count*100 if valid_count > 0 else 0:.1f}%')

# And the independent calculation from SQLite
print(f'\\n=== Independent from SQLite ===')
def pct_change2(new, old):
    try:
        if new is None or old is None:
            return None
        n, o = float(new), float(old)
        if not (np.isfinite(n) and np.isfinite(o)) or o == 0:
            return None
        return (n - o) / o * 100.0
    except (TypeError, ValueError):
        return None

up_count2 = 0
eligible_count2 = 0
for sym in tickers:
    q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '{latest_session}' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, db)
    if df.empty:
        continue
    row = df.iloc[0]
    snap = type('S', (), {})()
    snap.is_valid = bool(row.get('is_valid'))
    snap.data_age_seconds = row.get('data_age_seconds')
    snap.previous_close = row.get('previous_close')
    snap.current_price = row.get('price')
    change = pct_change2(row['price'], row.get('previous_close'))
    snap.change_vs_previous_close = change
    
    # Simple eligibility: just has valid price and change
    if change is not None:
        eligible_count2 += 1
        if change > 0.10:
            up_count2 += 1

print(f'Data Center: eligible={eligible_count2}, up={up_count2}, Up%={up_count2/eligible_count2*100 if eligible_count2 > 0 else 0:.1f}%')

db.close()
print()
print('=== DONE ===')