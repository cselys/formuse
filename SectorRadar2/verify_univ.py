from utils.config import load_settings, load_themes
from data.collector import build_universe, CollectionConfig

settings = load_settings()
coll = settings['data'].get('collection', {})
cfg = CollectionConfig(**coll)
themes = load_themes()
universe = build_universe(cfg, themes)

print(f"Universe size: {len(universe)}")
print(f"Config: {coll}")
print(f"Theme count: {len(load_themes())}")

# Show deduplication
tickers = [s for s in universe if not s.endswith('ETF')]
etfs = [s for s in universe if s.endswith('ETF')]
print(f"Tickers: {len(tickers)}")
print(f"ETFs: {len(etfs)}")
print(f"First 10: {universe[:10]}")
print(f"Last 10: {universe[-10:]}")