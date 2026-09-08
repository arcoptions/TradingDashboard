"""Honest evaluation of CAS direction rules.

The finding this module exists to guard against: **always-long is a strong baseline**. Over
the 22 CAS sessions it hits 82% for +35.9 Nifty points a session (t=+2.64), because the
auction window has a structural upward drift of +13.8 bps. Only **4 sessions were down**.

So the entire prize for "predicting direction" is those 4 sessions. A rule that never shorts
gives up nothing; a rule that shorts on the wrong days gives up a lot. Every metric here is
therefore reported against always-long rather than against a coin flip, and every rule
reports `differs` -- the count of sessions where it actually departs from always-long. That
column is the real sample size behind any claim of edge, and it is usually humiliating.

Three specific traps, each checked:

  THRESHOLD PEEKING. "Short when drift < -5 bps" catches 3 of the 4 down days beautifully.
  It also had -5 chosen by a human who had already seen all 22 outcomes. `walk_forward`
  re-picks the threshold using only prior sessions, which is the only version that means
  anything.

  MAGNITUDE MASQUERADING AS ACCURACY. A rule can lose on hit rate and still win on P&L by
  catching a few large moves. That is a real effect but it rests on fewer sessions than the
  hit rate does, so both are always printed together.

  CONFIDENCE INTERVALS. At n=22 a hit rate carries roughly +/-20 points. At n=4 -- the down
  sessions -- it carries nothing at all. Wilson intervals are printed so the width is
  impossible to overlook.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .panel import build

#: Nifty level used to convert bps into points. Round number on purpose -- this is for
#: sizing intuition, not for P&L accounting.
LVL = 26_000
BOOTSTRAP_N = 10_000
SEED = 20260901


# ------------------------------------------------------------------ statistics
def wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval. Correct at small n, where the normal approximation is not."""
    if n == 0:
        return (np.nan, np.nan)
    p = hits / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_diff(a: np.ndarray, b: np.ndarray, n: int = BOOTSTRAP_N) -> tuple[float, float]:
    """95% CI on mean(a) - mean(b) for paired per-session P&L, resampling sessions."""
    if len(a) < 3:
        return (np.nan, np.nan)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(a), size=(n, len(a)))
    d = (a[idx] - b[idx]).mean(axis=1)
    return tuple(np.percentile(d, [2.5, 97.5]))


@dataclass
class Result:
    name: str
    n: int
    hit: float
    ci: tuple[float, float]
    pts: float
    t: float
    differs: int
    down_caught: int
    false_short: int
    vs_long: float
    vs_long_ci: tuple[float, float]


def evaluate(name: str, sign: pd.Series, target: pd.Series) -> Result:
    """`sign` in {-1, 0, +1}; 0 means stand aside. P&L is sign * jump, in Nifty points."""
    m = sign != 0
    s, tgt = sign[m], target[m]
    pnl = (s * tgt).to_numpy() * LVL * 1e-4
    long_pnl = tgt.to_numpy() * LVL * 1e-4  # always-long over the SAME sessions
    hits = int((np.sign(tgt) == s).sum())
    t = pnl.mean() / (pnl.std(ddof=1) / np.sqrt(len(pnl))) if len(pnl) > 1 else np.nan
    down = target < 0
    return Result(
        name=name,
        n=int(m.sum()),
        hit=hits / max(len(s), 1),
        ci=wilson_ci(hits, len(s)),
        pts=float(pnl.mean()),
        t=float(t),
        differs=int((s != 1).sum()),
        down_caught=int(((sign < 0) & down).sum()),
        false_short=int(((sign < 0) & ~down).sum()),
        vs_long=float(pnl.mean() - long_pnl.mean()),
        vs_long_ci=bootstrap_diff(pnl, long_pnl),
    )


def table(results: list[Result], n_down: int) -> None:
    print(f"  {'rule':>30} {'n':>3} {'hit':>5} {'95% CI':>13} {'pts':>7} {'t':>6}"
          f" {'diff':>5} {'down':>5} {'false':>6} {'vs long':>8} {'95% CI':>16}")
    for r in results:
        ci = f"{r.ci[0]:.0%}-{r.ci[1]:.0%}"
        vci = ("     n/a" if not np.isfinite(r.vs_long_ci[0])
               else f"[{r.vs_long_ci[0]:+.0f},{r.vs_long_ci[1]:+.0f}]")
        print(f"  {r.name:>30} {r.n:>3} {r.hit:>5.0%} {ci:>13} {r.pts:>+7.1f} {r.t:>+6.2f}"
              f" {r.differs:>5} {r.down_caught:>2}/{n_down} {r.false_short:>6}"
              f" {r.vs_long:>+8.1f} {vci:>16}")


# ----------------------------------------------------------------- the rules
def threshold_sign(drift: pd.Series, thr: float) -> pd.Series:
    """Long unless the futures drift is below `thr`, in which case short."""
    return pd.Series(np.where(drift < thr, -1.0, 1.0), index=drift.index)


def walk_forward(drift: pd.Series, target: pd.Series, grid: np.ndarray,
                 min_train: int = 10) -> tuple[pd.Series, pd.Series]:
    """Re-pick the threshold each session using only prior sessions.

    Returns (signal, chosen_threshold), both NaN over the training prefix. This is the only
    version of the threshold rule that is not fitted on its own test set -- and with 22
    sessions and a 10-session warm-up, it leaves 12 sessions and typically 2 down days to
    judge on, which is the honest amount of evidence available.
    """
    sig = pd.Series(np.nan, index=drift.index)
    chosen = pd.Series(np.nan, index=drift.index)
    for i in range(min_train, len(drift)):
        tr_d, tr_y = drift.iloc[:i], target.iloc[:i]
        best, best_pnl = np.nan, -np.inf
        for thr in grid:
            pnl = (threshold_sign(tr_d, thr) * tr_y).mean()
            if pnl > best_pnl:
                best, best_pnl = thr, pnl
        chosen.iloc[i] = best
        sig.iloc[i] = -1.0 if drift.iloc[i] < best else 1.0
    return sig, chosen


# -------------------------------------------------------------------- driver
def run(as_of: str = "15:27", start: str = "2026-06-01", min_train: int = 10) -> None:
    sess, now, _ = build(start)
    cas = sess[sess.is_cas]
    w = now[now.date.isin(cas.index) & (now.as_of == as_of)].set_index("date")
    df = pd.DataFrame({"jump": cas.jump_bps, "drift": w.fut_drift_bps,
                       "mom5": cas.mom5_bps}).dropna().sort_index()
    tgt, n_down = df.jump, int((df.jump < 0).sum())

    print("=" * 118)
    print(f"CAS DIRECTION BACKTEST  --  decision at {as_of}, {len(df)} CAS sessions")
    print("=" * 118)
    print(f"  target mean {tgt.mean():+.1f} bps ({tgt.mean()*LVL*1e-4:+.1f} pts), "
          f"sd {tgt.std():.1f}, up {int((tgt>0).sum())}/{len(tgt)}")
    print(f"  DOWN SESSIONS: {n_down}. That is the entire prize. A rule can only beat")
    print(f"  always-long by shorting some of those {n_down} without shorting the other "
          f"{len(df)-n_down}.\n")

    ones = pd.Series(1.0, index=df.index)
    results = [
        evaluate("always long", ones, tgt),
        evaluate("always short", -ones, tgt),
        evaluate("sign(futures drift)", np.sign(df.drift).replace(0, 1), tgt),
        evaluate("sign(mom5, pre-freeze)", np.sign(df.mom5).replace(0, 1), tgt),
    ]
    for thr in (-2.0, -5.0, -8.0):
        results.append(evaluate(f"short if drift < {thr:+.0f} bps  [PEEKED]",
                                threshold_sign(df.drift, thr), tgt))
    results.append(evaluate("perfect foresight", np.sign(tgt), tgt))
    table(results, n_down)

    print("\n  'diff'  = sessions where the rule departs from always-long -- the real n.")
    print("  'down'  = down sessions correctly shorted.  'false' = up sessions wrongly shorted.")
    print("  [PEEKED] rules had their threshold chosen with all 22 outcomes already visible.")
    print("  They are shown to size the effect, and must not be read as achievable.")

    # ------------------------------------------------------------- walk-forward
    print()
    print("=" * 118)
    print(f"WALK-FORWARD  --  threshold re-picked each session on prior data only "
          f"({min_train}-session warm-up)")
    print("=" * 118)
    sig, chosen = walk_forward(df.drift, tgt, np.arange(-15, 1, 0.5), min_train)
    live = sig.dropna().index
    if len(live) < 3:
        print("  Not enough sessions after the warm-up to evaluate.")
        return
    sub, n_down_live = tgt.loc[live], int((tgt.loc[live] < 0).sum())
    table([evaluate("always long", pd.Series(1.0, index=live), sub),
           evaluate("walk-forward threshold", sig.loc[live], sub)], n_down_live)

    print(f"\n  Test window: {live[0].date()} .. {live[-1].date()}  "
          f"({len(live)} sessions, {n_down_live} of them down)")
    print(f"  Threshold chosen: {chosen.dropna().min():+.1f} to {chosen.dropna().max():+.1f} bps"
          f"  (changed {int((chosen.dropna().diff() != 0).sum())} times)")
    print("\n  Read the 'vs long' CI, not the point estimate. If it spans zero -- and at this")
    print(f"  sample size it will -- the rule is not distinguishable from always-long on "
          f"{n_down_live} down sessions.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest CAS direction rules against always-long.")
    ap.add_argument("--as-of", default="15:27", help="nowcast decision minute")
    ap.add_argument("--from", dest="start", default="2026-06-01")
    ap.add_argument("--min-train", type=int, default=10)
    a = ap.parse_args()
    run(a.as_of, a.start, a.min_train)


if __name__ == "__main__":
    main()
