import streamlit as st
import pandas as pd
import time
from datetime import datetime
import broker_api as api
from core_engines.nlp_router import extract_asset_from_text, parse_trade_metrics, FNO_SYMBOLS
from integrations.google_sheets import fetch_dataframe_safe

TIP_CHANNELS = [
    "-1003141350480", "-1003858490010", "1005281196022", "-5281196022", 
    "-1003800707569", "-1003770951544", "-1003148687413", "-1003121140019", "-1003770810999",
    "INVESTOLOGY", "ELEPHANT PRO", "CHARTIST", "CHIKOUTRADER", "SUNIL V TINANI"
]

def render(wb_obj, watchlist_symbols, sheet_headers, *args, **kwargs):
    st.markdown("#### Social Feeds and Media Hub")
    
    # Dual Axis Filters
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        selected_date = st.date_input("Filter Logs by Date", datetime.today().date(), key="social_log_date")
    
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
        from integrations.google_sheets import fetch_settings_cell
        daily_token = fetch_settings_cell('B2') or ""
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
                is_tip_channel = any(tip in source_upper for tip in TIP_CHANNELS) or "TEST" == source_upper
                
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
    df_date_filtered = df_master[df_master["Log_Date"] == selected_date]
    
    # Render Source Filter dynamically based on matching date results
    with col_f2:
        available_sources = sorted(list(df_date_filtered["Source"].dropna().unique())) if not df_date_filtered.empty else []
        selected_sources = st.multiselect("Filter Logs by Source Handle", options=available_sources, default=[])
        
    if selected_sources:
        df_date_filtered = df_date_filtered[df_date_filtered["Source"].isin(selected_sources)]
        
    df_display = df_date_filtered.sort_values(by="Timestamp", ascending=False).head(200)
    
    def check_news(row): return "BEAT THE STREET" in str(row["Source"]).upper() or "NEWS" in str(row["Source"]).upper()
    def check_tip(row): return any(t in str(row["Source"]).upper() for t in TIP_CHANNELS) or "X" == str(row["Network"]) or "TEST" == str(row["Source"]).upper()

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
