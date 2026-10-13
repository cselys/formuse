"""
Unit tests for yfinance data loader and validation in stock_scanner.
"""

import pytest
import pandas as pd
from stock_scanner.src.data.yfinance_loader import YFinanceLoader, DataValidationError


def test_clean_and_validate_dataframe():
    loader = YFinanceLoader()
    dates = pd.date_range(start="2025-01-01", periods=50, freq="B")
    df = pd.DataFrame({
        'Open': [100.0] * 50,
        'High': [105.0] * 50,
        'Low': [95.0] * 50,
        'Close': [102.0] * 50,
        'Volume': [1000000.0] * 50
    }, index=dates)

    cleaned = loader._clean_and_validate_dataframe(df, "TEST")
    assert len(cleaned) == 50
    assert 'Open' in cleaned.columns
    assert 'Volume' in cleaned.columns


def test_clean_and_validate_insufficient_bars():
    loader = YFinanceLoader()
    dates = pd.date_range(start="2025-01-01", periods=10, freq="B")
    df = pd.DataFrame({
        'Open': [100.0] * 10,
        'High': [105.0] * 10,
        'Low': [95.0] * 10,
        'Close': [102.0] * 10,
        'Volume': [1000000.0] * 10
    }, index=dates)

    with pytest.raises(DataValidationError):
        loader._clean_and_validate_dataframe(df, "TEST")
