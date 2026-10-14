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

# Create client and set quotes
client = FakeFinnhubClient()
ts = datetime(2026, 10, 5, 14, 0, 0, tzinfo=timezone.utc).timestamp()

# Set quotes for ALL symbols
for sym in universe:
    client.set_quotes({sym: {'c': 100.0 + hash(sym) % 100, 'pc': 100.0, 'o': 100.5, 'h': 102.0, 'l': 99.5, 't': ts}})

# Check if symbols are in quotes
print(f'NVDA in quotes: {"NVDA" in client.quotes}')
print(f'First 3 quote keys: {list(client.quotes.keys())[:3]}')

# Now test directly
status, headers, body = client.get('/quote', {'symbol': 'NVDA'})
print(f'Client get for NVDA: status={status}, body={body}')

# Now with collector
collector = FinnhubCollector(settings)
collector.provider._transport = client

status2, headers2, body2 = collector.provider._transport.get('/quote', {'symbol': 'NVDA'})
print(f'Collector transport get for NVDA: status={status2}')

raw, rate_limited, hdrs = collector.provider.fetch_quote_raw('NVDA', 3, 2.0)
print(f'fetch_quote_raw: raw={raw is not None}, rate_limited={rate_limited}')