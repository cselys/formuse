from tests.conftest import build_metrics
from utils.config import load_settings
from engine.sector_engine import run_sector_engine
from engine.breadth_engine import compute_breadth

settings = load_settings()

# Build metrics like the dashboard does
md, metrics = build_metrics({'A': [101.0], 'B': [102.0]}, settings=settings)

# Run sector engine
themes_cfg = {
    'TestTheme': {
        'tickers': ['A', 'B'],
        'etf': []
    }
}
result = run_sector_engine(themes_cfg, metrics, md, settings)

# result is a list of ThemeMetrics
if result:
    t = result[0]
    print(f'Theme: {t.theme}')
    print(f'up_percent: {t.up_percent}')
    print(f'down_percent: {t.down_percent}')
    print(f'average_return: {t.average_return}')
    print(f'median_return: {t.median_return}')
    print(f'valid_stocks: {t.valid_stocks}')
    print(f'total_stocks: {t.total_stocks}')
    print(f'up_stocks: {t.up_stocks}')
    print(f'down_stocks: {t.down_stocks}')
    print(f'flat_stocks: {t.flat_stocks}')
    
    # Now compute breadth directly
    print()
    print('Direct compute_breadth:')
    stock_list = list(metrics.values())
    result2 = compute_breadth(stock_list, settings)
    print(f'  up_percent: {result2["up_percent"]}')
    print(f'  down_percent: {result2["down_percent"]}')
    print(f'  valid_stocks: {result2["valid_stocks"]}')
    print(f'  total_stocks: {result2["total_stocks"]}')
    print(f'  up_stocks: {result2["up_stocks"]}')