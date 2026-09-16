"""Standing analysis of discovery quality: do entry-time features (entry_score,
return_z, volume_ratio, rsi) actually predict which tickers go on to confirm
(short_signal/sold/closed) vs fizzle (faded/stale)? Rerun anytime -- the answer
gets more reliable as more tickers resolve.

    python analyze.py
"""

from __future__ import annotations

import pandas as pd

import config
import store

# CONFIRMED = the entry trigger fired at all (short_signal), regardless of how the
# post-signal cover phase later resolved -- this is about whether entry criteria
# predicted a reversal, not about the exit/cover strategy.
CONFIRMED = {"short_signal", "sold", "closed"}
FALSE_POSITIVE = {"faded", "stale"}
PENDING = {"watching"}

SCORE_THRESHOLDS = [0, 5, 8, 10, 12, 15, 20, 25]
REBOUND_THRESHOLDS = [0.05, 0.08, 0.10, 0.12, 0.15, 0.20, 0.25, 0.30]


def _load() -> pd.DataFrame:
    wl = store._read(store.WATCHLIST_CSV, store.WATCHLIST_COLUMNS)
    hist = store._read(store.HISTORY_CSV, store.HISTORY_COLUMNS)

    # entry-day row per ticker gives the individual signal components (entry_score
    # is just their composite) -- join them in for a richer breakdown.
    entry_day = hist.merge(
        wl[["ticker", "entry_date"]], on="ticker"
    )
    entry_day = entry_day[entry_day["date"] == entry_day["entry_date"]]
    entry_day = entry_day[["ticker", "return_z", "volume_ratio", "rsi"]]

    return wl.merge(entry_day, on="ticker", how="left")


def _outcome(status: str) -> str:
    if status in CONFIRMED:
        return "confirmed"
    if status in FALSE_POSITIVE:
        return "false_positive"
    return "pending"


def outcome_breakdown(df: pd.DataFrame) -> None:
    df = df.copy()
    df["outcome"] = df["status"].apply(_outcome)
    resolved = df[df["outcome"] != "pending"]

    print(f"=== Outcome breakdown ({len(resolved)} resolved, {len(df) - len(resolved)} still pending) ===")
    if resolved.empty:
        print("(nothing resolved yet)")
        return
    summary = resolved.groupby("outcome")[["entry_score", "return_z", "volume_ratio", "rsi"]].agg(["count", "mean", "median"])
    print(summary.round(2).to_string())
    print()


def threshold_sweep(df: pd.DataFrame) -> None:
    df = df.copy()
    df["outcome"] = df["status"].apply(_outcome)
    resolved = df[df["outcome"] != "pending"]

    print("=== entry_score threshold sweep (resolved tickers only) ===")
    if resolved.empty:
        print("(nothing resolved yet)")
        return
    print(f"{'threshold':>9} {'kept':>6} {'confirmed_kept':>15} {'confirm_rate':>13} {'confirmed_excluded':>19}")
    total_confirmed = (resolved["outcome"] == "confirmed").sum()
    for t in SCORE_THRESHOLDS:
        kept = resolved[resolved["entry_score"] >= t]
        confirmed_kept = (kept["outcome"] == "confirmed").sum()
        confirm_rate = confirmed_kept / len(kept) if len(kept) else 0
        confirmed_excluded = total_confirmed - confirmed_kept
        print(f"{t:>9} {len(kept):>6} {confirmed_kept:>15} {confirm_rate:>12.0%} {confirmed_excluded:>19}")
    print()


def _signal_tickers() -> pd.DataFrame:
    """Every ticker that ever entered short_signal (whether still open, sold, or
    closed), with the signal date/price a simulated exit would be measured from."""
    wl = store._read(store.WATCHLIST_CSV, store.WATCHLIST_COLUMNS)
    signaled = wl[wl["status"].isin(["short_signal", "sold", "closed"])]
    return signaled[["ticker", "signal_date", "signal_price"]].dropna(subset=["signal_date"])


def _simulate_exit(prices: pd.DataFrame, signal_price: float, rebound_pct: float):
    """prices: this ticker's history from signal_date onward, sorted by date.
    Replays the real state machine's logic (running low, rebound check, 20-day
    backstop) with a different rebound_pct to see what would have happened.
    Returns (exit_price, days_held, resolution) -- resolution is "open" if the
    ticker hasn't accumulated enough history yet to resolve either way.
    """
    signal_date = pd.to_datetime(prices.iloc[0]["date"])
    running_min = signal_price
    for _, row in prices.iterrows():
        price = row["price"]
        running_min = min(running_min, price)
        rebound = (price - running_min) / running_min if running_min else 0
        days_held = (pd.to_datetime(row["date"]) - signal_date).days
        if rebound >= rebound_pct:
            return price, days_held, "sold"
        if days_held >= config.SHORT_TRACK_DAYS:
            return price, days_held, "timeout"
    last = prices.iloc[-1]
    days_held = (pd.to_datetime(last["date"]) - signal_date).days
    return last["price"], days_held, "open"


def rebound_threshold_sweep() -> None:
    """What if REBOUND_FROM_LOW_PCT had been set differently? Replays every signal
    to date (resolved or still open) under each candidate threshold and totals the
    $1000-per-signal P&L, so a config change can be checked against history before
    committing to it live."""
    signals = _signal_tickers()
    hist = store._read(store.HISTORY_CSV, store.HISTORY_COLUMNS)

    print("=== rebound_from_low_pct threshold sweep (simulated on all signals to date) ===")
    if signals.empty:
        print("(no short_signal has fired yet)")
        return

    print(f"{'threshold':>9} {'n':>4} {'total_pnl_$1000':>16} {'avg_days_held':>14}")
    for t in REBOUND_THRESHOLDS:
        total_pnl, total_days, n = 0.0, 0, 0
        for _, sig in signals.iterrows():
            ticker_hist = hist[(hist["ticker"] == sig["ticker"]) & (hist["date"] >= sig["signal_date"])]
            ticker_hist = ticker_hist.sort_values("date")
            if ticker_hist.empty:
                continue
            exit_price, days_held, _ = _simulate_exit(ticker_hist, sig["signal_price"], t)
            gain_pct = (sig["signal_price"] - exit_price) / sig["signal_price"] if sig["signal_price"] else 0
            total_pnl += 1000 * gain_pct
            total_days += days_held
            n += 1
        avg_days = total_days / n if n else 0
        marker = "  <- current config" if abs(t - config.REBOUND_FROM_LOW_PCT) < 1e-9 else ""
        print(f"{t:>8.0%} {n:>4} {total_pnl:>15,.2f} {avg_days:>13.1f}{marker}")
    print()


def indicators() -> None:
    df = store._read(store.INDICATORS_CSV, store.INDICATORS_COLUMNS)
    print("=== Post-signal outcome indicators (sold=covered on a rebound, timeout=hit the backstop) ===")
    if df.empty:
        print("(no short_signal has resolved yet -- needs a rebound or SHORT_TRACK_DAYS to elapse)")
        return
    print(df.to_string(index=False))
    print()


if __name__ == "__main__":
    data = _load()
    outcome_breakdown(data)
    threshold_sweep(data)
    indicators()
    rebound_threshold_sweep()
