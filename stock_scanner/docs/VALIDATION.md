# Stock Scanner V1.2 — Validation & Scientific Contract

## 1. Lookahead Rules
- Every indicator and signal must be computed using information available strictly up to the scan date `as_of_date`.
- Future bars, future swing points, and future benchmark prices are strictly prohibited.

---

## 2. Weekly Candle Handling
- Weekly bars are resampled via `resample_to_weekly(df_daily, as_of_date=..., drop_partial=True)`.
- Incomplete current partial weeks are dropped in historical evaluations to prevent lookahead bias.

---

## 3. Historical Evaluation Methodology
- Evaluates historical signals across multiple past trading dates against forward returns (+1D, +5D, +10D, +20D).
- Tracks win rates, averages, medians, and distribution percentiles across states, score buckets, and entry quality tiers.

---

## 4. Versioning & Baselines
- **V1.1**: Baseline deterministic scanner with Trend Score, Bottom Score, Reversal Score, and state classification.
- **V1.2**: Evidence-based upgrade introducing Entry Quality, Candidate Score, Market Regime, and flexible volume confirmation windows for Bottom Breakout.

---

## 5. Paper-Validation Safety Boundary
- **Does NOT place trades**.
- **Does NOT submit orders**.
- **Does NOT connect to intraday engines**.
- **Produces research/scanning signals only**.
