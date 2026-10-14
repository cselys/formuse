"""SQLite persistence for intraday snapshots (spec sections 25, 26).

Stores theme-level and stock-level snapshots at every refresh so the V2
research module can later answer questions like:

    "When Semiconductor had Up% > 80, Avg Return > +2% and breadth
    momentum > +15 pp, what happened over the next 5/15/30/60 minutes?"

The store is a thin wrapper over the stdlib ``sqlite3`` module — no ORM.

Additive table (Finnhub migration, Phase 1): ``quote_snapshots`` retains
provider_timestamp, fetched_at and data_age_seconds per symbol so the engine
can distinguish network latency from market-data freshness and detect stale /
incomplete themes from history.
"""
from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Iterable, List, Optional

import pandas as pd

from models.schemas import StockSnapshot, ThemeMetrics
from utils.logging import get_logger

logger = get_logger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sector_snapshots (
    session_date TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    theme        TEXT NOT NULL,
    total_stocks INTEGER,
    up_stocks    INTEGER,
    down_stocks  INTEGER,
    flat_stocks  INTEGER,
    up_percent   REAL,
    down_percent REAL,
    average_return REAL,
    median_return REAL,
    average_change_from_open REAL,
    intraday_high REAL,
    intraday_low  REAL,
    breadth      REAL,
    state        TEXT,
    PRIMARY KEY (timestamp, theme)
);
CREATE TABLE IF NOT EXISTS stock_snapshots (
    session_date TEXT NOT NULL,
    timestamp    TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    price        REAL,
    previous_close REAL,
    today_open   REAL,
    change_vs_close REAL,
    change_vs_open  REAL,
    volume       INTEGER,
    intraday_high REAL,
    intraday_low  REAL,
    PRIMARY KEY (timestamp, symbol)
);
CREATE INDEX IF NOT EXISTS idx_sector_theme ON sector_snapshots (theme, session_date);
CREATE INDEX IF NOT EXISTS idx_stock_symbol ON stock_snapshots (symbol, session_date);
CREATE TABLE IF NOT EXISTS quote_snapshots (
    symbol            TEXT NOT NULL,
    session_date      TEXT NOT NULL,
    provider_timestamp REAL,
    fetched_at        TEXT NOT NULL,
    data_age_seconds  REAL,
    source            TEXT NOT NULL,
    price             REAL,
    previous_close    REAL,
    today_open        REAL,
    intraday_high     REAL,
    intraday_low      REAL,
    volume            INTEGER,
    is_valid          INTEGER,
    issue             TEXT,
    PRIMARY KEY (symbol, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_quote_symbol ON quote_snapshots (symbol, session_date);
CREATE INDEX IF NOT EXISTS idx_quote_session ON quote_snapshots (session_date);
"""


class SnapshotStore:
    """Read/write snapshot history in a local SQLite database."""

    def __init__(self, db_path: str | Path = "data/sector_radar.db"):
        self.db_path = Path(db_path)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        with closing(self._connect()) as conn:
            conn.executescript(_SCHEMA)

    # ------------------------------------------------------------------ io
    def _connect(self):
        import sqlite3
        return sqlite3.connect(str(self.db_path), timeout=30)

    def save_snapshots(self, session_date: str,
                       theme_metrics: Iterable[ThemeMetrics],
                       stock_snapshots: Iterable[StockSnapshot]) -> int:
        """Upsert the latest snapshot for every theme and stock. Returns row count."""
        sector_rows = []
        for m in theme_metrics:
            sector_rows.append((
                session_date, m.timestamp, m.theme,
                m.total_stocks, m.up_stocks, m.down_stocks, m.flat_stocks,
                m.up_percent, m.down_percent,
                m.average_return, m.median_return, m.average_change_from_open,
                m.intraday_high, m.intraday_low,
                m.breadth_now, m.state,
            ))
        stock_rows = []
        for s in stock_snapshots:
            stock_rows.append((
                session_date, s.timestamp, s.symbol,
                s.current_price, s.previous_close, s.today_open,
                s.change_vs_previous_close, s.change_vs_open,
                s.volume, s.intraday_high, s.intraday_low,
            ))
        with closing(self._connect()) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO sector_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                sector_rows,
            )
            conn.executemany(
                "INSERT OR REPLACE INTO stock_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                stock_rows,
            )
            conn.commit()
        logger.debug("saved %d sector + %d stock snapshot rows to %s",
                     len(sector_rows), len(stock_rows), self.db_path)
        return len(sector_rows) + len(stock_rows)

    # ------------------------------------------------------------------ read
    def load_sector_history(self, theme: str, session_date: Optional[str] = None) -> pd.DataFrame:
        q = "SELECT * FROM sector_snapshots WHERE theme = ?"
        args: list = [theme]
        if session_date:
            q += " AND session_date = ?"
            args.append(session_date)
        q += " ORDER BY timestamp"
        with closing(self._connect()) as conn:
            return pd.read_sql_query(q, conn, params=args)

    def session_quote_snapshots(self, session_date: str) -> pd.DataFrame:
        """One SQLite read snapshot for both current metrics and history."""
        with closing(self._connect()) as conn:
            return pd.read_sql_query(
                "SELECT * FROM quote_snapshots WHERE session_date = ? "
                "ORDER BY fetched_at, symbol", conn, params=[session_date])

    def load_stock_history(self, symbol: str, session_date: Optional[str] = None) -> pd.DataFrame:
        q = "SELECT * FROM stock_snapshots WHERE symbol = ?"
        args: list = [symbol]
        if session_date:
            q += " AND session_date = ?"
            args.append(session_date)
        q += " ORDER BY timestamp"
        with closing(self._connect()) as conn:
            return pd.read_sql_query(q, conn, params=args)

    def recent_sessions(self, limit: int = 5) -> List[str]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT DISTINCT session_date FROM sector_snapshots "
                "ORDER BY session_date DESC LIMIT ?", (limit,)
            ).fetchall()
        return [r[0] for r in rows]

    # --------------------------------------------------------------- quotes
    def save_quote_snapshots(self, session_date: str,
                             snapshots: List[StockSnapshot]) -> int:
        """Persist per-symbol quote snapshots from a collector cycle.

        ``snapshots`` are the valid quotes produced by the collector this cycle.
        Failed/rate-limited symbols are tracked in the cycle summary (not the DB)
        so staleness/coverage can be computed from history in Phase 2.
        Returns the number of rows inserted.
        """
        rows = []
        for s in snapshots:
            rows.append((
                s.symbol,
                session_date,
                s.provider_timestamp,
                s.fetched_at,
                s.data_age_seconds,
                "finnhub",
                s.current_price,
                s.previous_close,
                s.today_open,
                s.intraday_high,
                s.intraday_low,
                s.volume,
                1 if s.is_valid else 0,
                s.issue,
            ))
        if not rows:
            logger.debug("no quote snapshots to persist for %s", session_date)
            return 0
        with closing(self._connect()) as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO quote_snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
        logger.debug("saved %d quote snapshot rows to %s (session %s)",
                     len(rows), self.db_path, session_date)
        return len(rows)

    def latest_quote_snapshots(self, session_date: Optional[str] = None) -> pd.DataFrame:
        """Latest quote snapshot per symbol (one row per symbol, most recent).

        Returns a DataFrame with the same columns as quote_snapshots, suitable
        for feeding the Phase-2 theme engine (valid/metadata fields, freshness,
        and per-symbol issue flags for staleness detection).
        """
        q_wl = (
            "SELECT symbol, session_date, provider_timestamp, fetched_at, data_age_seconds,"
            " source, price, previous_close, today_open, intraday_high, intraday_low,"
            " volume, is_valid, issue FROM ("
            "   SELECT *, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY fetched_at DESC) AS rn"
            "   FROM quote_snapshots"
        )
        if session_date:
            q_wl += " WHERE session_date = ?"
        q_wl += " ) t WHERE t.rn = 1 ORDER BY symbol"
        with closing(self._connect()) as conn:
            return pd.read_sql_query(q_wl, conn, params=(session_date,) if session_date else ())

    def quote_history(self, symbol: str, session_date: Optional[str] = None) -> pd.DataFrame:
        """All quote snapshots for one symbol, ordered by fetch time."""
        q = "SELECT * FROM quote_snapshots WHERE symbol = ?"
        args: list = [symbol]
        if session_date:
            q += " AND session_date = ?"
            args.append(session_date)
        q += " ORDER BY fetched_at"
        with closing(self._connect()) as conn:
            return pd.read_sql_query(q, conn, params=args)
