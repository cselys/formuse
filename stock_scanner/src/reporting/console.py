"""
Console reporting for stock_scanner V1.2.
Displays formatted sections for each market state, top ranked candidates, and key V1.2 metrics.
"""

from stock_scanner.src.reporting.state_breakdown import StateBreakdown, render_state_terminal


def display_console_report(results: list[dict], top_n: int = None, state_breakdown=None):
    """
    Print formatted console report grouped by state and top candidates by candidate score.
    """
    if not results:
        print("\nNo scan results to display.")
        return

    # 1. Display Top Candidates Ranked by Candidate Score
    sorted_candidates = sorted(results, key=lambda x: x.get('candidate_score', 0), reverse=True)
    top_display = sorted_candidates[:10] if not top_n else sorted_candidates[:top_n]

    print("\n" + "=" * 110)
    print(" " * 38 + f"STOCK SCANNER V{results[0].get('scanner_version', '1.2')} â€” TOP CANDIDATES")
    print("=" * 110)
    print(f"{'Rank':<5} {'Symbol':<8} {'Cat':<15} {'State':<18} {'CandScore':<10} {'Trend':<7} {'EntryQ':<7} {'RS(20d)':<9} {'Regime':<15}")
    print("-" * 110)

    for idx, r in enumerate(top_display, 1):
        sym = r.get('symbol', '')
        cat = r.get('category', '')
        state = r.get('state', '')
        cand_score = r.get('candidate_score', 0)
        trend = r.get('trend_score', 0)
        entry_q = r.get('entry_quality', r.get('setup_quality', 0))
        rs_20 = r.get('relative_strength', {}).get('rs_20d', 0.0)
        regime = r.get('market_regime', 'NEUTRAL')

        print(f"{idx:<5} {sym:<8} {cat:<15} {state:<18} {cand_score:<10.1f} {trend:<7.1f} {entry_q:<7.1f} {rs_20:<+9.1f}% {regime:<15}")

    model = state_breakdown if state_breakdown is not None else StateBreakdown(results, top_n)
    print(render_state_terminal(model))
