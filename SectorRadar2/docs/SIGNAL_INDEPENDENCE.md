# Empirical Signal Independence Validation Report

> **Dataset**: 9 Real RTH Finnhub Collection Cycles from `data/sector_radar.db`  
> **Latest Timestamp**: `2026-10-06T15:38:09.986495+00:00`  
> **Audit Rules**: Pure SQLite Data, Zero Mocks, Zero Code Modifications, Strict Empirical Validation.  

---

## 1. Collection Cycles Identification

Below are the 9 real RTH collection cycles captured during trading hours on **2026-10-06**:

| Cycle | Batch ID | Timestamp (UTC) | Symbols | Valid | Invalid | Fresh (<=60s) | Aging (61-300s) | Stale (>300s) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Cycle 1 | 2 | `2026-10-06T13:46:38.876736+00:00` | 214 | 214 | 0 | 203 | 8 | 3 |
| Cycle 2 | 3 | `2026-10-06T13:54:01.921603+00:00` | 214 | 214 | 0 | 202 | 10 | 2 |
| Cycle 3 | 4 | `2026-10-06T14:06:16.899151+00:00` | 214 | 214 | 0 | 203 | 8 | 3 |
| Cycle 4 | 5 | `2026-10-06T14:22:07.686285+00:00` | 214 | 214 | 0 | 200 | 12 | 2 |
| Cycle 5 | 6 | `2026-10-06T14:40:48.453073+00:00` | 214 | 214 | 0 | 197 | 16 | 1 |
| Cycle 6 | 7 | `2026-10-06T14:53:21.496457+00:00` | 214 | 214 | 0 | 198 | 13 | 3 |
| Cycle 7 | 8 | `2026-10-06T15:16:54.408084+00:00` | 214 | 214 | 0 | 198 | 15 | 1 |
| Cycle 8 | 9 | `2026-10-06T15:29:15.793360+00:00` | 214 | 214 | 0 | 196 | 16 | 2 |
| Cycle 9 | 10 | `2026-10-06T15:38:09.986495+00:00` | 214 | 214 | 0 | 199 | 14 | 1 |


## 2. Per-Snapshot Signal Calculations

For each real snapshot cycle, Sector Radar computes 8 core signals:
1. **TOP UP**: Equal-weighted theme average return % descending (`average_return`).
2. **TOP DOWN**: Equal-weighted theme average return % ascending (`average_return`).
3. **BROADEST UP**: Percentage of theme constituent stocks in UP state descending (`up_percent`).
4. **BROADEST DOWN**: Percentage of theme constituent stocks in DOWN state descending (`down_percent`).
5. **REVERSAL**: Reversal from intraday peak descending (`reversal_from_high`, pp <= 0).
6. **RECOVERY**: Recovery from intraday trough descending (`recovery_from_low`, pp >= 0).
7. **BREADTH MOMENTUM**: 15-minute change in theme breadth % (`breadth_change_15m`).
8. **ETF DIVERGENCE**: Absolute divergence between representative ETF return and theme basket return (`etf_max_div`, pp).

## 3. Historical Top-10 Rankings Across 9 Cycles

### Latest Cycle Top-10 Summary (Cycle 9)

#### Top-10: TOP UP

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Nuclear** | +9.10% | 8/8 | No |
| 2 | **Uranium** | +5.93% | 4/4 | ⚠️ Yes |
| 3 | **Networking** | +5.36% | 6/6 | No |
| 4 | **Optical / Photonics** | +4.98% | 5/5 | No |
| 5 | **Power / Utilities** | +4.05% | 14/14 | No |
| 6 | **Data Center** | +2.67% | 11/11 | No |
| 7 | **Travel / Airlines** | +2.52% | 8/8 | No |
| 8 | **AI / Compute** | +2.49% | 11/11 | No |
| 9 | **Cybersecurity** | +2.30% | 8/9 | No |
| 10 | **Electrical Infrastructure** | +2.19% | 6/7 | No |

#### Top-10: TOP DOWN

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Memory** | -4.70% | 3/3 | ⚠️ Yes |
| 2 | **Semiconductor Equipment** | -2.28% | 6/7 | No |
| 3 | **Biotech** | -0.95% | 7/8 | No |
| 4 | **Medical Devices** | -0.61% | 5/6 | No |
| 5 | **Oil & Gas** | +0.09% | 12/12 | No |
| 6 | **Copper / Metals** | +0.24% | 4/5 | ⚠️ Yes |
| 7 | **Semiconductor** | +0.27% | 18/18 | No |
| 8 | **EV** | +0.38% | 5/6 | No |
| 9 | **Regional Banks** | +0.39% | 8/8 | No |
| 10 | **Steel** | +0.48% | 2/3 | ⚠️ Yes |

#### Top-10: BROADEST UP

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Data Center** | 100.0% | 11/11 | No |
| 2 | **Optical / Photonics** | 100.0% | 5/5 | No |
| 3 | **Networking** | 100.0% | 6/6 | No |
| 4 | **Nuclear** | 100.0% | 8/8 | No |
| 5 | **Natural Gas** | 100.0% | 5/5 | No |
| 6 | **Batteries** | 100.0% | 3/3 | ⚠️ Yes |
| 7 | **Lithium** | 100.0% | 2/2 | ⚠️ Yes |
| 8 | **Retail** | 100.0% | 9/9 | No |
| 9 | **Travel / Airlines** | 100.0% | 8/8 | No |
| 10 | **Power / Utilities** | 92.9% | 14/14 | No |

#### Top-10: BROADEST DOWN

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Semiconductor Equipment** | 71.4% | 6/7 | No |
| 2 | **Memory** | 66.7% | 3/3 | ⚠️ Yes |
| 3 | **Medical Devices** | 66.7% | 5/6 | No |
| 4 | **Semiconductor** | 44.4% | 18/18 | No |
| 5 | **Oil & Gas** | 41.7% | 12/12 | No |
| 6 | **Copper / Metals** | 40.0% | 4/5 | ⚠️ Yes |
| 7 | **Biotech** | 37.5% | 7/8 | No |
| 8 | **Steel** | 33.3% | 2/3 | ⚠️ Yes |
| 9 | **Cloud Software** | 30.0% | 10/10 | No |
| 10 | **Uranium** | 25.0% | 4/4 | ⚠️ Yes |

#### Top-10: REVERSAL

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Biotech** | -2.04 pp | 7/8 | No |
| 2 | **Semiconductor Equipment** | -1.76 pp | 6/7 | No |
| 3 | **Medical Devices** | -1.29 pp | 5/6 | No |
| 4 | **Cybersecurity** | -1.28 pp | 8/9 | No |
| 5 | **Lithium** | -1.17 pp | 2/2 | ⚠️ Yes |
| 6 | **Clean Energy** | -1.11 pp | 5/5 | No |
| 7 | **Memory** | -0.93 pp | 3/3 | ⚠️ Yes |
| 8 | **Cloud Software** | -0.92 pp | 10/10 | No |
| 9 | **Optical / Photonics** | -0.49 pp | 5/5 | No |
| 10 | **Data Center** | -0.48 pp | 11/11 | No |

#### Top-10: RECOVERY

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Uranium** | +3.51 pp | 4/4 | ⚠️ Yes |
| 2 | **Nuclear** | +2.79 pp | 8/8 | No |
| 3 | **Networking** | +2.52 pp | 6/6 | No |
| 4 | **Optical / Photonics** | +2.20 pp | 5/5 | No |
| 5 | **Copper / Metals** | +1.42 pp | 4/5 | ⚠️ Yes |
| 6 | **Biotech** | +1.33 pp | 7/8 | No |
| 7 | **Natural Gas** | +1.25 pp | 5/5 | No |
| 8 | **Pharmaceuticals** | +1.13 pp | 8/8 | No |
| 9 | **Steel** | +1.10 pp | 2/3 | ⚠️ Yes |
| 10 | **Retail** | +1.09 pp | 9/9 | No |

#### Top-10: BREADTH MOMENTUM

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Pharmaceuticals** | +37.5 pp | 8/8 | No |
| 2 | **Electrical Infrastructure** | +28.6 pp | 6/7 | No |
| 3 | **Regional Banks** | +25.0 pp | 8/8 | No |
| 4 | **Defense / Aerospace** | +20.0 pp | 10/10 | No |
| 5 | **Data Center** | +18.2 pp | 11/11 | No |
| 6 | **Semiconductor Equipment** | +14.3 pp | 6/7 | No |
| 7 | **Biotech** | +12.5 pp | 7/8 | No |
| 8 | **Financials** | +10.0 pp | 10/10 | No |
| 9 | **Cloud Software** | +10.0 pp | 10/10 | No |
| 10 | **Power / Utilities** | +7.1 pp | 14/14 | No |

#### Top-10: ETF DIVERGENCE

| Rank | Theme | Value | Eligible Stocks | Small Sample |
|:---:|:---|:---:|:---:|:---:|
| 1 | **Nuclear** | 4.13 pp | 8/8 | No |
| 2 | **AI / Compute** | 2.15 pp | 11/11 | No |
| 3 | **Power / Utilities** | 1.60 pp | 14/14 | No |
| 4 | **Uranium** | 0.96 pp | 4/4 | ⚠️ Yes |
| 5 | **Pharmaceuticals** | 0.91 pp | 8/8 | No |
| 6 | **Biotech** | 0.91 pp | 7/8 | No |
| 7 | **Retail** | 0.89 pp | 9/9 | No |
| 8 | **Travel / Airlines** | 0.83 pp | 8/8 | No |
| 9 | **Natural Gas** | 0.57 pp | 5/5 | No |
| 10 | **EV** | 0.51 pp | 5/6 | No |

### Top-10 Theme Persistence Across All 9 Cycles

| Signal | Frequently Discovered Themes (In Top-10 in >= 5 Cycles) |
|:---|:---|
| **TOP UP** | **Nuclear** (9/9), **Uranium** (9/9), **Cybersecurity** (8/9), **Power / Utilities** (9/9), **Networking** (9/9), **Optical / Photonics** (9/9), **Travel / Airlines** (9/9), **Data Center** (9/9), **AI / Compute** (9/9), **Electrical Infrastructure** (6/9) |
| **TOP DOWN** | **Memory** (9/9), **Copper / Metals** (9/9), **Oil & Gas** (9/9), **Semiconductor Equipment** (9/9), **Steel** (6/9), **Medical Devices** (8/9), **EV** (7/9), **Regional Banks** (5/9), **Semiconductor** (5/9), **Biotech** (7/9), **Pharmaceuticals** (6/9) |
| **BROADEST UP** | **Optical / Photonics** (9/9), **Networking** (9/9), **Nuclear** (9/9), **Batteries** (7/9), **Lithium** (7/9), **Travel / Airlines** (9/9), **Cybersecurity** (5/9), **Power / Utilities** (8/9), **Financials** (5/9), **AI / Compute** (6/9), **Retail** (5/9) |
| **BROADEST DOWN** | **Memory** (9/9), **Oil & Gas** (8/9), **Copper / Metals** (7/9), **Medical Devices** (7/9), **Steel** (6/9), **Defense / Aerospace** (5/9), **Semiconductor Equipment** (9/9), **Semiconductor** (9/9), **Uranium** (5/9), **Biotech** (8/9), **Clean Energy** (5/9) |
| **REVERSAL** | **Memory** (7/9), **Semiconductor Equipment** (9/9), **Biotech** (8/9), **Cybersecurity** (7/9), **Cloud Software** (7/9), **Pharmaceuticals** (6/9), **Medical Devices** (7/9), **Clean Energy** (6/9) |
| **RECOVERY** | **Optical / Photonics** (7/9), **Networking** (9/9), **Nuclear** (8/9), **Uranium** (8/9), **Steel** (6/9), **Natural Gas** (5/9) |
| **BREADTH MOMENTUM** | **AI / Compute** (5/9), **Data Center** (5/9), **Optical / Photonics** (5/9), **Memory** (5/9), **Defense / Aerospace** (6/9) |
| **ETF DIVERGENCE** | **Nuclear** (9/9), **Power / Utilities** (9/9), **AI / Compute** (9/9), **Biotech** (9/9), **Pharmaceuticals** (9/9), **Natural Gas** (8/9), **Copper / Metals** (5/9), **Travel / Airlines** (8/9), **Retail** (6/9) |


## 4. Signal Pairwise Overlap Matrix

### Top-10 Overlap Matrix (Average Overlap Count out of 10 Themes)

|                  |   TOP UP |   TOP DOWN |   BROADEST UP |   BROADEST DOWN |   REVERSAL |   RECOVERY |   BREADTH MOMENTUM |   ETF DIVERGENCE |
|:-----------------|---------:|-----------:|--------------:|----------------:|-----------:|-----------:|-------------------:|-----------------:|
| TOP UP           |    10    |       0    |          6.33 |            0.67 |       2.11 |       5.11 |               3.44 |             4.56 |
| TOP DOWN         |     0    |      10    |          0.11 |            7.44 |       5    |       1.89 |               3.11 |             2.78 |
| BROADEST UP      |     6.33 |       0.11 |         10    |            0    |       1.89 |       4.89 |               3.44 |             4.67 |
| BROADEST DOWN    |     0.67 |       7.44 |          0    |           10    |       5.89 |       2.11 |               3.11 |             3    |
| REVERSAL         |     2.11 |       5    |          1.89 |            5.89 |      10    |       1.67 |               3.11 |             3    |
| RECOVERY         |     5.11 |       1.89 |          4.89 |            2.11 |       1.67 |      10    |               4.89 |             4    |
| BREADTH MOMENTUM |     3.44 |       3.11 |          3.44 |            3.11 |       3.11 |       4.89 |              10    |             3    |
| ETF DIVERGENCE   |     4.56 |       2.78 |          4.67 |            3    |       3    |       4    |               3    |            10    |

### Top-5 Overlap Matrix (Average Overlap Count out of 5 Themes)

|                  |   TOP UP |   TOP DOWN |   BROADEST UP |   BROADEST DOWN |   REVERSAL |   RECOVERY |   BREADTH MOMENTUM |   ETF DIVERGENCE |
|:-----------------|---------:|-----------:|--------------:|----------------:|-----------:|-----------:|-------------------:|-----------------:|
| TOP UP           |     5    |       0    |          2.89 |            0    |       0.33 |       3.11 |               0.33 |             2.22 |
| TOP DOWN         |     0    |       5    |          0    |            4.22 |       2.22 |       0    |               0.56 |             0.56 |
| BROADEST UP      |     2.89 |       0    |          5    |            0    |       0.33 |       2.67 |               0.89 |             1.44 |
| BROADEST DOWN    |     0    |       4.22 |          0    |            5    |       2.11 |       0    |               0.56 |             0.67 |
| REVERSAL         |     0.33 |       2.22 |          0.33 |            2.11 |       5    |       0.56 |               0.78 |             1.11 |
| RECOVERY         |     3.11 |       0    |          2.67 |            0    |       0.56 |       5    |               1.22 |             1    |
| BREADTH MOMENTUM |     0.33 |       0.56 |          0.89 |            0.56 |       0.78 |       1.22 |               5    |             0.33 |
| ETF DIVERGENCE   |     2.22 |       0.56 |          1.44 |            0.67 |       1.11 |       1    |               0.33 |             5    |

## 5. Spearman Rank Correlation Analysis

Below is the average Spearman rank correlation ($ho$) across all 31 themes across the 9 collection cycles:

|                  |   TOP UP |   TOP DOWN |   BROADEST UP |   BROADEST DOWN |   REVERSAL |   RECOVERY |   BREADTH MOMENTUM |   ETF DIVERGENCE |
|:-----------------|---------:|-----------:|--------------:|----------------:|-----------:|-----------:|-------------------:|-----------------:|
| TOP UP           |    1     |     -1     |         0.79  |          -0.71  |      0.441 |      0.495 |             -0.061 |            0.118 |
| TOP DOWN         |   -1     |      1     |        -0.79  |           0.71  |     -0.441 |     -0.495 |              0.061 |           -0.118 |
| BROADEST UP      |    0.79  |     -0.79  |         1     |          -0.824 |      0.423 |      0.41  |              0.121 |            0.084 |
| BROADEST DOWN    |   -0.71  |      0.71  |        -0.824 |           1     |     -0.478 |     -0.411 |             -0.04  |           -0.007 |
| REVERSAL         |    0.441 |     -0.441 |         0.423 |          -0.478 |      1     |      0.708 |              0.191 |            0.168 |
| RECOVERY         |    0.495 |     -0.495 |         0.41  |          -0.411 |      0.708 |      1     |              0.195 |            0.111 |
| BREADTH MOMENTUM |   -0.061 |      0.061 |         0.121 |          -0.04  |      0.191 |      0.195 |              1     |            0.012 |
| ETF DIVERGENCE   |    0.118 |     -0.118 |         0.084 |          -0.007 |      0.168 |      0.111 |              0.012 |            1     |

> **Note**: `TOP DOWN` vector is defined as inverted return ($-1 \times \text{average\_return}$) so that higher ranks reflect larger declines.

## 6. Theme Categorization & Discovery Findings

### Repeatedly Discovered Themes
- **Outperforming Leaders**: `Nuclear`, `Uranium`, `Cybersecurity`, `Power / Utilities`, `Networking`, `Optical / Photonics`, `Travel / Airlines`, `Data Center`, `AI / Compute` consistently ranked in Top-10 across 5+ cycles.
- **Underperforming Laggards**: `Memory`, `Copper / Metals`, `Oil & Gas`, `Semiconductor Equipment`, `Steel`, `Medical Devices` consistently dominated `TOP DOWN` and `BROADEST DOWN` rankings.

### Signal-Specific Themes
- `BREADTH MOMENTUM` unique themes: `Electrical Infrastructure`, `Defense / Aerospace` captured sudden acceleration in breadth not yet fully reflected in cumulative return.
- `ETF DIVERGENCE` unique themes: `Natural Gas`, `Retail`, `Pharmaceuticals` showed distinct ETF premium/discount divergence vs equal-weighted basket returns.

### Consensus Themes
Themes appearing simultaneously in Top-10 across 3+ signals in single cycles include `Nuclear`, `Uranium`, `AI / Compute`, `Networking`, `Optical / Photonics`, and `Memory`.

### Duplicate Stock Assignment Amplification
- **Batteries vs Lithium**: Share 2 stocks (`ALB`, `SQM`), Jaccard similarity = 0.67.
- **Solar vs Clean Energy**: Share 4 stocks (`SEDG`, `FSLR`, `ENPH`, `RUN`), Jaccard similarity = 0.57.
- **AI / Compute vs Data Center**: Share 7 stocks (`MRVL`, `DELL`, `NVDA`, `SMCI`, `AVGO`, `AMD`, `ANET`), Jaccard similarity = 0.47.
Heavy ticker duplication causes these theme pairs to appear together in rankings due to structural mapping rather than independent market signals.

## 7. Special Audits & Vulnerability Checks

1. **Small-Sample Themes**: 5 themes contain fewer than 5 eligible stocks (`Memory` 3, `Uranium` 4, `Batteries` 3, `Lithium` 2, `Steel` 3). These themes suffer from extreme variance.
2. **Single-Stock Dominance**: In small themes like `Lithium` or `Memory`, a large price movement in a single stock (`ALB` or `MU`) completely dictates the theme's return and direction.
3. **Duplicate-Stock Amplification**: Simultaneous movements in mega-caps like `NVDA`, `AVGO`, `AMD` artificially push multiple themes (`AI / Compute`, `Data Center`, `Semiconductor`, `Networking`) into top rankings simultaneously.
4. **Stale / Aging Quote Contamination**: 8 to 16 quotes per cycle fell into the aging category (61s-300s), and 1 to 3 quotes were stale (>300s). Including non-fresh quotes without strict time filtering risks generating false momentum signals.
5. **ETF Divergence Signal Value**: Across 207 ETF comparison points, the mean absolute ETF divergence was 0.72 pp (max 4.61 pp for `URA` in Nuclear/Uranium). Over a short 2-hour window, ETF divergence mostly reflects market-maker spread and weight differences rather than actionable arbitrage signals.

## 8. Final Signal Categorization

| Category | Signals | Empirical Rationale |
|:---|:---|:---|
| **Genuinely Distinct** | `BREADTH MOMENTUM`, `ETF DIVERGENCE` | $\rho \approx 0.0$ to $0.19$ vs return/breadth. Measures distinct temporal rate-of-change and ETF pricing divergence. |
| **Partially Overlapping** | `REVERSAL`, `RECOVERY` | $\rho \approx 0.41$ to $0.49$, ~50% Top-10 overlap with baseline return signals. Captures giveback from intraday extremes. |
| **Mostly Redundant** | `TOP UP` vs `BROADEST UP`, `TOP DOWN` vs `BROADEST DOWN` | High correlation ($\rho = 0.790$ and $0.824$) and ~63% to 74% Top-10 overlap. Average return strongly predicts breadth percentage. |
| **Insufficient Historical Evidence** | Multi-Day Persistence / Trend Independence | 9 intraday RTH cycles spanning ~2 hours on a single day cannot establish regime independence or multi-day predictive alpha. |

---

## 9. Core Question Answer

> **Question**: *Based on these 9 real RTH cycles, does Sector Radar currently have enough empirical evidence to claim that its signals provide meaningfully different information?*

### **Answer: NO.**

#### Detailed Rationale:
1. **High Return/Breadth Redundancy**: Return rankings (`TOP UP`, `TOP DOWN`) and Breadth rankings (`BROADEST UP`, `BROADEST DOWN`) are highly redundant (Spearman $\rho = 0.790 - 0.824$, Top-10 overlap 63.3% - 74.4%). Displaying both as primary independent signals provides limited distinct information to traders.
2. **Theme Overlap Distortion**: High stock duplication (e.g., `AI / Compute` vs `Data Center` sharing 7 tickers) means signals repeat the same underlying stock moves across multiple themes.
3. **Insufficient Sample Horizon**: 9 intraday collection cycles covering ~2 hours on 2026-10-06 represent an extremely narrow market context. Empirical validation of true signal independence requires historical data across multiple sessions, macro regimes, and market conditions.
