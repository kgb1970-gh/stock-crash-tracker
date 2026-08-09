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
import market_data
import signals
import store


def run() -> dict[str, list[str]]:
    tracked = store.get_tracked_rows()
    today = dt.date.today().isoformat()
    result = {"short_signal": [], "stale": [], "updated": []}

    by_ticker = {r["ticker"]: r for r in tracked}
    bars, unresolved = market_data.fetch_all(list(by_ticker.keys()))

    history_rows, alert_rows, watchlist_updates = [], [], {}

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

        history_rows.append({
            "ticker": ticker, "date": today, "price": latest["Close"],
            "volume": int(latest["Volume"]), "return_z": _none_if_nan(latest["return_z"]),
            "volume_ratio": _none_if_nan(latest["volume_ratio"]), "rsi": _none_if_nan(latest["rsi"]),
            "composite_score": _none_if_nan(latest["composite_score"]),
            "status_at_time": row["status"],
        })

        new_status, reason = _evaluate(row, new_peak_price, new_peak_rsi, latest, today)
        watchlist_updates[ticker] = {
            "peak_price": new_peak_price, "peak_rsi": new_peak_rsi,
            "status": new_status, "last_updated": today,
        }

        if new_status != row["status"]:
            alert_rows.append({"ticker": ticker, "date": today,
                                "alert_type": new_status, "detail": reason})
            result[new_status].append(ticker)
        else:
            result["updated"].append(ticker)

    store.append_history_rows(history_rows)
    store.update_watchlist_rows(watchlist_updates)
    store.append_alert_rows(alert_rows)

    if unresolved:
        print(f"[tracker] {len(unresolved)} tracked ticker(s) had no usable data this run "
              f"(rate-limited?), left unchanged: {unresolved}")

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


def _none_if_nan(v):
    return None if pd.isna(v) else float(v)


if __name__ == "__main__":
    summary = run()
    print(f"short_signal: {summary['short_signal']}")
    print(f"stale: {summary['stale']}")
    print(f"still watching ({len(summary['updated'])}): {summary['updated']}")
