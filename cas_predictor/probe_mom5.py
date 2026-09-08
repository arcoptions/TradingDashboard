"""Probe the one surprising number in the panel: mom5_bps vs the jump, spearman +0.72.

That correlation, if real, matters more than anything else found so far -- it is knowable at
15:14, which makes it a forecast rather than the nowcast the futures-drift signal gives. The
earlier study concluded nothing pre-freeze predicted the jump, but it only ever tested day
return (+0.034) and basis (-0.053). It never looked at 5-minute momentum.

Four ways it could be fake, each tested here:

  1. SHARED PRICE. mom5 = P1514/P1509 and jump = Pfinal/P1514. The 15:14 print sits in the
     numerator of one and the denominator of the other, so its noise moves them oppositely.
     That biases the correlation NEGATIVE, meaning it cannot manufacture the +0.72 -- but the
     clean variant P1513/P1508, which shares no price with the target, has to confirm it.
  2. ONE OR TWO DAYS. At n=22 a pair of outliers can carry a rank correlation on its own.
  3. GENERIC MOMENTUM. If it works pre-CAS too then it is a property of late-afternoon
     drift, not of the auction, and the CAS framing is wrong.
  4. NOT TRADEABLE. A correlation is not an edge. What counts is the hit rate, the points,
     and how many sessions it actually disagrees with always-long on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import dhan_bars as db
from .features import FREEZE_HM, hm_shift
from .panel import CAS_START, build

LVL = 26_000  # Nifty level, for turning bps into points


def _mom(closes: pd.Series, end_hm: str, minutes: int) -> float:
    a, b = end_hm, hm_shift(end_hm, -minutes)
    if a not in closes.index or b not in closes.index:
        return np.nan
    return (float(closes[a]) / float(closes[b]) - 1.0) * 1e4


def variants() -> pd.DataFrame:
    """Momentum measured over several windows and end-minutes, plus the target."""
    idx = db.bars_by_session(db.read_cached(db.NIFTY_INDEX, "2026-06-01", None))
    rows = []
    for d, f in sorted(idx.items()):
        c = f.close.astype(float)
        if FREEZE_HM not in c.index or str(c.index[-1]) <= FREEZE_HM:
            continue
        row = {"date": pd.Timestamp(d),
               "jump_bps": (float(c.iloc[-1]) / float(c[FREEZE_HM]) - 1.0) * 1e4}
        for n in (2, 3, 5, 10, 15, 30):
            row[f"mom{n}"] = _mom(c, FREEZE_HM, n)
        # Clean variants: end one and two minutes early, so the 15:14 print -- the target's
        # own denominator -- appears nowhere in the signal.
        for lag in (1, 2):
            end = hm_shift(FREEZE_HM, -lag)
            for n in (5, 10):
                row[f"mom{n}_lag{lag}"] = _mom(c, end, n)
        rows.append(row)
    p = pd.DataFrame(rows).set_index("date").sort_index()
    p["is_cas"] = p.index >= CAS_START
    return p


def _sp(a: pd.Series, b: pd.Series) -> float:
    return a.corr(b, method="spearman")


def main() -> None:
    pd.set_option("display.width", 200, "display.max_columns", 40)
    p = variants()
    cas, pre = p[p.is_cas], p[~p.is_cas]
    print(f"CAS sessions {len(cas)}   pre-CAS control {len(pre)}\n")

    # ---------------------------------------------------------------- 1 + 3
    print("=" * 88)
    print("(1) SHARED-PRICE CONTAMINATION  and  (3) IS IT JUST GENERIC MOMENTUM?")
    print("=" * 88)
    print("  lag0 signals end at 15:14 and share that print with the target's denominator.")
    print("  lag1/lag2 end at 15:13/15:12 and share nothing. If the effect survives the lag,")
    print("  the shared price is not what is driving it.\n")
    print(f"  {'signal':>12}  {'CAS spearman':>13}  {'pre-CAS':>9}  {'CAS pearson':>12}")
    for c in ["mom2", "mom3", "mom5", "mom10", "mom15", "mom30",
              "mom5_lag1", "mom10_lag1", "mom5_lag2", "mom10_lag2"]:
        print(f"  {c:>12}  {_sp(cas[c], cas.jump_bps):>+13.3f}"
              f"  {_sp(pre[c], pre.jump_bps):>+9.3f}"
              f"  {cas[c].corr(cas.jump_bps):>+12.3f}")
    print("\n  Noise threshold at n=22 is roughly +/-0.43 (2/sqrt(n)); at n=44, +/-0.30.")

    # ---------------------------------------------------------------------- 2
    print()
    print("=" * 88)
    print("(2) IS IT ONE OR TWO DAYS?  jackknife -- drop each session, recompute")
    print("=" * 88)
    for c in ["mom5", "mom5_lag1"]:
        g = cas[[c, "jump_bps"]].dropna()
        jk = pd.Series({d: _sp(g.drop(d)[c], g.drop(d).jump_bps) for d in g.index})
        print(f"  {c:>10}  full {_sp(g[c], g.jump_bps):+.3f}   "
              f"jackknife range {jk.min():+.3f} .. {jk.max():+.3f}")
        worst = jk.idxmax()  # dropping this day RAISES the correlation most => it hurts least
        best = jk.idxmin()   # dropping this day LOWERS it most => it carries the result
        print(f"             most load-bearing session: {best.date()} "
              f"(drops to {jk.min():+.3f})   mom5={g.loc[best, c]:+.1f} "
              f"jump={g.loc[best, 'jump_bps']:+.1f}")
        print(f"             most contrary session:     {worst.date()} "
              f"(rises to {jk.max():+.3f})   mom5={g.loc[worst, c]:+.1f} "
              f"jump={g.loc[worst, 'jump_bps']:+.1f}")

    # ---------------------------------------------------------------------- 4
    print()
    print("=" * 88)
    print("(4) IS IT TRADEABLE?  sign rules on CAS sessions, P&L in Nifty points")
    print("=" * 88)
    g = cas.dropna(subset=["mom5", "mom5_lag1", "jump_bps"])
    tgt = g.jump_bps
    print(f"  {'rule':>26}  {'n':>3}  {'hit':>5}  {'pts/session':>11}  {'t':>6}  {'differs':>7}")

    def show(name: str, sign: pd.Series) -> None:
        m = sign != 0
        pnl = (sign[m] * tgt[m]) * LVL * 1e-4
        t = pnl.mean() / (pnl.std(ddof=1) / np.sqrt(len(pnl))) if len(pnl) > 1 else np.nan
        hit = (np.sign(tgt[m]) == sign[m]).mean()
        differs = int((sign[m] != 1).sum())  # sessions where it is NOT just always-long
        print(f"  {name:>26}  {int(m.sum()):>3}  {hit:>5.0%}  {pnl.mean():>+11.1f}"
              f"  {t:>+6.2f}  {differs:>7}")

    show("always long", pd.Series(1, index=g.index))
    show("sign(mom5)", np.sign(g.mom5))
    show("sign(mom5_lag1)", np.sign(g.mom5_lag1))
    show("long unless mom5 < -10bps", pd.Series(
        np.where(g.mom5 < -10, -1, 1), index=g.index))
    show("perfect foresight", np.sign(tgt))

    print("\n  'differs' is the only honest sample size for any claim of edge over always-long.")
    print("  The earlier study's '73% hit rate' collapsed on exactly this column: the rule")
    print("  differed from always-long on 4 sessions and happened to get 3 of them right.")

    print()
    print("=" * 88)
    print("SIGN AGREEMENT BETWEEN mom5 AND THE JUMP, SESSION BY SESSION")
    print("=" * 88)
    tab = g[["mom5", "mom5_lag1", "jump_bps"]].copy()
    tab["agree"] = np.where(np.sign(tab.mom5) == np.sign(tab.jump_bps), "yes", "NO")
    tab["pts"] = tab.jump_bps * LVL * 1e-4
    print(tab.round(1).to_string())


if __name__ == "__main__":
    main()
