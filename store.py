"""CSV-backed storage. Swapped in for SQLite -- at this data scale (thousands of
tickers, a watchlist of dozens, history growing by a handful of rows a day) a
database is more machinery than the problem needs, and plain CSVs diff cleanly
in git if this ever gets committed back to a repo from a CI run.

Every write rewrites the whole file, atomically (write to a temp file in the same
directory, then os.replace). Callers should batch: build up all the rows for a run
in memory and write once, not once per ticker.
"""

from __future__ import annotations

import datetime as dt
import os
import tempfile

import pandas as pd

import config

TICKERS_COLUMNS = ["ticker", "name", "exchange", "asset_type", "updated_at"]
WATCHLIST_COLUMNS = ["ticker", "entry_date", "entry_price", "entry_score",
                      "peak_price", "peak_rsi", "status", "last_updated"]
HISTORY_COLUMNS = ["ticker", "date", "price", "volume", "return_z", "volume_ratio",
                    "rsi", "composite_score", "status_at_time"]
ALERTS_COLUMNS = ["ticker", "date", "alert_type", "detail"]


def _path(name: str) -> str:
    return os.path.join(config.DATA_DIR, name)


TICKERS_CSV = _path("tickers.csv")
WATCHLIST_CSV = _path("watchlist.csv")
HISTORY_CSV = _path("watchlist_history.csv")
ALERTS_CSV = _path("alerts.csv")


def init_store() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    for path, columns in (
        (TICKERS_CSV, TICKERS_COLUMNS),
        (WATCHLIST_CSV, WATCHLIST_COLUMNS),
        (HISTORY_CSV, HISTORY_COLUMNS),
        (ALERTS_CSV, ALERTS_COLUMNS),
    ):
        if not os.path.exists(path):
            pd.DataFrame(columns=columns).to_csv(path, index=False)


# A real NASDAQ ticker is "NA" (Nano Labs) -- pandas treats "NA" as a missing-value
# marker by default, which silently turns that ticker into NaN. Only apply NaN
# detection to non-ticker columns; a ticker symbol is never legitimately missing.
_NA_MARKERS = ["", "NaN", "nan", "NULL", "null", "None"]


def _read(path: str, columns: list[str]) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame(columns=columns)
    na_values = {c: _NA_MARKERS for c in columns if c != "ticker"}
    return pd.read_csv(path, keep_default_na=False, na_values=na_values, dtype={"ticker": str})


def _write_atomic(df: pd.DataFrame, path: str) -> None:
    dirpath = os.path.dirname(path) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            df.to_csv(f, index=False)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# --- tickers ---

def upsert_tickers(rows: list[dict]) -> int:
    if not rows:
        return 0
    existing = _read(TICKERS_CSV, TICKERS_COLUMNS)
    new = pd.DataFrame(rows)
    new["updated_at"] = dt.datetime.now().isoformat()
    combined = pd.concat([existing, new], ignore_index=True)
    combined = combined.drop_duplicates(subset="ticker", keep="last")
    combined = combined.sort_values("ticker").reset_index(drop=True)
    _write_atomic(combined, TICKERS_CSV)
    return len(new)


def get_universe(limit: int | None = None) -> list[str]:
    df = _read(TICKERS_CSV, TICKERS_COLUMNS)
    tickers = sorted(df["ticker"].tolist())
    return tickers[:limit] if limit else tickers


# --- watchlist ---

def get_tracked_tickers() -> set[str]:
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS)
    return set(df.loc[df["status"] == "watching", "ticker"])


def get_tracked_rows() -> list[dict]:
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS)
    return df.loc[df["status"] == "watching"].to_dict("records")


def get_watchlist_rows() -> list[dict]:
    return _read(WATCHLIST_CSV, WATCHLIST_COLUMNS).to_dict("records")


def insert_watchlist_rows(rows: list[dict]) -> None:
    """Batch-insert new entries, silently skipping any ticker already present."""
    if not rows:
        return
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS)
    existing = set(df["ticker"])
    new_rows = [r for r in rows if r["ticker"] not in existing]
    if not new_rows:
        return
    df = pd.concat([df, pd.DataFrame(new_rows)], ignore_index=True)
    _write_atomic(df, WATCHLIST_CSV)


def update_watchlist_rows(updates: dict[str, dict]) -> None:
    """updates: {ticker: {field: value, ...}}"""
    if not updates:
        return
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS).set_index("ticker")
    for ticker, fields in updates.items():
        if ticker in df.index:
            for key, value in fields.items():
                df.loc[ticker, key] = value
    _write_atomic(df.reset_index(), WATCHLIST_CSV)


# --- watchlist_history ---

def append_history_rows(rows: list[dict]) -> None:
    if not rows:
        return
    df = _read(HISTORY_CSV, HISTORY_COLUMNS)
    combined = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    combined = combined.drop_duplicates(subset=["ticker", "date"], keep="last")
    combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)
    _write_atomic(combined, HISTORY_CSV)


# --- alerts ---

def append_alert_rows(rows: list[dict]) -> None:
    if not rows:
        return
    df = _read(ALERTS_CSV, ALERTS_COLUMNS)
    combined = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
    _write_atomic(combined, ALERTS_CSV)
