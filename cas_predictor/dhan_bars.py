"""Dhan 1-minute bar access with an on-disk parquet cache.

Deliberately dependency-free beyond pandas/requests: no Django, no Streamlit. The live
paths (the `collect_cas` management command and the CAS page in `django_v1/`) import this
module directly, and so does plain research code. Keeping it framework-agnostic is also
what makes the package portable to wherever the deployed Django source actually lives.

Token resolution order: explicit argument -> DHAN_ACCESS_TOKEN env var (this is how the
Django app on Azure App Service gets it) -> legacy Streamlit Google Sheets settings.
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

IST = "Asia/Kolkata"
INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"
CACHE_DIR = Path(__file__).resolve().parent / "cache"

# Dhan rejects intraday ranges much wider than this.
MAX_SPAN_DAYS = 30
# Historical-data endpoint is rate limited; stay well under it.
INTER_CALL_SLEEP = 0.35


@dataclass(frozen=True)
class Instrument:
    security_id: str
    segment: str
    instrument: str
    label: str

    @property
    def key(self) -> str:
        return f"{self.segment}_{self.security_id}"


#: The Nifty 50 spot index. Freezes at 15:15 under CAS and re-prints off auction closes.
NIFTY_INDEX = Instrument("13", "IDX_I", "INDEX", "NIFTY")


# --------------------------------------------------------------------------- auth
def _decode_jwt_payload(token: str) -> dict:
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        return json.loads(base64.urlsafe_b64decode(part))
    except Exception:
        return {}


def resolve_token(token: str | None = None) -> str:
    """Explicit token, else DHAN_ACCESS_TOKEN, else the legacy Streamlit app's settings."""
    if token:
        return token.strip()
    env = os.environ.get("DHAN_ACCESS_TOKEN", "").strip()
    if env:
        return env
    try:  # legacy Streamlit path only; absent in the Django app
        from integrations.google_sheets import fetch_settings_dict

        return str(fetch_settings_dict().get("Dhan Access Token", "")).strip()
    except Exception:
        return ""


def token_expiry(token: str) -> datetime | None:
    exp = _decode_jwt_payload(token).get("exp")
    return datetime.fromtimestamp(exp) if exp else None


def token_is_expired(token: str) -> bool:
    exp = token_expiry(token)
    return exp is None or exp <= datetime.now()


def client_id_from_token(token: str) -> str:
    return str(_decode_jwt_payload(token).get("dhanClientId", "")).strip()


def _headers(token: str, client_id: str | None = None) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "access-token": token,
        "client-id": client_id or client_id_from_token(token),
    }


# ------------------------------------------------------------------- scrip master
def scrip_master(max_age_hours: int = 12) -> pd.DataFrame:
    """Dhan's instrument list, cached to disk and refreshed twice a day."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / "scrip_master.parquet"
    if path.exists():
        age_h = (time.time() - path.stat().st_mtime) / 3600
        if age_h < max_age_hours:
            return pd.read_parquet(path)
    raw = requests.get(SCRIP_MASTER_URL, timeout=120).text
    df = pd.read_csv(io.StringIO(raw), low_memory=False)
    df.to_parquet(path, index=False)
    return df


def futures_chain(symbol: str = "NIFTY") -> pd.DataFrame:
    """All listed index-future contracts for `symbol`, ascending by expiry."""
    sm = scrip_master()
    prefix = f"{symbol.upper()}-"
    fut = sm[
        (sm["SEM_EXM_EXCH_ID"] == "NSE")
        & (sm["SEM_INSTRUMENT_NAME"] == "FUTIDX")
        & (sm["SEM_TRADING_SYMBOL"].astype(str).str.upper().str.startswith(prefix))
    ].copy()
    fut["expiry"] = pd.to_datetime(fut["SEM_EXPIRY_DATE"], errors="coerce")
    return fut.dropna(subset=["expiry"]).sort_values("expiry")


def front_month_future(as_of: date | str, symbol: str = "NIFTY") -> Instrument:
    """The nearest contract that has NOT yet expired as of `as_of`.

    Rolls on the expiry DATE, not the calendar month — an August date resolves to the
    August contract right up to its expiry, and to September only afterwards. Getting
    this wrong stitches two different contracts into one series and silently injects a
    fake gap on the roll day.

    CAVEAT for historical dates: the chain only contains contracts Dhan still lists, so
    already-expired months are gone. Asking for 03-Aug-2026 today returns the September
    contract (then the second month), not the August one. That keeps the backtest on a
    single unbroken series, but pre-roll bars are second-month and therefore thinner.
    """
    as_of = pd.Timestamp(as_of).normalize()
    chain = futures_chain(symbol)
    live = chain[chain["expiry"].dt.normalize() >= as_of]
    if live.empty:
        raise ValueError(f"No {symbol} future listed on or after {as_of.date()}")
    row = live.iloc[0]
    return Instrument(
        security_id=str(int(row["SEM_SMST_SECURITY_ID"])),
        segment="NSE_FNO",
        instrument="FUTIDX",
        label=str(row["SEM_TRADING_SYMBOL"]),
    )


def equity(symbol: str) -> Instrument:
    """Resolve an NSE cash-segment EQ scrip."""
    sm = scrip_master()
    m = sm[
        (sm["SEM_EXM_EXCH_ID"] == "NSE")
        & (sm["SEM_SEGMENT"] == "E")
        & (sm["SEM_SERIES"] == "EQ")
        & (sm["SEM_TRADING_SYMBOL"].astype(str).str.upper() == symbol.strip().upper())
    ]
    if m.empty:
        raise ValueError(f"No NSE EQ scrip for {symbol!r}")
    return Instrument(str(int(m.iloc[0]["SEM_SMST_SECURITY_ID"])), "NSE_EQ", "EQUITY",
                      symbol.strip().upper())


# ------------------------------------------------------------------------- fetch
def _request_chunk(inst: Instrument, start: date, end: date, token: str,
                   tries: int = 4) -> pd.DataFrame:
    payload = {
        "securityId": inst.security_id,
        "exchangeSegment": inst.segment,
        "instrument": inst.instrument,
        "interval": "1",
        "fromDate": str(start),
        "toDate": str(end),
    }
    delay = 1.0
    for attempt in range(tries):
        try:
            r = requests.post(INTRADAY_URL, headers=_headers(token), json=payload, timeout=60)
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 200:
            data = r.json()
            if not data.get("timestamp"):
                return pd.DataFrame()
            df = pd.DataFrame(data)
            df["ts"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST)
            keep = ["ts", "open", "high", "low", "close", "volume"]
            if "open_interest" in df.columns:
                keep.append("open_interest")
            return df[keep]

        if r.status_code in (429, 500, 502, 503, 504) and attempt < tries - 1:
            time.sleep(delay)
            delay *= 2
            continue

        raise RuntimeError(
            f"Dhan intraday {inst.label} {start}..{end} -> {r.status_code}: {r.text[:200]}"
        )
    return pd.DataFrame()


def _meta_path(inst: Instrument) -> Path:
    return CACHE_DIR / f"{inst.key}.meta.json"


def _data_path(inst: Instrument) -> Path:
    return CACHE_DIR / f"{inst.key}.parquet"


def _load_meta(inst: Instrument) -> set[str]:
    p = _meta_path(inst)
    if not p.exists():
        return set()
    try:
        return set(json.loads(p.read_text()).get("covered", []))
    except Exception:
        return set()


def _save_meta(inst: Instrument, covered: set[str]) -> None:
    _meta_path(inst).write_text(json.dumps({"covered": sorted(covered)}))


def fetch_bars(inst: Instrument, start: date | str, end: date | str,
               token: str | None = None, use_cache: bool = True) -> pd.DataFrame:
    """1-minute bars for [start, end], inclusive, IST-localised, sorted by time.

    Caches to parquet and only requests calendar days not already covered. `covered`
    tracks *requested* days rather than days with data, so exchange holidays are not
    re-requested on every run.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    token = resolve_token(token)
    start = pd.Timestamp(start).date()
    end = pd.Timestamp(end).date()

    cached = pd.DataFrame()
    covered: set[str] = set()
    if use_cache and _data_path(inst).exists():
        cached = pd.read_parquet(_data_path(inst))
        covered = _load_meta(inst)

    wanted = {str(d.date()) for d in pd.date_range(start, end, freq="D")}
    missing = sorted(wanted - covered)

    fetched = []
    if missing:
        # Collapse the missing days into contiguous runs, then chunk by MAX_SPAN_DAYS.
        runs, run_start, prev = [], missing[0], missing[0]
        for d in missing[1:]:
            if (pd.Timestamp(d) - pd.Timestamp(prev)).days > 1:
                runs.append((run_start, prev))
                run_start = d
            prev = d
        runs.append((run_start, prev))

        for run_a, run_b in runs:
            a, b = pd.Timestamp(run_a).date(), pd.Timestamp(run_b).date()
            while a <= b:
                chunk_end = min(a + timedelta(days=MAX_SPAN_DAYS - 1), b)
                part = _request_chunk(inst, a, chunk_end, token)
                if not part.empty:
                    fetched.append(part)
                time.sleep(INTER_CALL_SLEEP)
                a = chunk_end + timedelta(days=1)

    if fetched:
        out = pd.concat([cached, *fetched], ignore_index=True) if not cached.empty \
            else pd.concat(fetched, ignore_index=True)
        out = out.drop_duplicates(subset="ts").sort_values("ts").reset_index(drop=True)
        if use_cache:
            out.to_parquet(_data_path(inst), index=False)
            _save_meta(inst, covered | wanted)
    else:
        out = cached
        if use_cache and missing:
            _save_meta(inst, covered | wanted)

    if out.empty:
        return out
    out = out.copy()
    out["ts"] = pd.to_datetime(out["ts"], utc=True).dt.tz_convert(IST)
    lo = pd.Timestamp(start, tz=IST)
    hi = pd.Timestamp(end, tz=IST) + pd.Timedelta(days=1)
    return out[(out.ts >= lo) & (out.ts < hi)].sort_values("ts").reset_index(drop=True)


def read_cached(inst: Instrument, start: date | str | None = None,
                end: date | str | None = None) -> pd.DataFrame:
    """Bars already on disk, with no possibility of a network call.

    `fetch_bars` will silently reach for Dhan when a day is uncached, which is wrong for
    panel building and backtests: a run should either use the history it has or say it is
    missing, not quietly depend on a live token months after the fact.
    """
    path = _data_path(inst)
    if not path.exists():
        return pd.DataFrame()
    out = pd.read_parquet(path)
    if out.empty:
        return out
    out["ts"] = pd.to_datetime(out["ts"], utc=True).dt.tz_convert(IST)
    if start is not None:
        out = out[out.ts >= pd.Timestamp(pd.Timestamp(start).date(), tz=IST)]
    if end is not None:
        out = out[out.ts < pd.Timestamp(pd.Timestamp(end).date(), tz=IST) + pd.Timedelta(days=1)]
    return out.sort_values("ts").reset_index(drop=True)


def cached_instruments() -> list[str]:
    """Cache keys ('SEGMENT_securityid') currently on disk."""
    if not CACHE_DIR.exists():
        return []
    return sorted(p.stem for p in CACHE_DIR.glob("*.parquet") if p.stem != "scrip_master")


def bars_by_session(df: pd.DataFrame) -> dict[date, pd.DataFrame]:
    """Split a bar frame into {session date -> frame indexed by 'HH:MM'}."""
    if df.empty:
        return {}
    d = df.copy()
    d["session"] = d.ts.dt.date
    d["hm"] = d.ts.dt.strftime("%H:%M")
    return {s: g.set_index("hm") for s, g in d.groupby("session")}
