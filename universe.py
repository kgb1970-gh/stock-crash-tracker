"""Job 1: refresh the tradable ticker universe from NASDAQ Trader's free symbol directory.

Run weekly (or whenever) -- this doesn't need to run every day.
"""

from __future__ import annotations

import io

import requests

import config
import store

EXCHANGE_NAMES = {
    "A": "NYSE American",
    "N": "NYSE",
    "P": "NYSE Arca",
    "Z": "Cboe BZX",
    "V": "IEX",
}


def _fetch(url: str) -> list[str]:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    lines = resp.text.splitlines()
    # last line is a "File Creation Time" footer, not data
    return [l for l in lines if l and not l.startswith("File Creation Time")]


def _parse_nasdaq_listed() -> list[dict]:
    lines = _fetch(config.NASDAQ_LISTED_URL)
    header = lines[0].split("|")
    rows = []
    for line in lines[1:]:
        fields = dict(zip(header, line.split("|")))
        if fields.get("Test Issue") == "Y":
            continue
        rows.append({
            "ticker": fields["Symbol"],
            "name": fields["Security Name"],
            "exchange": "NASDAQ",
            "asset_type": "etf" if fields.get("ETF") == "Y" else "stock",
        })
    return rows


def _parse_other_listed() -> list[dict]:
    lines = _fetch(config.OTHER_LISTED_URL)
    header = lines[0].split("|")
    rows = []
    for line in lines[1:]:
        fields = dict(zip(header, line.split("|")))
        if fields.get("Test Issue") == "Y":
            continue
        rows.append({
            "ticker": fields["ACT Symbol"],
            "name": fields["Security Name"],
            "exchange": EXCHANGE_NAMES.get(fields.get("Exchange"), fields.get("Exchange")),
            "asset_type": "etf" if fields.get("ETF") == "Y" else "stock",
        })
    return rows


def sync_universe() -> int:
    rows = _parse_nasdaq_listed() + _parse_other_listed()
    store.upsert_tickers(rows)
    return len(rows)


if __name__ == "__main__":
    store.init_store()
    n = sync_universe()
    print(f"Synced {n} tickers")
