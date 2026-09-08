"""Feature definitions for the CAS predictor, each pinned to an explicit as-of minute.

The leakage guard is mechanical, not documentary. A feature never receives a session's bar
frame; it receives a `View` whose series are truncated at the decision minute, so asking for
a later bar raises `LeakageError` instead of quietly returning a number that would not have
existed when the trade had to be placed.

That discipline is here because the exploratory study hit the same class of bug in a
different form: `final_price_T` appeared on both sides of a correlation and manufactured a
strong-looking result out of an accounting identity. A declared as-of in a docstring would
not have caught it; a truncated series would have.

Timeline of an NSE session under CAS (verified from Dhan 1-minute bars, not documentation):

    09:15           open
    15:14           last minute of continuous cash trading
    15:15 -> 15:28  spot index FROZEN (flat closes, constant volume); futures trade on,
                    with rising volume -- this is the tradeable window
    15:28 / 15:29   index re-prints off the auction closes; that jump is the target
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

import numpy as np
import pandas as pd

SESSION_OPEN_HM = "09:15"
#: Last minute of continuous cash trading. Empirical, not assumed -- `panel.freeze_report`
#: re-derives it per session so a change in NSE's timings shows up as a warning rather than
#: as silently wrong features.
FREEZE_HM = "15:14"
WINDOW_END_HM = "15:29"

#: Minutes at which the nowcast re-predicts. 15:29 is included to measure the ceiling; it is
#: not tradeable, since the auction has matched by then.
CHECKPOINTS = ["15:17", "15:19", "15:21", "15:23", "15:25", "15:27", "15:29"]


class LeakageError(RuntimeError):
    """A feature asked for a bar later than the decision minute it was granted."""


def hm_shift(hm: str, minutes: int) -> str:
    """'15:19' shifted by +/- n minutes, as 'HH:MM'. Same-day only; no wraparound."""
    t = datetime.strptime(hm, "%H:%M") + timedelta(minutes=minutes)
    return t.strftime("%H:%M")


# ---------------------------------------------------------------- the leakage guard
class Series:
    """One session's bars for one instrument, truncated at `as_of`.

    Zero-padded 'HH:MM' strings order lexicographically the same way they order in time, so
    plain string comparison is a correct time comparison here and needs no parsing.
    """

    __slots__ = ("_f", "as_of", "label")

    def __init__(self, frame: pd.DataFrame | None, as_of: str, label: str = "series"):
        self.as_of = as_of
        self.label = label
        self._f = None if frame is None or frame.empty else frame[frame.index <= as_of]

    @property
    def empty(self) -> bool:
        return self._f is None or self._f.empty

    def _guard(self, hm: str) -> None:
        if hm > self.as_of:
            raise LeakageError(f"{self.label}: asked for {hm} but as-of is {self.as_of}")

    def close(self, hm: str) -> float:
        """Close of the bar at exactly `hm`; NaN if that minute did not print."""
        self._guard(hm)
        if self.empty or hm not in self._f.index:
            return np.nan
        return float(self._f.close.loc[hm])

    def last_close(self) -> float:
        return np.nan if self.empty else float(self._f.close.iloc[-1])

    def closes(self, lo: str, hi: str) -> pd.Series:
        self._guard(hi)
        if self.empty:
            return pd.Series(dtype=float)
        s = self._f.close.astype(float)
        return s[(s.index >= lo) & (s.index <= hi)]

    def volume(self, lo: str, hi: str) -> float:
        self._guard(hi)
        if self.empty or "volume" not in self._f.columns:
            return np.nan
        v = self._f.volume
        return float(v[(v.index >= lo) & (v.index <= hi)].sum())

    def flat_run(self) -> int:
        """How many trailing bars share the last close. The freeze detector."""
        if self.empty:
            return 0
        c = self._f.close.to_numpy(dtype=float)
        n = 1
        while n < len(c) and c[-1 - n] == c[-1]:
            n += 1
        return n


@dataclass(frozen=True)
class View:
    """What a feature is allowed to see: two clamped series and the decision minute."""

    date: pd.Timestamp
    as_of: str
    index: Series
    future: Series


@dataclass
class Session:
    """Raw material for one session. Features never touch this -- only `view()` output."""

    date: pd.Timestamp
    index: pd.DataFrame  # indexed by 'HH:MM'
    future: pd.DataFrame

    def view(self, as_of: str) -> View:
        d = self.date.date()
        return View(
            date=self.date,
            as_of=as_of,
            index=Series(self.index, as_of, f"index {d}"),
            future=Series(self.future, as_of, f"future {d}"),
        )


# --------------------------------------------------------------------- helpers
def _bps(a: float, b: float) -> float:
    """(a/b - 1) in basis points, NaN-safe."""
    if not (np.isfinite(a) and np.isfinite(b)) or b == 0:
        return np.nan
    return (a / b - 1.0) * 1e4


# ----------------------------------------------------------- pre-freeze features
# Everything knowable at 15:14 -- a genuine forecast. The study measured these at ~0.05
# correlation with the jump, so the expectation is that they are near-useless. They are here
# to be reported as such and to act as controls, not because they are believed to work.
def f_day_ret_bps(v: View) -> float:
    return _bps(v.index.close(FREEZE_HM), v.index.close(SESSION_OPEN_HM))


def f_mom30_bps(v: View) -> float:
    return _bps(v.index.close(FREEZE_HM), v.index.close(hm_shift(FREEZE_HM, -30)))


def f_mom5_bps(v: View) -> float:
    return _bps(v.index.close(FREEZE_HM), v.index.close(hm_shift(FREEZE_HM, -5)))


def f_rvol30_bps(v: View) -> float:
    """Per-minute realised vol of the index over the half hour into the freeze."""
    c = v.index.closes(hm_shift(FREEZE_HM, -29), FREEZE_HM)
    if len(c) < 10:
        return np.nan
    return float(c.pct_change().dropna().std() * 1e4)


def f_basis_bps(v: View) -> float:
    return _bps(v.future.close(FREEZE_HM), v.index.close(FREEZE_HM))


def f_basis_chg30_bps(v: View) -> float:
    back = hm_shift(FREEZE_HM, -30)
    now = _bps(v.future.close(FREEZE_HM), v.index.close(FREEZE_HM))
    then = _bps(v.future.close(back), v.index.close(back))
    return now - then


def f_fut_vol_pre30(v: View) -> float:
    """Raw futures volume in the half hour into the freeze; normalised in panel.py."""
    return v.future.volume(hm_shift(FREEZE_HM, -29), FREEZE_HM)


def f_dow(v: View) -> float:
    return float(v.date.dayofweek)


# ------------------------------------------------------------ in-window features
# The nowcast. Spot is frozen but futures trade, so these are knowable AND tradeable at
# `as_of`. Futures drift is the backbone: 15:14->15:29 vs the actual jump measured
# pearson +0.573 over 22 sessions, and was already +0.311 by 15:24.
def f_fut_drift_bps(v: View) -> float:
    return _bps(v.future.close(v.as_of), v.future.close(FREEZE_HM))


def f_fut_drift_accel_bps(v: View) -> float:
    """Recent 5-minute drift minus the 5 before it. Both legs stay inside the window."""
    mid, early = hm_shift(v.as_of, -5), hm_shift(v.as_of, -10)
    if early < FREEZE_HM:
        return np.nan
    recent = _bps(v.future.close(v.as_of), v.future.close(mid))
    prior = _bps(v.future.close(mid), v.future.close(early))
    return recent - prior


def f_fut_gap_bps(v: View) -> float:
    """How far the futures basis has widened since the freeze.

    Distinct from raw drift: the frozen index is a constant over the window, so this is
    drift measured against a stale spot rather than against the futures' own start. When
    the two disagree the freeze is not clean.
    """
    now = _bps(v.future.close(v.as_of), v.index.close(v.as_of))
    at_freeze = _bps(v.future.close(FREEZE_HM), v.index.close(FREEZE_HM))
    return now - at_freeze


def f_fut_vol_window(v: View) -> float:
    """Raw futures volume from the freeze to now; normalised in panel.py."""
    return v.future.volume(hm_shift(FREEZE_HM, 1), v.as_of)


def f_index_moved_bps(v: View) -> float:
    """Index move since the freeze. A VALIDATION feature, not a predictor.

    Under a clean CAS freeze this is exactly 0 until the re-print. Non-zero before 15:28
    means the session did not freeze as expected -- a pre-CAS control day, a partial
    session, or a data problem -- and the row should be treated with suspicion.
    """
    return _bps(v.index.close(v.as_of), v.index.close(FREEZE_HM))


@dataclass(frozen=True)
class Feature:
    name: str
    kind: str  # 'pre_freeze' (as-of 15:14) | 'in_window' (as-of the checkpoint)
    fn: Callable[[View], float]
    doc: str


FEATURES: list[Feature] = [
    Feature("day_ret_bps", "pre_freeze", f_day_ret_bps, "index open -> freeze"),
    Feature("mom30_bps", "pre_freeze", f_mom30_bps, "index 30-min momentum into freeze"),
    Feature("mom5_bps", "pre_freeze", f_mom5_bps, "index 5-min momentum into freeze"),
    Feature("rvol30_bps", "pre_freeze", f_rvol30_bps, "per-minute realised vol into freeze"),
    Feature("basis_bps", "pre_freeze", f_basis_bps, "futures basis at freeze"),
    Feature("basis_chg30_bps", "pre_freeze", f_basis_chg30_bps, "basis change over 30 min"),
    Feature("fut_vol_pre30", "pre_freeze", f_fut_vol_pre30, "raw futures volume into freeze"),
    Feature("dow", "pre_freeze", f_dow, "day of week, 0=Mon"),
    Feature("fut_drift_bps", "in_window", f_fut_drift_bps, "futures move since freeze"),
    Feature("fut_drift_accel_bps", "in_window", f_fut_drift_accel_bps, "drift acceleration"),
    Feature("fut_gap_bps", "in_window", f_fut_gap_bps, "basis widening since freeze"),
    Feature("fut_vol_window", "in_window", f_fut_vol_window, "raw futures volume since freeze"),
    Feature("index_moved_bps", "in_window", f_index_moved_bps, "VALIDATION: freeze integrity"),
]

PRE_FREEZE_NAMES = [f.name for f in FEATURES if f.kind == "pre_freeze"]
IN_WINDOW_NAMES = [f.name for f in FEATURES if f.kind == "in_window"]


def compute(session: Session, as_of: str, kind: str) -> dict[str, float]:
    """Every `kind` feature for `session`, decided at `as_of`.

    A feature that raises is recorded as NaN with its error kept in `_errors`; a feature
    that raises `LeakageError` is NOT swallowed, because that is a bug in the feature rather
    than a gap in the data.
    """
    view = session.view(as_of)
    out: dict[str, float] = {}
    errors: dict[str, str] = {}
    for f in FEATURES:
        if f.kind != kind:
            continue
        try:
            out[f.name] = float(f.fn(view))
        except LeakageError:
            raise
        except Exception as e:
            out[f.name] = np.nan
            errors[f.name] = f"{type(e).__name__}: {e}"
    if errors:
        out["_errors"] = errors  # type: ignore[assignment]
    return out
