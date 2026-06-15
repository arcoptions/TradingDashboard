import json
import sqlite3
import threading
from datetime import datetime

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
