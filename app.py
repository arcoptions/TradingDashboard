import re
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

st.set_page_config(page_title="ARC Trading Dashboard", layout="wide")
st.title("📈 ARC Trading Dashboard & Journal")

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

# --- 2. AUTO-DOWNLOAD SCRIP MASTER ---
@st.cache_data(ttl=43200)
def get_dhan_scrip_master():
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty: return df
        return df[df['SEM_EXM_EXCH_ID'] == 'NSE']
    except: return pd.DataFrame()

scrip_df = get_dhan_scrip_master()

# --- 3. GOOGLE SHEETS SETUP ---
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

# --- 4. SIDEBAR: LOG NEW TRADES ---
st.sidebar.header("📝 Log a New Tip or Trade")
raw_tip = st.sidebar.text_area("⚡ Quick Paste Tip:")
parsed_data = parse_telegram_tip(raw_tip)

search_query = st.sidebar.text_input("🔍 Find Instrument", value=parsed_data["symbol"])
auto_symbol, auto_sec_id, auto_exch = "", "", "NSE_EQ"

if search_query and not scrip_df.empty:
    search_terms = search_query.upper().split()
    if 'SEARCH_STRING' not in scrip_df.columns:
        scrip_df['SEARCH_STRING'] = scrip_df['SEM_TRADING_SYMBOL'].fillna('') + " " + scrip_df['SEM_CUSTOM_SYMBOL'].fillna('')
    mask = pd.Series([True] * len(scrip_df))
    for term in search_terms:
        mask = mask & scrip_df['SEARCH_STRING'].str.upper().str.contains(term, regex=False)
    results = scrip_df[mask].head(30)
    
    if not results.empty:
        selected_display = st.sidebar.selectbox("Select Exact Contract expiry:", results['SEM_TRADING_SYMBOL'].tolist())
        row = results[results['SEM_TRADING_SYMBOL'] == selected_display].iloc[0]
        auto_symbol = str(row['SEM_TRADING_SYMBOL'])
        auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
        exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
        if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
        elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"

with st.sidebar.form("entry_form"):
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
        st.sidebar.success(f"Successfully logged {symbol}!")
        st.rerun()

# --- 5. MAIN DASHBOARD: INTERACTIVE TRACKER ---
data = worksheet.get_all_records()
df = pd.DataFrame(data) if data else pd.DataFrame()

if not df.empty:
    df['_Sheet_Row'] = range(2, len(df) + 2) 
    
    st.markdown("### Monitor & Update Active Positions")
    st.caption("1. **To Edit:** Double-click Status, Live Price, Exit Price, SL, or Targets. \n2. **To Delete:** Check the row's box on the far left, then click the **Trash Can icon** on the top right. \n3. Click **Save Changes & Deletions** when done.")
    
    df_active = df[df["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])].copy()
    df_active = df_active.reset_index(drop=True) 
    
    view_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Status (Watch/Active/Closed)", "Entry CMP / Range", "Live Price", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2", "_Sheet_Row"]
    
    # FIX: Explicitly enforce string types across all editable columns to unlock them completely
    for col in view_cols:
        if col not in df_active.columns: 
            df_active[col] = ""
        elif col in ["Stop Loss (SL)", "Target 1", "Target 2", "Live Price", "Exit Price"]:
            # Clean up default empty markers ('nan') and force everything to an editable text block
            df_active[col] = df_active[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})

    # Render data editor
    edited_df = st.data_editor(
        df_active[view_cols],
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic", 
        key="trade_editor",
        column_config={
            "_Sheet_Row": None, 
            "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True),
            "Stop Loss (SL)": st.column_config.TextColumn("Stop Loss"),
            "Target 1": st.column_config.TextColumn("Target 1"),
            "Target 2": st.column_config.TextColumn("Target 2"),
            "Live Price": st.column_config.TextColumn("Live Price"),
            "Exit Price": st.column_config.TextColumn("Exit Price"),
        },
        disabled=["Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Entry CMP / Range"] 
    )
    
    if st.button("💾 Save Changes & Deletions", type="primary"):
        editor_state = st.session_state.trade_editor
        updates_made = False
        
        # Process Deletions
        deleted_indices = editor_state.get("deleted_rows", [])
        if deleted_indices:
            rows_to_delete = df_active.iloc[deleted_indices]['_Sheet_Row'].tolist()
            rows_to_delete.sort(reverse=True)
            for r in rows_to_delete:
                worksheet.delete_row(r)
            updates_made = True
                
        # Process Edits
        edited_rows = editor_state.get("edited_rows", {})
        if edited_rows:
            for idx, changes in edited_rows.items():
                sheet_row = df_active.iloc[idx]['_Sheet_Row']
                for col_name, new_val in changes.items():
                    if col_name in sheet_headers:
                        col_idx = sheet_headers.index(col_name) + 1
                        worksheet.update_cell(sheet_row, col_idx, str(new_val))
            updates_made = True
                        
        if updates_made:
            st.success("Database successfully synchronized!")
            st.rerun()
        else:
            st.info("No changes or deletions detected.")

    st.markdown("---")

    # --- 6. DEEP DIVE JOURNAL PORTAL ---
    st.markdown("### 🧠 Deep Dive Journal Portal")
    trade_list = df['Symbol / Asset'].tolist()
    selected_trade = st.selectbox("Select a trade to view its background and performance:", reversed(trade_list))
    
    if selected_trade:
        trade_data = df[df['Symbol / Asset'] == selected_trade].iloc[0]
        
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
                
                if pnl > 0:
                    st.success(f"🏆 Winning Trade! Net Points Captured: +{round(pnl, 2)}")
                else:
                    st.error(f"📉 Losing Trade. Net Points Lost: {round(pnl, 2)}")
            except:
                st.info("💡 Performance will calculate automatically once an Exit Price is recorded.")
            
            st.markdown("#### Trading Psychology")
            st.text_area("Pre-Trade Rationale", trade_data.get('Strategic Rationale (Why I took it)', 'No rationale logged.'), disabled=True)
            st.text_area("Emotional State", trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', 'No emotions logged.'), disabled=True)
else:
    st.info("Your database is currently empty. Use the sidebar to log your first trade!")
