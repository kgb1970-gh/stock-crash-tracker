"""Single entry point for the daily batch run: sync universe (cheap, safe to run every
time), scan for new candidates, then update everything already being tracked.

This is what a GitHub Actions cron step (or a local cron job) should call.
"""

from __future__ import annotations

import argparse

import scanner
import store
import tracker
import universe


def main(limit: int | None = None) -> None:
    store.init_store()

    n = universe.sync_universe()
    print(f"[universe] synced {n} tickers")

    promoted = scanner.run(limit=limit)
    print(f"[scanner] promoted {len(promoted)} new ticker(s): {promoted}")

    summary = tracker.run()
    print(f"[tracker] short_signal={summary['short_signal']} "
          f"stale={summary['stale']} still_watching={len(summary['updated'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                         help="cap the discovery scan to the first N tickers (local testing)")
    args = parser.parse_args()
    main(limit=args.limit)
