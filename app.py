import re
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

st.set_page_config(page_title="ARC Trading Dashboard", layout="wide")
st.title("📈 ARC Trading Dashboard & Journal")

# --- INITIALIZE SESSION STATE FOR NAVIGATION ---
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
except Exception as e:
    st.error(f"Google Sheets Connection Failed: {e}")
    st.stop()

# --- 4. SIDEBAR PANEL: DATA ENTRY ---
st.sidebar.header("📝 Data Entry Hub")

with st.sidebar.expander("📥 Bulk Import (Multiple Lines)"):
    bulk_text = st.text_area("Raw Text Block:")
    bulk_source = st.selectbox("Source for all:", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"], key="bulk_src")
    if st.button("🚀 Send to Watchlist", type="primary"):
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
            st.sidebar.success(f"Logged {len(rows_to_insert)} items successfully!")
            st.rerun()

with st.sidebar.expander("✍️ Single Trade (Manual Entry)", expanded=True):
    raw_tip = st.text_area("⚡ Quick Paste Single:")
    parsed_data = parse_telegram_tip(raw_tip)
    search_query = st.text_input("🔍 Find Instrument", value=parsed_data["symbol"])
    auto_symbol, auto_sec_id, auto_exch = "", "", "NSE_EQ"
    results = search_instruments(search_query)
    if not results.empty:
        selected_display = st.selectbox("Select Exact Contract expiry:", results['SEM_TRADING_SYMBOL'].tolist())
        row = results[results['SEM_TRADING_SYMBOL'] == selected_display].iloc[0]
        auto_symbol = str(row['SEM_TRADING_SYMBOL'])
        auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
        exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
        if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
        elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"

    with st.form("entry_form"):
        date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
        source = st.selectbox("Source", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"])
        symbol = st.text_input("Symbol / Asset", value=auto_symbol if auto_symbol else parsed_data["symbol"])
        trade_type = st.selectbox("Trade Type", ["Option", "Equity"], index=0 if parsed_data["trade_type"] == "Option" else 1)
        exchange = st.selectbox("Exchange", ["NSE_EQ", "NSE_FNO"], index=0 if auto_exch == "NSE_EQ" else 1)
        sec_id = st.text_input("Security ID (Number only)", value=auto_sec_id)
        status = st.selectbox("Status", ["Watchlist", "Active", "Closed"])
        entry_range = st.text_input("Entry CMP / Range", value=parsed_data["entry"])
        add_levels = st.text_input("Add-On / Dip Levels", value=parsed_data["add_levels"])
        sl = st.text_input("Stop Loss (SL)", value=parsed_data["sl"])
        t1 = st.text_input("Target 1", value=parsed_data["t1"])
        t2 = st.text_input("Target 2", value=parsed_data["t2"])
        rationale = st.text_area("Why are you taking this trade?")
        emotions = st.text_input("Emotions right now")
        
        if st.form_submit_button("Log Trade"):
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
            st.sidebar.success("Logged successfully!")
            st.rerun()

# --- 5. AUTOMATED BACKGROUND DATA SYNC ENGINE ---
initial_data = worksheet.get_all_records()
initial_df = pd.DataFrame(initial_data) if initial_data else pd.DataFrame()

def run_background_sync(df_filtered, state_key):
    """Intercepts UI clicks to open the journal, and syncs standard edits to Google Sheets."""
    if state_key in st.session_state and not df_filtered.empty:
        editor_state = st.session_state[state_key]
        
        # 1. INTERCEPT JOURNAL 'VIEW' CLICKS
        edited_rows = editor_state.get("edited_rows", {})
        for idx, changes in list(edited_rows.items()):
            if "🔍 View" in changes and changes["🔍 View"] is True:
                # User clicked the journal button. Set state and ignore this "edit"
                sym = df_filtered.iloc[idx]['Symbol / Asset']
                st.session_state.viewing_trade = sym
                del changes["🔍 View"]
                if not changes:
                    del editor_state["edited_rows"][idx]
        
        # 2. PROCESS ROW DELETIONS
        deleted_indices = editor_state.get("deleted_rows", [])
        if deleted_indices:
            rows_to_delete = df_filtered.iloc[deleted_indices]['_Sheet_Row'].tolist()
            rows_to_delete.sort(reverse=True)
            for r in rows_to_delete:
                worksheet.delete_rows(r)
            
        # 3. PROCESS INLINE CELL EDITS
        if editor_state.get("edited_rows"):
            for idx, changes in editor_state["edited_rows"].items():
                sheet_row = df_filtered.iloc[idx]['_Sheet_Row']
                for col_name, new_val in changes.items():
                    if col_name in sheet_headers:
                        col_idx = sheet_headers.index(col_name) + 1
                        worksheet.update_cell(sheet_row, col_idx, str(new_val))

# --- 6. MAIN ENGINE: MASTER-DETAIL VIEW ---
if not initial_df.empty:
    initial_df['_Sheet_Row'] = range(2, len(initial_df) + 2)
    
    # Inject the UI-Only Action Column
    initial_df["🔍 View"] = False
    
    view_cols = ["🔍 View", "Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Status (Watch/Active/Closed)", "Entry CMP / Range", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2", "_Sheet_Row"]
    
    for col in view_cols:
        if col not in initial_df.columns: initial_df[col] = ""
        elif col in ["Stop Loss (SL)", "Target 1", "Target 2", "Live Price", "Exit Price"]:
            initial_df[col] = initial_df[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})

    # Centralized column formatting
    table_column_config = {
        "🔍 View": st.column_config.CheckboxColumn("🔍 View", help="Check box to open Journal", default=False),
        "Idea Source (Chartink/Telegram/X/Self)": st.column_config.TextColumn("Idea Source"), # Cleaned UI Header
        "_Sheet_Row": None, 
        "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True),
        "Stop Loss (SL)": st.column_config.TextColumn("Stop Loss"),
        "Target 1": st.column_config.TextColumn("Target 1"),
        "Target 2": st.column_config.TextColumn("Target 2"),
        "Live Price": st.column_config.TextColumn("Live Price"),
        "Exit Price": st.column_config.TextColumn("Exit Price"),
    }
    disabled_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Entry CMP / Range"] 

    # ==========================================
    # DRILL-DOWN VIEW: JOURNAL DEEP DIVE
    # ==========================================
    if st.session_state.viewing_trade:
        st.button("⬅️ Back to Dashboard", on_click=close_journal, type="secondary")
        st.header(f"🧠 Journal: {st.session_state.viewing_trade}")
        
        trade_data = initial_df[initial_df['Symbol / Asset'] == st.session_state.viewing_trade].iloc[0]
        sheet_row_id = int(trade_data['_Sheet_Row'])
        
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Status", trade_data.get('Status (Watch/Active/Closed)', 'N/A'))
            col2.metric("Entry Range", trade_data.get('Entry CMP / Range', 'N/A'))
            col3.metric("Live Price", trade_data.get('Live Price', '-'))
            col4.metric("Exit Price", trade_data.get('Exit Price', 'Not Exited'))
            
            try:
                entry_val = float(re.findall(r'[\d\.]+', str(trade_data['Entry CMP / Range']))[0])
                exit_val = float(str(trade_data['Exit Price']))
                pnl = exit_val - entry_val
                if pnl > 0: st.success(f"🏆 Winning Trade! Net Points Captured: +{round(pnl, 2)}")
                else: st.error(f"📉 Losing Trade. Net Points Lost: {round(pnl, 2)}")
            except:
                st.info("💡 Performance will calculate automatically once a numerical Exit Price is recorded.")
            
            st.markdown("#### Update Trading Psychology Logs")
            with st.form("psychology_update_form"):
                curr_rationale = str(trade_data.get('Strategic Rationale (Why I took it)', ''))
                curr_emotions = str(trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', ''))
                
                new_rationale = st.text_area("Pre-Trade Rationale & Setups", value=curr_rationale if curr_rationale != 'nan' else '')
                new_emotions = st.text_area("Emotional/Mindset Logs", value=curr_emotions if curr_emotions != 'nan' else '')
                
                if st.form_submit_button("💾 Save Psychology Updates", type="primary"):
                    rat_col = sheet_headers.index("Strategic Rationale (Why I took it)") + 1
                    emo_col = sheet_headers.index("Emotions at Entry (FOMO, Calm, etc.)") + 1
                    
                    worksheet.update_cell(sheet_row_id, rat_col, str(new_rationale))
                    worksheet.update_cell(sheet_row_id, emo_col, str(new_emotions))
                    st.success("Notes synchronized successfully!")
                    st.rerun()

    # ==========================================
    # MASTER VIEW: CENTRAL TABS
    # ==========================================
    else:
        tab1, tab2, tab3 = st.tabs(["📋 Watchlist Ideas", "💼 Active Trades", "🔒 Closed Trades"])
        
        # TAB 1: WATCHLIST
        with tab1:
            st.caption("Check the **🔍 View** box in any row to instantly open its Deep Dive Journal.")
            df_watchlist = initial_df[initial_df["Status (Watch/Active/Closed)"] == "Watchlist"].copy().reset_index(drop=True)
            
            if not df_watchlist.empty:
                st.data_editor(
                    df_watchlist[view_cols],
                    use_container_width=True, hide_index=True, num_rows="dynamic", key="wl_editor",
                    on_change=run_background_sync, kwargs={"df_filtered": df_watchlist, "state_key": "wl_editor"},
                    column_config=table_column_config,
                    disabled=disabled_cols
                )
            else:
                st.info("Watchlist is currently empty.")

        # TAB 2: ACTIVE TRADES
        with tab2:
            st.caption("Check the **🔍 View** box in any row to instantly open its Deep Dive Journal.")
            df_active = initial_df[initial_df["Status (Watch/Active/Closed)"] == "Active"].copy().reset_index(drop=True)
            
            if not df_active.empty:
                st.data_editor(
                    df_active[view_cols],
                    use_container_width=True, hide_index=True, num_rows="dynamic", key="act_editor",
                    on_change=run_background_sync, kwargs={"df_filtered": df_active, "state_key": "act_editor"},
                    column_config=table_column_config,
                    disabled=disabled_cols
                )
            else:
                st.info("No active trades tracking right now.")
                
        # TAB 3: CLOSED TRADES
        with tab3:
            st.caption("Check the **🔍 View** box in any row to instantly review your historical executions.")
            df_closed = initial_df[initial_df["Status (Watch/Active/Closed)"] == "Closed"].copy().reset_index(drop=True)
            
            if not df_closed.empty:
                st.data_editor(
                    df_closed[view_cols],
                    use_container_width=True, hide_index=True, num_rows="fixed", key="cls_editor",
                    on_change=run_background_sync, kwargs={"df_filtered": df_closed, "state_key": "cls_editor"},
                    column_config=table_column_config,
                    # Lock everything in closed trades except the View Journal checkbox
                    disabled=disabled_cols + ["Status (Watch/Active/Closed)", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2"]
                )
            else:
                st.info("No closed trades logged yet.")
                
else:
    st.info("Database is currently empty. Initialize trades from the manual panel.")
