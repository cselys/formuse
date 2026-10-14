"""Regression coverage for YAML ticker types and theme normalization."""
import pytest

from utils.config import DEFAULT_THEMES_PATH, load_themes, load_yaml


@pytest.mark.parametrize("loader", [load_yaml, load_themes])
def test_semiconductor_on_remains_a_string(loader):
    tickers = loader(DEFAULT_THEMES_PATH)["Semiconductor"]["tickers"]
    assert "ON" in tickers
    assert all(isinstance(ticker, str) for ticker in tickers)
    assert "TRUE" not in tickers
    assert True not in tickers
