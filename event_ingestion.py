import pandas as pd
import local_db
import analytics
import broker_api as api
from datetime import datetime


def ingest_signal_event(source_type, source_name, raw_text):
    """
    Unified entry point for all signal events (Telegram, X, Scanners, Manual).
    Parses the tip, resolves the instrument, and stores as an event.
    """
    if not raw_text or not raw_text.strip():
        return None, "Empty input"

    parsed = analytics.parse_telegram_tip(raw_text)
    if not parsed.get("symbol") or parsed["symbol"] == "-":
        return None, "Could not extract symbol from text"

    t_sym, t_sec, t_exch = api.resolve_instrument(parsed["symbol"])
    if not t_sec:
        return None, f"Symbol {parsed['symbol']} not found in master"

    event_id = local_db.save_signal_event(
        source_type=source_type,
        source_name=source_name,
        raw_text=raw_text,
        parsed_symbol=t_sym,
        parsed_trade_type=parsed.get("trade_type", "Equity"),
        source_sl=parsed.get("sl", ""),
        source_target_1=parsed.get("t1", ""),
        source_target_2=parsed.get("t2", ""),
        metadata={
            "entry": parsed.get("entry", ""),
            "add_levels": parsed.get("add_levels", ""),
            "timeframe": parsed.get("tf", ""),
            "rating": parsed.get("rating", ""),
        },
    )

    return event_id, "Success"


def convert_event_to_watchlist_row(event_id, sheet_headers, daily_token=None):
    """
    Convert a stored signal event into a watchlist row for Sheet1.
    Returns the row as a list ready for append_row().
    """
    with local_db._DB_LOCK:
        conn = local_db._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM signal_events WHERE id = ?",
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                return None, "Event not found"
        finally:
            conn.close()

    event_data = dict(row)
    parsed_symbol = event_data["parsed_symbol"]
    parsed_trade_type = event_data["parsed_trade_type"]
    source_name = event_data["source_name"]

    t_sym, t_sec, t_exch = api.resolve_instrument(parsed_symbol)
    from core_engines.nlp_router import FNO_SYMBOLS

    is_fno = parsed_symbol in FNO_SYMBOLS or parsed_trade_type == "Option"
    contract_symbol = parsed_symbol

    if is_fno and parsed_trade_type == "Option":
        if " CE" not in parsed_symbol.upper() and " PE" not in parsed_symbol.upper():
            chain_data = api.get_option_chain_metrics(parsed_symbol, daily_token=daily_token)
            if chain_data and chain_data.get("best_ce") and chain_data.get("best_ce") != "-":
                contract_symbol = f"{parsed_symbol.split()[0]} {chain_data['best_ce']} CE"

    new_row = [""] * len(sheet_headers)

    def set_col(col_name, val):
        if col_name in sheet_headers:
            new_row[sheet_headers.index(col_name)] = str(val)

    set_col("Trade Date", datetime.today().strftime("%Y-%m-%d"))
    set_col("Idea Source (Chartink/Telegram/X/Self)", source_name)
    set_col("Symbol / Asset", contract_symbol if is_fno else (t_sym or parsed_symbol))
    set_col("Trade Type (Eq/Option)", "Option" if is_fno else "Equity")
    set_col("Exchange", t_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
    set_col("Security ID", t_sec or "")
    set_col("Status (Watch/Active/Closed)", "Watchlist")
    set_col("Entry CMP / Range", event_data.get("metadata_json", {}).get("entry", ""))
    set_col("Add-On / Dip Levels", event_data.get("metadata_json", {}).get("add_levels", ""))
    set_col("Stop Loss (SL)", event_data.get("source_sl", ""))
    set_col("Target 1", event_data.get("source_target_1", ""))
    set_col("Target 2", event_data.get("source_target_2", ""))
    set_col("Time Frame", event_data.get("metadata_json", {}).get("timeframe", ""))
    set_col("Setup Rating", event_data.get("metadata_json", {}).get("rating", ""))
    set_col("Raw Tip Text", event_data.get("raw_text", ""))

    return new_row, "Success"


def bulk_promote_events_to_watchlist(event_ids, sheet_headers, watchlist_ws, daily_token=None):
    """
    Promote multiple events to the main watchlist sheet.
    """
    if not event_ids:
        return 0, "No events to promote"

    bulk_rows = []
    for event_id in event_ids:
        row, status = convert_event_to_watchlist_row(event_id, sheet_headers, daily_token=daily_token)
        if status == "Success" and row:
            bulk_rows.append(row)

    if not bulk_rows:
        return 0, "No valid rows to insert"

    try:
        watchlist_ws.append_rows(bulk_rows)
        return len(bulk_rows), "Success"
    except Exception as e:
        return 0, f"Sheet append failed: {e}"
