"""Assemble the session panel: the target, the features, and the checks that keep both honest.

Two frames come out of `build()`:

  sessions  -- one row per session. The target `jump_bps`, every pre-freeze feature (as-of
               15:14, a genuine forecast), trailing statistics, and freeze-integrity columns.
  nowcast   -- one row per (session, checkpoint minute). The in-window features, which are
               knowable and tradeable while spot is frozen but futures still trade.

Nothing here calls Dhan. It reads the parquet cache only, so a panel either uses the history
already on disk or reports it missing -- it never depends on a live token months after the
fact.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from . import dhan_bars as db
from .features import (
    CHECKPOINTS,
    FREEZE_HM,
    IN_WINDOW_NAMES,
    PRE_FREEZE_NAMES,
    Session,
    compute,
)

#: First session of NSE's Closing Auction Session.
CAS_START = pd.Timestamp("2026-08-03")
#: Nifty 50 constituent rebalance. The constituent reconstruction breaks here -- turnover was
#: ~35x normal, so turnover weighting put the jump at +62.5 bps against an actual +11.8. The
#: session stays in the panel and gets flagged; it is not dropped and not fitted.
REBALANCE_DAYS = {pd.Timestamp("2026-08-31")}

TRAIL_WINDOW = 20
TRAIL_MIN = 5


# ------------------------------------------------------------------- loading
def load_sessions(start: str | date, end: str | date,
                  future_key: str | None = None) -> tuple[dict[date, Session], dict]:
    """Sessions built from the on-disk cache, plus a note on what was and was not found."""
    idx_raw = db.read_cached(db.NIFTY_INDEX, start, end)
    if idx_raw.empty:
        raise RuntimeError(
            "No cached NIFTY index bars. Run: DHAN_ACCESS_TOKEN=... python -m cas_predictor.backfill"
        )

    fut_inst, fut_raw = _resolve_future(start, end, future_key)
    idx_by, fut_by = db.bars_by_session(idx_raw), db.bars_by_session(fut_raw)

    sessions = {d: Session(pd.Timestamp(d), f, fut_by.get(d, pd.DataFrame()))
                for d, f in idx_by.items()}
    meta = {
        "future_label": fut_inst.label if fut_inst else None,
        "n_sessions": len(sessions),
        "n_with_future": sum(1 for s in sessions.values() if not s.future.empty),
        "first": min(sessions) if sessions else None,
        "last": max(sessions) if sessions else None,
    }
    return sessions, meta


def _resolve_future(start, end, future_key: str | None):
    """The cached futures series to pair with the index.

    Dhan delists expired contracts, so the scrip master cannot name the contract that was
    front-month on a past date. Whatever single continuous series is cached is used, and
    sessions before it starts simply get no futures features rather than a stitched-together
    series with a fake gap on the roll.
    """
    keys = [k for k in db.cached_instruments() if k.startswith("NSE_FNO_")]
    if future_key:
        keys = [future_key] if future_key in keys else []
    if not keys:
        return None, pd.DataFrame()
    inst = db.Instrument(keys[0].split("_", 2)[2], "NSE_FNO", "FUTIDX", keys[0])
    return inst, db.read_cached(inst, start, end)


# ---------------------------------------------------- target + freeze integrity
@dataclass(frozen=True)
class FreezeReport:
    freeze_px: float
    final_px: float
    jump_bps: float
    last_bar_hm: str
    flat_from: str | None
    flat_minutes: int
    reprint_hm: str | None


def freeze_report(session: Session) -> FreezeReport | None:
    """Measure the freeze rather than assume it.

    `FREEZE_HM` is the documented boundary, but every session gets checked against what the
    bars actually did: where the flat run starts, how long it lasts, and which minute the
    re-print lands on. A pre-CAS control session produces flat_minutes ~0, which is the
    point -- the same code path must show the effect appearing on 03-Aug rather than being
    told when to look for it.
    """
    f = session.index
    if f.empty:
        return None
    closes = f.close.astype(float)
    freeze_px = float(closes.loc[FREEZE_HM]) if FREEZE_HM in closes.index else np.nan
    if not np.isfinite(freeze_px):
        return None

    last_hm = str(closes.index[-1])
    final_px = float(closes.iloc[-1])

    # Longest run of identical closes ending at or before the final bar.
    post = closes[closes.index > FREEZE_HM]
    flat_from, flat_minutes, reprint_hm = None, 0, None
    if len(post):
        vals, mins = post.to_numpy(dtype=float), list(post.index)
        run_val, run_start, best = vals[0], 0, (0, None)
        for i in range(1, len(vals) + 1):
            if i == len(vals) or vals[i] != run_val:
                if i - run_start > best[0]:
                    best = (i - run_start, mins[run_start])
                if i < len(vals):
                    run_val, run_start = vals[i], i
        flat_minutes, flat_from = best
        if flat_from is not None:
            after = [m for m in mins if m > flat_from]
            base = float(post.loc[flat_from])
            reprint_hm = next((m for m in after if float(post.loc[m]) != base), None)

    return FreezeReport(
        freeze_px=freeze_px,
        final_px=final_px,
        jump_bps=(final_px / freeze_px - 1.0) * 1e4,
        last_bar_hm=last_hm,
        flat_from=flat_from,
        flat_minutes=int(flat_minutes),
        reprint_hm=reprint_hm,
    )


# ------------------------------------------------------------------- building
def build(start: str | date = "2026-06-01", end: str | date | None = None,
          future_key: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """(sessions, nowcast, meta). See the module docstring for what each frame holds."""
    end = end or str(date.today())
    sessions, meta = load_sessions(start, end, future_key)

    rows, now_rows, skipped = [], [], []
    for d in sorted(sessions):
        s = sessions[d]
        rep = freeze_report(s)
        if rep is None:
            skipped.append((d, "no 15:14 index bar"))
            continue
        if rep.last_bar_hm <= FREEZE_HM:
            skipped.append((d, f"session ends at {rep.last_bar_hm}, no post-freeze bars"))
            continue

        row = {
            "date": pd.Timestamp(d),
            "freeze_px": rep.freeze_px,
            "final_px": rep.final_px,
            "jump_bps": rep.jump_bps,
            "last_bar_hm": rep.last_bar_hm,
            "flat_from": rep.flat_from,
            "flat_minutes": rep.flat_minutes,
            "reprint_hm": rep.reprint_hm,
            "has_future": not s.future.empty,
        }
        row.update({k: v for k, v in compute(s, FREEZE_HM, "pre_freeze").items()
                    if k != "_errors"})
        rows.append(row)

        for hm in CHECKPOINTS:
            if hm > rep.last_bar_hm:
                continue
            nr = {"date": pd.Timestamp(d), "as_of": hm, "jump_bps": rep.jump_bps}
            nr.update({k: v for k, v in compute(s, hm, "in_window").items()
                       if k != "_errors"})
            now_rows.append(nr)

    sess = pd.DataFrame(rows).set_index("date").sort_index()
    now = pd.DataFrame(now_rows)

    sess["is_cas"] = sess.index >= CAS_START
    sess["is_rebalance"] = sess.index.isin(REBALANCE_DAYS)
    sess["is_month_end"] = sess.index.to_period("M") != pd.Series(
        sess.index, index=sess.index).shift(-1).dt.to_period("M")
    # A clean CAS freeze is a long flat run starting the minute after the freeze.
    sess["freeze_ok"] = (sess.flat_from == "15:15") & (sess.flat_minutes >= 10)

    _add_trailing(sess)
    if not now.empty:
        now = _normalise_window_volume(now, sess)

    meta["skipped"] = skipped
    meta["n_rows"] = len(sess)
    return sess, now, meta


def _add_trailing(sess: pd.DataFrame) -> None:
    """Trailing statistics, computed strictly on prior sessions and within a single regime.

    `shift(1)` before `rolling` is what makes a row unable to see its own outcome. The
    regime split matters just as much: a window straddling 03-Aug would blend the +1.1 bps
    pre-CAS mean with the +13.8 bps CAS mean and hand early-August rows a trailing average
    that describes a market that no longer existed.
    """
    for col, src in [("trail_jump_mean_bps", sess.jump_bps),
                     ("trail_jump_sd_bps", sess.jump_bps),
                     ("trail_jump_hit", (sess.jump_bps > 0).astype(float))]:
        agg = "std" if col.endswith("sd_bps") else "mean"
        sess[col] = (
            src.groupby(sess.is_cas)
            .transform(lambda s, a=agg: getattr(
                s.shift(1).rolling(TRAIL_WINDOW, min_periods=TRAIL_MIN), a)())
        )
    # Volume normalisation spans the regime break deliberately: the level shift in futures
    # volume is itself informative, and per-regime windows would blank out early August.
    sess["fut_vol_pre30_z"] = _trailing_ratio(sess.fut_vol_pre30)


def _trailing_ratio(s: pd.Series) -> pd.Series:
    med = s.shift(1).rolling(TRAIL_WINDOW, min_periods=TRAIL_MIN).median()
    return s / med.replace(0, np.nan)


def _normalise_window_volume(now: pd.DataFrame, sess: pd.DataFrame) -> pd.DataFrame:
    """Futures window volume against its own trailing median for the SAME checkpoint.

    Volume accumulates through the window, so 15:27 is mechanically larger than 15:17.
    Comparing a checkpoint only against its own history is what makes the ratio mean
    'busier than usual' instead of 'later in the window'.
    """
    now = now.sort_values(["as_of", "date"]).copy()
    now["fut_vol_window_z"] = (
        now.groupby("as_of", group_keys=False)["fut_vol_window"].transform(_trailing_ratio)
    )
    return now.sort_values(["date", "as_of"]).reset_index(drop=True)


# --------------------------------------------------------------------- report
def _report(sess: pd.DataFrame, now: pd.DataFrame, meta: dict) -> None:
    pd.set_option("display.width", 200, "display.max_columns", 40)
    print("=" * 92)
    print("CAS PANEL")
    print("=" * 92)
    print(f"  futures series      : {meta['future_label']}")
    print(f"  sessions            : {meta['n_rows']}  ({meta['first']} .. {meta['last']})")
    print(f"  with futures bars   : {int(sess.has_future.sum())}")
    for d, why in meta["skipped"]:
        print(f"  skipped {d}: {why}")

    print("\n--- freeze integrity (measured, not assumed) ---")
    for label, grp in [("pre-CAS ", sess[~sess.is_cas]), ("CAS     ", sess[sess.is_cas])]:
        if grp.empty:
            continue
        print(f"  {label} n={len(grp):3d}  freeze_ok {int(grp.freeze_ok.sum()):3d}"
              f"  median flat-run {grp.flat_minutes.median():4.0f} min"
              f"  modal flat_from {grp.flat_from.mode().iat[0] if grp.flat_from.notna().any() else '-'}"
              f"  modal reprint {grp.reprint_hm.mode().iat[0] if grp.reprint_hm.notna().any() else '-'}")

    print("\n--- target: jump_bps = (final print / 15:14 close - 1) x 1e4 ---")
    for label, grp in [("pre-CAS", sess[~sess.is_cas]), ("CAS", sess[sess.is_cas])]:
        if len(grp) < 2:
            continue
        j = grp.jump_bps
        t = j.mean() / (j.std(ddof=1) / np.sqrt(len(j)))
        print(f"  {label:8s} n={len(j):3d}  mean {j.mean():+6.1f} bps  sd {j.std():5.1f}"
              f"  t={t:+5.2f}  up {int((j > 0).sum())}/{len(j)}")

    print("\n--- pre-freeze features vs target (as-of 15:14, CAS sessions only) ---")
    cas = sess[sess.is_cas]
    for c in PRE_FREEZE_NAMES + ["trail_jump_mean_bps", "fut_vol_pre30_z"]:
        if c not in cas or cas[c].notna().sum() < 5:
            continue
        r = cas[c].corr(cas.jump_bps, method="spearman")
        print(f"  {c:24s} n={cas[c].notna().sum():3d}  spearman {r:+.3f}")
    print("  (~0.05 expected -- these are controls, not the edge)")

    if not now.empty:
        print("\n--- in-window nowcast by checkpoint (CAS sessions only) ---")
        nc = now[now.date.isin(cas.index)]
        print(f"  {'as_of':>6}  {'n':>3}  {'pearson':>8}  {'spearman':>9}  {'sign-agree':>10}")
        for hm, g in nc.groupby("as_of"):
            g = g.dropna(subset=["fut_drift_bps", "jump_bps"])
            if len(g) < 5:
                continue
            agree = (np.sign(g.fut_drift_bps) == np.sign(g.jump_bps)).mean()
            print(f"  {hm:>6}  {len(g):>3}  {g.fut_drift_bps.corr(g.jump_bps):>+8.3f}"
                  f"  {g.fut_drift_bps.corr(g.jump_bps, method='spearman'):>+9.3f}"
                  f"  {agree:>9.0%}")
        print("\n  index_moved_bps should be ~0 on every CAS checkpoint before the re-print:")
        chk = nc.groupby("as_of").index_moved_bps.apply(lambda s: s.abs().max())
        print("   ", " ".join(f"{k}={v:.1f}" for k, v in chk.items()))


def main() -> None:
    ap = argparse.ArgumentParser(description="Build and report the CAS session panel.")
    ap.add_argument("--from", dest="start", default="2026-06-01")
    ap.add_argument("--to", dest="end", default=None)
    ap.add_argument("--csv", action="store_true", help="write data/panel_*.csv")
    a = ap.parse_args()

    sess, now, meta = build(a.start, a.end)
    _report(sess, now, meta)

    if a.csv:
        from pathlib import Path

        out = Path(__file__).resolve().parent / "data"
        out.mkdir(exist_ok=True)
        sess.to_csv(out / "panel_sessions.csv")
        now.to_csv(out / "panel_nowcast.csv", index=False)
        print(f"\nwrote {out / 'panel_sessions.csv'} and {out / 'panel_nowcast.csv'}")


if __name__ == "__main__":
    main()
