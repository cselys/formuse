"""Shared deterministic daily/weekly snapshot calculation for live reports."""
from stock_scanner.src.analysis.daily import run_daily_analysis
from stock_scanner.src.analysis.weekly import run_weekly_analysis
from stock_scanner.src.analysis.relative_strength import calculate_relative_strength
from stock_scanner.src.analysis.regime import classify_state, detect_market_regime
from stock_scanner.src.scoring.trend_score import calculate_trend_score
from stock_scanner.src.scoring.bottom_score import calculate_bottom_score
from stock_scanner.src.scoring.reversal_score import calculate_reversal_score
from stock_scanner.src.scoring.entry_quality import calculate_entry_quality
from stock_scanner.src.scoring.candidate_score import calculate_candidate_score


def analyze_snapshot(daily, weekly, benchmark, market, config):
    _, d = run_daily_analysis(daily, config)
    w = run_weekly_analysis(weekly, config)
    rs = calculate_relative_strength(daily, benchmark, periods=[20, 60])
    structure = d.get('structure', {})
    trend, trend_detail = calculate_trend_score(w, d, structure, rs, config)
    bottom, bottom_detail = calculate_bottom_score(d, structure, rs, daily, config)
    reversal, reversal_detail = calculate_reversal_score(d, w, structure, rs, config)
    entry, entry_detail = calculate_entry_quality(d, structure, config)
    state = classify_state(trend, bottom, reversal, d, w, structure, rs, config)
    candidate, candidate_detail = calculate_candidate_score(trend, entry, rs, state, config)
    regime = detect_market_regime(market)
    return {
        'state': state, 'candidate_score': candidate, 'trend_score': trend,
        'entry_quality': entry, 'bottom_score': bottom, 'reversal_score': reversal,
        'market_regime': regime['regime'], 'market_regime_score': regime['regime_score'],
        'trend_score_breakdown': trend_detail, 'bottom_score_breakdown': bottom_detail,
        'reversal_score_breakdown': reversal_detail, 'entry_quality_details': entry_detail,
        'candidate_score_breakdown': candidate_detail, 'daily': d, 'weekly': w,
        'relative_strength': rs, 'structure': structure,
    }
