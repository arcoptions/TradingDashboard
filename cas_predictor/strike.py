"""Price the CAS trade as an option, using the empirical jump distribution.

    DHAN_ACCESS_TOKEN=... python -m cas_predictor.strike [--entry 15:10]

The question a strike suggestion has to answer is not "which way does it go" -- that is the
+11.3 bps drift, already known -- but "does the drift clear the premium". Those are different
questions and only the second one decides whether there is a trade.

So this does not name a strike off direction. It takes the empirical distribution of
(final auction print / entry-minute close) over every completed CAS session, applies it to
today's live spot to get a distribution of settlement prices, and computes each strike's
expected payoff under that distribution. Against the live ask, that gives an edge per strike
in rupees. If nothing clears its premium, the honest output is "no trade", and the tool says
so rather than picking the least-bad strike.

The distribution is measured from the entry minute, not from the 15:14 freeze, because the
4 minutes of continuous trading between them are real risk the buyer carries and pricing off
the freeze would quietly drop them.

n is 26 sessions. An expected-value estimate off 26 draws has a wide standard error, and it
is reported alongside so the number is not read as precision it does not have.
"""

from __future__ import annotations

import argparse
import datetime
import sys
import zoneinfo

import numpy as np
import pandas as pd
import requests

from . import dhan_bars as db

IST = zoneinfo.ZoneInfo("Asia/Kolkata")
QUOTE_URL = "https://api.dhan.co/v2/marketfeed/quote"
CAS_START = pd.Timestamp("2026-08-03").date()
FREEZE_HM = "15:14"
LOT = 75  # NIFTY contract multiplier


def entry_to_settle_bps(entry_hm: str) -> pd.Series:
    """Empirical (final print / entry close - 1) in bps, one value per CAS session.

    Read straight off cached bars rather than through `panel.build`, because the quantity
    the option buyer is exposed to starts at the entry minute -- the panel's target starts
    at the freeze and would understate the risk by however much the index moves in between.
    """
    bars = db.read_cached(db.NIFTY_INDEX)
    if bars.empty:
        raise RuntimeError("no cached index bars -- run backfill first")
    out = {}
    for day, frame in db.bars_by_session(bars).items():
        if day < CAS_START:
            continue
        c = frame.close.astype(float)
        if entry_hm not in c.index or FREEZE_HM not in c.index:
            continue
        # A completed session re-prints after the freeze; today's in-progress one has not.
        after = c[c.index > FREEZE_HM]
        if after.empty or after.iloc[-1] == c[FREEZE_HM]:
            continue
        out[day] = (after.iloc[-1] / c[entry_hm] - 1.0) * 1e4
    return pd.Series(out).sort_index()


def option_chain(expiry: str, spot: float, width: int = 400) -> pd.DataFrame:
    """Listed NIFTY CE/PE for `expiry` within `width` points of spot."""
    sm = db.scrip_master()
    opt = sm[
        (sm["SEM_EXM_EXCH_ID"] == "NSE")
        & (sm["SEM_INSTRUMENT_NAME"] == "OPTIDX")
        & (sm["SEM_TRADING_SYMBOL"].astype(str).str.startswith("NIFTY-"))
    ].copy()
    opt["expiry"] = pd.to_datetime(opt["SEM_EXPIRY_DATE"], errors="coerce").dt.normalize()
    opt = opt[opt.expiry == pd.Timestamp(expiry)]
    opt["strike"] = pd.to_numeric(opt["SEM_STRIKE_PRICE"], errors="coerce")
    opt["right"] = opt["SEM_OPTION_TYPE"].astype(str).str.upper()
    opt = opt[(opt.strike >= spot - width) & (opt.strike <= spot + width)]
    return opt[["SEM_SMST_SECURITY_ID", "SEM_TRADING_SYMBOL", "strike", "right"]].rename(
        columns={"SEM_SMST_SECURITY_ID": "sid", "SEM_TRADING_SYMBOL": "sym"}
    )


def quotes(sids: list[int], token: str) -> dict:
    """Live quote for each securityId. Dhan caps a quote request at 1000 instruments."""
    r = requests.post(
        QUOTE_URL, headers=db._headers(token),
        json={"NSE_FNO": [int(s) for s in sids]}, timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"quote -> {r.status_code}: {r.text[:300]}")
    return r.json().get("data", {}).get("NSE_FNO", {})


def evaluate(chain: pd.DataFrame, q: dict, spot: float, dist: pd.Series) -> pd.DataFrame:
    """Expected settlement payoff per strike vs its live ask."""
    settle = spot * (1.0 + dist.to_numpy() / 1e4)  # one simulated close per past session
    rows = []
    for _, o in chain.iterrows():
        d = q.get(str(int(o.sid))) or {}
        ltp = float(d.get("last_price") or 0.0)
        dep = (d.get("depth") or {})
        asks = dep.get("sell") or []
        bids = dep.get("buy") or []
        ask = float(asks[0]["price"]) if asks and asks[0].get("price") else ltp
        bid = float(bids[0]["price"]) if bids and bids[0].get("price") else ltp
        if ask <= 0:
            continue
        payoff = (np.maximum(settle - o.strike, 0.0) if o.right == "CE"
                  else np.maximum(o.strike - settle, 0.0))
        ev = float(payoff.mean())
        rows.append({
            "sym": o.sym, "right": o.right, "strike": float(o.strike),
            "bid": bid, "ask": ask, "ltp": ltp,
            "ev": ev, "se": float(payoff.std(ddof=1) / np.sqrt(len(payoff))),
            "edge": ev - ask, "p_itm": float((payoff > 0).mean()),
            "p_profit": float((payoff > ask).mean()),
        })
    return pd.DataFrame(rows).sort_values(["right", "strike"])


def main() -> None:
    ap = argparse.ArgumentParser(description="CAS strike selection by expected payoff.")
    ap.add_argument("--entry", default="15:10", help="entry minute, IST (default 15:10)")
    ap.add_argument("--width", type=int, default=400, help="strikes within +/- N of spot")
    a = ap.parse_args()

    token = db.resolve_token()
    if not token:
        sys.exit("No Dhan token. Set DHAN_ACCESS_TOKEN.")
    if db.token_is_expired(token):
        sys.exit(f"Dhan token expired at {db.token_expiry(token)}.")

    dist = entry_to_settle_bps(a.entry)
    today = datetime.datetime.now(IST).date()

    idx = db.fetch_bars(db.NIFTY_INDEX, str(today), str(today), token, use_cache=False)
    if idx.empty:
        sys.exit("no index bars today -- holiday, or the feed is down")
    live = db.bars_by_session(idx)[max(db.bars_by_session(idx))].close.astype(float)
    spot, last_bar = float(live.iloc[-1]), str(live.index[-1])

    exp = str(pd.to_datetime(db.scrip_master()
              .pipe(lambda s: s[(s["SEM_INSTRUMENT_NAME"] == "OPTIDX")
                                & (s["SEM_TRADING_SYMBOL"].astype(str).str.startswith("NIFTY-"))])
              ["SEM_EXPIRY_DATE"]).dt.normalize().pipe(
                  lambda e: e[e >= pd.Timestamp(today)].min()).date())

    print(f"\n[{datetime.datetime.now(IST):%H:%M:%S} IST]  spot {spot:,.2f} (bar {last_bar})  "
          f"front expiry {exp}{'  <-- TODAY' if exp == str(today) else ''}")
    print(f"entry->settle distribution from {a.entry}, n={len(dist)} CAS sessions: "
          f"mean {dist.mean():+.1f} bps ({dist.mean() * spot / 1e4:+.0f} pts), "
          f"sd {dist.std():.1f}, up {int((dist > 0).sum())}/{len(dist)}")
    lo, hi = np.percentile(dist, [10, 90])
    print(f"  80% band {lo:+.0f} to {hi:+.0f} bps  "
          f"=  {spot * (1 + lo / 1e4):,.0f} to {spot * (1 + hi / 1e4):,.0f}")

    chain = option_chain(exp, spot, a.width)
    if chain.empty:
        sys.exit(f"no listed NIFTY options for {exp} near {spot:,.0f}")
    res = evaluate(chain, quotes(chain.sid.tolist(), token), spot, dist)
    if res.empty:
        sys.exit("no tradeable quotes returned")

    print(f"\n{'strike':>8} {'r':>3} {'bid':>7} {'ask':>7} {'EV':>7} {'+/-':>6} "
          f"{'edge':>7} {'P(itm)':>7} {'P(win)':>7}  per lot")
    for _, r in res.iterrows():
        flag = "  <<<" if r.edge > 0 else ""
        print(f"{r.strike:>8,.0f} {r.right:>3} {r.bid:>7.2f} {r.ask:>7.2f} {r.ev:>7.2f} "
              f"{r.se:>6.2f} {r.edge:>+7.2f} {r.p_itm:>6.0%} {r.p_profit:>6.0%}  "
              f"{r.edge * LOT:>+8,.0f}{flag}")

    best = res.loc[res.edge.idxmax()]
    print()
    if best.edge <= 0:
        print(f"NO TRADE. Every strike is priced above its expected payoff. Closest is "
              f"{best.sym} at {best.ask:.2f} vs EV {best.ev:.2f} "
              f"(edge {best.edge:+.2f}, {best.edge * LOT:+,.0f}/lot).")
        print("The +11 bps drift is real but the market is already charging more than it.")
    else:
        print(f"BEST: {best.sym}  ask {best.ask:.2f}  EV {best.ev:.2f} +/- {best.se:.2f}  "
              f"edge {best.edge:+.2f} ({best.edge * LOT:+,.0f}/lot)  "
              f"P(profit) {best.p_profit:.0%}")
        if best.edge < 2 * best.se:
            print(f"  CAUTION: the edge is inside one standard error of the EV estimate "
                  f"(+/-{best.se:.2f} off {len(dist)} sessions). Not distinguishable from zero.")


if __name__ == "__main__":
    main()
