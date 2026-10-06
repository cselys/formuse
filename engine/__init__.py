"""Calculation engines — pure functions of the data, no I/O, no Streamlit.

price_engine      : per-stock metrics (spec section 8)
breadth_engine    : theme breadth aggregation (spec sections 9-11)
reversal_engine   : intraday high/low, reversal, recovery, state (spec 12-14)
sector_engine     : per-theme orchestration
ranking_engine    : rankings + optional composite score (spec 15-16)
alerts            : simple cross-refresh alert detection (spec 27)
"""
