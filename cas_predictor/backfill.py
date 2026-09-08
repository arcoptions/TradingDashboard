"""Backfill 1-minute history into the local parquet cache.

    DHAN_ACCESS_TOKEN=... python -m cas_predictor.backfill [--from 2026-06-01] [--no-stocks]

Defaults to 01-Jun-2026 so the panel gets ~44 pre-CAS control sessions alongside every
CAS session. Re-runs are cheap: only calendar days not already cached are requested.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

from . import dhan_bars as db

DEFAULT_START = "2026-06-01"
BASKET_SIZE = 50


def top_symbols(n: int = BASKET_SIZE) -> list[str]:
    """The n names with the largest typical auction turnover, from the NSE CAS files."""
    root = Path(__file__).resolve().parent.parent / "cas_analysis"
    sys.path.insert(0, str(root))
    try:
        from load_cas import load_all
    finally:
        sys.path.pop(0)
    cwd = Path.cwd()
    import os

    os.chdir(root)  # load_all resolves its data dir relative to cwd
    try:
        panel = load_all()
    finally:
        os.chdir(cwd)
    return list(panel.groupby("symbol").value_cr.median().sort_values(ascending=False).head(n).index)


def run(start: str, end: str, token: str, stocks: bool = True) -> None:
    print(f"backfill {start} .. {end}")
    print(f"  token expires {db.token_expiry(token)}")

    idx = db.fetch_bars(db.NIFTY_INDEX, start, end, token)
    print(f"  {'NIFTY (index)':22s} {len(idx):>7,} bars  "
          f"{idx.ts.min() if len(idx) else '-'} .. {idx.ts.max() if len(idx) else '-'}")

    fut = db.front_month_future(end)
    fb = db.fetch_bars(fut, start, end, token)
    print(f"  {fut.label:22s} {len(fb):>7,} bars  "
          f"{fb.ts.min() if len(fb) else '-'} .. {fb.ts.max() if len(fb) else '-'}")

    if not stocks:
        return

    syms = top_symbols()
    print(f"\n  {len(syms)} constituents by median auction turnover")
    ok, missing, failed = 0, [], []
    for i, s in enumerate(syms, 1):
        try:
            inst = db.equity(s)
        except ValueError:
            missing.append(s)
            continue
        try:
            d = db.fetch_bars(inst, start, end, token)
        except Exception as e:  # keep going; report at the end
            failed.append((s, str(e)[:80]))
            continue
        ok += 1
        if i % 10 == 0 or i == len(syms):
            print(f"    {i:>3}/{len(syms)}  last: {s:<12} {len(d):>7,} bars")

    print(f"\n  cached {ok}/{len(syms)} constituents")
    if missing:
        print(f"  unresolved scrips ({len(missing)}): {', '.join(missing)}")
    if failed:
        print(f"  failed ({len(failed)}):")
        for s, err in failed:
            print(f"    {s}: {err}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default=DEFAULT_START)
    ap.add_argument("--to", dest="end", default=str(date.today()))
    ap.add_argument("--no-stocks", action="store_true")
    a = ap.parse_args()

    token = db.resolve_token()
    if not token:
        sys.exit("No Dhan token. Set DHAN_ACCESS_TOKEN.")
    if db.token_is_expired(token):
        sys.exit(f"Dhan token expired at {db.token_expiry(token)}.")

    run(a.start, a.end, token, stocks=not a.no_stocks)


if __name__ == "__main__":
    main()
