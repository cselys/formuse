"""Presentation-only ticker lines reuse quote fixtures and current eligibility."""
from copy import deepcopy
from dataclasses import replace

import pytest

from data.snapshot_loader import snapshot_from_row
from models.schemas import Alert
from tests.test_theme_alignment import quote, T
from ui.dashboard import _alert_tickers, _render_alerts


def stock(symbol, change=2, **overrides):
    return replace(snapshot_from_row(quote(symbol, change), T), **overrides)


def test_order_format_limit_and_membership():
    stocks = {s: stock(s, v) for s, v in zip('ABCDEFGX', [-2, 0, 3, 3, 1, -1, -4, 99])}
    themes = {'Theme': {'tickers': list('GFEDCBAA'), 'etf': ['X']}}
    before = deepcopy((stocks, themes))
    assert _alert_tickers('Theme', stocks, themes, {}) == (
        'C +3.00% · D +3.00% · E +1.00% · B +0.00% · F -1.00%')
    assert (stocks, themes) == before


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -float('inf'), '2', True])
def test_unusable_percentage_omitted(value):
    stocks = {'A': stock('A', change_vs_previous_close=value)}
    assert _alert_tickers('Theme', stocks, {'Theme': {'tickers': ['A']}}, {}) == ''


@pytest.mark.parametrize('age,valid,shown', [
    (59, True, True), (120, True, True), (179, True, True),
    (180, True, False), (300, True, False), (-1, True, False),
    (None, True, False), (float('nan'), True, False), (0, False, False),
])
def test_existing_current_eligibility(age, valid, shown):
    stocks = {'A': stock('A', data_age_seconds=age, is_valid=valid)}
    result = _alert_tickers('Theme', stocks, {'Theme': {'tickers': ['A']}}, {})
    assert bool(result) is shown


def test_configured_current_policy_and_missing_quotes():
    stocks = {'A': stock('A', data_age_seconds=120)}
    themes = {'Theme': {'tickers': ['A', 'MISSING']}}
    settings = {'data': {'finnhub': {'freshness': {'current_signal_max_age_seconds': 60}}}}
    assert _alert_tickers('Theme', stocks, themes, settings) == ''
    assert _alert_tickers('Unknown', stocks, themes, {}) == ''


@pytest.mark.parametrize('with_stocks', [True, False])
def test_render_preserves_first_lines_order_and_inputs(monkeypatch, with_stocks):
    alerts = [Alert('Breadth Collapse', 'Theme', 'Theme rank 2: -1.25%', 'warn'),
              Alert('Top 3 Entry', 'Theme', 'Theme rank 1: +2.34%')]
    stocks = {'A': stock('A', -1.25), 'B': stock('B', 2.34)} if with_stocks else {}
    themes = {'Theme': {'tickers': ['A', 'B']}}
    before = deepcopy((alerts, stocks, themes))
    calls = []
    monkeypatch.setattr('ui.dashboard.st.subheader', lambda text: calls.append(('header', text)))
    monkeypatch.setattr('ui.dashboard.st.warning', lambda text, **kw: calls.append(('warning', text, kw)))
    monkeypatch.setattr('ui.dashboard.st.caption', lambda text: calls.append(('caption', text)))
    _render_alerts(alerts, stocks, themes, {})
    expected = [('header', '🚨 Alerts')]
    for alert, icon in zip(alerts, ['📉', '📈']):
        expected.append(('warning', f'**{alert.kind.upper()}** — {alert.message}', {'icon': icon}))
        if with_stocks:
            expected.append(('caption', 'B +2.34% · A -1.25%'))
    assert calls == expected
    assert (alerts, stocks, themes) == before
