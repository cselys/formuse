from pathlib import Path

from stock_scanner.src.reporting.state_breakdown import StateBreakdown, formatted_row, render_state_section, save_state_breakdown
from stock_scanner.src.reporting.console import display_console_report
from stock_scanner.src.reporting.daily_report import DailyReport
from stock_scanner.src.reporting.file_writer import save_daily_report


def records():
    return [dict(symbol=symbol, category='tech<&>', state=state, candidate_score=score,
                 trend_score=71.2, entry_quality=68.1, bottom_score=42.3, reversal_score=54.6,
                 relative_strength={'rs_20d': -2.7}, daily={'rsi': 53.1, 'distance_ema20': 2.2},
                 daily_change_pct=1.2, signal_tier='WATCHLIST')
            for symbol, state, score in [('AAA', 'UPTREND', 72.1), ('BBB', 'REVERSAL', 80.5), ('CCC', 'UPTREND', 89.7)]]


def test_state_html_matches_shared_terminal_values(tmp_path, capsys):
    data = records()
    model = StateBreakdown(data)
    display_console_report(data, state_breakdown=model)
    terminal = capsys.readouterr().out
    standalone = Path(save_state_breakdown(model, '2026-09-21', tmp_path)).read_text(encoding='utf-8')
    assert 'state_breakdown_2026-09-21.html' in str(tmp_path / 'state_breakdown_2026-09-21.html')
    for group in model.groups:
        assert f'{group.state} ({len(group.rows)} symbols)' in terminal
        assert f'{group.state} ({len(group.rows)} symbols)' in standalone
        for row in group.rows:
            for value in formatted_row(row):
                if value != 'tech<&>':
                    assert value in terminal and value in standalone
    assert 'tech&lt;&amp;&gt;' in standalone and 'tech<&>' not in standalone
    assert 'WATCHLIST' in standalone
    assert [r['symbol'] for r in model.groups[0].rows] == ['CCC', 'AAA']


def test_daily_and_standalone_share_exact_section(tmp_path):
    model = StateBreakdown(records(), top_n=1)
    report = DailyReport(records(), scan_date='2026-09-21', state_breakdown=model)
    paths = save_daily_report(report, tmp_path)
    section = render_state_section(model)
    assert section in Path(paths['html']).read_text(encoding='utf-8')
    assert section in Path(paths['state_breakdown']).read_text(encoding='utf-8')
    assert 'UPTREND (1 symbols)' in section
    assert 'Showing 1 of 2' in section
    assert 'AAA' not in section
    assert model.groups[0].rows[0]['candidate_score'] == 89.7


def test_state_model_does_not_mutate_or_reclassify():
    data = records()
    original = [r.copy() for r in data]
    StateBreakdown(data, top_n=1)
    assert data == original


def test_empty_state_breakdown(tmp_path):
    path = save_state_breakdown(StateBreakdown([]), '2026-09-21', tmp_path)
    assert 'No scan results' in Path(path).read_text()
