"""Job 3: refresh every actively-tracked ticker and run the state machine.

    watching --(price falls DRAWDOWN_FROM_PEAK_PCT off its peak, or RSI rolls over
                 hard from an overbought peak)--> short_signal
    watching --(never triggers within STALE_AFTER_DAYS)--> stale

    short_signal --(tracks the running low daily)--> short_signal
    short_signal --(SHORT_TRACK_DAYS after the trigger)--> closed
                 writes an outcome row (how far it fell, how many days that took)
                 and refreshes the aggregate indicators.
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
    result = {"short_signal": [], "closed": [], "stale": [], "updated": []}

    by_ticker = {r["ticker"]: r for r in tracked}
    bars, unresolved = market_data.fetch_all(list(by_ticker.keys()))

    history_rows, alert_rows, outcome_rows = [], [], []
    watchlist_updates = {}

    for ticker, df in bars.items():
        row = by_ticker[ticker]
        if len(df) < 20:
            continue

        scored = signals.compute_all(df)
        latest = scored.iloc[-1]
        if pd.isna(latest["Close"]):
            continue

        history_rows.append({
            "ticker": ticker, "date": today, "price": latest["Close"],
            "volume": int(latest["Volume"]), "return_z": _none_if_nan(latest["return_z"]),
            "volume_ratio": _none_if_nan(latest["volume_ratio"]), "rsi": _none_if_nan(latest["rsi"]),
            "composite_score": _none_if_nan(latest["composite_score"]),
            "status_at_time": row["status"],
        })

        if row["status"] == "watching":
            new_status, reason, updates = _evaluate_watching(row, latest, today)
        else:
            new_status, reason, updates = _evaluate_short_signal(row, latest, today, outcome_rows)

        watchlist_updates[ticker] = updates

        if new_status != row["status"]:
            alert_rows.append({"ticker": ticker, "date": today,
                                "alert_type": new_status, "detail": reason})
            result[new_status].append(ticker)
        else:
            result["updated"].append(ticker)

    store.append_history_rows(history_rows)
    store.update_watchlist_rows(watchlist_updates)
    store.append_alert_rows(alert_rows)
    if outcome_rows:
        store.append_outcome_rows(outcome_rows)
        store.recompute_indicators()

    if unresolved:
        print(f"[tracker] {len(unresolved)} tracked ticker(s) had no usable data this run "
              f"(rate-limited?), left unchanged: {unresolved}")

    return result


def _evaluate_watching(row: dict, latest: pd.Series, today: str):
    new_peak_price = max(row["peak_price"], latest["Close"])
    new_peak_rsi = max(row["peak_rsi"], latest["rsi"]) if not pd.isna(latest["rsi"]) else row["peak_rsi"]

    entry_date = dt.date.fromisoformat(row["entry_date"])
    days_tracked = (dt.date.fromisoformat(today) - entry_date).days

    drawdown_pct = (new_peak_price - latest["Close"]) / new_peak_price if new_peak_price else 0
    rsi_rolled_over = new_peak_rsi >= config.RSI_ROLLOVER_FROM and latest["rsi"] < 50

    updates = {"peak_price": new_peak_price, "peak_rsi": new_peak_rsi,
               "status": "watching", "last_updated": today}

    if drawdown_pct >= config.DRAWDOWN_FROM_PEAK_PCT:
        updates.update(_start_signal_tracking(latest, today))
        return "short_signal", f"down {drawdown_pct:.1%} from peak {new_peak_price:.2f}", updates
    if rsi_rolled_over and latest["Close"] < new_peak_price:
        updates.update(_start_signal_tracking(latest, today))
        return "short_signal", f"RSI rolled over from {new_peak_rsi:.1f} to {latest['rsi']:.1f}", updates
    if days_tracked >= config.STALE_AFTER_DAYS:
        updates["status"] = "stale"
        return "stale", f"no trigger after {days_tracked} days", updates

    return "watching", None, updates


def _start_signal_tracking(latest: pd.Series, today: str) -> dict:
    return {
        "status": "short_signal",
        "signal_date": today, "signal_price": latest["Close"],
        "min_price_since_signal": latest["Close"], "min_price_date": today,
    }


def _evaluate_short_signal(row: dict, latest: pd.Series, today: str, outcome_rows: list):
    min_price = row["min_price_since_signal"]
    min_date = row["min_price_date"]
    if latest["Close"] < min_price:
        min_price = latest["Close"]
        min_date = today

    signal_date = dt.date.fromisoformat(row["signal_date"])
    days_since_signal = (dt.date.fromisoformat(today) - signal_date).days

    updates = {"min_price_since_signal": min_price, "min_price_date": min_date,
               "status": "short_signal", "last_updated": today}

    if days_since_signal >= config.SHORT_TRACK_DAYS:
        max_gain_pct = (row["signal_price"] - min_price) / row["signal_price"] if row["signal_price"] else 0
        days_to_max_gain = (dt.date.fromisoformat(min_date) - signal_date).days
        outcome_rows.append({
            "ticker": row["ticker"], "signal_date": row["signal_date"],
            "signal_price": row["signal_price"], "min_price": min_price,
            "min_price_date": min_date, "max_gain_pct": max_gain_pct,
            "days_to_max_gain": days_to_max_gain, "closed_date": today,
        })
        updates["status"] = "closed"
        return "closed", f"closed out: max gain {max_gain_pct:.1%} in {days_to_max_gain}d", updates

    return "short_signal", None, updates


def _none_if_nan(v):
    return None if pd.isna(v) else float(v)


if __name__ == "__main__":
    summary = run()
    print(f"short_signal: {summary['short_signal']}")
    print(f"closed: {summary['closed']}")
    print(f"stale: {summary['stale']}")
    print(f"still active ({len(summary['updated'])}): {summary['updated']}")
