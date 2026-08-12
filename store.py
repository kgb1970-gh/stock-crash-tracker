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
                      "peak_price", "peak_rsi", "peak_date", "status", "last_updated",
                      "signal_date", "signal_price", "min_price_since_signal", "min_price_date"]
HISTORY_COLUMNS = ["ticker", "date", "price", "volume", "return_z", "volume_ratio",
                    "rsi", "composite_score", "status_at_time"]
ALERTS_COLUMNS = ["ticker", "date", "alert_type", "detail"]
OUTCOMES_COLUMNS = ["ticker", "signal_date", "signal_price", "min_price", "min_price_date",
                     "max_gain_pct", "days_to_max_gain", "closed_date"]
INDICATORS_COLUMNS = ["sample_count", "avg_max_gain_pct", "p90_max_gain_pct",
                       "avg_days_to_max_gain", "p90_days_to_max_gain", "updated_at"]


def _path(name: str) -> str:
    return os.path.join(config.DATA_DIR, name)


TICKERS_CSV = _path("tickers.csv")
WATCHLIST_CSV = _path("watchlist.csv")
HISTORY_CSV = _path("watchlist_history.csv")
ALERTS_CSV = _path("alerts.csv")
OUTCOMES_CSV = _path("signal_outcomes.csv")
INDICATORS_CSV = _path("indicators.csv")


def init_store() -> None:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    for path, columns in (
        (TICKERS_CSV, TICKERS_COLUMNS),
        (WATCHLIST_CSV, WATCHLIST_COLUMNS),
        (HISTORY_CSV, HISTORY_COLUMNS),
        (ALERTS_CSV, ALERTS_COLUMNS),
        (OUTCOMES_CSV, OUTCOMES_COLUMNS),
        (INDICATORS_CSV, INDICATORS_COLUMNS),
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
    df = pd.read_csv(path, keep_default_na=False, na_values=na_values, dtype={"ticker": str})
    # Reindex to the current schema so a column added after old rows were written
    # (e.g. signal_date) doesn't KeyError -- missing cells just read back as NaN.
    return df.reindex(columns=columns)


def _append(existing: pd.DataFrame, rows: list[dict], columns: list[str]) -> pd.DataFrame:
    """Concat that doesn't warn/misbehave when `existing` is empty -- an empty
    DataFrame still carries dtype info pandas wants to reconcile during concat,
    which is noisy (and slated to change) when there's nothing to reconcile."""
    new = pd.DataFrame(rows).reindex(columns=columns)
    if existing.empty:
        return new
    return pd.concat([existing, new], ignore_index=True)


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

_TICKER_COMPARE_COLUMNS = ["name", "exchange", "asset_type"]


def upsert_tickers(rows: list[dict]) -> int:
    """Only bumps updated_at (and rewrites the row) for tickers that are new or
    actually changed. Otherwise a full universe sync touches all ~13,000 rows on
    every run just from timestamp churn, which defeats the point of CSVs being
    git-diff-friendly.
    """
    if not rows:
        return 0
    now = dt.datetime.now().isoformat()
    new = pd.DataFrame(rows).set_index("ticker")
    existing = _read(TICKERS_CSV, TICKERS_COLUMNS).set_index("ticker")

    new["updated_at"] = now
    if not existing.empty:
        common = new.index.intersection(existing.index)
        unchanged = common[
            (new.loc[common, _TICKER_COMPARE_COLUMNS] == existing.loc[common, _TICKER_COMPARE_COLUMNS]).all(axis=1)
        ]
        new.loc[unchanged, "updated_at"] = existing.loc[unchanged, "updated_at"]

    combined = new.sort_index().reset_index()
    _write_atomic(combined, TICKERS_CSV)
    return len(new)


def get_universe(limit: int | None = None) -> list[str]:
    df = _read(TICKERS_CSV, TICKERS_COLUMNS)
    tickers = sorted(df["ticker"].tolist())
    return tickers[:limit] if limit else tickers


# --- watchlist ---

_ACTIVE_STATUSES = ["watching", "short_signal"]


def get_tracked_tickers() -> set[str]:
    """Tickers currently in any active state -- scanner.py uses this to avoid
    re-promoting something that's already being watched or tracked post-signal."""
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS)
    return set(df.loc[df["status"].isin(_ACTIVE_STATUSES), "ticker"])


def get_tracked_rows() -> list[dict]:
    """Rows tracker.py needs to process this run: both tickers still being watched
    for a reversal, and tickers past that whose post-signal outcome is still open."""
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS)
    return df.loc[df["status"].isin(_ACTIVE_STATUSES)].to_dict("records")


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
    df = _append(df, new_rows, WATCHLIST_COLUMNS)
    _write_atomic(df, WATCHLIST_CSV)


def update_watchlist_rows(updates: dict[str, dict]) -> None:
    """updates: {ticker: {field: value, ...}}"""
    if not updates:
        return
    # A column that's all-NaN so far (e.g. signal_date before any signal has fired)
    # reads back as float64; assigning a string into it would raise in future pandas.
    df = _read(WATCHLIST_CSV, WATCHLIST_COLUMNS).astype(object).set_index("ticker")
    for ticker, fields in updates.items():
        if ticker in df.index:
            for key, value in fields.items():
                df.loc[ticker, key] = value
    _write_atomic(df.reset_index(), WATCHLIST_CSV)


# --- watchlist_history ---

def append_history_rows(rows: list[dict]) -> None:
    if not rows:
        return
    combined = _append(_read(HISTORY_CSV, HISTORY_COLUMNS), rows, HISTORY_COLUMNS)
    combined = combined.drop_duplicates(subset=["ticker", "date"], keep="last")
    combined = combined.sort_values(["ticker", "date"]).reset_index(drop=True)
    _write_atomic(combined, HISTORY_CSV)


# --- alerts ---

def append_alert_rows(rows: list[dict]) -> None:
    if not rows:
        return
    combined = _append(_read(ALERTS_CSV, ALERTS_COLUMNS), rows, ALERTS_COLUMNS)
    _write_atomic(combined, ALERTS_CSV)


# --- signal_outcomes / indicators ---

def append_outcome_rows(rows: list[dict]) -> None:
    """One row per short_signal that finished its SHORT_TRACK_DAYS tracking window:
    how far it fell from the signal price, and how many days that took."""
    if not rows:
        return
    combined = _append(_read(OUTCOMES_CSV, OUTCOMES_COLUMNS), rows, OUTCOMES_COLUMNS)
    combined = combined.drop_duplicates(subset=["ticker", "signal_date"], keep="last")
    _write_atomic(combined, OUTCOMES_CSV)


def recompute_indicators() -> None:
    """Rebuilds indicators.csv from every closed-out outcome to date. A single
    summary row -- avg/p90 of how far a signal falls and how long that takes --
    that gets more meaningful as more signals close out."""
    df = _read(OUTCOMES_CSV, OUTCOMES_COLUMNS)
    if df.empty:
        return
    row = {
        "sample_count": len(df),
        "avg_max_gain_pct": df["max_gain_pct"].mean(),
        "p90_max_gain_pct": df["max_gain_pct"].quantile(0.9),
        "avg_days_to_max_gain": df["days_to_max_gain"].mean(),
        "p90_days_to_max_gain": df["days_to_max_gain"].quantile(0.9),
        "updated_at": dt.datetime.now().isoformat(),
    }
    _write_atomic(pd.DataFrame([row]), INDICATORS_CSV)
