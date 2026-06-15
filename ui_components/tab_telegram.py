import streamlit as st
import pandas as pd
import time
import asyncio
from datetime import datetime
import broker_api as api
from core_engines.nlp_router import extract_asset_from_text, parse_trade_metrics, FNO_SYMBOLS
from integrations.google_sheets import fetch_dataframe_safe
from telethon import TelegramClient
from telethon.sessions import StringSession

TIP_CHANNELS = [
    "-1003141350480", "-1003858490010", "-3858490010", "1005281196022", "-5281196022", 
    "-1003800707569", "-1003770951544", "-1003148687413", "-1003121140019", "-1003770810999",
    "INVESTOLOGY", "ELEPHANT PRO", "CHARTIST", "CHIKOUTRADER", "SUNIL V TINANI"
]

TRACKED_CHANNELS = [
    -1003141350480, -1003858490010, -3858490010, -1001320942683, -1005281196022, -5281196022,
    -1003800707569, -1003770951544, 'Shortterm01', -1003148687413, -1003121140019,
    'The_ChartWizard', -1003770810999, -1003109328674, 'SwingWisely', -1003101198634,
    'BeatTheStreetNews'
]


def _extract_channel_digits(value):
    text = str(value or "")
    return "".join(ch for ch in text if ch.isdigit())


def _is_tip_source(source_value):
    source_text = str(source_value or "")
    source_upper = source_text.upper()

    # Name-based matching (e.g., ELEPHANT PRO)
    if any(tip in source_upper for tip in TIP_CHANNELS):
        return True

    # Numeric channel matching: treat -3858490010 and -1003858490010 as equivalent.
    src_digits = _extract_channel_digits(source_text)
    if not src_digits:
        return False

    src_tail = src_digits[-10:] if len(src_digits) >= 10 else src_digits
    for tip in TIP_CHANNELS:
        tip_digits = _extract_channel_digits(tip)
        if not tip_digits:
            continue
        tip_tail = tip_digits[-10:] if len(tip_digits) >= 10 else tip_digits
        if src_digits == tip_digits or src_tail == tip_tail:
            return True
    return False


def _run_async(coro):
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


async def _manual_backfill_recent_telegram(raw_ws, existing_df, lookback_limit=60):
    try:
        tg_cfg = st.secrets.get("telegram", {})
        api_id = int(tg_cfg.get("api_id", 0) or 0)
        api_hash = str(tg_cfg.get("api_hash", "") or "")
        session_string = str(tg_cfg.get("session_string", "") or "")
    except Exception:
        return 0, "Telegram secrets not configured in app settings"

    if not api_id or not api_hash or not session_string:
        return 0, "Missing Telegram credentials (api_id/api_hash/session_string)"

    existing_keys = set()
    if existing_df is not None and not existing_df.empty:
        for _, r in existing_df.iterrows():
            src = str(r.get("Channel Source", "")).strip().lower()
            txt = str(r.get("Raw Message Text", "")).strip().lower()
            if src and txt:
                existing_keys.add((src, txt))

    rows_to_add = []
    today = datetime.today().date()

    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.start()
    try:
        for channel in TRACKED_CHANNELS:
            try:
                entity = await client.get_entity(channel)
                title_token = getattr(entity, 'title', '')
                username_token = getattr(entity, 'username', '')
                if "BeatTheStreet" in str(username_token) or "Beat The Street" in str(title_token):
                    source_name = "Beat The Street"
                else:
                    source_name = title_token if title_token else (username_token if username_token else str(channel))

                history = await client.get_messages(entity, limit=lookback_limit)
                for msg in history:
                    raw_text = str(getattr(msg, "message", "") or "").strip()
                    if not raw_text:
                        continue
                    msg_dt = getattr(msg, "date", None)
                    if msg_dt is None:
                        continue
                    if msg_dt.date() != today:
                        continue

                    key = (str(source_name).strip().lower(), raw_text.lower())
                    if key in existing_keys:
                        continue

                    rows_to_add.append([
                        msg_dt.strftime("%Y-%m-%d %H:%M:%S"),
                        source_name,
                        raw_text,
                        "pending review",
                    ])
                    existing_keys.add(key)
            except Exception:
                continue
    finally:
        await client.disconnect()

    if rows_to_add:
        raw_ws.append_rows(rows_to_add)
    return len(rows_to_add), ""

def render(wb_obj, watchlist_symbols, sheet_headers, *args, **kwargs):
    st.markdown("#### Social Feeds and Media Hub")

    # Reset filter state before widgets are instantiated on rerun.
    if st.session_state.pop("telegram_clear_filters_requested", False):
        st.session_state["social_log_all_dates"] = True
        st.session_state["social_log_stock_query"] = ""
        st.session_state["social_log_date"] = datetime.today().date()
        st.session_state.pop("social_log_selected_sources", None)
    
    # Dual Axis Filters
    col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([1.2, 1.2, 1.4, 1.0, 0.8])
    with col_f1:
        selected_date = st.date_input("Filter Logs by Date", datetime.today().date(), key="social_log_date")
    with col_f2:
        use_all_dates = st.checkbox("Show All Dates", value=False, key="social_log_all_dates")
    with col_f3:
        stock_query = st.text_input("Find Stock / Keyword", value="", placeholder="e.g. ASHOKLEY, NTPC", key="social_log_stock_query")
    with col_f4:
        if st.button("🔄 Refresh Today's Feeds", key="telegram_refresh_btn"):
            try:
                tele_ws = wb_obj.worksheet("Telegram_Raw_Logs")
                current_logs = fetch_dataframe_safe("Telegram_Raw_Logs")

                added_count, err_msg = _run_async(_manual_backfill_recent_telegram(tele_ws, current_logs))
                if err_msg:
                    st.warning(f"⚠️ {err_msg}")
                else:
                    st.success(f"✅ Refresh complete. Added {added_count} new Telegram messages for today.")
                fetch_dataframe_safe.clear()
                st.rerun()
            except Exception as e:
                st.error(f"⚠️ Error triggering backfill: {e}")
    with col_f5:
        if st.button("Clear Filters", key="telegram_clear_filters"):
            st.session_state["telegram_clear_filters_requested"] = True
            st.rerun()
    
    df_tele_logs = fetch_dataframe_safe("Telegram_Raw_Logs")
    df_x_logs = fetch_dataframe_safe("X_Raw_Logs")
    
    if wb_obj is None:
        st.error("Data core connection uninitialized.")
        return
        
    tele_ws = wb_obj.worksheet("Telegram_Raw_Logs")
    x_ws = wb_obj.worksheet("X_Raw_Logs")
    
    # 1. BACKGROUND ENGINE: AUTOMATED DATA ROUTING MATRIX
    daily_token = ""
    try:
        from integrations.google_sheets import fetch_settings_dict
        daily_token = fetch_settings_dict().get("Dhan Access Token", "")
    except: pass

    # A. Process Pending Telegram Logs
    if not df_tele_logs.empty:
        df_tele_logs["_Row_ID"] = range(2, len(df_tele_logs) + 2)
        df_tele_pending = df_tele_logs[df_tele_logs["Parsing Status"].astype(str).str.strip().str.lower().isin(["pending review", "pending extraction", "pending parsing", "news ingested"])].copy()
        
        if not df_tele_pending.empty:
            tele_updates, bulk_watchlist_rows, bulk_study_rows = [], [], []
            for idx, row in df_tele_pending.iterrows():
                text = str(row['Raw Message Text'])
                source = str(row['Channel Source'])
                source_upper = source.upper()
                
                is_news_channel = any(kw in source.lower() for kw in ["beat the street", "news"])
                is_tip_channel = _is_tip_source(source) or "TEST" == source_upper
                
                if is_news_channel:
                    tele_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["News Logged"]]})
                    continue
                    
                raw_symbol = extract_asset_from_text(text)
                valid_sym, valid_sec, valid_exch = None, None, None
                if raw_symbol and raw_symbol != "-":
                    valid_sym, valid_sec, valid_exch = api.resolve_instrument(raw_symbol)
                    
                if not valid_sec:
                    tele_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Logged (No Valid Stock)"]]})
                    continue
                    
                metrics = parse_trade_metrics(text)
                is_fno = raw_symbol in FNO_SYMBOLS
                contract_symbol = raw_symbol
                if is_fno:
                    if metrics["strike"] and metrics["option_type"]:
                        contract_symbol = f"{raw_symbol} {metrics['strike']} {metrics['option_type']}"
                    else:
                        chain_data = api.get_option_chain_metrics(raw_symbol, daily_token=daily_token)
                        if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                            contract_symbol = f"{raw_symbol} {chain_data['best_ce']} (Auto)"

                if is_tip_channel:
                    if contract_symbol in watchlist_symbols:
                        tele_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Duplicate Watchlist Item"]]})
                        continue
                    new_row = [""] * len(sheet_headers)
                    def fill(col, val): 
                        if col in sheet_headers: new_row[sheet_headers.index(col)] = str(val)
                    fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                    fill("Idea Source (Chartink/Telegram/X/Self)", source)
                    fill("Symbol / Asset", contract_symbol if is_fno else (valid_sym or raw_symbol))
                    fill("Trade Type (Eq/Option)", "Option" if is_fno else "Equity")
                    fill("Exchange", valid_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
                    fill("Security ID", valid_sec or "")
                    fill("Status (Watch/Active/Closed)", "Watchlist")
                    fill("Entry CMP / Range", metrics["entry"] or "")
                    fill("Stop Loss (SL)", metrics["sl"] or "")
                    fill("Target 1", metrics["target_1"] or "")
                    fill("Target 2", metrics["target_2"] or "")
                    fill("Raw Tip Text", text)
                    bulk_watchlist_rows.append(new_row)
                    tele_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Watchlist"]]})
                else:
                    bulk_study_rows.append([str(row['Timestamp']), source, contract_symbol if is_fno else (valid_sym or raw_symbol), f"Entry: {metrics['entry'] or '-'} | SL: {metrics['sl'] or '-'} | TGT: {metrics['target_1'] or '-'}\n\n{text}", datetime.today().strftime("%Y-%m-%d")])
                    tele_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Study"]]})
                    
            if bulk_study_rows:
                target_study_ws = wb_obj.worksheet("Stocks to study")
                target_study_ws.append_rows(bulk_study_rows)
            if bulk_watchlist_rows:
                wb_obj.sheet1.append_rows(bulk_watchlist_rows)
            if tele_updates:
                tele_ws.batch_update(tele_updates)
                fetch_dataframe_safe.clear(); st.rerun()

    # B. Process Pending X (Twitter) Logs
    if not df_x_logs.empty:
        df_x_logs["_Row_ID"] = range(2, len(df_x_logs) + 2)
        df_x_pending = df_x_logs[df_x_logs["Parsing Status"].astype(str).str.strip().str.lower().isin(["pending review", "pending extraction", "pending parsing"])].copy()
        
        if not df_x_pending.empty:
            x_updates, bulk_watchlist_rows = [], []
            for idx, row in df_x_pending.iterrows():
                text = str(row['Post Content'])
                source = str(row['Account Handle'])
                
                raw_symbol = extract_asset_from_text(text)
                valid_sym, valid_sec, valid_exch = None, None, None
                if raw_symbol and raw_symbol != "-":
                    valid_sym, valid_sec, valid_exch = api.resolve_instrument(raw_symbol)
                    
                if not valid_sec:
                    x_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Logged (No Valid Stock)"]]})
                    continue
                    
                metrics = parse_trade_metrics(text)
                is_fno = raw_symbol in FNO_SYMBOLS
                contract_symbol = raw_symbol
                if is_fno:
                    if metrics["strike"] and metrics["option_type"]:
                        contract_symbol = f"{raw_symbol} {metrics['strike']} {metrics['option_type']}"
                    else:
                        chain_data = api.get_option_chain_metrics(raw_symbol, daily_token=daily_token)
                        if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                            contract_symbol = f"{raw_symbol} {chain_data['best_ce']} (Auto)"

                if contract_symbol in watchlist_symbols:
                    x_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Duplicate Watchlist Item"]]})
                    continue
                    
                new_row = [""] * len(sheet_headers)
                def fill(col, val): 
                    if col in sheet_headers: new_row[sheet_headers.index(col)] = str(val)
                fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                fill("Idea Source (Chartink/Telegram/X/Self)", f"X: {source}")
                fill("Symbol / Asset", contract_symbol if is_fno else (valid_sym or raw_symbol))
                fill("Trade Type (Eq/Option)", "Option" if is_fno else "Equity")
                fill("Exchange", valid_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
                fill("Security ID", valid_sec or "")
                fill("Status (Watch/Active/Closed)", "Watchlist")
                fill("Entry CMP / Range", metrics["entry"] or "")
                fill("Stop Loss (SL)", metrics["sl"] or "")
                fill("Target 1", metrics["target_1"] or "")
                fill("Target 2", metrics["target_2"] or "")
                fill("Raw Tip Text", text)
                bulk_watchlist_rows.append(new_row)
                x_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Watchlist"]]})
                
            if bulk_watchlist_rows:
                wb_obj.sheet1.append_rows(bulk_watchlist_rows)
            if x_updates:
                x_ws.batch_update(x_updates)
                fetch_dataframe_safe.clear(); st.rerun()

    # 2. CONSOLIDATED LOG NORMALIZATION AND RENDERING AREA
    normalized_list = []
    if not df_tele_logs.empty:
        for _, r in df_tele_logs.iterrows():
            normalized_list.append({
                "Timestamp": r.get("Timestamp", ""), "Source": r.get("Channel Source", ""),
                "Content": r.get("Raw Message Text", ""), "Status": r.get("Parsing Status", ""),
                "Log_Date": pd.to_datetime(r.get("Timestamp", ""), errors='coerce').date(), "Network": "Telegram"
            })
    if not df_x_logs.empty:
        for _, r in df_x_logs.iterrows():
            normalized_list.append({
                "Timestamp": r.get("Timestamp", ""), "Source": f"X: {r.get('Account Handle', '')}",
                "Content": r.get("Post Content", ""), "Status": r.get("Parsing Status", ""),
                "Log_Date": pd.to_datetime(r.get("Timestamp", ""), errors='coerce').date(), "Network": "X"
            })
            
    if not normalized_list:
        st.info("No network log data found.")
        return
        
    df_master = pd.DataFrame(normalized_list)
    if use_all_dates:
        df_date_filtered = df_master.copy()
    else:
        df_date_filtered = df_master[df_master["Log_Date"] == selected_date]
    
    with col_f2:
        available_sources = sorted(list(df_date_filtered["Source"].dropna().unique())) if not df_date_filtered.empty else []
        selected_sources = st.multiselect(
            "Filter Logs by Source Handle",
            options=available_sources,
            default=st.session_state.get("social_log_selected_sources", []),
            key="social_log_selected_sources",
            help="If you select one source (e.g., Beat The Street), all other channels are hidden.",
        )
        
    if selected_sources:
        df_date_filtered = df_date_filtered[df_date_filtered["Source"].isin(selected_sources)]

    if stock_query.strip():
        q = stock_query.strip()
        mask = (
            df_date_filtered["Content"].astype(str).str.contains(q, case=False, na=False)
            | df_date_filtered["Source"].astype(str).str.contains(q, case=False, na=False)
        )
        df_date_filtered = df_date_filtered[mask]

    if selected_sources:
        st.warning(
            f"Active source filter: {', '.join(selected_sources)}. "
            "Only these sources are shown. Use Clear Filters to view all channels."
        )
    elif not use_all_dates:
        st.caption(
            f"Showing logs for {selected_date}. "
            "If other channels look empty, enable Show All Dates or click Refresh Today's Feeds."
        )
        
    df_display = df_date_filtered.sort_values(by="Timestamp", ascending=False).head(200)
    
    def check_news(row): return "BEAT THE STREET" in str(row["Source"]).upper() or "NEWS" in str(row["Source"]).upper()
    def check_tip(row):
        return _is_tip_source(str(row["Source"])) or "X" == str(row["Network"]) or "TEST" == str(row["Source"]).upper()

    df_news = df_display[df_display.apply(check_news, axis=1)]
    df_tips = df_display[df_display.apply(check_tip, axis=1) & ~df_display.apply(check_news, axis=1)]
    df_discussions = df_display[~df_display.apply(check_news, axis=1) & ~df_display.apply(check_tip, axis=1)]

    sub_news, sub_mentions, sub_discussions = st.tabs(["Exclusive News Log", "Auto Routed Tips", "General Discussions"])
    
    def render_log_table(df):
        if df.empty:
            st.info("No matching entries for this selection.")
            return
        st.dataframe(
            df[["Timestamp", "Source", "Content", "Status"]], use_container_width=True, hide_index=True,
            column_config={
                "Timestamp": st.column_config.TextColumn("Time", width="small"),
                "Source": st.column_config.TextColumn("Source Channel / Handle", width="medium"),
                "Content": st.column_config.TextColumn("Content Body", width="large"),
                "Status": st.column_config.TextColumn("System Status Route", width="small")
            }
        )

    with sub_news: render_log_table(df_news)
    with sub_mentions: render_log_table(df_tips)
    with sub_discussions: render_log_table(df_discussions)
