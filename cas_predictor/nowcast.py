"""Live CAS nowcast: run it during 15:15-15:30 to update the call as futures move.

    DHAN_ACCESS_TOKEN=... python -m cas_predictor.nowcast [--watch]

Before 15:14 it prints the standing forecast (the structural drift, which is all there is --
no pre-freeze feature beat always-long). From 15:15 it prints the futures drift since the
freeze and the threshold call, refreshing every 30s under --watch.

The threshold is re-derived from prior sessions on every run rather than hard-coded, so this
cannot silently keep trading a number that stopped applying. It is the same walk-forward
rule as `backtest.py`, which over 16 test sessions departed from always-long three times:
two correct shorts and one false one, +12.3 pts/session with a bootstrap CI of [-5, +36].
That CI spans zero. Treat a short call as "stand aside", not as conviction.
"""

from __future__ import annotations

import argparse
import datetime
import sys
import time
import zoneinfo

import numpy as np
import pandas as pd

from . import dhan_bars as db
from .features import FREEZE_HM
from .panel import build

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
FUT = db.Instrument("68407", "NSE_FNO", "FUTIDX", "NIFTY-Sep2026-FUT")
GRID = np.arange(-15, 1, 0.5)


def fit_threshold(as_of: str = "15:27") -> tuple[float, int]:
    """Best drift threshold on all completed CAS sessions. Returns (threshold, n_sessions)."""
    sess, now, _ = build("2026-06-01")
    cas = sess[sess.is_cas]
    w = now[now.date.isin(cas.index) & (now.as_of == as_of)].set_index("date")
    df = pd.DataFrame({"jump": cas.jump_bps, "drift": w.fut_drift_bps}).dropna()
    best, best_pnl = np.nan, -np.inf
    for thr in GRID:
        pnl = (np.where(df.drift < thr, -1.0, 1.0) * df.jump).mean()
        if pnl > best_pnl:
            best, best_pnl = float(thr), pnl
    return best, len(df)


def snapshot(token: str) -> dict:
    """Today's index and futures state, fetched fresh.

    `use_cache=False` is load-bearing, not tidiness. The cache marks a calendar day covered
    once any part of it has been requested, so a backfill run earlier in the session would
    pin this to whatever minute it happened to stop at -- the nowcast would sit there
    reporting a stale price with a live timestamp, which is the worst failure available.
    """
    today = str(datetime.datetime.now(IST).date())
    idx = db.fetch_bars(db.NIFTY_INDEX, today, today, token, use_cache=False)
    fut = db.fetch_bars(FUT, today, today, token, use_cache=False)
    if idx.empty:
        raise RuntimeError("no index bars for today -- market holiday, or the feed is down")

    i = db.bars_by_session(idx)[max(db.bars_by_session(idx))].close.astype(float)
    f = db.bars_by_session(fut)[max(db.bars_by_session(fut))].close.astype(float)
    frozen = FREEZE_HM in i.index

    out = {
        "now_hm": datetime.datetime.now(IST).strftime("%H:%M"),
        "last_bar": str(i.index[-1]),
        "index_last": float(i.iloc[-1]),
        "fut_last": float(f.iloc[-1]),
        "frozen": frozen,
        "freeze_px": float(i[FREEZE_HM]) if frozen else np.nan,
        "fut_freeze": float(f[FREEZE_HM]) if FREEZE_HM in f.index else np.nan,
    }
    if np.isfinite(out["fut_freeze"]):
        out["drift_bps"] = (out["fut_last"] / out["fut_freeze"] - 1.0) * 1e4
    else:
        out["drift_bps"] = np.nan
    # Freeze integrity: index should not move at all between 15:15 and the re-print.
    out["index_moved_bps"] = (
        (out["index_last"] / out["freeze_px"] - 1.0) * 1e4 if frozen else np.nan
    )
    return out


def show(s: dict, thr: float, n_hist: int, central_bps: float) -> None:
    print(f"\n[{s['now_hm']} IST]  bars to {s['last_bar']}   "
          f"index {s['index_last']:,.2f}   future {s['fut_last']:,.2f}")

    if not s["frozen"]:
        px = s["index_last"]
        print(f"  pre-freeze. Standing forecast only: {central_bps:+.1f} bps "
              f"({central_bps * px * 1e-4:+.0f} pts).")
        print(f"  If the 15:14 close were here ({px:,.2f}) -> {px * (1 + central_bps/1e4):,.0f}")
        print("  No pre-freeze feature beat always-long, so this is the drift, not a forecast.")
        return

    moved = s["index_moved_bps"]
    tag = "clean" if abs(moved) < 2 else f"*** MOVED {moved:+.1f} bps -- freeze not clean ***"
    print(f"  freeze 15:14 {s['freeze_px']:,.2f}   index since freeze {moved:+.1f} bps  [{tag}]")

    d = s["drift_bps"]
    if not np.isfinite(d):
        print("  no futures bar at 15:14 -- nowcast unavailable")
        return
    call = "SHORT (stand aside)" if d < thr else "LONG"
    print(f"  futures drift since freeze  {d:+.1f} bps      threshold {thr:+.1f}   -> {call}")
    if s["now_hm"] < "15:21":
        print("  NOTE: drift correlates NEGATIVELY with the jump before 15:21 (-0.40 at 15:17,")
        print("        -0.32 at 15:19) and this is unexplained. Do not act on it yet.")
    est = central_bps if d >= thr else min(central_bps, d)
    print(f"  predicted final print  {s['freeze_px'] * (1 + est/1e4):,.0f}  "
          f"({est:+.1f} bps, {est * s['freeze_px'] * 1e-4:+.0f} pts)   "
          f"[threshold fitted on {n_hist} sessions]")


def main() -> None:
    ap = argparse.ArgumentParser(description="Live CAS nowcast.")
    ap.add_argument("--watch", action="store_true", help="refresh every 30s until 15:31")
    ap.add_argument("--central", type=float, default=12.0,
                    help="central jump estimate in bps (default 12: decay vs expiry blend)")
    a = ap.parse_args()

    token = db.resolve_token()
    if not token:
        sys.exit("No Dhan token. Set DHAN_ACCESS_TOKEN.")
    if db.token_is_expired(token):
        sys.exit(f"Dhan token expired at {db.token_expiry(token)}.")

    thr, n_hist = fit_threshold()
    print(f"threshold re-fitted on {n_hist} completed CAS sessions: {thr:+.1f} bps")

    while True:
        try:
            show(snapshot(token), thr, n_hist, a.central)
        except Exception as e:  # a dropped poll must not end the watch during the window
            print(f"  [{datetime.datetime.now(IST):%H:%M}] poll failed: {type(e).__name__}: {e}")
        if not a.watch or datetime.datetime.now(IST).strftime("%H:%M") >= "15:31":
            return
        time.sleep(30)


if __name__ == "__main__":
    main()
