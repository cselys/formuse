"""
Candidate Score calculation module for stock_scanner V1.2.
Combines Trend Score, Entry Quality, Relative Strength score, and State Quality.
"""

def calculate_candidate_score(
    trend_score: float,
    entry_quality_score: float,
    rs_analysis: dict,
    state: str,
    config: dict
) -> tuple[float, dict]:
    """
    Calculate deterministic Candidate Score (0-100) and its weighted component breakdown.
    Weights default: Trend 45%, Entry Quality 30%, Relative Strength 15%, State Quality 10%.
    """
    weights = config['scoring']['weights']['candidate']
    state_quality_map = config['scoring']['weights']['state_quality']

    w_trend = weights['trend_weight']
    w_entry = weights['entry_quality_weight']
    w_rs = weights['relative_strength_weight']
    w_state = weights['state_quality_weight']

    # Normalize Relative Strength (20d RS) into a 0-100 score
    # rs_20d typically ranges from -15% to +30%. Map 0% to 50, +15% to 80, +30% to 100.
    rs_20 = rs_analysis.get('rs_20d', 0.0)
    rs_score = 50.0 + (rs_20 * 2.5)
    rs_score = max(0.0, min(100.0, rs_score))

    # State Quality score from config map
    state_score = float(state_quality_map.get(state, 50.0))

    # Weighted combination
    candidate_score = (
        (trend_score * w_trend) +
        (entry_quality_score * w_entry) +
        (rs_score * w_rs) +
        (state_score * w_state)
    )

    candidate_score = round(max(0.0, min(100.0, candidate_score)), 1)

    breakdown = {
        'trend_component': round(trend_score * w_trend, 1),
        'entry_quality_component': round(entry_quality_score * w_entry, 1),
        'relative_strength_component': round(rs_score * w_rs, 1),
        'state_quality_component': round(state_score * w_state, 1),
        'rs_normalized_score': round(rs_score, 1),
        'state_score': state_score
    }

    return candidate_score, breakdown
