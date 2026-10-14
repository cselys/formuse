"""Production quote path regressions: asynchronous delivery, coherent baskets."""
import math
from datetime import date

import pandas as pd
import pytest

from data.cache import SnapshotStore
from data.snapshot_loader import load_snapshot_market_data, snapshot_from_row
from engine.alerts import detect_alerts
from engine.reversal_engine import analyze_history
from engine.sector_engine import run_sector_engine
from engine.theme_history import build_theme_history, observation_at, prepare_quotes
from ui.dashboard import _momentum_table, _panel
from ui.formatting import fmt_plain


T = pd.Timestamp("2026-10-07 10:15:00", tz="America/New_York")


def quote(symbol, ret, provider=T, fetched=None, valid=True, previous=100):
    fetched = provider + pd.Timedelta(seconds=2) if fetched is None else fetched
    return dict(symbol=symbol, session_date="2026-10-07", provider_timestamp=provider.timestamp(),
                fetched_at=fetched.isoformat(), data_age_seconds=(fetched-provider).total_seconds(),
                source="finnhub", price=previous * (1 + ret / 100), previous_close=previous,
                today_open=previous, intraday_high=previous*1.1, intraday_low=previous*.9,
                volume=100, is_valid=int(valid), issue="")


def history_rows(returns, breadth=False):
    rows = []
    for i, values in enumerate(returns):
        target = T - pd.Timedelta(minutes=5*(len(returns)-1-i))
        for j, value in enumerate(values):
            rows.append(quote(chr(65+j), value, target - pd.Timedelta(seconds=j*3),
                              target + pd.Timedelta(seconds=j+1)))
    return rows


def pipeline(tmp_path, rows, monkeypatch, symbols=None):
    from app import run_pipeline
    store = SnapshotStore(tmp_path / "test.db")
    store.save_quote_snapshots("2026-10-07", [snapshot_from_row(r) for r in rows])
    md, stocks = load_snapshot_market_data(store, "2026-10-07", T + pd.Timedelta(hours=1))
    symbols = symbols or sorted({r['symbol'] for r in rows})
    ctx = run_pipeline(md, {"session_day": date(2026,10,7), "status":"OPEN"}, {},
                       {"Theme": {"tickers": symbols, "etf":[]}}, symbols, store, T,
                       stock_metrics=stocks)
    tables=[]
    monkeypatch.setattr("ui.dashboard.st.dataframe", lambda sty, **kw: tables.append(sty.data))
    _momentum_table(ctx["metrics"])
    return ctx["metrics"][0], tables, md, store


def test_async_delivery_forms_one_basket():
    # Different delivery times do not create theme timestamps. The market quotes
    # are within 60s at their intended target, independent of delivery latency.
    base = T.floor("h")
    rows = [quote(s, v, base-pd.Timedelta(seconds=i*10), base+pd.Timedelta(seconds=d))
            for i,(s,v,d) in enumerate([("A",2,10),("B",-1,65),("C",3,140)])]
    h, current = build_theme_history(pd.DataFrame(rows), list("ABC"), base, {})
    assert current['eligible_count'] == 3
    assert current['average_return'] == pytest.approx(4/3)
    assert current['median_return'] == pytest.approx(2)
    assert current['up_count'] == 2
    assert current['up_percent'] == pytest.approx(200/3)
    assert h.index.is_unique
    assert all(len(c) != 1 or not sufficient for c,sufficient in zip(h.constituents,h.sufficient))


def test_sqlite_pipeline_renderer_breadth_and_multirow_history(tmp_path, monkeypatch):
    rows=history_rows([[1,1,1,-1,-1]]*4)
    m,tables,md,_=pipeline(tmp_path,rows,monkeypatch)
    assert m.up_stocks == 3 and m.valid_stocks == 5
    assert m.up_percent == m.breadth_now == pytest.approx(60)
    assert tables[0].iloc[0]['Up % Now'] == fmt_plain(60)
    assert len(md.bars['A']) == 4
    assert md.asof == T and md.fetched_at == T+pd.Timedelta(hours=1)
    assert md.bars['A'].index[-1] == T


@pytest.mark.parametrize('returns,peak,low,current,rev,rec', [
    ([2,4,1,-1],4,-1,-1,5,0), ([2,-3,-1],2,-3,-1,3,2)])
def test_reversal_recovery_and_display_invariants(tmp_path,monkeypatch,returns,peak,low,current,rev,rec):
    m,tables,_,_=pipeline(tmp_path,history_rows([[v,v] for v in returns]),monkeypatch)
    assert m.average_return == pytest.approx(current)
    assert m.intraday_high == pytest.approx(peak)
    assert m.intraday_low == pytest.approx(low)
    assert -m.reversal_from_high == pytest.approx(rev)
    assert m.recovery_from_low == pytest.approx(rec)
    assert -m.reversal_from_high == pytest.approx(m.intraday_high-m.average_return)
    assert m.recovery_from_low == pytest.approx(m.average_return-m.intraday_low)
    _panel([m],[("Theme","theme","text"),("Current","average_return","signed"),
                ("Peak","intraday_high","signed"),("Recovery","recovery_from_low","signed")],"",False)
    assert tables[-1].iloc[0]['Current'] == f'{current:+.2f}%'


def test_known_historical_breadth_and_rendered_deltas(tmp_path,monkeypatch):
    m,tables,_,_=pipeline(tmp_path,history_rows([
        [1,-1,-1,-1,-1], [1,1,-1,-1,-1], [1,1,1,-1,-1], [1,1,1,1,-1]]),monkeypatch)
    assert m.breadth_now == 80
    assert m.breadth_5m_ago == 60
    assert m.breadth_15m_ago == 20
    assert m.breadth_change_5m == 20
    assert m.breadth_change_15m == 60
    assert tables[0].iloc[0]['Δ 5m'] == '+20.0 pp'
    assert tables[0].iloc[0]['Δ 15m'] == '+60.0 pp'


def test_two_minutes_do_not_manufacture_5_or_15_minutes():
    h=pd.DataFrame({'avg_return':[0,1,2],'up_percent':[0,50,100]},
                   index=pd.date_range(T,periods=3,freq='1min'))
    result=analyze_history(h,{})
    assert math.isnan(result['breadth_5m_ago'])
    assert math.isnan(result['breadth_15m_ago'])


def test_no_future_lookahead_or_unbounded_carry():
    rows=[quote('A',2,T-pd.Timedelta(seconds=59)), quote('B',-1,T-pd.Timedelta(seconds=60)),
          quote('C',3,T+pd.Timedelta(seconds=1)),quote('D',4,T-pd.Timedelta(seconds=300))]
    q=prepare_quotes(pd.DataFrame(rows),list('ABCD'))
    x=observation_at(q,list('ABCD'),T,{})
    assert x['eligible_count']==1 and x['status']=='INSUFFICIENT DATA'
    assert math.isnan(x['average_return']) and math.isnan(x['up_percent'])
    assert x['aging_stocks']==1 and x['stale_stocks']==1


def test_invalid_latest_uses_latest_valid_own_reference_and_duplicate_tie():
    rows=[quote('A',2,T-pd.Timedelta(seconds=10),previous=200),
          quote('A',99,T,valid=False),quote('B',-1),quote('B',3,fetched=T+pd.Timedelta(seconds=4))]
    q=prepare_quotes(pd.DataFrame(rows),list('AB'))
    x=observation_at(q,list('AB'),T,{})
    assert x['average_return']==pytest.approx(2.5)
    assert x['eligible_count']==2


def test_missing_current_never_falls_back_to_historical_basket(tmp_path,monkeypatch):
    rows=history_rows([[2,2],[4,4],[1,1]])+[quote('ETF',1,T+pd.Timedelta(minutes=5))]
    m,tables,_,_=pipeline(tmp_path,rows,monkeypatch,symbols=list('AB'))
    assert m.observation_status=='INSUFFICIENT DATA'
    assert m.valid_stocks==0 and math.isnan(m.average_return)
    assert math.isnan(m.reversal_from_high) and math.isnan(m.breadth_now)
    assert tables[0].iloc[0]['Up % Now'] == fmt_plain(float('nan'))
    assert not detect_alerts([m])


def test_refresh_loads_new_quotes_asof_and_session(tmp_path):
    store=SnapshotStore(tmp_path/'refresh.db')
    store.save_quote_snapshots('2026-10-07',[snapshot_from_row(quote('A',1))])
    old,_=load_snapshot_market_data(store,'2026-10-07',T)
    store.save_quote_snapshots('2026-10-07',[snapshot_from_row(quote('A',2,T+pd.Timedelta(minutes=5)))])
    new,_=load_snapshot_market_data(store,'2026-10-07',T+pd.Timedelta(minutes=6))
    assert len(old.bars['A'])==1 and len(new.bars['A'])==2
    assert new.asof-old.asof==pd.Timedelta(minutes=5)
    empty,_=load_snapshot_market_data(store,'2026-10-08',T+pd.Timedelta(days=1))
    assert empty.asof is None and empty.quote_snapshots.empty


def test_real_zero_breadth_is_not_missing():
    h,current=build_theme_history(pd.DataFrame([quote('A',-1),quote('B',-2)]),list('AB'),T,{})
    assert current['up_percent']==0 and current['sufficient']
    assert analyze_history(h,{})['breadth_now']==0


def test_same_quotes_do_not_inflate_history_evidence():
    rows=[quote(s,1,T-pd.Timedelta(seconds=i)) for i,s in enumerate('AB')]
    rows += [dict(r,fetched_at=(T+pd.Timedelta(seconds=30)).isoformat()) for r in rows]
    h,_=build_theme_history(pd.DataFrame(rows),list('AB'),T,{})
    assert not analyze_history(h,{})['has_history']


def test_actual_provider_times_spread_over_two_minutes_are_not_all_fresh():
    start=T.floor('h')
    times=[start+pd.Timedelta(seconds=s) for s in (10,65,140)]
    rows=[quote(s,r,t) for s,r,t in zip('ABC',[2,-1,3],times)]
    _,current=build_theme_history(pd.DataFrame(rows),list('ABC'),times[-1],{})
    assert current['eligible_count']==1
    assert current['status']=='INSUFFICIENT DATA'
    assert math.isnan(current['average_return'])


def test_configured_aging_policy_applies_equally_to_basket_history_and_current():
    settings={'data':{'finnhub':{'freshness':{'include_aging_in_current':True}}}}
    rows=[quote('A',2,T-pd.Timedelta(seconds=130)),quote('B',-1)]
    h,current=build_theme_history(pd.DataFrame(rows),list('AB'),T,settings)
    assert current['eligible_count']==2
    assert current['average_return']==pytest.approx(.5)
    assert h.iloc[-1]['up_percent']==50


def test_streamlit_main_refresh_uses_canonical_output(tmp_path,monkeypatch):
    from streamlit.testing.v1 import AppTest
    import app
    store=SnapshotStore(tmp_path/'ui.db')
    rows=history_rows([[1,1,1,-1,-1]]*4)
    store.save_quote_snapshots('2026-10-07',[snapshot_from_row(r) for r in rows])
    monkeypatch.setattr(app,'get_store',lambda:store)
    monkeypatch.setattr(app,'load_themes',lambda:{'Theme':{'tickers':list('ABCDE'),'etf':[]}})
    monkeypatch.setattr(app,'now_et',lambda:T+pd.Timedelta(seconds=20))
    def render():
        import app
        app.main()
    at=AppTest.from_function(render).run(timeout=30)
    assert not at.exception
    momentum=next(d.value for d in at.dataframe if 'Up % Now' in d.value.columns)
    assert momentum.iloc[0]['Up % Now']==fmt_plain(60)
    # New provider cycle, new history, and a zero breadth observation.
    more=[quote(s,-1,T+pd.Timedelta(minutes=5)) for s in 'ABCDE']
    store.save_quote_snapshots('2026-10-07',[snapshot_from_row(r) for r in more])
    monkeypatch.setattr(app,'now_et',lambda:T+pd.Timedelta(minutes=5,seconds=20))
    at.run(timeout=30)
    assert not at.exception
    momentum=next(d.value for d in at.dataframe if 'Up % Now' in d.value.columns)
    assert momentum.iloc[0]['Up % Now']==fmt_plain(0)
    assert momentum.iloc[0]['5m Ago']==fmt_plain(60)
