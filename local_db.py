import json
import sqlite3
import threading
from datetime import datetime
from datetime import datetime as dt_module

_DB_PATH = "arc_trading.db"
_DB_LOCK = threading.Lock()


def _connect():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_local_db():
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS instruments (
                    symbol TEXT PRIMARY KEY,
                    base_symbol TEXT,
                    asset_type TEXT,
                    sector TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signal_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_type TEXT,
                    source_name TEXT,
                    raw_text TEXT,
                    parsed_symbol TEXT,
                    parsed_trade_type TEXT,
                    source_sl TEXT,
                    source_target_1 TEXT,
                    source_target_2 TEXT,
                    event_time TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS news_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT,
                    symbol TEXT,
                    headline TEXT,
                    impact_label TEXT,
                    event_time TEXT,
                    metadata_json TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS watchlist_items (
                    sheet_row INTEGER PRIMARY KEY,
                    symbol TEXT,
                    base_asset TEXT,
                    trade_type TEXT,
                    source TEXT,
                    status TEXT,
                    sector TEXT,
                    sector_strength REAL,
                    entry_range TEXT,
                    stop_loss TEXT,
                    target_1 TEXT,
                    target_2 TEXT,
                    live_price TEXT,
                    score INTEGER,
                    decision TEXT,
                    recommendation TEXT,
                    raw_tip_text TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS recommendation_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_time TEXT NOT NULL,
                    symbol TEXT,
                    trade_type TEXT,
                    score INTEGER,
                    decision TEXT,
                    recommendation TEXT,
                    sector_strength REAL,
                    live_price TEXT,
                    metadata_json TEXT
                );

                CREATE TABLE IF NOT EXISTS oi_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    underlying TEXT NOT NULL,
                    expiry TEXT NOT NULL,
                    strike REAL NOT NULL,
                    call_oi REAL,
                    put_oi REAL,
                    call_oi_change REAL,
                    put_oi_change REAL,
                    timestamp TEXT NOT NULL,
                    bucket_5m TEXT,
                    bucket_15m TEXT,
                    bucket_30m TEXT,
                    bucket_1h TEXT,
                    bucket_day TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_oi_snapshots_underlying_expiry 
                    ON oi_snapshots(underlying, expiry);
                CREATE INDEX IF NOT EXISTS idx_oi_snapshots_timestamp 
                    ON oi_snapshots(timestamp);
                CREATE INDEX IF NOT EXISTS idx_oi_snapshots_bucket_5m 
                    ON oi_snapshots(bucket_5m);
                CREATE INDEX IF NOT EXISTS idx_oi_snapshots_bucket_15m 
                    ON oi_snapshots(bucket_15m);
                CREATE INDEX IF NOT EXISTS idx_oi_snapshots_bucket_1h 
                    ON oi_snapshots(bucket_1h);
                """
            )
            conn.commit()
        finally:
            conn.close()


def sync_watchlist_snapshot(df):
    if df is None or df.empty:
        return

    now = datetime.utcnow().isoformat(timespec="seconds")
    rows = []
    snapshot_rows = []
    for _, row in df.iterrows():
        symbol = str(row.get("Symbol / Asset", "")).strip()
        if not symbol:
            continue
        base_asset = str(row.get("Base Asset", symbol.split("-")[0].strip())).strip().upper()
        trade_type = str(row.get("Trade Type (Eq/Option)", "")).strip()
        sector = str(row.get("Sector/Industry", "")).strip()
        sector_strength = row.get("Sector Strength %", None)
        score = row.get("Score", None)
        rows.append((
            symbol,
            base_asset,
            trade_type,
            sector,
            now,
        ))
        snapshot_rows.append((
            int(row.get("_Sheet_Row", 0) or 0),
            symbol,
            base_asset,
            trade_type,
            str(row.get("Idea Source (Chartink/Telegram/X/Self)", "")),
            str(row.get("Status (Watch/Active/Closed)", "")),
            sector,
            float(sector_strength) if sector_strength not in [None, "", "-"] else None,
            str(row.get("Entry CMP / Range", "")),
            str(row.get("Stop Loss (SL)", "")),
            str(row.get("Target 1", "")),
            str(row.get("Target 2", "")),
            str(row.get("Live Price", "")),
            int(score) if score not in [None, "", "-"] else None,
            str(row.get("Decision", "")),
            str(row.get("Recommendation", "")),
            str(row.get("Raw Tip Text", "")),
            now,
        ))

    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.executemany(
                """
                INSERT INTO instruments(symbol, base_symbol, asset_type, sector, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    base_symbol = excluded.base_symbol,
                    asset_type = excluded.asset_type,
                    sector = excluded.sector,
                    updated_at = excluded.updated_at
                """,
                rows,
            )
            cur.executemany(
                """
                INSERT INTO watchlist_items(
                    sheet_row, symbol, base_asset, trade_type, source, status, sector,
                    sector_strength, entry_range, stop_loss, target_1, target_2,
                    live_price, score, decision, recommendation, raw_tip_text, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(sheet_row) DO UPDATE SET
                    symbol = excluded.symbol,
                    base_asset = excluded.base_asset,
                    trade_type = excluded.trade_type,
                    source = excluded.source,
                    status = excluded.status,
                    sector = excluded.sector,
                    sector_strength = excluded.sector_strength,
                    entry_range = excluded.entry_range,
                    stop_loss = excluded.stop_loss,
                    target_1 = excluded.target_1,
                    target_2 = excluded.target_2,
                    live_price = excluded.live_price,
                    score = excluded.score,
                    decision = excluded.decision,
                    recommendation = excluded.recommendation,
                    raw_tip_text = excluded.raw_tip_text,
                    updated_at = excluded.updated_at
                """,
                snapshot_rows,
            )
            conn.commit()
        finally:
            conn.close()


def save_recommendation_snapshot(df):
    if df is None or df.empty:
        return

    snapshot_time = datetime.utcnow().isoformat(timespec="seconds")
    rows = []
    for _, row in df.iterrows():
        metadata = {
            "source": str(row.get("Idea Source (Chartink/Telegram/X/Self)", "")),
            "sector": str(row.get("Sector/Industry", "")),
            "oi_buildup": str(row.get("OI Buildup Label", "")),
        }
        sector_strength = row.get("Sector Strength %", None)
        score = row.get("Score", None)
        rows.append((
            snapshot_time,
            str(row.get("Symbol / Asset", "")),
            str(row.get("Trade Type (Eq/Option)", "")),
            int(score) if score not in [None, "", "-"] else None,
            str(row.get("Decision", "")),
            str(row.get("Recommendation", "")),
            float(sector_strength) if sector_strength not in [None, "", "-"] else None,
            str(row.get("Live Price", "")),
            json.dumps(metadata),
        ))

    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.executemany(
                """
                INSERT INTO recommendation_snapshots(
                    snapshot_time, symbol, trade_type, score, decision,
                    recommendation, sector_strength, live_price, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()


def _get_time_bucket(timestamp_str, bucket_type):
    from datetime import datetime as dt
    dt_obj = dt.fromisoformat(timestamp_str)
    
    if bucket_type == "5m":
        minutes = (dt_obj.minute // 5) * 5
        bucketed = dt_obj.replace(minute=minutes, second=0, microsecond=0)
    elif bucket_type == "15m":
        minutes = (dt_obj.minute // 15) * 15
        bucketed = dt_obj.replace(minute=minutes, second=0, microsecond=0)
    elif bucket_type == "30m":
        minutes = (dt_obj.minute // 30) * 30
        bucketed = dt_obj.replace(minute=minutes, second=0, microsecond=0)
    elif bucket_type == "1h":
        bucketed = dt_obj.replace(minute=0, second=0, microsecond=0)
    elif bucket_type == "day":
        bucketed = dt_obj.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        bucketed = dt_obj
    
    return bucketed.isoformat(timespec="seconds")


def save_oi_snapshot(underlying, expiry, strikes_data, timestamp_str=None):
    if not strikes_data:
        return
    
    if timestamp_str is None:
        timestamp_str = datetime.utcnow().isoformat(timespec="seconds")
    
    bucket_5m = _get_time_bucket(timestamp_str, "5m")
    bucket_15m = _get_time_bucket(timestamp_str, "15m")
    bucket_30m = _get_time_bucket(timestamp_str, "30m")
    bucket_1h = _get_time_bucket(timestamp_str, "1h")
    bucket_day = _get_time_bucket(timestamp_str, "day")
    
    rows = []
    for strike_data in strikes_data:
        rows.append((
            underlying,
            expiry,
            float(strike_data.get("strike", 0)),
            float(strike_data.get("call_oi", 0)),
            float(strike_data.get("put_oi", 0)),
            float(strike_data.get("call_oi_change", 0)),
            float(strike_data.get("put_oi_change", 0)),
            timestamp_str,
            bucket_5m,
            bucket_15m,
            bucket_30m,
            bucket_1h,
            bucket_day,
            datetime.utcnow().isoformat(timespec="seconds"),
        ))
    
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.executemany(
                """
                INSERT INTO oi_snapshots(
                    underlying, expiry, strike, call_oi, put_oi,
                    call_oi_change, put_oi_change, timestamp,
                    bucket_5m, bucket_15m, bucket_30m, bucket_1h, bucket_day, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()


def query_oi_changes(underlying, expiry, strike, time_window="1h"):
    bucket_col = {
        "5m": "bucket_5m",
        "15m": "bucket_15m",
        "30m": "bucket_30m",
        "1h": "bucket_1h",
        "day": "bucket_day",
    }.get(time_window, "bucket_1h")
    
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT {bucket_col} as time_bucket, 
                       call_oi, put_oi, call_oi_change, put_oi_change, 
                       timestamp
                FROM oi_snapshots
                WHERE underlying = ? AND expiry = ? AND strike = ?
                GROUP BY {bucket_col}
                ORDER BY timestamp DESC
                """,
                (underlying, expiry, strike),
            )
            rows = cur.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


def save_signal_event(source_type, source_name, raw_text, parsed_symbol, parsed_trade_type, source_sl="", source_target_1="", source_target_2="", metadata=None):
    if metadata is None:
        metadata = {}
    
    now = datetime.utcnow().isoformat(timespec="seconds")
    
    with _DB_LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO signal_events(
                    source_type, source_name, raw_text, parsed_symbol,
                    parsed_trade_type, source_sl, source_target_1, source_target_2,
                    event_time, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source_type,
                    source_name,
                    raw_text,
                    parsed_symbol,
                    parsed_trade_type,
                    source_sl,
                    source_target_1,
                    source_target_2,
                    now,
                    json.dumps(metadata),
                    now,
                ),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()
