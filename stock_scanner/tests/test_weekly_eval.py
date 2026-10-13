"""
Unit tests for weekly partial candle handling and historical evaluation in stock_scanner.
"""

import pytest
import pandas as pd
from stock_scanner.src.data.yfinance_loader import YFinanceLoader


def test_resample_to_weekly_drop_partial():
    loader = YFinanceLoader()
    # Create daily index spanning across weeks
    dates = pd.date_range(start="2025-01-06", periods=10, freq="B") # Mon Jan 6 to Fri Jan 17
    df = pd.DataFrame({
        'Open': [100.0] * 10,
        'High': [105.0] * 10,
        'Low': [95.0] * 10,
        'Close': [102.0] * 10,
        'Volume': [1000000.0] * 10
    }, index=dates)

    # Test with drop_partial=True and as_of_date on a Wednesday mid-week (e.g. Jan 15, 2025 is Wednesday)
    res_partial = loader.resample_to_weekly(df, as_of_date="2025-01-15", drop_partial=True)
    # Week ending Jan 10 is complete (Friday). Week ending Jan 17 has daily data only up to Wed Jan 15.
    # With drop_partial=True, the partial week ending Jan 17 should be dropped.
    assert len(res_partial) == 1
    assert res_partial.index[0].strftime('%Y-%m-%d') == '2025-01-10'
