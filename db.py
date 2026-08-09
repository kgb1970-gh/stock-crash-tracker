"""SQLite schema + connection helper. One file, no server, good enough for a personal tracker."""

import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickers (
    ticker      TEXT PRIMARY KEY,
    name        TEXT,
    exchange    TEXT,
    asset_type  TEXT,       -- 'stock' | 'etf'
    updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlist (
    ticker           TEXT PRIMARY KEY REFERENCES tickers(ticker),
    entry_date       TEXT NOT NULL,
    entry_price      REAL NOT NULL,
    entry_score      REAL NOT NULL,
    peak_price       REAL NOT NULL,
    peak_rsi         REAL NOT NULL,
    status           TEXT NOT NULL DEFAULT 'watching',  -- watching | short_signal | stale
    last_updated     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS watchlist_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL REFERENCES tickers(ticker),
    date            TEXT NOT NULL,
    price           REAL,
    volume          INTEGER,
    return_z        REAL,
    volume_ratio    REAL,
    rsi             REAL,
    composite_score REAL,
    status_at_time  TEXT,
    UNIQUE(ticker, date)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    alert_type  TEXT NOT NULL,   -- 'entry' | 'short_signal' | 'stale'
    detail      TEXT
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)


if __name__ == "__main__":
    init_db()
    print(f"Initialized {config.DB_PATH}")
