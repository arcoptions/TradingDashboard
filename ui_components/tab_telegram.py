import streamlit as st
import pandas as pd
import time
from datetime import datetime
import broker_api as api
from core_engines.nlp_router import extract_asset_from_text, parse_trade_metrics, FNO_SYMBOLS
from integrations.google_sheets import fetch_dataframe_safe

# Your designated instant-execution tip sources
TIP_CHANNELS = [
    "-1003141350480", "-1003858490010", "1005281196022", "-5281196022", 
    "-1003800707569", "-1003770951544", "-1003148687413", "-1003121140019", "-1003770810999",
    "INVESTOLOGY", "ELEPHANT PRO", "CHARTIST", "CHIKOUTRADER", "SUNIL V TINANI", "TEST"
]

def render(wb_obj, watchlist_symbols, sheet_headers, *args, **kwargs):
    st.markdown("#### ⚙️ Automated Telegram Routing Engine")
    
    df_raw_logs = fetch_dataframe_safe("Telegram_Raw_Logs")
    if wb_obj is None:
        st.error("Data core connection uninitialized.")
        return
        
    raw_log_ws = wb_obj.worksheet("Telegram_Raw_Logs")
    
    if not df_raw_logs.empty:
        df_raw_logs["_Row_ID"] = range(2, len(df_raw_logs) + 2)
        df_pending = df_raw_logs[df_raw_logs["Parsing Status"].astype(str).str.strip().str.lower().isin(["pending review", "pending extraction", "pending parsing", "news ingested"])].copy()
        
        if df_pending.empty:
            st.success("✅ Inbox Zero! All inbound Telegram streams have been automatically parsed and routed.")
            st.info("News updates were filed silently in the background. Tip alerts were sent to your Main Watchlist. General discussions were queued in 'Stocks to Study'.")
            return

        st.info(f"Background Process: Routing {len(df_pending)} new inbound signals...")
        
        status_updates, bulk_watchlist_rows, bulk_study_rows = [], [], []
        
        daily_token = ""
        try:
            from integrations.google_sheets import fetch_settings_cell
            daily_token = fetch_settings_cell('B2') or ""
        except: pass

        processed_count = {"watch": 0, "study": 0, "news": 0}

        for idx, row in df_pending.iterrows():
            text = str(row['Raw Message Text'])
            source = str(row['Channel Source'])
            source_upper = source.upper()
            
            # RULE 1: Hide Beat The Street entirely (Silently Logged)
            if "BEAT THE STREET" in source_upper or "NEWS" in source_upper:
                status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Background News Processed"]]})
                processed_count["news"] += 1
                continue
                
            matched_symbol = extract_asset_from_text(text)
            if not matched_symbol or matched_symbol == "-":
                status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["No Stock Found"]]})
                continue
                
            metrics = parse_trade_metrics(text)
            is_fno = matched_symbol in FNO_SYMBOLS
            is_tip_channel = any(tip in source_upper for tip in TIP_CHANNELS)
            
            # RULE 2: Instant Watchlist Promotion for Tip Channels
            if is_tip_channel:
                if matched_symbol in watchlist_symbols:
                    status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Duplicate Watchlist Item"]]})
                    continue
                    
                new_row = [""] * len(sheet_headers)
                def fill(col, val): 
                    if col in sheet_headers: new_row[sheet_headers.index(col)] = str(val)
                
                t_sym, t_sec, t_exch = api.resolve_instrument(matched_symbol)
                trade_type = "Option" if is_fno else "Equity"
                contract_symbol = matched_symbol
                
                if is_fno:
                    if metrics["strike"] and metrics["option_type"]:
                        contract_symbol = f"{matched_symbol} {metrics['strike']} {metrics['option_type']}"
                    else:
                        chain_data = api.get_option_chain_metrics(matched_symbol, daily_token=daily_token)
                        if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                            contract_symbol = f"{matched_symbol} {chain_data['best_ce']} (Auto)"
                            
                fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                fill("Idea Source (Chartink/Telegram/X/Self)", source)
                fill("Symbol / Asset", contract_symbol if is_fno else (t_sym or matched_symbol))
                fill("Trade Type (Eq/Option)", trade_type)
                fill("Exchange", t_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
                fill("Security ID", t_sec or "")
                fill("Status (Watch/Active/Closed)", "Watchlist")
                fill("Entry CMP / Range", metrics["entry"] or "")
                fill("Stop Loss (SL)", metrics["sl"] or "")
                fill("Target 1", metrics["target_1"] or "")
                fill("Target 2", metrics["target_2"] or "")
                fill("Raw Tip Text", text)
                
                bulk_watchlist_rows.append(new_row)
                status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Watchlist"]]})
                processed_count["watch"] += 1
                
            # RULE 3: Discussions get captured to Stocks to Study
            else:
                bulk_study_rows.append([
                    str(row['Timestamp']), 
                    source, 
                    matched_symbol, 
                    f"Entry: {metrics['entry'] or '-'} | SL: {metrics['sl'] or '-'} | TGT: {metrics['target_1'] or '-'}\n\n{text}", 
                    datetime.today().strftime("%Y-%m-%d")
                ])
                status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Study"]]})
                processed_count["study"] += 1
                
        # Batch commit logic
        if bulk_study_rows:
            try: target_study_ws = wb_obj.worksheet("Stocks to study")
            except: 
                target_study_ws = wb_obj.add_worksheet(title="Stocks to study", rows="3000", cols="5")
                target_study_ws.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
            target_study_ws.append_rows(bulk_study_rows)
            
        if bulk_watchlist_rows:
            target_watchlist_ws = wb_obj.sheet1
            target_watchlist_ws.append_rows(bulk_watchlist_rows)
            
        if status_updates:
            raw_log_ws.batch_update(status_updates)
            fetch_dataframe_safe.clear()
            st.success(f"**Pipeline Execution Complete!**\n* {processed_count['watch']} pushed to Watchlist\n* {processed_count['study']} pushed to Stocks to Study\n* {processed_count['news']} background news cataloged.")
            time.sleep(2)
            st.rerun()
            
    else: 
        st.info("System initializing tracking logs. Awaiting fresh inbound advisory data.")
