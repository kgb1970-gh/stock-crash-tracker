"""Job 3: refresh every ticker currently being tracked, append to history, and run the
watching -> short_signal / stale state machine.

    watching --(price falls DRAWDOWN_FROM_PEAK_PCT off its peak, or RSI rolls over hard
                 from an overbought peak)--> short_signal   (the actionable alert)
    watching --(never triggers within STALE_AFTER_DAYS)--> stale
"""

from __future__ import annotations

import datetime as dt

import pandas as pd

import config
from db import connect
from scanner import _chunks, _download_chunk
import signals


def _tracked_rows() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM watchlist WHERE status = 'watching'"
        ).fetchall()
    return [dict(r) for r in rows]


def run() -> dict[str, list[str]]:
    tracked = _tracked_rows()
    today = dt.date.today().isoformat()
    result = {"short_signal": [], "stale": [], "updated": []}

    for chunk in _chunks([r["ticker"] for r in tracked], config.CHUNK_SIZE):
        bars = _download_chunk(chunk)
        by_ticker = {r["ticker"]: r for r in tracked}

        for ticker, df in bars.items():
            row = by_ticker[ticker]
            if len(df) < 20:
                continue

            scored = signals.compute_all(df)
            latest = scored.iloc[-1]
            if pd.isna(latest["Close"]):
                continue

            new_peak_price = max(row["peak_price"], latest["Close"])
            new_peak_rsi = max(row["peak_rsi"], latest["rsi"]) if not pd.isna(latest["rsi"]) else row["peak_rsi"]

            _append_history(ticker, today, latest, row["status"])

            new_status, reason = _evaluate(row, new_peak_price, new_peak_rsi, latest, today)
            _update_watchlist(ticker, new_peak_price, new_peak_rsi, new_status)

            if new_status != row["status"]:
                _alert(ticker, today, new_status, reason)
                result[new_status].append(ticker)
            else:
                result["updated"].append(ticker)

    return result


def _evaluate(row: dict, peak_price: float, peak_rsi: float, latest: pd.Series, today: str):
    entry_date = dt.date.fromisoformat(row["entry_date"])
    days_tracked = (dt.date.fromisoformat(today) - entry_date).days

    drawdown_pct = (peak_price - latest["Close"]) / peak_price if peak_price else 0
    rsi_rolled_over = peak_rsi >= config.RSI_ROLLOVER_FROM and latest["rsi"] < 50

    if drawdown_pct >= config.DRAWDOWN_FROM_PEAK_PCT:
        return "short_signal", f"down {drawdown_pct:.1%} from peak {peak_price:.2f}"
    if rsi_rolled_over and latest["Close"] < peak_price:
        return "short_signal", f"RSI rolled over from {peak_rsi:.1f} to {latest['rsi']:.1f}"
    if days_tracked >= config.STALE_AFTER_DAYS:
        return "stale", f"no trigger after {days_tracked} days"

    return row["status"], None


def _append_history(ticker: str, today: str, latest: pd.Series, status: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO watchlist_history (ticker, date, price, volume, return_z,
                                            volume_ratio, rsi, composite_score, status_at_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker, date) DO UPDATE SET
                price = excluded.price, volume = excluded.volume,
                return_z = excluded.return_z, volume_ratio = excluded.volume_ratio,
                rsi = excluded.rsi, composite_score = excluded.composite_score
            """,
            (ticker, today, latest["Close"], int(latest["Volume"]),
             _none_if_nan(latest["return_z"]), _none_if_nan(latest["volume_ratio"]),
             _none_if_nan(latest["rsi"]), _none_if_nan(latest["composite_score"]), status),
        )


def _update_watchlist(ticker: str, peak_price: float, peak_rsi: float, status: str) -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE watchlist
            SET peak_price = ?, peak_rsi = ?, status = ?, last_updated = datetime('now')
            WHERE ticker = ?
            """,
            (peak_price, peak_rsi, status, ticker),
        )


def _alert(ticker: str, today: str, status: str, reason: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO alerts (ticker, date, alert_type, detail) VALUES (?, ?, ?, ?)",
            (ticker, today, status, reason),
        )


def _none_if_nan(v):
    return None if pd.isna(v) else float(v)


if __name__ == "__main__":
    summary = run()
    print(f"short_signal: {summary['short_signal']}")
    print(f"stale: {summary['stale']}")
    print(f"still watching ({len(summary['updated'])}): {summary['updated']}")
