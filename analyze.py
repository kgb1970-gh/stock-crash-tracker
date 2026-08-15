"""Standing analysis of discovery quality: do entry-time features (entry_score,
return_z, volume_ratio, rsi) actually predict which tickers go on to confirm
(short_signal/sold/closed) vs fizzle (faded/stale)? Rerun anytime -- the answer
gets more reliable as more tickers resolve.

    python analyze.py
"""

from __future__ import annotations

import pandas as pd

import store

# CONFIRMED = the entry trigger fired at all (short_signal), regardless of how the
# post-signal cover phase later resolved -- this is about whether entry criteria
# predicted a reversal, not about the exit/cover strategy.
CONFIRMED = {"short_signal", "sold", "closed"}
FALSE_POSITIVE = {"faded", "stale"}
PENDING = {"watching"}

SCORE_THRESHOLDS = [0, 5, 8, 10, 12, 15, 20, 25]


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
