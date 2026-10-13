"""
Unit tests for configurable shortlist and full list YAML watchlist generation in stock_scanner V1.2.
"""

import os
import tempfile
import yaml
import pytest

from stock_scanner.src.reporting.yaml_watchlist import save_watchlist_yaml


@pytest.fixture
def sample_results():
    return [
        {
            'scanner_version': '1.2',
            'symbol': f'STOCK{i}',
            'category': 'technology',
            'state': 'UPTREND',
            'candidate_score': float(100 - i * 2),
            'trend_score': 80.0,
            'entry_quality': 90.0
        }
        for i in range(1, 15)  # 14 stocks with candidate scores 98, 96, 94, ...
    ] + [
        {
            'scanner_version': '1.2',
            'symbol': 'BEAR1',
            'category': 'energy',
            'state': 'DOWNTREND',
            'candidate_score': 20.0,
            'trend_score': 15.0,
            'entry_quality': 40.0
        }
    ]


def test_default_config_shortlist_and_full(sample_results):
    with tempfile.TemporaryDirectory() as tmpdir:
        config = {'output': {'shortlist': {'enabled': True, 'size': 5}, 'save_full_list': True}}
        files = save_watchlist_yaml(sample_results, output_dir=tmpdir, config=config)

        assert 'call' in files
        assert 'put' in files
        assert 'call_full' in files
        assert 'put_full' in files

        with open(files['call'], 'r', encoding='utf-8') as f:
            call_data = yaml.safe_load(f)
        with open(files['call_full'], 'r', encoding='utf-8') as f:
            call_full_data = yaml.safe_load(f)

        # 1. Default config produces a 5-stock shortlist
        assert len(call_data['stocks']) == 5

        # 5. save_full_list: true produces full list with all 14 candidates
        assert len(call_full_data['stocks']) == 14

        # 7. Shortlist contains the same top-ranked candidates as the full result
        for i in range(5):
            assert call_data['stocks'][i]['symbol'] == call_full_data['stocks'][i]['symbol']

        # 8. Shortlist priorities are renumbered sequentially from 1
        for idx, stock in enumerate(call_data['stocks'], 1):
            assert stock['priority'] == idx


def test_shortlist_sizes(sample_results):
    with tempfile.TemporaryDirectory() as tmpdir:
        # 2. shortlist.size: 10 produces 10 candidates
        config_10 = {'output': {'shortlist': {'enabled': True, 'size': 10}}}
        files_10 = save_watchlist_yaml(sample_results, output_dir=tmpdir, config=config_10)
        with open(files_10['call'], 'r', encoding='utf-8') as f:
            data_10 = yaml.safe_load(f)
        assert len(data_10['stocks']) == 10
        assert data_10['stocks'][-1]['priority'] == 10

        # 3. shortlist.size: 1 produces 1 candidate
        config_1 = {'output': {'shortlist': {'enabled': True, 'size': 1}}}
        files_1 = save_watchlist_yaml(sample_results, output_dir=tmpdir, config=config_1)
        with open(files_1['call'], 'r', encoding='utf-8') as f:
            data_1 = yaml.safe_load(f)
        assert len(data_1['stocks']) == 1
        assert data_1['stocks'][0]['priority'] == 1


def test_shortlist_disabled(sample_results):
    with tempfile.TemporaryDirectory() as tmpdir:
        # 4. shortlist.enabled: false disables shortlist files
        config = {'output': {'shortlist': {'enabled': False, 'size': 5}, 'save_full_list': True}}
        files = save_watchlist_yaml(sample_results, output_dir=tmpdir, config=config)

        assert 'call' not in files
        assert 'put' not in files
        assert 'call_full' in files
        assert os.path.exists(files['call_full'])
        assert not os.path.exists(os.path.join(tmpdir, 'call_stocks.yaml'))


def test_save_full_list_disabled(sample_results):
    with tempfile.TemporaryDirectory() as tmpdir:
        # 6. save_full_list: false does not produce _full.yaml
        config = {'output': {'shortlist': {'enabled': True, 'size': 5}, 'save_full_list': False}}
        files = save_watchlist_yaml(sample_results, output_dir=tmpdir, config=config)

        assert 'call_full' not in files
        assert 'put_full' not in files
        assert 'call' in files
        assert os.path.exists(files['call'])
        assert not os.path.exists(os.path.join(tmpdir, 'call_stocks_full.yaml'))


def test_shortlist_size_larger_than_available(sample_results):
    with tempfile.TemporaryDirectory() as tmpdir:
        # 10. Requested shortlist size larger than available candidates works correctly (e.g. size 50 when 14 exist)
        config = {'output': {'shortlist': {'enabled': True, 'size': 50}}}
        files = save_watchlist_yaml(sample_results, output_dir=tmpdir, config=config)
        with open(files['call'], 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert len(data['stocks']) == 14
        assert data['stocks'][-1]['priority'] == 14


def test_empty_results():
    with tempfile.TemporaryDirectory() as tmpdir:
        # 11. Empty CALL/PUT results do not crash
        files = save_watchlist_yaml([], output_dir=tmpdir)
        with open(files['call'], 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        assert data['stocks'] == []


def test_invalid_config_validation(sample_results):
    with tempfile.TemporaryDirectory() as tmpdir:
        # Invalid size (negative or zero)
        with pytest.raises(ValueError):
            save_watchlist_yaml(sample_results, output_dir=tmpdir, config={'output': {'shortlist': {'size': 0}}})

        with pytest.raises(ValueError):
            save_watchlist_yaml(sample_results, output_dir=tmpdir, config={'output': {'shortlist': {'size': -5}}})

        # Invalid enabled (non-boolean)
        with pytest.raises(ValueError):
            save_watchlist_yaml(sample_results, output_dir=tmpdir, config={'output': {'shortlist': {'enabled': 'yes'}}})

        # Invalid save_full_list (non-boolean)
        with pytest.raises(ValueError):
            save_watchlist_yaml(sample_results, output_dir=tmpdir, config={'output': {'save_full_list': 1}} )
