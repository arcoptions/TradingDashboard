import streamlit as st
import pandas as pd
import time
from datetime import datetime
import broker_api as api
import analytics
from core_engines.nlp_router import extract_asset_from_text
from integrations.google_sheets import fetch_dataframe_safe

def render(wb_obj, watchlist_symbols, sheet_headers, *args, **kwargs):
    st.markdown("#### Operational Staging Workspaces")
    
    df_raw_logs = fetch_dataframe_safe("Telegram_Raw_Logs")
    if wb_obj is None:
        st.error("Data core connection uninitialized.")
        return
        
    raw_log_ws = wb_obj.worksheet("Telegram_Raw_Logs")
    
    if not df_raw_logs.empty:
        df_raw_logs["_Row_ID"] = range(2, len(df_raw_logs) + 2)
        df_pending = df_raw_logs[df_raw_logs["Parsing Status"].astype(str).str.strip().str.lower().isin(["pending review", "pending extraction", "pending parsing", "news ingested"])].copy()
        
        mentions_list, news_list, discussions_list = [], [], []
        
        for idx, row in df_pending.iterrows():
            text = str(row['Raw Message Text'])
            source = str(row['Channel Source'])
            is_news_channel = any(kw in source.lower() for kw in ["beat the street", "news"])
            
            matched_symbol = extract_asset_from_text(text)

            if matched_symbol:
                t_sym, t_sec, t_exch_type = api.resolve_instrument(matched_symbol)
                if t_sec:
                    row['Extracted_Symbol'] = t_sym
                    row['Exchange_Segment_Verified'] = t_exch_type
                    mentions_list.append(row)
                else:
                    if is_news_channel: news_list.append(row)
                    else: discussions_list.append(row)
            elif is_news_channel:
                row['Extracted_Symbol'] = "-"
                row['Exchange_Segment_Verified'] = ""
                news_list.append(row)
            else:
                row['Extracted_Symbol'] = "-"
                row['Exchange_Segment_Verified'] = ""
                discussions_list.append(row)
                
        df_mentions = pd.DataFrame(mentions_list) if mentions_list else pd.DataFrame()
        df_news = pd.DataFrame(news_list) if news_list else pd.DataFrame()
        df_discussions = pd.DataFrame(discussions_list) if discussions_list else pd.DataFrame()

        sub_mentions, sub_news, sub_discussions = st.tabs(["🎯 Stock Mentions", "📰 Exclusive News Log", "💬 General Discussions"])
        
        def render_bulk_table(df, tab_name):
            if df.empty:
                st.success(f"✨ {tab_name} Queue Clear!")
                return
            
            df_display = df.copy()
            df_display.insert(0, "Select", False)
            
            if tab_name == "Stock Mentions":
                df_display["Status"] = df_display["Extracted_Symbol"].apply(lambda x: "⚠️ Duplicate" if str(x).upper() in watchlist_symbols else "🟢 Unique")
            else:
                df_display["Status"] = "ℹ expose"
                
            b1, b2, b3 = st.columns([1, 1, 1])
            
            edited_df = st.data_editor(
                df_display, hide_index=True, use_container_width=True, key=f"editor_{tab_name}",
                column_config={
                    "Select": st.column_config.CheckboxColumn("✓", width="small"),
                    "_Row_ID": None, "Parsing Status": None, "Exchange_Segment_Verified": None,
                    "Timestamp": st.column_config.TextColumn("Time", width="small"),
                    "Channel Source": st.column_config.TextColumn("Source", width="medium"),
                    "Raw Message Text": st.column_config.TextColumn("Message Content", width="large"),
                    "Extracted_Symbol": st.column_config.TextColumn("Asset Token", width="small"),
                    "Status": st.column_config.TextColumn("Status", width="small")
                }
            )
            
            selected_rows = edited_df[edited_df["Select"] == True]
            
            if b1.button("⚡ Stage Selected Rows", key=f"stg_{tab_name}", use_container_width=True) and not selected_rows.empty:
                status_updates = []
                
                if tab_name == "News Feeds" or str(selected_rows.iloc[0].get('Extracted_Symbol', '-')) == "-" or any(kw in str(selected_rows.iloc[0]['Channel Source']).lower() for kw in ["beat the street", "news"]):
                    target_study_ws = wb_obj.worksheet("Stocks to study")
                    bulk_study_rows = []
                    for _, s_row in selected_rows.iterrows():
                        bulk_study_rows.append([str(s_row['Timestamp']), str(s_row['Channel Source']), str(s_row['Extracted_Symbol']), str(s_row['Raw Message Text']), datetime.today().strftime("%Y-%m-%d")])
                        status_updates.append({'range': f"D{s_row['_Row_ID']}", 'values': [["Staged to Study"]]})
                    if bulk_study_rows: target_study_ws.append_rows(bulk_study_rows)
                else:
                    target_watchlist_ws = wb_obj.sheet1
                    bulk_watchlist_rows = []
                    for _, s_row in selected_rows.iterrows():
                        if "Duplicate" in s_row["Status"]: continue 
                        t_sym, t_sec, t_exch = api.resolve_instrument(s_row['Extracted_Symbol'])
                        pre_parsed = analytics.parse_telegram_tip(s_row['Raw Message Text'])
                        auto_derived_trade_type = "Equity" if "EQ" in str(s_row['Exchange_Segment_Verified']) else "Option"
                        
                        new_row = [""] * len(sheet_headers)
                        def fill(col, val): 
                            if col in sheet_headers: new_row[sheet_headers.index(col)] = str(val)
                        fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                        fill("Idea Source (Chartink/Telegram/X/Self)", s_row['Channel Source'])
                        fill("Symbol / Asset", t_sym)
                        fill("Trade Type (Eq/Option)", auto_derived_trade_type)
                        fill("Exchange", t_exch)
                        fill("Security ID", t_sec)
                        fill("Status (Watch/Active/Closed)", "Watchlist")
                        fill("Entry CMP / Range", pre_parsed.get('entry', ''))
                        fill("Stop Loss (SL)", pre_parsed.get('sl', ''))
                        fill("Target 1", pre_parsed.get('t1', ''))
                        fill("Raw Tip Text", s_row['Raw Message Text'])
                        bulk_watchlist_rows.append(new_row)
                        status_updates.append({'range': f"D{s_row['_Row_ID']}", 'values': [["Successfully Staged"]]})
                    if bulk_watchlist_rows: target_watchlist_ws.append_rows(bulk_watchlist_rows)
                    
                if status_updates:
                    raw_log_ws.batch_update(status_updates)
                    fetch_dataframe_safe.clear()
                    st.toast(f"Staged elements redirected successfully!")
                    time.sleep(0.5); st.rerun()

            if b2.button("📦 Archive Selected Rows", key=f"arc_{tab_name}", use_container_width=True) and not selected_rows.empty:
                try: archive_ws = wb_obj.worksheet("Telegram_Archive")
                except: archive_ws = wb_obj.add_worksheet(title="Telegram_Archive", rows="2000", cols="4")
                
                arc_rows, status_updates = [], []
                for _, s_row in selected_rows.iterrows():
                    arc_rows.append([str(s_row['Timestamp']), str(s_row['Channel Source']), str(s_row['Raw Message Text']), datetime.today().strftime("%Y-%m-%d")])
                    status_updates.append({'range': f"D{s_row['_Row_ID']}", 'values': [["Archived Data"]]})
                if arc_rows:
                    archive_ws.append_rows(arc_rows)
                    raw_log_ws.batch_update(status_updates)
                    fetch_dataframe_safe.clear()
                    st.toast(f"Archived successfully.")
                    time.sleep(0.5); st.rerun()

            if b3.button("🗑️ Discard Selected Rows", key=f"dsc_{tab_name}", use_container_width=True) and not selected_rows.empty:
                status_updates = [{'range': f"D{s_row['_Row_ID']}", 'values': [["Discarded"]]} for _, s_row in selected_rows.iterrows()]
                raw_log_ws.batch_update(status_updates)
                fetch_dataframe_safe.clear()
                st.toast(f"Discarded successfully.")
                time.sleep(0.5); st.rerun()

        with sub_mentions: render_bulk_table(df_mentions, "Stock Mentions")
        with sub_news: render_bulk_table(df_news, "News Feeds")
        with sub_discussions: render_bulk_table(df_discussions, "General Discussions")
        
    else: st.info("System initializing tracking logs. Awaiting fresh inbound advisory data.")
