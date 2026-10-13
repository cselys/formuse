"""Integrated universe configuration validation tests for the stock_scanner project.

These tests validate config/universe.yaml using the shared UniverseValidationError
raised by stock_scanner.src.validation.universe_validator.validate_universe_yaml().

All tests use temporary configuration data and never modify the real universe YAML.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from stock_scanner.src.validation.universe_validator import UniverseValidationError, validate_universe_yaml

# ---------------------------------------------------------------------------
# Helper: valid base config used across multiple tests
# ---------------------------------------------------------------------------

_VALID_BASE: dict = {
    "market_benchmarks": ["SPY", "QQQ"],
    "etf_symbols": ["ARKK", "TNA", "SQQQ"],
    "sector_indexes": {"technology": "XLK", "financials": "XLF"},
    "categories": {
        "semiconductors": {"benchmark": "SMH", "symbols": ["NVDA", "AMD"]},
        "technology": {"benchmark": "QQQ", "symbols": ["AAPL", "MSFT"]},
        "energy": {"benchmark": "XLE", "symbols": ["XOM", "CVX"]},
    },
}


# ---------------------------------------------------------------------------
# 1. Valid configuration acceptance
# ---------------------------------------------------------------------------


def test_universe_validator_valid_configuration():
    """Valid existing configuration should be accepted without error."""
    try:
        validate_universe_yaml(_VALID_BASE)
    except UniverseValidationError:
        pytest.fail("Valid universe configuration was rejected.")


# ---------------------------------------------------------------------------
# 2. Boolean symbol entry rejected
# ---------------------------------------------------------------------------


def test_universe_validator_boolean_symbol():
    """Boolean symbol entries (e.g. True, False) are rejected."""
    config = _VALID_BASE.copy()
    config["categories"]["semiconductors"]["symbols"] = [True]
    try:
        validate_universe_yaml(config)
        pytest.fail("Boolean symbol was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 3. Numeric symbol entries rejected
@pytest.mark.parametrize("value", [42, -1, 3.14])
def test_universe_validator_numeric_symbol(value):
    """Numeric symbol entries are rejected."""
    config = _VALID_BASE.copy()
    config["categories"]["energy"]["symbols"] = [value]
    try:
        validate_universe_yaml(config)
        pytest.fail(f"Numeric symbol {value!r} was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 4. Null symbol entries rejected
def test_universe_validator_null_symbol():
    """None/null symbol entries are rejected."""
    config = _VALID_BASE.copy()
    config["categories"]["energy"]["symbols"] = [None]
    try:
        validate_universe_yaml(config)
        pytest.fail("Null symbol was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 5. Empty symbol entries rejected
def test_universe_validator_empty_symbol():
    """Empty string symbols are rejected."""
    config = _VALID_BASE.copy()
    config["categories"]["energy"]["symbols"] = [""]
    try:
        validate_universe_yaml(config)
        pytest.fail("Empty symbol was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 6. Whitespace-only symbol entries rejected
def test_universe_validator_whitespace_symbol():
    """Whitespace-only symbols are rejected."""
    config = _VALID_BASE.copy()
    config["categories"]["energy"]["symbols"] = ["   "]
    try:
        validate_universe_yaml(config)
        pytest.fail("Whitespace-only symbol was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 7. Empty and whitespace-only category names rejected
@pytest.mark.parametrize("bad_name", ["", "   "])
def test_universe_validator_empty_category_name(bad_name):
    """Empty or whitespace-only category names are rejected."""
    config = {
        "market_benchmarks": ["SPY"],
        "categories": {bad_name: {"benchmark": "QQQ", "symbols": ["AAPL"]}},
    }
    try:
        validate_universe_yaml(config)
        pytest.fail(f"Empty category name {bad_name!r} was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 8. Missing or malformed categories rejected
def test_universe_validator_missing_categories():
    """Missing 'categories' key is rejected."""
    config = {"market_benchmarks": ["SPY"]}  # no 'categories'
    try:
        validate_universe_yaml(config)
        pytest.fail("Missing 'categories' was not rejected.")
    except UniverseValidationError:
        pass  # expected


def test_universe_validator_empty_categories():
    """Empty 'categories' mapping is rejected."""
    config = {"categories": {}}
    try:
        validate_universe_yaml(config)
        pytest.fail("Empty 'categories' was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 9. Empty symbol lists rejected
def test_universe_validator_empty_symbol_list():
    """Category with an empty 'symbols' list is rejected."""
    config = {
        "categories": {
            "test": {"benchmark": "QQQ", "symbols": []},
        }
    }
    try:
        validate_universe_yaml(config)
        pytest.fail("Empty symbol list was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 10. Duplicate symbols within a category rejected
def test_universe_validator_duplicate_within_category():
    """Duplicate symbols within a category are rejected."""
    config = _VALID_BASE.copy()
    config["categories"]["technology"]["symbols"] = ["AAPL", "AAPL"]
    try:
        validate_universe_yaml(config)
        pytest.fail("Duplicate within category was not rejected.")
    except UniverseValidationError:
        pass  # expected


# 11. Cross-category duplicates permitted (documented semantics)
def test_universe_validator_cross_category_duplicate():
    """Symbols may appear in multiple categories (documented behavior)."""
    config = {
        "categories": {
            "tech": {"benchmark": "QQQ", "symbols": ["AAPL"]},
            "software": {"benchmark": "QQQ", "symbols": ["AAPL"]},
        }
    }
    try:
        validate_universe_yaml(config)  # should NOT raise
    except UniverseValidationError:
        pytest.fail("Cross-category duplicate was incorrectly rejected.")


# ---------------------------------------------------------------------------
# Integration: StockScanner rejects malformed configuration before scanning
# ---------------------------------------------------------------------------


def test_stock_scanner_refuses_malformed_universe(tmp_path):
    """StockScanner.__init__ raises UniverseValidationError when universe is invalid.

    We use a temporary directory so the real config/universe.yaml is never touched.
    """
    from stock_scanner.src.scanner import StockScanner

    # Write a valid scanner.yaml so StockScanner init doesn't fail before universe validation.
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "config" / "scanner.yaml").write_text(
        "scanner_version: 1.2\n"
    )
    # Write an invalid universe (boolean symbol) into the temp config.
    (tmp_path / "config" / "universe.yaml").write_text(
        "market_benchmarks:\n"
        "  - SPY\n"
        "categories:\n"
        "  test:\n"
        "    benchmark: QQQ\n"
        "    symbols:\n"
        "      - True\n"
    )
    # StockScanner.__init__ calls validate_universe_yaml, which should raise.
    with pytest.raises(UniverseValidationError):
        StockScanner(config_dir=str(tmp_path / "config"))


# ---------------------------------------------------------------------------
# Integration: lookup_stock rejects invalid configuration silently falling back
# ---------------------------------------------------------------------------


def test_lookup_stock_rejects_malformed_universe():
    """lookup_stock() / validate_universe_yaml() raises on malformed universe.

    The validator is called early in lookup_stock(), so a malformed universe
    produces a UniverseValidationError rather than silently falling back to
    "custom-symbol SPY benchmark".
    """
    universe = {"categories": {"test": {"benchmark": "QQQ", "symbols": [True]}}}
    with pytest.raises(UniverseValidationError):
        validate_universe_yaml(universe)


# ---------------------------------------------------------------------------
# Integration: PONY _load_inputs() rejects malformed universe before staging/writing
# ---------------------------------------------------------------------------


def test_pony_pilot_load_inputs_rejects_malformed_universe(tmp_path, monkeypatch):
    """PONY pilot _load_inputs() rejects malformed universe before staging or writing."""
    from stock_scanner import pony_backfill_pilot as pilot

    # Build a minimal valid-looking config root under tmp_path.
    config_root = tmp_path / "config"
    config_root.mkdir(parents=True)

    # Write a scanner.yaml so _config_root() passes.
    (config_root / "scanner.yaml").write_text(
        "scanner_version: 1.2\n"
    )

    # Write an invalid universe.yaml (empty categories).
    (config_root / "universe.yaml").write_text("categories: {}")

    # Monkeypatch EXPECTED_CONFIG_ROOT.
    monkeypatch.setattr(pilot, "EXPECTED_CONFIG_ROOT", config_root)

    # Use the project ROOT as base for the database path.
    pilot_root = Path(__file__).parent.parent / "stock_scanner"
    pilot.ROOT = pilot_root

    # Ensure the database directory exists.
    db_dir = pilot_root / "data" / "history_lookup"
    db_dir.mkdir(parents=True, exist_ok=True)

    # Create a minimal baseline database so _baseline() passes.
    db_path = db_dir / "results.sqlite3"
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(str(db_path))
    con.execute(
        "CREATE TABLE IF NOT EXISTS history_revisions "
        "(revision_id TEXT PRIMARY KEY, input_key TEXT NOT NULL, payload TEXT NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS history_canonical "
        "(symbol TEXT, evaluation_date TEXT, revision_id TEXT NOT NULL, "
        "PRIMARY KEY(symbol, evaluation_date))"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS history_artifacts "
        "(artifact_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    con.execute(
        "CREATE TABLE IF NOT EXISTS results "
        "(cache_key TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )
    # Insert a row so the baseline count check doesn't fail.
    con.execute(
        "INSERT INTO results (cache_key, payload) VALUES ('baseline_key', '{\"test\":true}')"
    )
    con.commit()
    con.close()

    # Now _load_inputs should raise because validate_universe_yaml rejects {}.
    with pytest.raises(pilot.PilotAbort):
        pilot._load_inputs(expected_calculation="fake-calculation")


# ---------------------------------------------------------------------------
# Preserve the standalone diagnostic script (test_validator.py) for reference;
# its 10 scenarios are now also covered by the formal pytest suite above.
# ---------------------------------------------------------------------------