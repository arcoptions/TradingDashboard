import streamlit as st
import pandas as pd
import re
from datetime import datetime
import analytics
import database as db
import broker_api as api

def format_index_display(name, raw_val):
    if not raw_val or raw_val == "-": 
        return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>-</span>"
    
    parts = str(raw_val).split(",")
    if len(parts) == 3:
        lp, diff, pct = parts
        diff_f, pct_f = float(diff), float(pct)
        
        if diff_f == 0 and pct_f == 0:
            return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp;&nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>{lp}</span>"

        sign = "+" if diff_f > 0 else ""
        color = "#089981" if diff_f >= 0 else "#F23645" 
        arrow = "▲" if diff_f >= 0 else "▼"
        
        return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp;&nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>{lp}</span> &nbsp;&nbsp; <span style='color: {color}; font-size: 14px; font-weight: 500;'>{sign}{diff_f:.2f} ({sign}{pct_f:.2f}%) {arrow}</span>"
        
    return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>{raw_val}</span>"

def render_top_ticker_tape(settings_sheet):
    try:
        nifty = format_index_display("NIFTY50", settings_sheet.acell('B10').value)
        html = f"<div class='index-tape'>{nifty}</div>"
        st.markdown(html, unsafe_allow_html=True)
    except: pass

def check_for_audio_alerts(df_act):
    current_targets = len(df_act[df_act['Target Status'] == '🎯 Reached'])
    sl_hits = 0
    for idx, row in df_act.iterrows():
        try:
            live = float(str(row.get('Live Price', '')).strip())
            sl_digits = re.findall(r'[\d\.]+', str(row.get('Stop Loss (SL)', '')).strip())
            if sl_digits and live <= float(sl_digits[0]):
                sl_hits += 1
        except: pass

    if "audio_initialized" not in st.session_state:
        st.session_state.target_hits = current_targets
        st.session_state.sl_hits = sl_hits
        st.session_state.audio_initialized = True
        return

    if current_targets > st.session_state.target_hits:
        st.markdown(f'<audio autoplay style="display:none;"><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg"></audio>', unsafe_allow_html=True)
        st.session_state.target_hits = current_targets
        
    if sl_hits > st.session_state.sl_hits:
        st.markdown(f'<audio autoplay style="display:none;"><source src="https://assets.mixkit.co/active_storage/sfx/2870/2870-preview.mp3" type="audio/mpeg"></audio>', unsafe_allow_html=True)
        st.session_state.sl_hits = sl_hits

def close_journal():
    st.session_state.viewing_trade = None
    st.session_state.viewing_trade_row = None

def render_options_tracker(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    render_top_ticker_tape(settings_sheet)
    
    col_t1, col_t2 = st.columns([9, 1])
    with col_t1: st.markdown("### Options Tracker")
    with col_t2: 
        if st.button("⚙️ UI Reset", help="Click to force sidebar open if stuck", use_container_width=True):
            import streamlit.components.v1 as components
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)
            
    initial_data = worksheet.get_all_records()
    initial_df = pd.DataFrame(initial_data) if initial_data else pd.DataFrame()

    if not initial_df.empty:
        initial_df['_Sheet_Row'] = range(2, len(initial_df) + 2)
        initial_df["Journal"] = False
        initial_df = analytics.compute_signal_indicators(initial_df)
        
        # --- DYNAMIC SOURCE COMPILATION FOR INLINE SELECTBOX CONFIG ---
        try:
            col_target = "Idea Source (Chartink/Telegram/X/Self)"
            if col_target in initial_df.columns:
                raw_srcs = initial_df[col_target].astype(str).str.strip()
                existing_sources = sorted(list(raw_srcs[(raw_srcs != "") & (raw_srcs != "nan") & (raw_srcs != "None")].unique()))
            else:
                existing_sources = []
        except:
            existing_sources = []
            
        defaults = ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chikou Trader", "Chartink", "Self/X"]
        dynamic_source_list = sorted(list(set(defaults + existing_sources)))

        view_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Journal", "Symbol / Asset", "Status (Watch/Active/Closed)", "Vs Entry", "Target Status", "Entry CMP / Range", "Add-On / Dip Levels", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2", "Notes", "Security ID", "_Sheet_Row"]
        for col in view_cols:
            if col not in initial_df.columns: initial_df[col] = ""
            elif col not in ["Journal", "_Sheet_Row"]:
                initial_df[col] = initial_df[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})
        initial_df["Journal"] = initial_df["Journal"].replace({'': False, 'False': False, 'True': True}).astype(bool)

        table_column_config = {
            # Converted Column to an interactive dynamic Selectbox Dropdown
            "Idea Source (Chartink/Telegram/X/Self)": st.column_config.SelectboxColumn("Source", options=dynamic_source_list, required=True),
            "Journal": st.column_config.CheckboxColumn("Inspect", default=False),
            "Symbol / Asset": st.column_config.TextColumn("Option Contract"), 
            "_Sheet_Row": None, 
            "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True),
        }
        disabled_cols = ["Vs Entry", "Target Status"] 

        if st.session_state.get("viewing_trade_row"):
            if st.button("Back to Terminal", key="top_reset_view_btn"):
                close_journal()
                st.rerun()
                
            trade_rows = initial_df[initial_df['_Sheet_Row'] == st.session_state.viewing_trade_row]
            if not trade_rows.empty:
                trade_data = trade_rows.iloc[0]
                sheet_row_id = int(trade_data['_Sheet_Row'])
                st.subheader(f"Trade Review: {trade_data['Symbol / Asset']}")
                
                with st.container(border=True):
                    col1, col2, col3, col4 = st.columns(4)
                    col1.metric("Status", trade_data.get('Status (Watch/Active/Closed)', 'N/A'))
                    col2.metric("Entry Range", trade_data.get('Entry CMP / Range', 'N/A'))
                    col3.metric("Live Price", trade_data.get('Live Price', '-'))
                    col4.metric("Exit Price", trade_data.get('Exit Price', 'Pending'))
                    try:
                        entry_val = float(re.findall(r'[\d\.]+', str(trade_data['Entry CMP / Range']))[0])
                        exit_val = float(str(trade_data['Exit Price']))
                        pnl = exit_val - entry_val
                        if pnl > 0: st.success(f"Net Points Captured: +{round(pnl, 2)}")
                        else: st.error(f"Net Points Lost: {round(pnl, 2)}")
                    except: pass
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    st.markdown("### Advanced Repair Tool")
                    default_search = str(trade_data['Symbol / Asset']).split()[0]
                    fix_query = st.text_input("Search Official Master Database", value=default_search, key="fix_contract_query")
                    fix_results = api.search_instruments(fix_query)
                    updated_symbol = str(trade_data['Symbol / Asset'])
                    updated_sec_id = str(trade_data.get('Security ID', ''))
                    updated_exch = str(trade_data.get('Exchange', 'NSE_EQ'))
                    
                    if not fix_results.empty:
                        selected_fix = st.selectbox("Select Correct Contract & Expiry:", fix_results['SEM_TRADING_SYMBOL'].tolist(), key="fix_contract_select")
                        fix_row = fix_results[fix_results['SEM_TRADING_SYMBOL'] == selected_fix].iloc[0]
                        updated_symbol = str(fix_row['SEM_TRADING_SYMBOL'])
                        updated_sec_id = str(fix_row['SEM_SMST_SECURITY_ID'])
                        exch, seg = str(fix_row['SEM_EXM_EXCH_ID']), str(fix_row['SEM_SEGMENT'])
                        if exch == "NSE" and seg == "E": updated_exch = "NSE_EQ"
                        elif exch == "NSE" and seg == "D": updated_exch = "NSE_FNO"
                    else:
                        if fix_query: st.warning(f"No match found for '{fix_query}'. Try looking up the root ticker symbol.")
                            
                    if st.button("Save & Re-Link Contract", type="primary", key="save_fix_contract", use_container_width=True):
                        sym_col = sheet_headers.index("Symbol / Asset") + 1
                        sec_col = sheet_headers.index("Security ID") + 1
                        exch_col = sheet_headers.index("Exchange") + 1
                        worksheet.update_cell(sheet_row_id, sym_col, updated_symbol)
                        worksheet.update_cell(sheet_row_id, sec_col, updated_sec_id)
                        worksheet.update_cell(sheet_row_id, exch_col, updated_exch)
                        st.success(f"Successfully re-linked row {sheet_row_id} to official asset: {updated_symbol}!")
                        st.session_state.viewing_trade = updated_symbol
                        st.rerun()
                    
                    st.divider()
                    with st.form("psychology_update_form"):
                        curr_rationale = str(trade_data.get('Strategic Rationale (Why I took it)', ''))
                        curr_emotions = str(trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', ''))
                        new_rationale = st.text_area("Execution Rationale", value=curr_rationale if curr_rationale != 'nan' else '')
                        new_emotions = st.text_area("Psychological State", value=curr_emotions if curr_emotions != 'nan' else '')
                        if st.form_submit_button("Update Records", type="primary"):
                            rat_col = sheet_headers.index("Strategic Rationale (Why I took it)") + 1
                            emo_col = sheet_headers.index("Emotions at Entry (FOMO, Calm, etc.)") + 1
                            worksheet.update_cell(sheet_row_id, rat_col, str(new_rationale))
                            worksheet.update_cell(sheet_row_id, emo_col, str(new_emotions))
                            st.success("Database synchronized.")
                            st.rerun()
            else: st.error("Row context lost or mismatch detected. Click the top button to reset the view canvas safely.")
        else:
            if "Trade Date" in initial_df.columns and not initial_df.empty:
                parsed_dates = pd.to_datetime(initial_df["Trade Date"], errors='coerce').dt.date
                valid_dates = parsed_dates.dropna().unique()
                if len(valid_dates) > 0: min_date, max_date = min(valid_dates), max(valid_dates)
                else: min_date, max_date = datetime.today().date(), datetime.today().date()
            else: min_date, max_date = datetime.today().date(), datetime.today().date()

            all_sources = sorted(list(initial_df["Idea Source (Chartink/Telegram/X/Self)"].dropna().unique())) if "Idea Source (Chartink/Telegram/X/Self)" in initial_df.columns else []
            
            f_col1, f_col2, f_col3 = st.columns([4, 4, 2], vertical_alignment="bottom")
            with f_col1: selected_sources = st.multiselect("Filter by Source", options=all_sources, default=all_sources)
            with f_col2: selected_date_range = st.date_input("Filter by Date Range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
            with f_col3:
                if st.button("Sync Live Prices", use_container_width=True): api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
            
            try: timestamp_val = settings_sheet.acell('B9').value or "Pending"
            except: timestamp_val = "Pending"
            st.markdown(f"<div class='sync-timestamp-text'>Last Synced: {timestamp_val}</div>", unsafe_allow_html=True)

            filtered_df = initial_df.copy()
            if "Idea Source (Chartink/Telegram/X/Self)" in filtered_df.columns and selected_sources:
                filtered_df = filtered_df[filtered_df["Idea Source (Chartink/Telegram/X/Self)"].isin(selected_sources)]
            
            if "Trade Date" in filtered_df.columns and not filtered_df.empty:
                filtered_df['_Tmp_Date'] = pd.to_datetime(filtered_df["Trade Date"], errors='coerce').dt.date
                if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
                    filtered_df = filtered_df[(filtered_df['_Tmp_Date'] >= selected_date_range[0]) & (filtered_df['_Tmp_Date'] <= selected_date_range[1])]
                elif isinstance(selected_date_range, tuple) and len(selected_date_range) == 1:
                    filtered_df = filtered_df[filtered_df['_Tmp_Date'] == selected_date_range[0]]
                filtered_df = filtered_df.drop(columns=['_Tmp_Date'])
                    
            tab1, tab2, tab3 = st.tabs(["Watchlist", "Active Trades", "Closed Executions"])
            
            with tab1:
                df_wl = filtered_df[filtered_df["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
                if not df_wl.empty:
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total Assets", len(df_wl))
                    m2.metric("🟢 Above Entry", len(df_wl[df_wl['Vs Entry'] == '🟢 Above']))
                    m3.metric("🔴 Below Entry", len(df_wl[df_wl['Vs Entry'] == '🔴 Below']))
                    m4.metric("🎯 Targets Reached", len(df_wl[df_wl['Target Status'] == '🎯 Reached']))
                    st.write("")
                    st.data_editor(df_wl[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key="wl_editor",
                        on_change=db.run_background_sync, kwargs={"df_filtered": df_wl, "state_key": "wl_editor", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                else: st.info("No records found.")

            with tab2:
                df_act = filtered_df[filtered_df["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
                if not df_act.empty:
                    check_for_audio_alerts(df_act)
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total Active Positions", len(df_act))
                    m2.metric("🟢 Floating Profit", len(df_act[df_act['Vs Entry'] == '🟢 Above']))
                    m3.metric("🔴 Floating Loss", len(df_act[df_act['Vs Entry'] == '🔴 Below']))
                    m4.metric("🎯 Targets Reached", len(df_act[df_act['Target Status'] == '🎯 Reached']))
                    st.write("")
                    st.data_editor(df_act[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key="act_editor",
                        on_change=db.run_background_sync, kwargs={"df_filtered": df_act, "state_key": "act_editor", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                else: st.info("No records found.")
                    
            with tab3:
                df_cls = filtered_df[filtered_df["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
                if not df_cls.empty:
                    st.data_editor(df_cls[view_cols], use_container_width=True, hide_index=True, num_rows="fixed", key="cls_editor",
                        on_change=db.run_background_sync, kwargs={"df_filtered": df_cls, "state_key": "cls_editor", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, 
                        disabled=disabled_cols + ["Status (Watch/Active/Closed)", "Entry CMP / Range", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2"])
                else: st.info("No records found.")
    else: st.info("Database connection established. No data available.")

def render_chartink_scanners(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    render_top_ticker_tape(settings_sheet)
    col_t1, col_t2 = st.columns([9, 1], vertical_alignment="bottom")
    with col_t1: st.markdown("### Automated Scan Feeds")
    with col_t2: 
        if st.button("⚙️ UI Reset", help="Click to force sidebar open if stuck", use_container_width=True):
            import streamlit.components.v1 as components
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)
            
    col1, col2 = st.columns([8, 2], vertical_alignment="bottom")
    with col1: st.write("")
    with col2:
        if st.button("Sync Live Prices", use_container_width=True, key="sync_scanner"):
            api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
        
    try: timestamp_val = settings_sheet.acell('B9').value or "Pending"
    except: timestamp_val = "Pending"
    st.markdown(f"<div class='sync-timestamp-text'>Last Synced: {timestamp_val}</div>", unsafe_allow_html=True)
    
    scanner_data = scanner_sheet.get_all_records()
    df_scan = pd.DataFrame(scanner_data) if scanner_data else pd.DataFrame()
    
    if not df_scan.empty:
        df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
        df_scan = analytics.compute_scanner_signals(df_scan)
        
        tab_ce1, tab_ce2, tab_pos = st.tabs(["CE1", "CE2", "Positional"])
        scan_view_cols = ["Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time", "Status", "Notes / Analysis", "_Sheet_Row"]
        scan_col_config = {"_Sheet_Row": None, "Status": st.column_config.SelectboxColumn("Status", options=["Monitoring", "Moved to Watchlist", "Discarded"], required=True)}

        def render_scanner_tab(tab_obj, filter_name):
            with tab_obj:
                df_filtered = df_scan[df_scan["Scanner"] == filter_name].reset_index(drop=True)
                if not df_filtered.empty:
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total Triggers", len(df_filtered))
                    m2.metric("🟢 Holding Above", len(df_filtered[df_filtered['Vs Entry'] == '🟢 Above']))
                    m3.metric("🔴 Slipped Below", len(df_filtered[df_filtered['Vs Entry'] == '🔴 Below']))
                    m4.metric("⚪ Flat / Pending", len(df_filtered[df_filtered['Vs Entry'].isin(['⚪ At Entry', '-'])]))
                    st.write("")
                    st.data_editor(
                        df_filtered[scan_view_cols],
                        use_container_width=True, hide_index=True, num_rows="dynamic", key=f"scan_{filter_name}",
                        on_change=db.run_scanner_sync, kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}", "scanner_sheet": scanner_sheet, "scanner_headers": scanner_headers},
                        column_config=scan_col_config, disabled=["Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time"]
                    )
                else: st.info(f"No active triggers for {filter_name}.")
        
        render_scanner_tab(tab_ce1, "CE1")
        render_scanner_tab(tab_ce2, "CE2")
        render_scanner_tab(tab_pos, "Positional")
