from tests.conftest import build_metrics
from utils.config import load_settings
from engine.sector_engine import run_sector_engine
from engine.breadth_engine import compute_breadth
import numpy as np

settings = load_settings()

# Build with a simple theme
md, metrics = build_metrics({'A': [101.0, 102.0, 103.0]}, settings=settings)
print(f'Metrics: {list(metrics.keys())}')

# Check each stock's change_vs_previous_close
for sym, snap in metrics.items():
    print(f'{sym}: change_vs_previous_close={snap.change_vs_previous_close}, is_valid={snap.is_valid}')

# Now run sector engine with a theme
themes_cfg = {'Test': {'tickers': ['A'], 'etf': []}}
result = run_sector_engine(themes_cfg, metrics, md, settings)
if result:
    t = result[0]
    print(f'\\nTheme up_percent: {t.up_percent}')
    print(f'valid_stocks: {t.valid_stocks}, total_stocks: {t.total_stocks}')
    print(f'up_stocks: {t.up_stocks}, down_stocks: {t.down_stocks}')
    
    # Now compute_breadth directly
    stock_list = list(metrics.values())
    result2 = compute_breadth(stock_list, settings)
    print(f'compute_breadth: up_percent={result2["up_percent"]}')