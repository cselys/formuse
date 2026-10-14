"""Refresh configuration and real Streamlit widget/timer wiring regressions."""
from types import SimpleNamespace

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


def render_sidebar(settings):
    import app
    import streamlit as st
    selected = app.render_sidebar(settings, {})
    st.session_state['returned_refresh'] = selected['refresh_sec']


def interval(at):
    return next(widget for widget in at.selectbox if widget.label == 'Interval')


@pytest.mark.parametrize('settings,expected', [
    ({'data': {'refresh_seconds': 300}}, 300),
    ({'data': {'refresh_seconds': 60}}, 60),
    ({'data': {'refresh_seconds': 240}}, 240),
    ({'data': {'refresh_seconds': 1}}, 1),
    ({}, 300),
    ({'data': {}}, 300),
    *[({'data': {'refresh_seconds': value}}, 300) for value in
      (None, '240', 'invalid', '', 1.5, 240.0, True, False, 0, -30, [], {})],
])
def test_configured_interval(settings, expected):
    at = AppTest.from_function(render_sidebar, args=(settings,)).run()
    assert not at.exception
    widget = interval(at)
    assert widget.value == expected
    assert f'{expected} seconds' in widget.options
    assert {f'{n} seconds' for n in (30, 60, 120, 300, 600)} <= set(widget.options)
    assert at.session_state['returned_refresh'] == expected


def test_user_selection_persists_and_drives_fragment(monkeypatch):
    import app

    settings = {'data': {'refresh_seconds': 240}}
    now = pd.Timestamp('2026-10-08 12:00', tz='America/New_York')
    monkeypatch.setattr(app, 'load_settings', lambda: settings)
    monkeypatch.setattr(app, 'load_themes', lambda: {})
    monkeypatch.setattr(app, 'get_store', lambda: object())
    monkeypatch.setattr(app, 'now_et', lambda: now)
    monkeypatch.setattr(app, 'market_status', lambda _: {
        'session_day': now.date(), 'status': 'OPEN', 'session_open': None})
    monkeypatch.setattr(app, 'load_snapshot_market_data',
                        lambda *args: (SimpleNamespace(asof=now), {}))
    monkeypatch.setattr(app, 'run_pipeline', lambda *args, **kwargs: {
        'metrics': [], 'rankings': {}, 'composite': None, 'alerts': [],
        'etf_rows': [], 'stock_metrics': {}, 'session_date': '2026-10-08'})
    monkeypatch.setattr(app, 'render_dashboard', lambda ctx: None)

    intervals = []
    real_fragment = app.st.fragment

    def record_fragment(*args, **kwargs):
        intervals.append(kwargs['run_every'])
        return real_fragment(*args, **kwargs)

    monkeypatch.setattr(app.st, 'fragment', record_fragment)

    def render():
        import app
        app.main()

    at = AppTest.from_function(render).run()
    assert not at.exception
    assert interval(at).value == 240
    assert intervals[-1] == '240s'

    interval(at).select(120).run()
    assert not at.exception
    assert interval(at).value == 120
    assert intervals[-1] == '120s'

    at.run()  # normal rerun without a widget change
    assert not at.exception
    assert interval(at).value == 120
    assert intervals[-1] == '120s'

    next(widget for widget in at.checkbox if widget.label == 'Top Up').uncheck().run()
    assert not at.exception
    assert interval(at).value == 120
    assert intervals[-1] == '120s'
    assert settings['data']['refresh_seconds'] == 240
