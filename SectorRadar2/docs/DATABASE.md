# DATABASE.md

## SQLite persistence (spec sections 25-26)

The application persists intraday snapshots in a local SQLite database for V2 research purposes.

### Database location

- Default: `data/sector_radar.db`
- Path configurable via env var: `SECTOR_RADAR_DB_PATH`
- Directory is created if it does not exist

### Tables

#### `sector_snapshots`

| Column | Type | Constraints |
|---------|------|-------------|
| `session_date` | `TEXT` | NOT NULL — ET date of the snapshot |
| `timestamp` | `TEXT` | NOT NULL — ISO-8601 time of the snapshot (e.g. `2026-10-02T15:55:00-04:00`) |
| `theme` | `TEXT` | NOT NULL — theme name |
| `total_stocks` | `INTEGER` | Number of configured tickers for the theme |
| `up_stocks` | `INTEGER` | Valid stocks with `change_vs_previous_close > flat_threshold` |
| `down_stocks` | `INTEGER` | Valid stocks with `change_vs_previous_close < -flat_threshold` |
| `flat_stocks` | `INTEGER` | Valid stocks within `+/-flat_threshold` |
| `up_percent` | `REAL` | `up_stocks / valid_stocks * 100` |
| `down_percent` | `REAL` | `down_stocks / valid_stocks * 100` |
| `average_return` | `REAL` | Mean `change_vs_previous_close` across valid stocks |
| `median_return` | `REAL` | Median `change_vs_previous_close` across valid stocks |
| `average_change_from_open` | `REAL` | Mean `change_vs_open` across valid stocks with data |
| `intraday_high` | `REAL` | Max theme avg return across session history |
| `intraday_low` | `REAL` | Min theme avg return across session history |
| `breadth` | `REAL` | Current `up_percent` value |
| `state` | `TEXT` | Theme state (TRENDING_UP, TRENDING_DOWN, REVERSING_DOWN, RECOVERING_UP, MIXED) |
| `PRIMARY KEY` | `(timestamp, theme)` | Same timestamp/theme replaces previous row |

#### `stock_snapshots`

| Column | Type | Constraints |
|---------|------|-------------|
| `session_date` | `TEXT` | NOT NULL |
| `timestamp` | `TEXT` | NOT NULL |
| `symbol` | `TEXT` | NOT NULL |
| `price` | `REAL` | Current price |
| `previous_close` | `REAL` | Previous close |
| `today_open` | `REAL` | Today's open |
| `change_vs_close` | `REAL` | `price - previous_close) / previous_close * 100` |
| `change_vs_open` | `REAL` | `(price - today_open) / today_open * 100` |
| `volume` | `INTEGER` | Session volume total |
| `intraday_high` | `REAL` | Session high |
| `intraday_low` | `REAL` | Session low |
| `PRIMARY KEY` | `(timestamp, symbol)` | |
| `INDEX` | `(symbol, session_date)` | |

### Snapshot behavior

- `save_snapshots(session_date, theme_metrics, stock_snapshots)` — INSERT OR REPLACE on primary keys
- One row per theme per timestamp; same timestamp/theme replaces previous
- One row per symbol per timestamp; same timestamp/symbol replaces previous
- `session_date` is the ET date from `md.asof.date()` (or current ET date if `md.asof` is `None`)
- Snapshots are taken on every refresh cycle

### Queries (V2 research)

```sql
-- Session history for a single theme
SELECT * FROM sector_snapshots WHERE theme = 'Semiconductor' AND session_date = '2026-10-02';

-- All snapshots for a single symbol
SELECT * FROM stock_snapshots WHERE symbol = 'NVDA' ORDER BY timestamp;

-- Recent sessions
SELECT DISTINCT session_date FROM sector_snapshots ORDER BY session_date DESC LIMIT 5;
```