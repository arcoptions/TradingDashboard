"""CAS predictor: forecasting the Nifty jump when the frozen index re-prints at 15:30.

Under NSE's Closing Auction Session (live 03-Aug-2026) the spot index freezes at 15:15
and re-prints off auction closes at ~15:29. This package models that jump.
"""

from .dhan_bars import (  # noqa: F401
    Instrument,
    NIFTY_INDEX,
    bars_by_session,
    equity,
    fetch_bars,
    front_month_future,
    futures_chain,
    resolve_token,
    scrip_master,
    token_expiry,
    token_is_expired,
)
