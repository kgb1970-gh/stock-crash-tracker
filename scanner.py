"""Job 2 (discovery): scan the universe for tickers that just became unusually extended
and promote new ones into the watchlist. Does NOT touch tickers already being tracked --
that's tracker.py's job.

Usage:
    python scanner.py                 # full universe from the tickers table
    python scanner.py --limit 300     # first N tickers, for a quick local test
"""

from __future__ import annotations

import argparse
import datetime as dt

import pandas as pd

import config
import market_data
import signals
from db import connect, init_db


def _get_universe(limit: int | None) -> list[str]:
    with connect() as conn:
        rows = conn.execute("SELECT ticker FROM tickers ORDER BY ticker").fetchall()
    tickers = [r["ticker"] for r in rows]
    return tickers[:limit] if limit else tickers


def _already_tracked() -> set[str]:
    with connect() as conn:
        rows = conn.execute("SELECT ticker FROM watchlist WHERE status = 'watching'").fetchall()
    return {r["ticker"] for r in rows}


def _passes_liquidity_floor(df: pd.DataFrame) -> bool:
    latest_close = df["Close"].iloc[-1]
    avg_volume = df["Volume"].tail(config.VOLUME_AVG_WINDOW).mean()
    return latest_close >= config.MIN_PRICE and avg_volume >= config.MIN_AVG_VOLUME


def run(limit: int | None = None) -> list[str]:
    init_db()
    skip = _already_tracked()
    universe = [t for t in _get_universe(limit) if t not in skip]
    today = dt.date.today().isoformat()
    promoted = []

    bars, unresolved = market_data.fetch_all(universe)
    for ticker, df in bars.items():
        if len(df) < 60 or not _passes_liquidity_floor(df):
            continue

        scored = signals.compute_all(df)
        latest = scored.iloc[-1]
        if latest[["return_z", "volume_ratio", "rsi"]].isna().any():
            continue
        if not signals.passes_discovery_threshold(latest):
            continue

        _promote(ticker, today, latest)
        promoted.append(ticker)

    if unresolved:
        print(f"[scanner] {len(unresolved)} ticker(s) never got usable data this run "
              f"(rate-limited or delisted) -- not evaluated")

    return promoted


def _promote(ticker: str, today: str, latest: pd.Series) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO watchlist (ticker, entry_date, entry_price, entry_score,
                                    peak_price, peak_rsi, status)
            VALUES (?, ?, ?, ?, ?, ?, 'watching')
            ON CONFLICT(ticker) DO NOTHING
            """,
            (ticker, today, latest["Close"], latest["composite_score"],
             latest["Close"], latest["rsi"]),
        )
        conn.execute(
            """
            INSERT INTO watchlist_history (ticker, date, price, volume, return_z,
                                            volume_ratio, rsi, composite_score, status_at_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'watching')
            ON CONFLICT(ticker, date) DO NOTHING
            """,
            (ticker, today, latest["Close"], int(latest["Volume"]), latest["return_z"],
             latest["volume_ratio"], latest["rsi"], latest["composite_score"]),
        )
        conn.execute(
            "INSERT INTO alerts (ticker, date, alert_type, detail) VALUES (?, ?, 'entry', ?)",
            (ticker, today, f"score={latest['composite_score']:.2f} rsi={latest['rsi']:.1f}"),
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="only scan the first N tickers (for local testing)")
    args = parser.parse_args()

    new_tickers = run(limit=args.limit)
    print(f"Promoted {len(new_tickers)} new ticker(s): {new_tickers}")
