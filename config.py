"""Thresholds and knobs for the scanner and tracker. Tune these as you observe real results."""

import os

DATA_DIR = os.environ.get("STOCK_TRACKER_DATA_DIR", "data")

# --- Universe ---
# NASDAQ Trader publishes these for free, no auth needed.
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

# --- Scanner (discovery) ---
LOOKBACK_DAYS = 90          # history pulled per ticker to compute rolling signals
RETURN_WINDOW = 10          # N-day return used for the "unusual move" check
VOLUME_AVG_WINDOW = 20      # rolling average volume window
RSI_WINDOW = 14
BOLLINGER_WINDOW = 20
BOLLINGER_STD = 2

RETURN_Z_THRESHOLD = 2.5    # 10-day return this many std devs above the ticker's own norm
VOLUME_RATIO_THRESHOLD = 2.0  # today's volume vs 20-day average
RSI_OVERBOUGHT = 75

MIN_PRICE = 3.0                    # skip penny/junk tickers
MIN_AVG_DOLLAR_VOLUME = 5_000_000  # skip illiquid tickers: 20-day avg (price * volume)
                                    # below this. Dollar volume, not share count, since
                                    # 100k shares of a $3 stock and 100k shares of a $300
                                    # stock are not comparably liquid.

CHUNK_SIZE = 50             # tickers per yfinance batch download call
REQUEST_DELAY_SECONDS = 3   # pause between chunk downloads, to avoid tripping rate limits
MAX_CHUNK_RETRIES = 3       # retry passes for chunks that look rate-limited
RATE_LIMIT_BACKOFF_SECONDS = 30       # base backoff before a retry pass; multiplied by attempt #
RATE_LIMIT_FAILURE_THRESHOLD = 0.3    # >=30% of a chunk failing is treated as rate limiting,
                                       # not just a few delisted/bad symbols

# --- Tracker (reversal / short-signal detection) ---
DRAWDOWN_FROM_PEAK_PCT = 0.15   # 15% off the peak recorded since entering watchlist
RSI_ROLLOVER_FROM = 70          # RSI must have been >= this at some point while watching
FLAT_DAYS_WITHOUT_NEW_PEAK = 7  # no new high in this many days, and never triggered ->
                                 # "faded": the extension fizzled, not worth watching further
STALE_AFTER_DAYS = 45           # rare backstop for a ticker that keeps grinding out small
                                 # new highs (so it never goes flat) without ever triggering

# --- Post-signal outcome tracking ---
SHORT_TRACK_DAYS = 20   # once short_signal fires, keep tracking the running low for this
                         # many days before closing the outcome out and folding it into
                         # indicators.csv -- this is what measures "how far did it actually
                         # fall, and how long did that take"
