import streamlit as st
import pandas as pd
import re
from datetime import datetime
import analytics
import broker_api as api
from integrations.google_sheets import fetch_dataframe_safe, fetch_settings_dict

@st.dialog("Log New Trade or Scan", width="large")
def trade_entry_modal(worksheet, sheet_headers):
    if "qp_key" not in st.session_state: 
        st.session_state.qp_key = 0

    try:
        records = worksheet.get_all_records()
        if records:
            df_existing = pd.DataFrame(records)
            col_name = "Idea Source (Chartink/Telegram/X/Self)"
            if col_name in df_existing.columns:
                raw_sources = df_existing[col_name].astype(str).str.strip()
                existing_sources = sorted(list(raw_sources[(raw_sources != "") & (raw_sources != "nan") & (raw_sources != "None")].unique()))
            else: existing_sources = []
        else: existing_sources = []
    except: existing_sources = []

    defaults = ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chikou Trader", "Chartink", "Self/X"]
    source_options = sorted(list(set(defaults + existing_sources)))

    tab1, tab2 = st.tabs(["Quick Parse (Manual Entry)", "Bulk Import List"])
    
    with tab1:
        st.caption("Paste any raw stock tips or option alerts here. The layout engine will process them into fields automatically.")
        raw_tip = st.text_area("Tip Input:", key=f"qp_{st.session_state.qp_key}", height=95)
        parsed_data = analytics.parse_telegram_tip(raw_tip)
        
        search_query = st.text_input("Refine Instrument Search", value=parsed_data["symbol"])
        auto_symbol, auto_sec_id, auto_exch = "", "", "NSE_EQ"
        results = api.search_instruments(search_query)
        
        if not results.empty:
            selected_display = st.selectbox("Select Exact Asset/Contract Expiry:", results['SEM_TRADING_SYMBOL'].tolist())
            row = results[results['SEM_TRADING_SYMBOL'] == selected_display].iloc[0]
            auto_symbol = str(row['SEM_TRADING_SYMBOL'])
            auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
            exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
            if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
            elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"
        else:
            if search_query:
                st.warning(f"⚠️ '{search_query}' not found in live Dhan scrip master. This could mean: (1) Contract expired, (2) Strike doesn't exist yet, (3) Data not synced. You can manually type the symbol below.")
            auto_symbol = search_query

        with st.form("entry_form", clear_on_submit=True):
            col1, col2, col3, col4 = st.columns(4)
            with col1: date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
            with col2: source_sel = st.selectbox("Source", source_options)
            with col3: custom_source = st.text_input("Custom Override", placeholder="New group name")
            with col4: trade_type = st.selectbox("Type", ["Option", "Equity"], index=0 if parsed_data["trade_type"] == "Option" else 1)

            symbol = st.text_input("Validated Asset Symbol", value=auto_symbol)
            exchange = st.selectbox("Exchange", ["NSE_EQ", "NSE_FNO"], index=0 if auto_exch == "NSE_EQ" else 1, label_visibility="collapsed", disabled=True)
            sec_id = st.text_input("Security ID", value=auto_sec_id, label_visibility="collapsed", disabled=True)
            
            c1, c2, c3, c4 = st.columns(4)
            with c1: status = st.selectbox("Status", ["Watchlist", "Active", "Closed"])
            with c2: entry_range = st.text_input("Entry Range/CMP", value=parsed_data["entry"])
            with c3: sl = st.text_input("Stop Loss (SL)", value=parsed_data["sl"])
            with c4: t1 = st.text_input("Target 1", value=parsed_data["t1"])
            
            tc1, tc2, tc3 = st.columns([2, 2, 4])
            with tc1: t2 = st.text_input("Target 2", value=parsed_data["t2"], placeholder="Target 2")
            with tc2: add_levels = st.text_input("Add-On Levels", value=parsed_data["add_levels"], placeholder="Add-On Levels")
            with tc3: emotions = st.text_input("Psychology", placeholder="Emotions at Entry")
            
            xc1, xc2 = st.columns(2)
            with xc1: timeframe_val = st.text_input("Horizon Time Frame (TF)", value=parsed_data["tf"], placeholder="e.g. 2 Months, 1 Year")
            with xc2: rating_val = st.text_input("Setup Strategic Rating", value=parsed_data["rating"], placeholder="e.g. 8.75/10")
            
            with st.expander("🔎 Verify Original Raw Tip Text"):
                raw_tip_captured = st.text_area("Original Text File Log", value=parsed_data["raw_text"], height=70)
                rationale = st.text_area("Execution Logic/Rationale", placeholder="Notes...", height=60)
            
            if st.form_submit_button("Submit Entry to Google Sheet Database", type="primary", use_container_width=True):
                final_source = custom_source.strip() if custom_source.strip() else source_sel
                new_row = [""] * len(sheet_headers)
                
                def set_val(col_name, val):
                    if col_name in sheet_headers: new_row[sheet_headers.index(col_name)] = val
                
                set_val("Trade Date", date); set_val("Idea Source (Chartink/Telegram/X/Self)", final_source)
                set_val("Symbol / Asset", symbol); set_val("Trade Type (Eq/Option)", trade_type)
                set_val("Exchange", exchange); set_val("Security ID", sec_id)
                set_val("Status (Watch/Active/Closed)", status); set_val("Entry CMP / Range", entry_range)
                set_val("Add-On / Dip Levels", add_levels); set_val("Stop Loss (SL)", sl)
                set_val("Target 1", t1); set_val("Target 2", t2)
                set_val("Strategic Rationale (Why I took it)", rationale)
                set_val("Emotions at Entry (FOMO, Calm, etc.)", emotions)
                
                set_val("Time Frame", timeframe_val)
                set_val("Setup Rating", rating_val)
                set_val("Raw Tip Text", raw_tip_captured)
                
                worksheet.append_row(new_row)
                fetch_dataframe_safe.clear()
                st.session_state.qp_key += 1
                st.rerun()

    with tab2:
        st.caption("Paste a sequence of text tips block to batch process standard items directly to Watchlist layout.")
        c1, c2 = st.columns(2)
        with c1: bulk_source_sel = st.selectbox("Source Reference:", source_options, key="bulk_src")
        with c2: bulk_custom_source = st.text_input("Custom Override:", key="bulk_cust_src")
        bulk_text = st.text_area("Bulk Text Block Parsing Window:", height=200)
        
        if st.button("Execute Bulk Portfolio Upload", type="primary", use_container_width=True):
            final_bulk_source = bulk_custom_source.strip() if bulk_custom_source.strip() else bulk_source_sel
            raw_lines = [line.strip() for line in bulk_text.split('\n') if line.strip()]
            unique_lines = list(dict.fromkeys(raw_lines))
            rows_to_insert = []
            
            try: existing_records = worksheet.get_all_records()
            except: existing_records = []
            existing_symbols = [str(r.get('Symbol / Asset', '')).upper().strip() for r in existing_records]
            existing_bases = [s.split('-')[0].split(' ')[0].strip() for s in existing_symbols]
            
            try: from core_engines.nlp_router import FNO_SYMBOLS
            except: FNO_SYMBOLS = []
            
            daily_token = fetch_settings_dict().get("Dhan Access Token", "")
            
            for line in unique_lines:
                p_data = analytics.parse_telegram_tip(line)
                if not p_data['symbol']: continue
                t_sym, t_sec, t_exch = api.resolve_instrument(p_data['symbol'])
                if not t_sec: continue
                
                base_to_check = t_sym.split('-')[0].split(' ')[0].strip()
                if base_to_check in existing_bases: continue
                
                is_fno = base_to_check in FNO_SYMBOLS or p_data.get('trade_type') == 'Option'
                contract_symbol = t_sym
                auto_derived_type = "Option" if is_fno else "Equity"
                final_exch = "NSE_FNO" if is_fno else t_exch
                
                if is_fno:
                    if " CE" not in p_data.get("symbol", "").upper() and " PE" not in p_data.get("symbol", "").upper():
                        chain_data = api.get_option_chain_metrics(base_to_check, daily_token=daily_token)
                        is_put = "PE" in p_data.get("symbol", "").upper() or "PUT" in line.upper()
                        target_key = "best_pe" if is_put else "best_ce"
                        if chain_data and chain_data.get(target_key) and chain_data.get(target_key) != "-":
                            opt_suffix = "PE" if is_put else "CE"
                            contract_symbol = f"{base_to_check} {chain_data[target_key]} {opt_suffix} (Auto-Suggested)"

                row = [""] * len(sheet_headers)
                def set_v(col_name, val):
                    if col_name in sheet_headers: row[sheet_headers.index(col_name)] = val
                
                set_v("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                set_v("Idea Source (Chartink/Telegram/X/Self)", final_bulk_source)
                set_v("Symbol / Asset", contract_symbol)
                set_v("Trade Type (Eq/Option)", auto_derived_type)
                set_v("Exchange", final_exch)
                set_v("Security ID", t_sec)
                set_v("Status (Watch/Active/Closed)", "Watchlist")
                set_v("Entry CMP / Range", p_data['entry'])
                set_v("Add-On / Dip Levels", p_data['add_levels'])
                set_v("Stop Loss (SL)", p_data['sl'])
                set_v("Target 1", p_data['t1'])
                set_v("Target 2", p_data['t2'])
                set_v("Time Frame", p_data['tf'])
                set_v("Setup Rating", p_data['rating'])
                set_v("Raw Tip Text", line)
                
                rows_to_insert.append(row)
                existing_bases.append(base_to_check)
                
            if rows_to_insert:
                worksheet.append_rows(rows_to_insert)
                fetch_dataframe_safe.clear()
                st.rerun()
            else:
                st.warning("All lines were either duplicates or invalid instruments. Nothing was added.")
