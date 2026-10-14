# CONFIGURATION.md

## Where configuration lives

All configuration is in `config/` and is editable without Python code changes.

### `config/themes.yaml`

Defines the complete theme universe. Each theme has:

- `tickers`: list of tickers (upper-cased, whitespace-trimmed, deduplicated, order-preserving)
- `etf`: optional list of ETF tickers for comparison (must not overlap with `tickers`)
- Theme names are case-sensitive as-written; the UI displays them as-is

**Example**:

```yaml
Semiconductor:
  tickers:
    - NVDA
    - AMD
    - AVGO
  etf:
    - SMH
```

### `config/settings.yaml`

All numeric thresholds and UI settings are here. The sidebar reflects these values and writes them back on every run (via `copy.deepcopy(settings)` + overrides).

#### `data` section

| Key | Default | Description |
|-----|---------|-------------|
| `provider` | `yfinance` | Data provider name |
| `intraday_interval` | `5m` | Bar interval: `5m` or `1m` |
| `refresh_seconds` | `300` | Initial dashboard auto-refresh interval in positive integer seconds |
| `cache_ttl_seconds` | `55` | How long to reuse fresh data (seconds) |
| `retry_count` | `3` | yfinance retry attempts |
| `retry_backoff_seconds` | `2.0` | Backoff multiplier per attempt |
| `stale_warn_minutes` | `20` | Age (min) that triggers "delayed" notice when market is OPEN |

`data.refresh_seconds` initializes the sidebar's **Interval** control. Missing,
null, boolean, string, fractional/floating-point, zero, or negative values fall
back to **300 seconds**. Use an unquoted positive YAML integer, such as `240`.
The standard choices remain 30, 60, 120, 300, and 600 seconds; a valid custom
configured value is added and selected exactly. User selections persist through
normal Streamlit reruns and drive the auto-refresh timer without changing the
YAML file. This setting does not control the collector's cycle interval.

#### `classification` section

| Key | Default | Description |
|-----|---------|-------------|
| `flat_threshold` | `0.10` | `±%` border between UP/DOWN/FLAT |
| `strong_move_threshold` | `1.0` | "Strong" move threshold in % |

#### `state` section

| Key | Default | Description |
|-----|---------|-------------|
| `breadth_threshold` | `60.0` | % needed for TRENDING states |
| `reversal_threshold` | `1.0` | pp giveback for REVERSING_DOWN |
| `recovery_threshold` | `1.0` | pp recovery for RECOVERING_UP |
| `min_history_bars` | `3` | Min bars before momentum/state are trusted |

#### `ui` section

| Key | Default | Description |
|-----|---------|-------------|
| `top_n` | `6` | Rows per ranking panel |
| `time_window_minutes` | `60` | 30 / 60 / 90 / 120 / full day |
| `min_theme_size` | `5` | Valid-stocks floor for rankings panels |
| `show_small_sample_warning` | `True` | Show ⚠️ small when valid < 5 |
| `show_panels` | `{top_up:true, top_down:true, reversals:true, recoveries:true, etf:true}` | Which panels to show |

#### `alerts` section

| Key | Default | Description |
|-----|---------|-------------|
| `breadth_change_5m` | `15.0` | pp change in 5 min → Breakout/Collapse |
| `breadth_change_15m` | `20.0` | pp change in 15 min → Breakout/Collapse |
| `strong_reversal_pp` | `2.0` | pp giveback → Strong Reversal |
| `strong_recovery_pp` | `2.0` | pp recovery → Strong Recovery |

#### `composite` section

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | If `true`, composite score appears in expander |
| `weights.breadth` | `0.40` | Min-max normalized contribution |
| `weights.avg_return` | `0.30` | |
| `weights.median_return` | `0.20` | |
| `weights.volume` | `0.10` | |

### How settings flow

1. `load_settings()` reads `config/settings.yaml`
2. `render_sidebar()` reads UI controls, then `eff = copy.deepcopy(settings)` + overrides
3. `eff` is passed to `run_pipeline()` and used throughout the dashboard
4. The sidebar write-knobs directly modify `eff`; on next run, fresh `load_settings()` + overrides apply

### Example: Changing the reversal threshold

In the sidebar, drag the "Reversal threshold (pp)" slider to `2.5`. The setting is saved to the runtime `eff` dict, and the dashboard immediately reflects the wider threshold (fewer reversals declared).

### How to add a new theme

1. Edit `config/themes.yaml`
2. Add a new top-level key with `tickers` list and optional `etf` list
3. Run `streamlit run app.py` — the new theme appears in all panels and the detail selector immediately
4. No Python code changes required

## Testing configuration changes

```bash
python -m pytest tests/ -q   # 39 tests, no network
streamlit run app.py         # verify dashboard loads with new values
```

## Full config file locations

- `config/themes.yaml`
- `config/settings.yaml`

Both are also available via environment variables (for CI / Docker):

```bash
SECTOR_RADAR_SETTINGS=/path/to/custom_settings.yaml
SECTOR_RADAR_THEMES=/path/to/custom_themes.yaml
SECTOR_RADAR_DB_PATH=/path/to/dbfile.sqlite
SECTOR_RADAR_LOG_LEVEL=DEBUG
SECTOR_RADAR_LOG_DIR=/path/to/logs
```
