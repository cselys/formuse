import os
os.environ['FINNHUB_API_KEY'] = 'dummy'

from tests.test_finnhub_provider import FakeFinnhubClient
from data.collector import FinnhubCollector, derive_schedule, CollectionConfig
from utils.config import load_settings, load_themes
from data.collector import build_universe
from datetime import datetime, timezone

settings = load_settings()
coll = settings['data'].get('collection', {})
cfg = CollectionConfig(**coll)
themes = load_themes()
universe = build_universe(cfg, themes)

print(f'Universe size: {len(universe)}')
print(f'First 5 symbols: {universe[:5]}')

# Use first symbol from universe
first_sym = universe[0]
print(f'First symbol: {first_sym}')

client = FakeFinnhubClient()
ts = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc).timestamp()
for sym in universe:
    client.set_quotes({sym: {'c': 100.0 + hash(sym) % 100, 'pc': 100.0, 'o': 100.5, 'h': 102.0, 'l': 99.5, 't': ts}})

collector = FinnhubCollector(settings)
print(f'Before replacement - transport type: {type(collector.provider._transport).__name__}')

collector.provider._transport = client
print(f'After replacement - transport type: {type(collector.provider._transport).__name__}')

# Now test directly with first symbol
status, headers, body = collector.provider._transport.get('/quote', {'symbol': first_sym})
print(f'Direct transport get for {first_sym}: status={status}, body keys={list(body.keys()) if body else None}')

# Now test fetch_quote_raw
raw, rate_limited, hdrs = collector.provider.fetch_quote_raw(first_sym, 3, 2.0)
print(f'fetch_quote_raw for {first_sym}: raw={raw is not None}, rate_limited={rate_limited}')

# Now run the collector cycle
with __import__('unittest').mock.patch('data.collector.time.sleep') as mock_sleep:
    with __import__('unittest').mock.patch('data.collector.datetime') as mock_dt:
        fixed_time = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc)
        mock_dt.now.return_value = fixed_time
        mock_dt.utcnow.return_value = fixed_time
        with __import__('unittest').mock.patch('data.collector.time.monotonic') as mock_mon:
            mock_mon.return_value = fixed_time.timestamp()
            summary = collector.run_cycle(universe)
            
print(f'Summary: n_succeeded={summary.n_succeeded}, n_failed={summary.n_failed}, n_rate_limited={summary.n_rate_limited}')
print(f'Sleep calls: {mock_sleep.call_count}')
print(f'Cycle seconds: {summary.cycle_seconds}')