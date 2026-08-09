"""Indicator math, computed vectorized over a single ticker's OHLCV history.

Everything here takes a DataFrame with 'Close' and 'Volume' columns (as returned
by yfinance) and returns Series aligned to the same index. No I/O in this file.
"""

import numpy as np
import pandas as pd

import config


def rsi(close: pd.Series, window: int = config.RSI_WINDOW) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window).mean()
    avg_loss = loss.rolling(window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def bollinger_pct_b(close: pd.Series, window: int = config.BOLLINGER_WINDOW,
                     num_std: float = config.BOLLINGER_STD) -> pd.Series:
    """0 = at lower band, 1 = at upper band, >1 = broken out above it."""
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    return (close - lower) / (upper - lower)


def return_zscore(close: pd.Series, return_window: int = config.RETURN_WINDOW,
                   lookback: int = 60) -> pd.Series:
    """Z-score of the N-day return against that ticker's own trailing distribution
    of N-day returns -- 'unusual for THIS ticker', not vs. the market."""
    n_day_return = close.pct_change(return_window)
    rolling_mean = n_day_return.rolling(lookback).mean()
    rolling_std = n_day_return.rolling(lookback).std()
    return (n_day_return - rolling_mean) / rolling_std.replace(0, np.nan)


def volume_ratio(volume: pd.Series, window: int = config.VOLUME_AVG_WINDOW) -> pd.Series:
    avg = volume.rolling(window).mean()
    return volume / avg.replace(0, np.nan)


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """df must have 'Close' and 'Volume' columns. Returns df with signal columns added."""
    out = df.copy()
    out["return_z"] = return_zscore(out["Close"])
    out["volume_ratio"] = volume_ratio(out["Volume"])
    out["rsi"] = rsi(out["Close"])
    out["pct_b"] = bollinger_pct_b(out["Close"])
    out["composite_score"] = composite_score(out["return_z"], out["volume_ratio"], out["rsi"])
    return out


def composite_score(return_z: pd.Series, volume_ratio_: pd.Series, rsi_: pd.Series) -> pd.Series:
    """Ad hoc weighted sum -- tune weights once you've watched real results for a while.
    Each term is clipped to 0 on the downside so a quiet/normal reading doesn't drag
    the score negative; we only care about how *extended* a ticker is.
    """
    return (
        return_z.clip(lower=0)
        + (volume_ratio_ - 1).clip(lower=0)
        + ((rsi_ - 50) / 50).clip(lower=0)
    )


def passes_discovery_threshold(latest: pd.Series) -> bool:
    return (
        latest["return_z"] >= config.RETURN_Z_THRESHOLD
        and latest["volume_ratio"] >= config.VOLUME_RATIO_THRESHOLD
        and latest["rsi"] >= config.RSI_OVERBOUGHT
    )
