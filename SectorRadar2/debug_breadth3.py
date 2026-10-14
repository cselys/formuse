from utils.config import load_settings
from engine.sector_engine import run_sector_engine
from engine.breadth_engine import compute_breadth
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

# Load snapshots
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

# Run sector engine with Data Center theme - need to provide md
# Create a minimal MarketData
from data.provider_base import MarketData
md = MarketData(
    source="finnhub_snapshot",
    interval="5m",
    fetched_at=pd.Timestamp.now(tz='US/Eastern').to_pydatetime(),
    asof=pd.Timestamp.now(tz='US/Eastern').to_pydatetime(),
    bars={},
    daily={},
    failed={},
)

themes_cfg = {
    'Data Center': {
        'tickers': themes_config['Data Center']['tickers'],
        'etf': themes_config['Data Center'].get('etf', [])
    }
}

from engine.sector_engine import run_sector_engine
result = run_sector_engine(themes_cfg, stock_metrics, md, settings)

if result:
    t = result[0]
    print(f'Theme: {t.theme}')
    print(f'up_percent: {t.up_percent}')
    print(f'down_percent: {t.down_percent}')
    print(f'valid_stocks: {t.valid_stocks}')
    print(f'total_stocks: {t.total_stocks}')
    print(f'up_stocks: {t.up_stocks}')
    print(f'down_stocks: {t.down_stocks}')
    print(f'flat_stocks: {t.flat_stocks}')

# Now independent calculation
print()
print('=== Independent calculation from SQLite ===')

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

cfg = themes_config['Data Center']
tickers = cfg.get('tickers', [])

up_count = 0
eligible_count = 0

from data.freshness import FreshnessPolicy, classify_eligibility
from models.schemas import StockSnapshot
from zoneinfo import ZoneInfo
from datetime import datetime

policy = FreshnessPolicy()

for sym in tickers:
    q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '{latest_session}' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, db)
    if df.empty:
        continue
    row = df.iloc[0]
    
    snap = StockSnapshot(
        symbol=sym,
        timestamp="",
        previous_close=row.get('previous_close'),
        today_open=row.get('today_open'),
        current_price=row.get('price'),
        intraday_high=row.get('intraday_high'),
        intraday_low=row.get('intraday_low'),
        change_vs_previous_close=pct_change2(row['price'], row.get('previous_close')),
        change_vs_open=pct_change2(row.get('price', 0), row.get('today_open', 0)),
        distance_from_intraday_high=pct_change2(row.get('price', 0), row.get('intraday_high', 0)),
        distance_from_intraday_low=pct_change2(row.get('price', 0), row.get('intraday_low', 0)),
        volume=int(row['volume']) if row['volume'] is not None else 0,
        is_valid=bool(row.get('is_valid')),
        issue=row.get('issue') or '',
        direction='FLAT',
        provider_timestamp=row.get('provider_timestamp'),
        fetched_at=row.get('fetched_at'),
        data_age_seconds=row.get('data_age_seconds'),
    )
    elig = classify_eligibility(snap, policy)
    print(f'  {sym}: is_valid={snap.is_valid}, data_age_seconds={snap.data_age_seconds:.1f}, category={elig.category}, participates={elig.participates_in_current}')
    
    if elig.participates_in_current:
        eligible_count += 1
        change = pct_change2(row['price'], row.get('previous_close'))
        if change is not None and change > 0.10:
            up_count += 1

if eligible_count > 0:
    independent_up_pct = up_count / eligible_count * 100
    print(f'\\nData Center: eligible={eligible_count}, up={up_count}, Up%={independent_up_pct:.1f}%')
else:
    print(f'\\nData Center: 0 eligible')

# Also check without freshness filter
print()
print('=== Without freshness filter ===')
up_count2 = 0
total_with_change = 0
for sym in tickers:
    q = f"SELECT * FROM quote_snapshots WHERE symbol = '{sym}' AND session_date = '{latest_session}' ORDER BY fetched_at DESC LIMIT 1"
    df = pd.read_sql_query(q, db)
    if df.empty:
        continue
    row = df.iloc[0]
    change = pct_change2(row['price'], row.get('previous_close'))
    if change is not None:
        total_with_change += 1
        if change > 0.10:
            up_count2 += 1

if total_with_change > 0:
    print(f'Data Center: total_with_change={total_with_change}, up={up_count2}, Up%={up_count2/total_with_change*100:.1f}%')

db.close()
print()
print('=== DONE ===')