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
import store


def _passes_liquidity_floor(df: pd.DataFrame) -> bool:
    latest_close = df["Close"].iloc[-1]
    window = df.tail(config.VOLUME_AVG_WINDOW)
    avg_dollar_volume = (window["Close"] * window["Volume"]).mean()
    return latest_close >= config.MIN_PRICE and avg_dollar_volume >= config.MIN_AVG_DOLLAR_VOLUME


def run(limit: int | None = None) -> list[str]:
    store.init_store()
    skip = store.get_tracked_tickers()
    universe = [t for t in store.get_universe(limit) if t not in skip]
    today = dt.date.today().isoformat()
    promoted = []
    watchlist_rows, history_rows, alert_rows = [], [], []

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

        watchlist_rows.append({
            "ticker": ticker, "entry_date": today, "entry_price": latest["Close"],
            "entry_score": latest["composite_score"], "peak_price": latest["Close"],
            "peak_rsi": latest["rsi"], "peak_date": today,
            "status": "watching", "last_updated": today,
        })
        history_rows.append({
            "ticker": ticker, "date": today, "price": latest["Close"],
            "volume": int(latest["Volume"]), "return_z": latest["return_z"],
            "volume_ratio": latest["volume_ratio"], "rsi": latest["rsi"],
            "composite_score": latest["composite_score"], "status_at_time": "watching",
        })
        alert_rows.append({
            "ticker": ticker, "date": today, "alert_type": "entry",
            "detail": f"score={latest['composite_score']:.2f} rsi={latest['rsi']:.1f}",
        })
        promoted.append(ticker)

    store.insert_watchlist_rows(watchlist_rows)
    store.append_history_rows(history_rows)
    store.append_alert_rows(alert_rows)

    if unresolved:
        print(f"[scanner] {len(unresolved)} ticker(s) never got usable data this run "
              f"(rate-limited or delisted) -- not evaluated")

    return promoted


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="only scan the first N tickers (for local testing)")
    args = parser.parse_args()

    new_tickers = run(limit=args.limit)
    print(f"Promoted {len(new_tickers)} new ticker(s): {new_tickers}")
