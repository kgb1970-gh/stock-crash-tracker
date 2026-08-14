"""Loads config.yaml and flattens it into module-level attributes, so the rest of
the codebase can keep doing `import config; config.SOME_VALUE`. Tune values in
config.yaml, not here.
"""

import os

import yaml

_CONFIG_PATH = os.environ.get(
    "STOCK_TRACKER_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml")
)

with open(_CONFIG_PATH) as _f:
    _raw = yaml.safe_load(_f)

DATA_DIR = os.environ.get("STOCK_TRACKER_DATA_DIR", _raw["data_dir"])

NASDAQ_LISTED_URL = _raw["universe"]["nasdaq_listed_url"]
OTHER_LISTED_URL = _raw["universe"]["other_listed_url"]

LOOKBACK_DAYS = _raw["scanner"]["lookback_days"]
RETURN_WINDOW = _raw["scanner"]["return_window"]
VOLUME_AVG_WINDOW = _raw["scanner"]["volume_avg_window"]
RSI_WINDOW = _raw["scanner"]["rsi_window"]
BOLLINGER_WINDOW = _raw["scanner"]["bollinger_window"]
BOLLINGER_STD = _raw["scanner"]["bollinger_std"]

RETURN_Z_THRESHOLD = _raw["scanner"]["return_z_threshold"]
VOLUME_RATIO_THRESHOLD = _raw["scanner"]["volume_ratio_threshold"]
RSI_OVERBOUGHT = _raw["scanner"]["rsi_overbought"]

MIN_PRICE = _raw["scanner"]["min_price"]
MIN_AVG_DOLLAR_VOLUME = _raw["scanner"]["min_avg_dollar_volume"]

CHUNK_SIZE = _raw["market_data"]["chunk_size"]
REQUEST_DELAY_SECONDS = _raw["market_data"]["request_delay_seconds"]
MAX_CHUNK_RETRIES = _raw["market_data"]["max_chunk_retries"]
RATE_LIMIT_BACKOFF_SECONDS = _raw["market_data"]["rate_limit_backoff_seconds"]
RATE_LIMIT_FAILURE_THRESHOLD = _raw["market_data"]["rate_limit_failure_threshold"]

DRAWDOWN_FROM_PEAK_PCT = _raw["tracker"]["drawdown_from_peak_pct"]
RSI_ROLLOVER_FROM = _raw["tracker"]["rsi_rollover_from"]
FLAT_DAYS_WITHOUT_NEW_PEAK = _raw["tracker"]["flat_days_without_new_peak"]
STALE_AFTER_DAYS = _raw["tracker"]["stale_after_days"]

SHORT_TRACK_DAYS = _raw["outcomes"]["short_track_days"]
