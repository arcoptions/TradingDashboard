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
    "INVESTOLOGY", "ELEPHANT PRO", "CHARTIST", "CHIKOUTRADER", "SUNIL V TINANI", "TEST"
]

def render(wb_obj, watchlist_symbols, sheet_headers, *args, **kwargs):
    st.markdown("#### 📱 Telegram Data Hub & News Feed")
    
    # ─── ADDED: INTERACTIVE CALENDAR DATE FILTER ───
    selected_date = st.date_input("📅 Filter Telegram Logs by Date", datetime.today().date(), key="telegram_log_date")
    st.write("")
    
    df_raw_logs = fetch_dataframe_safe("Telegram_Raw_Logs")
    if wb_obj is None:
        st.error("Data core connection uninitialized.")
        return
        
    raw_log_ws = wb_obj.worksheet("Telegram_Raw_Logs")
    
    if not df_raw_logs.empty:
        df_raw_logs["_Row_ID"] = range(2, len(df_raw_logs) + 2)
        
        # Standardize timestamp string elements to true Python date components
        df_raw_logs["Log_Date"] = pd.to_datetime(df_raw_logs["Timestamp"], errors='coerce').dt.date
        df_pending = df_raw_logs[df_raw_logs["Parsing Status"].astype(str).str.strip().str.lower().isin(["pending review", "pending extraction", "pending parsing", "news ingested"])].copy()
        
        # --- 1. BACKGROUND AUTO-ROUTER PIPELINE ---
        if not df_pending.empty:
            status_updates, bulk_watchlist_rows, bulk_study_rows = [], [], []
            daily_token = ""
            try:
                from integrations.google_sheets import fetch_settings_cell
                daily_token = fetch_settings_cell('B2') or ""
            except: pass

            for idx, row in df_pending.iterrows():
                text = str(row['Raw Message Text'])
                source = str(row['Channel Source'])
                source_upper = source.upper()
                
                is_news_channel = any(kw in source.lower() for kw in ["beat the street", "news"])
                is_tip_channel = any(tip in source_upper for tip in TIP_CHANNELS)
                
                raw_symbol = extract_asset_from_text(text)
                valid_sym, valid_sec, valid_exch = None, None, None
                
                if raw_symbol and raw_symbol != "-":
                    valid_sym, valid_sec, valid_exch = api.resolve_instrument(raw_symbol)
                
                if is_news_channel:
                    status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["News Logged"]]})
                    continue
                    
                if not valid_sec:
                    status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Logged (No Valid Stock)"]]})
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
                        status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Duplicate Watchlist Item"]]})
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
                    status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Watchlist"]]})
                    
                else:
                    bulk_study_rows.append([
                        str(row['Timestamp']), 
                        source, 
                        contract_symbol if is_fno else (valid_sym or raw_symbol), 
                        f"Entry: {metrics['entry'] or '-'} | SL: {metrics['sl'] or '-'} | TGT: {metrics['target_1'] or '-'}\n\n{text}", 
                        datetime.today().strftime("%Y-%m-%d")
                    ])
                    status_updates.append({'range': f"D{row['_Row_ID']}", 'values': [["Auto-Staged to Study"]]})
                    
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
                st.rerun()

        # --- 2. VISUAL LOG RENDERING (WITH DUAL SECURITY CONTROLS) ---
        df_filtered_by_date = df_raw_logs[df_raw_logs["Log_Date"] == selected_date]
        df_display = df_filtered_by_date.sort_values(by="_Row_ID", ascending=False).head(300)
        
        def is_news(src): return any(kw in str(src).lower() for kw in ["beat the street", "news"])
        def is_tip(src): return any(tip in str(src).upper() for tip in TIP_CHANNELS)
        
        # FIXED: Enforced strict exclusion constraints so news channels can NEVER leak into Tips or Discussions
        df_news = df_display[df_display["Channel Source"].apply(is_news)]
        df_mentions = df_display[df_display["Channel Source"].apply(is_tip) & ~df_display["Channel Source"].apply(is_news)]
        df_discussions = df_display[~df_display["Channel Source"].apply(is_news) & ~df_display["Channel Source"].apply(is_tip)]

        sub_news, sub_mentions, sub_discussions = st.tabs(["📰 Exclusive News Log", "🎯 Auto-Routed Tips", "💬 General Discussions"])
        
        def render_log_table(df, title):
            if df.empty:
                st.info(f"No log items recorded for {selected_date.strftime('%Y-%m-%d')}.")
                return
            st.dataframe(
                df[["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "Timestamp": st.column_config.TextColumn("Time", width="small"),
                    "Channel Source": st.column_config.TextColumn("Source", width="medium"),
                    "Raw Message Text": st.column_config.TextColumn("Message Content", width="large"),
                    "Parsing Status": st.column_config.TextColumn("System Action", width="small")
                }
            )

        with sub_news: render_log_table(df_news, "News")
        with sub_mentions: render_log_table(df_mentions, "Tips")
        with sub_discussions: render_log_table(df_discussions, "Discussions")
        
    else: 
        st.info("System initializing tracking logs. Awaiting fresh inbound advisory data.")
