"""Bulk OHLCV fetching from yfinance with rate-limit resilience.

Yahoo throttles hard under sustained batch requests (confirmed: a ~13,000-ticker scan
at chunk size 100 started getting YFRateLimitError by the 3rd chunk). This module
paces requests between chunks and retries chunks that look rate-limited, instead of
silently treating "never checked" the same as "checked, no signal".
"""

from __future__ import annotations

import time

import pandas as pd
import yfinance as yf

import config


def _chunks(seq: list, size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _download_chunk(tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Returns (ticker -> OHLCV dataframe, tickers with no usable data this attempt)."""
    raw = yf.download(
        tickers=tickers,
        period=f"{config.LOOKBACK_DAYS}d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    data: dict[str, pd.DataFrame] = {}
    failed: list[str] = []
    for t in tickers:
        try:
            # yfinance returns MultiIndex columns keyed by ticker whenever a list is
            # passed in, even a list of length 1.
            df = raw[t].dropna(subset=["Close", "Volume"])
        except (KeyError, TypeError):
            failed.append(t)
            continue
        if df.empty:
            failed.append(t)
        else:
            data[t] = df
    return data, failed


def fetch_all(tickers: list[str]) -> tuple[dict[str, pd.DataFrame], list[str]]:
    """Fetches OHLCV for every ticker, chunked, throttled, and retried.

    A chunk where a large fraction of tickers fail is assumed to be rate-limited
    (as opposed to a few individually delisted/bad symbols) and its failed tickers
    are retried after a backoff, up to config.MAX_CHUNK_RETRIES passes. Whatever is
    still unresolved after that is returned separately, so callers never confuse
    "genuinely no signal" with "we couldn't check it".
    """
    if not tickers:
        return {}, []

    data: dict[str, pd.DataFrame] = {}
    pending = list(tickers)

    for attempt in range(1, config.MAX_CHUNK_RETRIES + 1):
        failed_this_pass: list[str] = []

        for chunk in _chunks(pending, config.CHUNK_SIZE):
            chunk_data, chunk_failed = _download_chunk(chunk)
            data.update(chunk_data)

            failure_rate = len(chunk_failed) / len(chunk) if chunk else 0
            if failure_rate >= config.RATE_LIMIT_FAILURE_THRESHOLD:
                failed_this_pass.extend(chunk_failed)

            time.sleep(config.REQUEST_DELAY_SECONDS)

        if not failed_this_pass:
            break

        pending = failed_this_pass
        backoff = config.RATE_LIMIT_BACKOFF_SECONDS * attempt
        print(f"[market_data] {len(pending)} ticker(s) look rate-limited "
              f"(pass {attempt}/{config.MAX_CHUNK_RETRIES}), backing off {backoff}s")
        time.sleep(backoff)

    unresolved = sorted(set(pending) - data.keys())
    return data, unresolved
