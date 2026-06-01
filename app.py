import streamlit as st
import pandas as pd
import io
import re
from datetime import datetime
import backend as bk 

# --- PAGE CONFIG MUST BE FIRST ---
st.set_page_config(
    page_title="ARC Trading Terminal", 
    layout="wide",
    initial_sidebar_state="expanded" 
)

# --- CUSTOM CSS FOR INSTITUTIONAL CLEAN LOOK ---
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        [data-testid="stToolbar"] {visibility: hidden;} 
        footer {visibility: hidden;}
        
        /* Fixed Header Cut-off */
        .block-container {padding-top: 4rem; padding-bottom: 0rem;}
        
        /* 1. Log New Trade Button (Primary) - Shade 1: Deep Navy */
        [data-testid="stSidebar"] div.stButton > button[kind="primary"] {
            width: 100%;
            display: flex;
            justify-content: flex-start;
            padding: 14px 20px;
            border-radius: 6px;
            background-color: #0A111A !important; 
            border: 1px solid #1E293B !important;
            color: #F8FAFC !important;
            font-size: 15px;
            font-weight: 500;
            transition: all 0.2s ease;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="primary"] p {
            text-align: left;
            margin: 0;
        }
        [data-testid="stSidebar"] div.stButton > button[kind="primary"]:hover {
            background-color: #111A26 !important;
        }

        /* 2 & 3. Navigation Menu - Styled Radio Buttons */
        [data-testid="stSidebar"] div[role="radiogroup"] {
            gap: 0.5rem; 
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label {
            background-color: #131E2E !important; /* Shade 2: Medium Navy */
            padding: 14px 20px;
            border-radius: 6px;
            margin: 0;
            width: 100%;
            display: flex;
            align-items: center;
            border: 1px solid #1E293B !important;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        /* Hide the default radio circle */
        [data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
            display: none;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label > div:last-child {
            margin-left: 0;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label p {
            font-size: 15px;
            font-weight: 500;
            color: #CBD5E1 !important;
            margin: 0;
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
            background-color: #1A283C !important;
        }
        /* Active Tab State - Shade 3: Lighter Steel Blue */
        [data-testid="stSidebar"] div[role="radiogroup"] > label[data-checked="true"] {
            background-color: #1F314D !important; 
            border-left: 4px solid #4F8BFF !important; 
        }
        [data-testid="stSidebar"] div[role="radiogroup"] > label[data-checked="true"] p {
            color: #FFFFFF !important;
            font-weight: 600;
        }
        
        /* Clean up the Daily API Setup Expander */
        [data-testid="stSidebar"] div[data-testid="stExpander"] {
            border-color: #1E293B;
        }
    </style>
""", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "viewing_trade" not in st.session_state:
    st.session_state.viewing_trade = None
if "viewing_trade_row" not in st.session_state:
    st.session_state.viewing_trade_row = None
if "qp_key" not in st.session_state:
    st.session_state.qp_key = 0

def close_journal():
    st.session_state.viewing_trade = None
    st.session_state.viewing_trade_row = None

# --- DATABASE CONNECTION ---
try:
    worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers = bk.init_db()
except Exception as e:
    st.error(f"Database Connection Failed: {e}")
    st.stop()

# --- DYNAMIC ROW HIGHLIGHTING LOGIC ---
def highlight_rows(row):
    try:
        bg_color = ''
        live_price_str = str(row.get('Live Price', ''))
        entry_range_str = str(row.get('Entry CMP / Range', ''))
        
        if live_price_str.strip() in ['', 'nan', 'None']:
            return [bg_color] * len(row)
            
        live_price = float(live_price_str)
        
        numbers = re.findall(r'[\d\.]+', entry_range_str)
        if not numbers:
            return [bg_color] * len(row)
            
        min_entry = min([float(n) for n in numbers])
        
        if live_price > min_entry:
            bg_color = 'background-color: rgba(39, 174, 96, 0.15);' 
        elif live_price < min_entry:
            bg_color = 'background-color: rgba(231, 76, 60, 0.15);' 
            
        return [bg_color] * len(row)
    except:
        return [''] * len(row)

# --- MODAL: DATA ENTRY FORM ---
@st.dialog("Log New Trade or Scan", width="large")
def trade_entry_modal():
    tab1, tab2 = st.tabs(["Quick Parse (Manual Entry)", "Bulk Import List"])
    
    with tab1:
        st.caption("Paste a tip directly below to extract strike, range, stop loss, and targets automatically.")
        raw_tip = st.text_area("Tip Input:", key=f"qp_{st.session_state.qp_key}", height=100)
        parsed_data = bk.parse_telegram_tip(raw_tip)
        
        search_query = st.text_input("Refine Instrument Search", value=parsed_data["symbol"])
        auto_symbol, auto_sec_id, auto_exch = "", "", "NSE_EQ"
        results = bk.search_instruments(search_query)
        
        if not results.empty:
            selected_display = st.selectbox("Select Exact Option Expiry:", results['SEM_TRADING_SYMBOL'].tolist())
            row = results[results['SEM_TRADING_SYMBOL'] == selected_display].iloc[0]
            auto_symbol = str(row['SEM_TRADING_SYMBOL'])
            auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
            exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
            if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
            elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"
        else:
            if search_query:
                st.warning(f"No matches found for '{search_query}'. Try typing just the root ticker symbol.")
            auto_symbol = search_query

        with st.form("entry_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            with col1: date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
            with col2: source = st.selectbox("Source", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"])
            with col3: trade_type = st.selectbox("Type", ["Option", "Equity"], index=0 if parsed_data["trade_type"] == "Option" else 1)

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
                new_row = [""] * len(sheet_headers)
                def set_val(col_name, val):
                    if col_name in sheet_headers: new_row[sheet_headers.index(col_name)] = val
                set_val("Trade Date", date); set_val("Idea Source (Chartink/Telegram/X/Self)", source)
                set_val("Symbol / Asset", symbol); set_val("Trade Type (Eq/Option)", trade_type)
                set_val("Exchange", exchange); set_val("Security ID", sec_id)
                set_val("Status (Watch/Active/Closed)", status); set_val("Entry CMP / Range", entry_range)
                set_val("Add-On / Dip Levels", add_levels); set_val("Stop Loss (SL)", sl)
                set_val("Target 1", t1); set_val("Target 2", t2)
                set_val("Strategic Rationale (Why I took it)", rationale)
                set_val("Emotions at Entry (FOMO, Calm, etc.)", emotions)
                
                worksheet.append_row(new_row)
                st.session_state.qp_key += 1
                st.rerun()

    with tab2:
        st.caption("Paste a massive block of raw tips here to bulk-process them into your Watchlist.")
        bulk_source = st.selectbox("Source:", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"], key="bulk_src")
        bulk_text = st.text_area("Raw Text Block:", height=200)
        
        if st.button("Process Bulk Upload", type="primary", use_container_width=True):
            raw_lines = [line.strip() for line in bulk_text.split('\n') if line.strip()]
            unique_lines = list(dict.fromkeys(raw_lines))
            rows_to_insert = []
            for line in unique_lines:
                p_data = bk.parse_telegram_tip(line)
                if not p_data['symbol']: continue
                t_sym, t_sec, t_exch = bk.resolve_instrument(p_data['symbol'])
                row = [""] * len(sheet_headers)
                def set_v(col_name, val):
                    if col_name in sheet_headers: row[sheet_headers.index(col_name)] = val
                set_v("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                set_v("Idea Source (Chartink/Telegram/X/Self)", bulk_source)
                set_v("Symbol / Asset", t_sym); set_v("Trade Type (Eq/Option)", p_data['trade_type'])
                set_v("Exchange", t_exch); set_v("Security ID", t_sec)
                set_v("Status (Watch/Active/Closed)", "Watchlist"); set_v("Entry CMP / Range", p_data['entry'])
                set_v("Add-On / Dip Levels", p_data['add_levels']); set_v("Stop Loss (SL)", p_data['sl'])
                set_v("Target 1", p_data['t1']); set_v("Target 2", p_data['t2'])
                rows_to_insert.append(row)
            if rows_to_insert:
                worksheet.append_rows(rows_to_insert)
                st.rerun()

# --- SIDEBAR NAV & SETTINGS ---
with st.sidebar:
    # Removed column wrappers so the logo expands naturally and left-aligns with everything else
    try: 
        st.image("logo.png", use_container_width=True)
    except: 
        st.markdown("## ARC Terminal")
    
    st.markdown("<br>", unsafe_allow_html=True)
    
    if st.button("Log New Trade", type="primary", use_container_width=True):
        trade_entry_modal()
        
    st.markdown("<br>", unsafe_allow_html=True)
        
    current_page = st.radio(
        "Navigation",
        ["Options Tracker", "Chartink Scanners"],
        label_visibility="collapsed"
    )
    
    st.divider()
    with st.expander("Daily API Setup", expanded=False):
        st.caption("Paste today's generated Dhan Access Token here.")
        try: saved_token = settings_sheet.acell('B2').value or ""
        except: saved_token = ""
            
        new_token = st.text_input("Today's Token:", value=saved_token, type="password")
        if st.button("Save Key", use_container_width=True):
            settings_sheet.update_acell('B2', new_token)
            st.success("API Key Locked.")
            st.rerun()

# --- PAGE ROUTING ---
if current_page == "Options Tracker":
    st.markdown("### Options Tracker")
    initial_data = worksheet.get_all_records()
    initial_df = pd.DataFrame(initial_data) if initial_data else pd.DataFrame()

    if not initial_df.empty:
        initial_df['_Sheet_Row'] = range(2, len(initial_df) + 2)
        initial_df["Journal"] = False
        view_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Journal", "Symbol / Asset", "Status (Watch/Active/Closed)", "Entry CMP / Range", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2", "_Sheet_Row"]
        
        for col in view_cols:
            if col not in initial_df.columns: initial_df[col] = ""
            elif col in ["Stop Loss (SL)", "Target 1", "Target 2", "Live Price", "Exit Price"]:
                initial_df[col] = initial_df[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})

        table_column_config = {
            "Journal": st.column_config.CheckboxColumn("Inspect", default=False),
            "Symbol / Asset": st.column_config.TextColumn("Option Contract"), 
            "Idea Source (Chartink/Telegram/X/Self)": st.column_config.TextColumn("Source"), 
            "_Sheet_Row": None, 
            "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True),
            "Entry CMP / Range": st.column_config.TextColumn("Entry Range"),
            "Stop Loss (SL)": st.column_config.TextColumn("Stop Loss"),
            "Target 1": st.column_config.TextColumn("Target 1"),
            "Target 2": st.column_config.TextColumn("Target 2"),
            "Live Price": st.column_config.TextColumn("Live Price"),
            "Exit Price": st.column_config.TextColumn("Exit Price"),
        }
        
        disabled_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Entry CMP / Range"] 

        if st.session_state.get("viewing_trade_row"):
            st.button("Back to Terminal", on_click=close_journal)
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
                    st.caption("Use this if inline editing isn't finding the exact distant expiry you need.")
                    
                    default_search = str(trade_data['Symbol / Asset']).split()[0]
                    fix_query = st.text_input("Search Official Master Database", value=default_search, key="fix_contract_query")
                    fix_results = bk.search_instruments(fix_query)
                    
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
            else:
                st.error("Row context lost. Please return to the terminal.")
                st.button("Back to Terminal", on_click=close_journal)
        else:
            col1, col2 = st.columns([8, 2])
            with col2:
                if st.button("Sync Live Prices", use_container_width=True):
                    bk.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
                    
            tab1, tab2, tab3 = st.tabs(["Watchlist", "Active Trades", "Closed Executions"])
            
            with tab1:
                df_wl = initial_df[initial_df["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
                if not df_wl.empty:
                    st.data_editor(df_wl.style.apply(highlight_rows, axis=1), use_container_width=True, hide_index=True, num_rows="dynamic", key="wl_editor",
                        on_change=bk.run_background_sync, kwargs={"df_filtered": df_wl, "state_key": "wl_editor", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                else: st.info("No records found.")

            with tab2:
                df_act = initial_df[initial_df["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
                if not df_act.empty:
                    st.data_editor(df_act.style.apply(highlight_rows, axis=1), use_container_width=True, hide_index=True, num_rows="dynamic", key="act_editor",
                        on_change=bk.run_background_sync, kwargs={"df_filtered": df_act, "state_key": "act_editor", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                else: st.info("No records found.")
                    
            with tab3:
                df_cls = initial_df[initial_df["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
                if not df_cls.empty:
                    st.data_editor(df_cls.style.apply(highlight_rows, axis=1), use_container_width=True, hide_index=True, num_rows="fixed", key="cls_editor",
                        on_change=bk.run_background_sync, kwargs={"df_filtered": df_cls, "state_key": "cls_editor", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, 
                        disabled=disabled_cols + ["Status (Watch/Active/Closed)", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2"])
                else: st.info("No records found.")
    else:
        st.info("Database connection established. No data available.")

elif current_page == "Chartink Scanners":
    col1, col2 = st.columns([8, 2])
    with col1: st.markdown("### Automated Scan Feeds")
    with col2:
        if st.button("Sync Live Prices", use_container_width=True):
            bk.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
    
    scanner_data = scanner_sheet.get_all_records()
    df_scan = pd.DataFrame(scanner_data) if scanner_data else pd.DataFrame()
    
    if not df_scan.empty:
        df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
        
        tab_ce1, tab_ce2, tab_pos = st.tabs(["CE1", "CE2", "Positional"])
        scan_view_cols = ["Date Added", "Symbol", "Trigger Price", "Live Price", "Trigger Time", "Status", "Notes / Analysis", "_Sheet_Row"]
        scan_col_config = {
            "_Sheet_Row": None,
            "Status": st.column_config.SelectboxColumn("Status", options=["Monitoring", "Moved to Watchlist", "Discarded"], required=True),
            "Trigger Price": st.column_config.TextColumn("Trigger Price"),
            "Live Price": st.column_config.TextColumn("Live Price"),
            "Trigger Time": st.column_config.TextColumn("Trigger Time"),
            "Notes / Analysis": st.column_config.TextColumn("Notes / Analysis")
        }
        for col in ["Notes / Analysis", "Trigger Price", "Live Price", "Trigger Time"]:
            if col in df_scan.columns: df_scan[col] = df_scan[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})

        def render_scanner_tab(tab_obj, filter_name):
            with tab_obj:
                df_filtered = df_scan[df_scan["Scanner"] == filter_name].reset_index(drop=True)
                if not df_filtered.empty:
                    st.data_editor(
                        df_filtered[scan_view_cols],
                        use_container_width=True, hide_index=True, num_rows="dynamic", key=f"scan_{filter_name}",
                        on_change=bk.run_scanner_sync, kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}", "scanner_sheet": scanner_sheet, "scanner_headers": scanner_headers},
                        column_config=scan_col_config, disabled=["Date Added", "Symbol", "Trigger Price", "Live Price", "Trigger Time"]
                    )
                else: st.info(f"No active triggers for {filter_name}.")
        
        render_scanner_tab(tab_ce1, "CE1")
        render_scanner_tab(tab_ce2, "CE2")
        render_scanner_tab(tab_pos, "Positional")
        
        st.divider()
        with st.expander("Import Manual Backup", expanded=False):
            st.caption("Paste copied table directly from Chartink if webhooks fail.")
            scan_type = st.selectbox("Assign to Scanner:", ["CE1", "CE2", "Positional"])
            chartink_data = st.text_area("Data Dump:", height=100)
            
            if st.button("Process Dump", type="primary", use_container_width=True):
                if chartink_data:
                    try:
                        df_pasted = pd.read_csv(io.StringIO(chartink_data), sep='\t')
                        if 'Symbol' in df_pasted.columns:
                            rows_to_add = []
                            for _, row in df_pasted.iterrows():
                                new_row = [""] * len(scanner_headers)
                                def set_sv(col, val):
                                    if col in scanner_headers: new_row[scanner_headers.index(col)] = val
                                set_sv("Date Added", datetime.today().strftime("%Y-%m-%d")); set_sv("Scanner", scan_type)
                                set_sv("Symbol", str(row.get('Symbol', ''))); set_sv("Trigger Price", str(row.get('Close', '')))
                                set_sv("Trigger Time", datetime.now().strftime("%I:%M %p")); set_sv("Status", "Monitoring")
                                set_sv("Notes / Analysis", f"Manual Copy | Vol: {row.get('Volume', 'N/A')}"); set_sv("Live Price", "")
                                rows_to_add.append(new_row)
                            
                            if rows_to_add:
                                scanner_sheet.append_rows(rows_to_add)
                                st.success(f"Saved {len(rows_to_add)} records.")
                                st.rerun()
                        else: st.error("Invalid format. Missing 'Symbol' column.")
                    except Exception as e: st.error("Parse failed. Ensure TSV format.")
    else:
        st.info("System operational. Listening for incoming webhooks...")
