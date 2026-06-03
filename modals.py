import streamlit as st
import pandas as pd
import re
from datetime import datetime
import analytics
import broker_api as api

@st.dialog("Log New Trade or Scan", width="large")
def trade_entry_modal(worksheet, sheet_headers):
    # 1. Dynamically pull existing unique sources from database rows
    try:
        records = worksheet.get_all_records()
        if records:
            df_existing = pd.DataFrame(records)
            col_name = "Idea Source (Chartink/Telegram/X/Self)"
            if col_name in df_existing.columns:
                # Clean out blank lines, null strings, or NaN cells
                raw_sources = df_existing[col_name].astype(str).str.strip()
                existing_sources = sorted(list(raw_sources[(raw_sources != "") & (raw_sources != "nan") & (raw_sources != "None")].unique()))
            else:
                existing_sources = []
        else:
            existing_sources = []
    except:
        existing_sources = []

    # 2. Merge your permanent baseline favorites with whatever unique values are in the sheet
    defaults = ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chikou Trader", "Chartink", "Self/X"]
    source_options = sorted(list(set(defaults + existing_sources)))

    tab1, tab2 = st.tabs(["Quick Parse (Manual Entry)", "Bulk Import List"])
    
    with tab1:
        st.caption("Paste a tip directly below to extract strike, range, stop loss, and targets automatically.")
        raw_tip = st.text_area("Tip Input:", key=f"qp_{st.session_state.qp_key}", height=100)
        parsed_data = analytics.parse_telegram_tip(raw_tip)
        
        search_query = st.text_input("Refine Instrument Search", value=parsed_data["symbol"])
        auto_symbol, auto_sec_id, auto_exch = "", "", "NSE_EQ"
        results = api.search_instruments(search_query)
        
        if not results.empty:
            selected_display = st.selectbox("Select Exact Option Expiry:", results['SEM_TRADING_SYMBOL'].tolist())
            row = results[results['SEM_TRADING_SYMBOL'] == selected_display].iloc[0]
            auto_symbol = str(row['SEM_TRADING_SYMBOL'])
            auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
            exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
            if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
            elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"
        else:
            if search_query: st.warning(f"⚠️ No matches found for '{search_query}'. Try typing just the root ticker symbol.")
            auto_symbol = search_query

        with st.form("entry_form", clear_on_submit=True):
            col1, col2, col3, col4 = st.columns(4)
            with col1: date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
            with col2: source_sel = st.selectbox("Source", source_options) # Dynamic Dropdown List
            with col3: custom_source = st.text_input("Custom Source", placeholder="New source override")
            with col4: trade_type = st.selectbox("Type", ["Option", "Equity"], index=0 if parsed_data["trade_type"] == "Option" else 1)

            symbol = st.text_input("Validated Asset Name (Do not edit if auto-filled)", value=auto_symbol)
            exchange = st.selectbox("Exchange", ["NSE_EQ", "NSE_FNO"], index=0 if auto_exch == "NSE_EQ" else 1, label_visibility="collapsed", disabled=True)
            sec_id = st.text_input("Security ID", value=auto_sec_id, label_visibility="collapsed", disabled=True)
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: status = st.selectbox("Status", ["Watchlist", "Active", "Closed"])
            with c2: entry_range = st.text_input("Entry Range", value=parsed_data["entry"])
            with c3: sl = st.text_input("Stop Loss", value=parsed_data["sl"])
            with c4: t1 = st.text_input("Target 1", value=parsed_data["t1"])
            
            t2 = st.text_input("Target 2", value=parsed_data["t2"], label_visibility="collapsed", placeholder="Target 2 (Optional)")
            add_levels = st.text_input("Add-On Levels", value=parsed_data["add_levels"], label_visibility="collapsed", placeholder="Add-On Levels (Optional)")
            emotions = st.text_input("Psychology", placeholder="Emotions at Entry (FOMO, Calm, etc.)")
            rationale = st.text_area("Rationale", placeholder="Why are you taking this trade?", height=68)
            
            if st.form_submit_button("Submit to Database", type="primary", use_container_width=True):
                final_source = custom_source.strip() if custom_source.strip() else source_sel
                
                new_row = [""] * len(sheet_headers)
                def set_val(col_name, val):
                    if col_name in sheet_headers: new_row[sheet_headers.index(col_name)] = val
                
                set_val("Trade Date", date)
                set_val("Idea Source (Chartink/Telegram/X/Self)", final_source)
                set_val("Symbol / Asset", symbol)
                set_val("Trade Type (Eq/Option)", trade_type)
                set_val("Exchange", exchange)
                set_val("Security ID", sec_id)
                set_val("Status (Watch/Active/Closed)", status)
                set_val("Entry CMP / Range", entry_range)
                set_val("Add-On / Dip Levels", add_levels)
                set_val("Stop Loss (SL)", sl)
                set_val("Target 1", t1)
                set_val("Target 2", t2)
                set_val("Strategic Rationale (Why I took it)", rationale)
                set_val("Emotions at Entry (FOMO, Calm, etc.)", emotions)
                
                worksheet.append_row(new_row)
                st.session_state.qp_key += 1
                st.rerun()

    with tab2:
        st.caption("Paste a massive block of raw tips here to bulk-process them into your Watchlist.")
        c1, c2 = st.columns(2)
        with c1: bulk_source_sel = st.selectbox("Source:", source_options, key="bulk_src") # Dynamic Dropdown List
        with c2: bulk_custom_source = st.text_input("Custom Source (Overrides Dropdown):", key="bulk_cust_src")
        bulk_text = st.text_area("Raw Text Block:", height=200)
        
        if st.button("Process Bulk Upload", type="primary", use_container_width=True):
            final_bulk_source = bulk_custom_source.strip() if bulk_custom_source.strip() else bulk_source_sel
            raw_lines = [line.strip() for line in bulk_text.split('\n') if line.strip()]
            unique_lines = list(dict.fromkeys(raw_lines))
            rows_to_insert = []
            
            for line in unique_lines:
                p_data = analytics.parse_telegram_tip(line)
                if not p_data['symbol']: continue
                t_sym, t_sec, t_exch = api.resolve_instrument(p_data['symbol'])
                
                row = [""] * len(sheet_headers)
                def set_v(col_name, val):
                    if col_name in sheet_headers: row[sheet_headers.index(col_name)] = val
                
                set_v("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                set_v("Idea Source (Chartink/Telegram/X/Self)", final_bulk_source)
                set_v("Symbol / Asset", t_sym)
                set_v("Trade Type (Eq/Option)", p_data['trade_type'])
                set_v("Exchange", t_exch)
                set_v("Security ID", t_sec)
                set_v("Status (Watch/Active/Closed)", "Watchlist")
                set_v("Entry CMP / Range", p_data['entry'])
                set_v("Add-On / Dip Levels", p_data['add_levels'])
                set_v("Stop Loss (SL)", p_data['sl'])
                set_v("Target 1", p_data['t1'])
                set_v("Target 2", p_data['t2'])
                
                rows_to_insert.append(row)
                
            if rows_to_insert:
                worksheet.append_rows(rows_to_insert)
                st.rerun()
