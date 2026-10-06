"""Logging setup for Sector Radar (spec section 36).

Logs go to logs/sector_radar.log (append) and to the console (WARNING+).
Level controlled by the SECTOR_RADAR_LOG_LEVEL env var (default INFO).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from utils.config import PROJECT_ROOT

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_LOGS = "sector_radar"


def setup_logging() -> logging.Logger:
    logger = logging.getLogger(_LOGS)
    if logger.handlers:
        return logger

    level = getattr(logging, os.environ.get("SECTOR_RADAR_LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger.setLevel(level)

    log_dir = Path(os.environ.get("SECTOR_RADAR_LOG_DIR", str(PROJECT_ROOT / "logs")))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "sector_radar.log", encoding="utf-8")
        file_handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(file_handler)
    except OSError:
        # Logging to file is best-effort; never crash the app over it.
        pass

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    console.setLevel(logging.WARNING)
    logger.addHandler(console)
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return the app logger (or a child logger named ``sector_radar.<name>``)."""
    setup_logging()
    base = logging.getLogger(_LOGS)
    if name and name not in _LOGS:
        child = logging.getLogger(f"{_LOGS}.{name}")
        # propagate to the app logger's handlers
        child.setLevel(base.level)
        return child
    return base
