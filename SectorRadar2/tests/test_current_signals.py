import math
import pandas as pd
import pytest
from data.freshness import classify_eligibility, current_signal_policy
from data.snapshot_loader import snapshot_from_row
from data.provider_base import MarketData
from engine.current_signals import current_observation
from engine.sector_engine import build_theme_metrics
from tests.test_theme_alignment import quote, T, history_rows


def settings(age):
    return {'data': {'finnhub': {'freshness': {'current_signal_max_age_seconds': age}}}}


@pytest.mark.parametrize('age,category,eligible', [(59,'FRESH',True),(60,'AGING',True),
    (120,'AGING',True),(179,'AGING',True),(180,'STALE',False),(181,'STALE',False),(-1,'NO_DATA',False)])
def test_current_boundaries(age,category,eligible):
    row=quote('A',2,T-pd.Timedelta(seconds=age),fetched=T+pd.Timedelta(hours=2))
    snap=snapshot_from_row(row,T)
    result=classify_eligibility(snap,current_signal_policy({}))
    assert result.category==category
    assert result.participates_in_current is eligible
    assert current_observation(pd.DataFrame([row]),['A'],T,{})['eligible_count']==int(eligible)


@pytest.mark.parametrize('count',[0,1,2,8])
def test_partial_and_minimum(count):
    rows=[quote(str(i),2,T-pd.Timedelta(seconds=120)) for i in range(count)]
    rows += [quote('9',99,T-pd.Timedelta(seconds=180))]
    x=current_observation(pd.DataFrame(rows),list(map(str,range(10))),T,{})
    assert x['eligible_stocks']==count
    assert x['total_stocks']==10
    assert x['status']==('PASS' if count>=2 else 'INSUFFICIENT DATA')
    if count>=2:
        assert x['average_return']==pytest.approx(2)
        assert x['up_percent']==100
    else:
        assert math.isnan(x['average_return']) and math.isnan(x['up_percent'])
        assert x['valid_stocks']==0


def test_historical_isolation_and_current_operands():
    rows=history_rows([[2,2],[-3,-3],[4,4]])
    rows += [quote('A',-1,T+pd.Timedelta(seconds=120)),quote('B',3,T+pd.Timedelta(seconds=120))]
    cutoff=T+pd.Timedelta(seconds=240)
    md=MarketData('test','5m',cutoff,cutoff,quote_snapshots=pd.DataFrame(rows))
    a=build_theme_metrics('Theme',{'tickers':['A','B']},{},md,settings(60))
    b=build_theme_metrics('Theme',{'tickers':['A','B']},{},md,settings(180))
    pd.testing.assert_frame_equal(a.history,b.history,check_exact=True)
    for key in ('intraday_high','intraday_low','breadth_5m_ago','breadth_15m_ago'):
        av,bv=getattr(a,key),getattr(b,key)
        assert av==bv or (math.isnan(av) and math.isnan(bv))
    assert math.isnan(a.average_return) and math.isnan(a.reversal_from_high)
    assert b.average_return==pytest.approx(1)
    assert b.breadth_now==50
    assert -b.reversal_from_high==pytest.approx(b.intraday_high-b.average_return)
    assert b.recovery_from_low==pytest.approx(b.average_return-b.intraday_low)
    assert b.aging_stocks==2 and b.eligible_stocks==2


def test_current_does_not_expand_historical_extrema():
    rows=history_rows([[1,1],[2,2],[3,3]])
    rows += [quote(s,9,T+pd.Timedelta(seconds=120)) for s in 'AB']
    cutoff=T+pd.Timedelta(seconds=240)
    md=MarketData('test','5m',cutoff,cutoff,quote_snapshots=pd.DataFrame(rows))
    m=build_theme_metrics('Theme',{'tickers':['A','B']},{},md,{})
    assert m.average_return==pytest.approx(9)
    assert m.intraday_high==pytest.approx(3)
    assert m.reversal_from_high==pytest.approx(6) # no clamp or insertion into historical extrema


def test_invalid_and_missing_cutoff():
    rows=pd.DataFrame([quote('A',2,valid=False),quote('B',3)])
    assert current_observation(rows,['A','B'],T,{})['eligible_stocks']==1
    assert current_observation(rows,['A','B'],None,{})['eligible_stocks']==0
