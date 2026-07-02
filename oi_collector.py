import time
import threading
from datetime import datetime
import broker_api as api
import local_db
from core_engines.nlp_router import FNO_SYMBOLS
import pandas as pd


INDEX_TRACKERS = {
    "NIFTY": {
        "display": "Nifty",
        "expiry_source": "NIFTY",
    },
    "SENSEX": {
        "display": "Sensex",
        "expiry_source": "SENSEX",
    },
}


def collect_oi_for_symbols(watchlist_df, daily_token):
    """
    For all F&O items in the watchlist, fetch and store OI snapshots.
    """
    if watchlist_df is None or watchlist_df.empty:
        return 0

    fno_items = watchlist_df[
        (watchlist_df["Trade Type (Eq/Option)"].astype(str).str.lower().isin(["option", "fno"]))
        & (watchlist_df["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"]))
    ].copy()

    if fno_items.empty:
        return 0

    collected = 0
    for _, row in fno_items.iterrows():
        symbol = str(row.get("Symbol / Asset", "")).strip()
        if not symbol:
            continue

        base_symbol = symbol.split()[0].upper()
        if base_symbol not in FNO_SYMBOLS:
            continue

        try:
            df_chain, meta = api.get_option_chain_snapshot(symbol, daily_token=daily_token)
            if df_chain.empty:
                continue

            strikes_data = []
            for _, chain_row in df_chain.iterrows():
                strikes_data.append({
                    "strike": chain_row["strike"],
                    "call_oi": chain_row["call_oi"],
                    "put_oi": chain_row["put_oi"],
                    "call_oi_change": chain_row.get("call_oi_change", 0),
                    "put_oi_change": chain_row.get("put_oi_change", 0),
                })

            underlying = meta.get("underlying", base_symbol)
            expiry = meta.get("expiry", "")
            local_db.save_oi_snapshot(underlying, expiry, strikes_data)
            collected += 1
        except Exception as e:
            print(f"OI snapshot failed for {symbol}: {e}")
            continue

    return collected


def _resolve_index_snapshot_symbol(index_symbol):
    symbol = str(index_symbol or "").upper().strip()
    if symbol == "SENSEX":
        return "SENSEX"
    return "NIFTY"


def collect_index_oi_snapshots(daily_token):
    collected = 0
    for index_symbol in INDEX_TRACKERS.keys():
        try:
            df_chain, meta = api.get_index_option_chain_snapshot(_resolve_index_snapshot_symbol(index_symbol), daily_token=daily_token)
            if df_chain.empty:
                continue

            strikes_data = []
            for _, chain_row in df_chain.iterrows():
                strikes_data.append({
                    "strike": chain_row["strike"],
                    "call_oi": chain_row["call_oi"],
                    "put_oi": chain_row["put_oi"],
                    "call_oi_change": chain_row.get("call_oi_change", 0),
                    "put_oi_change": chain_row.get("put_oi_change", 0),
                })

            snapshot_underlying = meta.get("underlying", index_symbol)
            snapshot_expiry = meta.get("expiry", "")
            local_db.save_oi_snapshot(snapshot_underlying, snapshot_expiry, strikes_data)
            collected += 1
        except Exception as e:
            print(f"Index OI snapshot failed for {index_symbol}: {e}")
            continue

    return collected


def background_oi_collector(gcp_creds_dict, dhan_client_id, sync_interval=60):
    """
    Background thread that periodically collects OI snapshots for F&O items.
    Runs every sync_interval seconds during market hours.
    """
    from integrations.google_sheets import init_sheet_connection, fetch_dataframe_safe, fetch_settings_dict

    try:
        sh, watchlist_ws, _, _, _, settings_ws = init_sheet_connection()
    except Exception as e:
        print(f"OI Collector: Could not connect to sheets: {e}")
        return

    last_collect_time = 0

    while True:
        now_epoch = time.time()
        time_since_collect = now_epoch - last_collect_time

        if time_since_collect >= sync_interval:
            try:
                daily_token = fetch_settings_dict().get("Dhan Access Token", "")
                if not daily_token:
                    time.sleep(min(sync_interval, 10))
                    continue
                if api._is_dhan_token_expired(daily_token):
                    print("OI Collector: Dhan token expired; waiting for a fresh token in Settings.")
                    time.sleep(min(sync_interval, 10))
                    continue

                df_watchlist = fetch_dataframe_safe("Sheet1", is_sheet1=True)
                if df_watchlist.empty:
                    collected = 0
                else:
                    collected = collect_oi_for_symbols(df_watchlist, daily_token)

                collected += collect_index_oi_snapshots(daily_token)
                last_collect_time = now_epoch
                if collected > 0:
                    print(f"OI Collector: Saved snapshots for {collected} underlying(s)")
            except Exception as e:
                print(f"OI Collector error: {e}")
                last_collect_time = now_epoch

        time.sleep(min(sync_interval, 10))


def start_oi_collector_daemon(gcp_creds_dict, dhan_client_id, sync_interval=300):
    """
    Start the OI collector as a daemon thread (default: 5-minute interval).
    """
    from streamlit.runtime.scriptrunner import add_script_run_ctx
    import streamlit as st

    collector_thread = threading.Thread(
        target=background_oi_collector,
        args=(gcp_creds_dict, dhan_client_id, sync_interval),
        daemon=True,
    )

    try:
        add_script_run_ctx(collector_thread)
    except Exception:
        pass

    collector_thread.start()
    print(f"OI Collector daemon started (interval: {sync_interval}s)")
