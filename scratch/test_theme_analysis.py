import sys
sys.path.insert(0, '.')
import sqlite3
import pandas as pd
import numpy as np
import yaml
from collections import Counter

# Load themes config
with open('config/themes.yaml', 'r') as f:
    themes_cfg = yaml.safe_load(f)

# Import scratch/test_matrices.py data logic
from scratch.test_matrices import all_cycles_metrics, all_cycle_ranks, SIGNAL_NAMES, cycles

print("=== REPEATEDLY DISCOVERED THEMES (in Top-10 across >= 5 cycles per signal) ===")
repeated_by_signal = {}
for s in SIGNAL_NAMES:
    counts = Counter()
    for c_ranks in all_cycle_ranks:
        for t in c_ranks[s]:
            counts[t] += 1
    rep = [t for t, c in counts.items() if c >= 5]
    repeated_by_signal[s] = rep
    print(f"  {s}: {rep}")

print("\n=== SIGNAL-SPECIFIC THEMES (themes in Top-10 of ONLY 1 signal across all cycles) ===")
theme_signals_set = {t: set() for t in themes_cfg}
for c_ranks in all_cycle_ranks:
    for s in SIGNAL_NAMES:
        for t in c_ranks[s]:
            theme_signals_set[t].add(s)

signal_specific = {t: list(sigs)[0] for t, sigs in theme_signals_set.items() if len(sigs) == 1}
print(signal_specific)

print("\n=== CONSENSUS THEMES (appearing in Top-10 of >= 3 signals simultaneously in a single cycle) ===")
consensus_by_cycle = []
for c_idx, c_ranks in enumerate(all_cycle_ranks):
    c_counts = Counter()
    for s in SIGNAL_NAMES:
        for t in c_ranks[s]:
            c_counts[t] += 1
    cons = {t: cnt for t, cnt in c_counts.items() if cnt >= 3}
    consensus_by_cycle.append((c_idx+1, cons))
    print(f"Cycle {c_idx+1}: {cons}")

print("\n=== SMALL-SAMPLE THEMES (eligible < 5 stocks) ===")
small_sample_themes = []
for theme_name, t_cfg in themes_cfg.items():
    tickers = t_cfg.get('tickers', [])
    if len(tickers) < 5:
        small_sample_themes.append((theme_name, len(tickers)))
print(small_sample_themes)

print("\n=== DUPLICATE STOCK ASSIGNMENTS & OVERLAP ===")
# Check which tickers appear in multiple themes
ticker_themes = Counter()
for theme_name, t_cfg in themes_cfg.items():
    for t in t_cfg.get('tickers', []):
        ticker_themes[t.strip().upper()] += 1

multi_assigned = {t: cnt for t, cnt in ticker_themes.items() if cnt > 1}
print(f"Total tickers in multiple themes: {len(multi_assigned)}")
print(f"Top multi-assigned tickers: {Counter(multi_assigned).most_common(10)}")

# Find theme pairs with highest Jaccard stock overlap
theme_overlap = []
t_names = list(themes_cfg.keys())
for i in range(len(t_names)):
    for j in range(i+1, len(t_names)):
        t1, t2 = t_names[i], t_names[j]
        set1 = set([x.strip().upper() for x in themes_cfg[t1].get('tickers', [])])
        set2 = set([x.strip().upper() for x in themes_cfg[t2].get('tickers', [])])
        inter = set1 & set2
        union = set1 | set2
        if len(inter) > 0:
            jaccard = len(inter) / len(union)
            theme_overlap.append((t1, t2, len(inter), jaccard, list(inter)))

theme_overlap.sort(key=lambda x: -x[3])
print("\nTop overlapping theme pairs (by Jaccard stock similarity):")
for t1, t2, inter_cnt, jaccard, inter_list in theme_overlap[:10]:
    print(f"  {t1} vs {t2}: shared={inter_cnt} ({inter_list}), Jaccard={jaccard:.2f}")

print("\n=== ETF DIVERGENCE ANALYSIS ===")
# Check if ETF divergence provides useful info beyond stock returns
etf_div_details = []
for c_idx, c_metrics in enumerate(all_cycles_metrics):
    for m in c_metrics:
        for etf_c in m.etf:
            if etf_c.divergence is not None:
                etf_div_details.append({
                    'cycle': c_idx + 1,
                    'theme': m.theme,
                    'etf': etf_c.etf,
                    'etf_return': etf_c.etf_return,
                    'basket_return': etf_c.basket_return,
                    'divergence': etf_c.divergence
                })

df_etf = pd.DataFrame(etf_div_details)
print(f"Total valid ETF comparison points across 9 cycles: {len(df_etf)}")
if len(df_etf) > 0:
    print(f"Mean ETF divergence (abs): {df_etf['divergence'].abs().mean():.2f} pp")
    print(f"Max ETF divergence (abs): {df_etf['divergence'].abs().max():.2f} pp")
    print("Sample ETF divergences:")
    print(df_etf.head(10).to_string())
