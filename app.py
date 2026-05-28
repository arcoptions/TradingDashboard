import re
import io
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

# PAGE CONFIG MUST BE FIRST
st.set_page_config(
    page_title="ARC Trading Terminal", 
    layout="wide",
    initial_sidebar_state="expanded" # Forces the sidebar to stay open!
)

# CUSTOM CSS: Hides Streamlit branding but keeps the sidebar toggle safe!
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        [data-testid="stToolbar"] {visibility: hidden;} /* Hides the Deploy/GitHub icons */
        footer {visibility: hidden;}
        .block-container {padding-top: 2rem; padding-bottom: 0rem;}
    </style>
""", unsafe_allow_html=True)

st.markdown("## ARC Trading Terminal")

if "viewing_trade" not in st.session_state:
    st.session_state.viewing_trade = None

def close_journal():
    st.session_state.viewing_trade = None

# --- 1. NLP PARSER ---
def parse_telegram_tip(text):
    data = {"symbol": "", "trade_type": "Equity", "entry": "", "add_levels": "", "sl": "", "t1": "", "t2": ""}
    if not text: return data
        
    option_match = re.search(r'([A-Z\&]+)\s+(\d+)\s+(ce|pe|call|put)', text, re.IGNORECASE)
    if option_match:
        opt_type = option_match.group(3).upper()
        if opt_type == 'CALL': opt_type = 'CE'
        if opt_type == 'PUT': opt_type = 'PE'
        data["symbol"] = f"{option_match.group(1).upper()} {option_match.group(2)} {opt_type}"
        data["trade_type"] = "Option"
    else:
        equity_match = re.search(r'^([A-Z\&]+)\b', text)
        if equity_match: data["symbol"] = equity_match.group(1).upper()
            
    range_match = re.search(r'range\s+([\d\.-]+)', text, re.IGNORECASE)
    if range_match: data["entry"] = range_match.group(1)
    else:
        cmp_match = re.search(r'cmp\s+([\d\.]+)', text, re.IGNORECASE)
        if cmp_match: data["entry"] = cmp_match.group(1)
            
    add_match = re.search(r'add more\s*(?:levels?)?[-\s]*([\d\.\s-]+?)(?:\s+if comes|\.|\s+SL)', text, re.IGNORECASE)
    if add_match: data["add_levels"] = add_match.group(1).strip('- ')
        
    sl_match = re.search(r'SL\s+([\d\.]+\s*(?:clsb)?)', text, re.IGNORECASE)
    if sl_match: data["sl"] = sl_match.group(1)
        
    target_match = re.search(r'Target\s+([\d\.\s-]+)', text, re.IGNORECASE)
    if target_match:
        targets = re.findall(r'([\d\.]+)', target_match.group(1))
        if len(targets) > 0: data["t1"] = targets[0]
        if len(targets) > 1: data["t2"] = targets[1]
            
    return data

# --- 2. AUTO-DOWNLOAD SCRIP MASTER & RESOLVER ---
@st.cache_data(ttl=43200)
def get_dhan_scrip_master(v=12):
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty: return df
        return df[df['SEM_EXM_EXCH_ID'] == 'NSE']
    except: return pd.DataFrame()

scrip_df = get_dhan_scrip_master(v=12)

def search_instruments(query):
    if not query or scrip_df.empty: return pd.DataFrame()
    terms = query.upper().split()
    if 'SEARCH_STRING' not in scrip_df.columns:
        scrip_df['SEARCH_STRING'] = scrip_df['SEM_TRADING_SYMBOL'].fillna('') + " " + scrip_df['SEM_CUSTOM_SYMBOL'].fillna('')
        
    mask = pd.Series([True] * len(scrip_df))
    for term in terms:
        mask = mask & scrip_df['SEARCH_STRING'].str.upper().str.contains(term, regex=False)
        
    results = scrip_df[mask].copy()
    if not results.empty and 'SEM_EXPIRY_DATE' in results.columns:
        results['Parsed_Expiry'] = pd.to_datetime(results['SEM_EXPIRY_DATE'], errors='coerce')
        today = pd.Timestamp.today().normalize()
        results = results[(results['Parsed_Expiry'] >= today) | (results['Parsed_Expiry'].isna())]
        results = results.sort_values(by='Parsed_Expiry', ascending=True)
        
    return results.head(30)

def resolve_instrument(parsed_sym):
    results = search_instruments(parsed_sym)
    if not results.empty:
        row = results.iloc[0]
        sym = str(row['SEM_TRADING_SYMBOL'])
        sec = str(row['SEM_SMST_SECURITY_ID'])
        exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
        if exch == "NSE" and seg == "E": return sym, sec, "NSE_EQ"
        elif exch == "NSE" and seg == "D": return sym, sec, "NSE_FNO"
    return parsed_sym, "", "NSE_EQ"

# --- 3. AUTHENTICATION & GOOGLE SHEETS SETUP ---
try:
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    
    worksheet = sh.sheet1
    sheet_headers = worksheet.row_values(1)
    required_cols = ["Live Price", "Exit Price"]
    for col in required_cols:
        if col not in sheet_headers:
            worksheet.update_cell(1, len(sheet_headers) + 1, col)
            sheet_headers.append(col)
            
    worksheet_list = [ws.title for ws in sh.worksheets()]
    if "Scanners" in worksheet_list:
        scanner_sheet = sh.worksheet("Scanners")
    else:
        scanner_sheet = sh.add_worksheet(title="Scanners", rows="1000", cols="10")
        scanner_sheet.append_row(["Date Added", "Scanner", "Symbol", "Trigger Price", "Trigger Time", "Status", "Notes / Analysis"])
    scanner_headers = scanner_sheet.row_values(1)
    
except Exception as e:
    st.error(f"Database Connection Failed: {e}")
    st.stop()

# --- 4. SIDEBAR PANEL: NAVIGATION ---
with st.sidebar:
    # LOADS BRANDING LOGO
    try:
        st.image("logo.png", use_column_width=True)
    except:
        pass # Silently skips if logo.png hasn't been uploaded yet
        
    st.subheader("Navigation")
    current_page = st.radio(
        "Navigation Links", 
        ["Options Tracker", "Chartink Scanners"], 
        label_visibility="collapsed"
    )
    st.divider()

    # ==========================================
    # DATA ENTRY PANELS
    # ==========================================
    if current_page == "Options Tracker":
        st.subheader("Data Entry")

        with st.expander("Bulk Import", expanded=False):
            bulk_text = st.text_area("Raw Text Block:")
            bulk_source = st.selectbox("Source:", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"], key="bulk_src")
            if st.button("Process to Watchlist", type="primary", use_container_width=True):
                raw_lines = [line.strip() for line in bulk_text.split('\n') if line.strip()]
                unique_lines = list(dict.fromkeys(raw_lines))
                rows_to_insert = []
                for line in unique_lines:
                    p_data = parse_telegram_tip(line)
                    if not p_data['symbol']: continue
                    t_sym, t_sec, t_exch = resolve_instrument(p_data['symbol'])
                    row = [""] * len(sheet_headers)
                    def set_v(col_name, val):
                        if col_name in sheet_headers: row[sheet_headers.index(col_name)] = val
                    set_v("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                    set_v("Idea Source (Chartink/Telegram/X/Self)", bulk_source)
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
                    st.success(f"Processed {len(rows_to_insert)} items.")
                    st.rerun()

        with st.expander("Manual Entry", expanded=True):
            raw_tip = st.text_area("Quick Parse:")
            parsed_data = parse_telegram_tip(raw_tip)
            search_query = st.text_input("Find Instrument", value=parsed_data["symbol"])
            auto_symbol, auto_sec_id, auto_exch = "", "", "NSE_EQ"
            results = search_instruments(search_query)
            if not results.empty:
                selected_display = st.selectbox("Select Expiry:", results['SEM_TRADING_SYMBOL'].tolist())
                row = results[results['SEM_TRADING_SYMBOL'] == selected_display].iloc[0]
                auto_symbol = str(row['SEM_TRADING_SYMBOL'])
                auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
                exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
                if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
                elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"

            with st.form("entry_form"):
                date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
                source = st.selectbox("Source", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"])
                symbol = st.text_input("Asset", value=auto_symbol if auto_symbol else parsed_data["symbol"])
                trade_type = st.selectbox("Type", ["Option", "Equity"], index=0 if parsed_data["trade_type"] == "Option" else 1)
                exchange = st.selectbox("Exchange", ["NSE_EQ", "NSE_FNO"], index=0 if auto_exch == "NSE_EQ" else 1)
                sec_id = st.text_input("Security ID", value=auto_sec_id)
                status = st.selectbox("Status", ["Watchlist", "Active", "Closed"])
                entry_range = st.text_input("Entry Range", value=parsed_data["entry"])
                add_levels = st.text_input("Add-On Levels", value=parsed_data["add_levels"])
                sl = st.text_input("Stop Loss", value=parsed_data["sl"])
                t1 = st.text_input("Target 1", value=parsed_data["t1"])
                t2 = st.text_input("Target 2", value=parsed_data["t2"])
                rationale = st.text_area("Pre-Trade Rationale")
                emotions = st.text_input("Emotions at Entry")
                
                if st.form_submit_button("Submit Trade", use_container_width=True):
                    new_row = [""] * len(sheet_headers)
                    def set_val(col_name, val):
                        if col_name in sheet_headers: new_row[sheet_headers.index(col_name)] = val
                    set_val("Trade Date", date)
                    set_val("Idea Source (Chartink/Telegram/X/Self)", source)
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
                    st.success("Trade Logged.")
                    st.rerun()

    elif current_page == "Chartink Scanners":
        st.subheader("Manual Backup")
        with st.expander("Import Table Data", expanded=True):
            st.caption("Paste copied table from Chartink.")
            scan_type = st.selectbox("Scanner", ["CE1", "CE2", "Positional"])
            chartink_data = st.text_area("Data Dump:", height=150)
            
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
                                
                                set_sv("Date Added", datetime.today().strftime("%Y-%m-%d"))
                                set_sv("Scanner", scan_type)
                                set_sv("Symbol", str(row.get('Symbol', '')))
                                set_sv("Trigger Price", str(row.get('Close', '')))
                                set_sv("Trigger Time", datetime.now().strftime("%I:%M %p"))
                                set_sv("Status", "Monitoring")
                                set_sv("Notes / Analysis", f"Manual Copy | Vol: {row.get('Volume', 'N/A')}")
                                rows_to_add.append(new_row)
                            
                            if rows_to_add:
                                scanner_sheet.append_rows(rows_to_add)
                                st.success(f"Saved {len(rows_to_add)} records.")
                                st.rerun()
                        else:
                            st.error("Invalid format. Missing 'Symbol' column.")
                    except Exception as e:
                        st.error("Parse failed. Ensure TSV format.")

# --- 5. AUTOMATED BACKGROUND DATA SYNC ENGINES ---
def run_background_sync(df_filtered, state_key):
    if state_key in st.session_state and not df_filtered.empty:
        editor_state = st.session_state[state_key]
        
        edited_rows = editor_state.get("edited_rows", {})
        for idx, changes in list(edited_rows.items()):
            if "Journal" in changes and changes["Journal"] is True:
                sym = df_filtered.iloc[idx]['Symbol / Asset']
                st.session_state.viewing_trade = sym
                del changes["Journal"]
                if not changes: del editor_state["edited_rows"][idx]
        
        deleted_indices = editor_state.get("deleted_rows", [])
        if deleted_indices:
            rows_to_delete = df_filtered.iloc[deleted_indices]['_Sheet_Row'].tolist()
            rows_to_delete.sort(reverse=True)
            for r in rows_to_delete: worksheet.delete_rows(r)
            
        if editor_state.get("edited_rows"):
            for idx, changes in editor_state["edited_rows"].items():
                sheet_row = df_filtered.iloc[idx]['_Sheet_Row']
                for col_name, new_val in changes.items():
                    if col_name in sheet_headers:
                        col_idx = sheet_headers.index(col_name) + 1
                        worksheet.update_cell(sheet_row, col_idx, str(new_val))

def run_scanner_sync(df_filtered, state_key):
    if state_key in st.session_state and not df_filtered.empty:
        editor_state = st.session_state[state_key]
        
        deleted_indices = editor_state.get("deleted_rows", [])
        if deleted_indices:
            rows_to_delete = df_filtered.iloc[deleted_indices]['_Sheet_Row'].tolist()
            rows_to_delete.sort(reverse=True)
            for r in rows_to_delete: scanner_sheet.delete_rows(r)
            
        if editor_state.get("edited_rows"):
            for idx, changes in editor_state["edited_rows"].items():
                sheet_row = df_filtered.iloc[idx]['_Sheet_Row']
                for col_name, new_val in changes.items():
                    if col_name in scanner_headers:
                        col_idx = scanner_headers.index(col_name) + 1
                        scanner_sheet.update_cell(sheet_row, col_idx, str(new_val))

# --- 6. PAGE A: OPTIONS TRACKER & JOURNAL ---
if current_page == "Options Tracker":
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
        disabled_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Entry CMP / Range"] 

        if st.session_state.viewing_trade:
            st.button("Back to Terminal", on_click=close_journal)
            st.subheader(f"Trade Review: {st.session_state.viewing_trade}")
            trade_data = initial_df[initial_df['Symbol / Asset'] == st.session_state.viewing_trade].iloc[0]
            sheet_row_id = int(trade_data['_Sheet_Row'])
            
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
            tab1, tab2, tab3 = st.tabs(["Watchlist", "Active Trades", "Closed Executions"])
            
            with tab1:
                df_wl = initial_df[initial_df["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
                if not df_wl.empty:
                    st.data_editor(df_wl[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key="wl_editor",
                        on_change=run_background_sync, kwargs={"df_filtered": df_wl, "state_key": "wl_editor"}, column_config=table_column_config, disabled=disabled_cols)
                else: st.info("No records found.")

            with tab2:
                df_act = initial_df[initial_df["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
                if not df_act.empty:
                    st.data_editor(df_act[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key="act_editor",
                        on_change=run_background_sync, kwargs={"df_filtered": df_act, "state_key": "act_editor"}, column_config=table_column_config, disabled=disabled_cols)
                else: st.info("No records found.")
                    
            with tab3:
                df_cls = initial_df[initial_df["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
                if not df_cls.empty:
                    st.data_editor(df_cls[view_cols], use_container_width=True, hide_index=True, num_rows="fixed", key="cls_editor",
                        on_change=run_background_sync, kwargs={"df_filtered": df_cls, "state_key": "cls_editor"}, column_config=table_column_config, 
                        disabled=disabled_cols + ["Status (Watch/Active/Closed)", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2"])
                else: st.info("No records found.")
    else:
        st.info("Database connection established. No data available.")

# --- 7. PAGE B: CHARTINK SCANNERS ---
elif current_page == "Chartink Scanners":
    st.subheader("Automated Scan Feeds")
    
    scanner_data = scanner_sheet.get_all_records()
    df_scan = pd.DataFrame(scanner_data) if scanner_data else pd.DataFrame()
    
    if not df_scan.empty:
        df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
        
        tab_ce1, tab_ce2, tab_pos = st.tabs(["CE1", "CE2", "Positional"])
        
        scan_view_cols = ["Date Added", "Symbol", "Trigger Price", "Trigger Time", "Status", "Notes / Analysis", "_Sheet_Row"]
        scan_col_config = {
            "_Sheet_Row": None,
            "Status": st.column_config.SelectboxColumn("Status", options=["Monitoring", "Moved to Watchlist", "Discarded"], required=True),
            "Trigger Price": st.column_config.TextColumn("Trigger Price"),
            "Trigger Time": st.column_config.TextColumn("Trigger Time"),
            "Notes / Analysis": st.column_config.TextColumn("Notes / Analysis")
        }
        
        for col in ["Notes / Analysis", "Trigger Price", "Trigger Time"]:
            if col in df_scan.columns:
                df_scan[col] = df_scan[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})

        def render_scanner_tab(tab_obj, filter_name):
            with tab_obj:
                df_filtered = df_scan[df_scan["Scanner"] == filter_name].reset_index(drop=True)
                if not df_filtered.empty:
                    st.data_editor(
                        df_filtered[scan_view_cols],
                        use_container_width=True, hide_index=True, num_rows="dynamic", key=f"scan_{filter_name}",
                        on_change=run_scanner_sync, kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}"},
                        column_config=scan_col_config,
                        disabled=["Date Added", "Symbol", "Trigger Price", "Trigger Time"]
                    )
                else:
                    st.info(f"No active triggers for {filter_name}.")
        
        render_scanner_tab(tab_ce1, "CE1")
        render_scanner_tab(tab_ce2, "CE2")
        render_scanner_tab(tab_pos, "Positional")
    else:
        st.info("System operational. Listening for incoming webhooks...")
