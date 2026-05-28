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

# --- 3. AUTHENTICATION VAULT ---
try:
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    worksheet = sh.sheet1
    sheet_headers = worksheet.row_values(1) # Used to find exact columns later
except Exception as e:
    st.error(f"Google Sheets Connection Failed: {e}")
    st.stop()

# --- 4. SIDEBAR: QUICK PASTE & LOGGING ---
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
        new_row = [date, source, symbol, trade_type, exchange, sec_id, status, entry_range, add_levels, sl, t1, t2, "", "", "", rationale, emotions, ""]
        worksheet.append_row(new_row)
        st.sidebar.success(f"Successfully logged {symbol}!")
        st.rerun()

# --- 5. MAIN DASHBOARD: TABS ---
data = worksheet.get_all_records()
df = pd.DataFrame(data) if data else pd.DataFrame()

if not df.empty:
    # Append the actual Google Sheets row number for precise targeting later
    df['_Sheet_Row'] = range(2, len(df) + 2) 
    
    tab1, tab2, tab3 = st.tabs(["📊 Active Tracker", "🧠 Deep Dive & Journal", "⚙️ Manage Data"])
    
    # === TAB 1: ACTIVE TRACKER (INLINE EDITING) ===
    with tab1:
        st.markdown("### Monitor & Update Active Positions")
        st.caption("Double-click cells in the table to edit Targets, SL, Exit Prices, or change Status. Click Save to push to Database.")
        
        # Filter for active dashboard
        if 'Status (Watch/Active/Closed)' in df.columns:
            df_active = df[df["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])].copy()
            
            if "Exit Price" not in df_active.columns: df_active["Exit Price"] = ""
                
            view_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Status (Watch/Active/Closed)", "Entry CMP / Range", "Exit Price", "Stop Loss (SL)", "Target 1", "Target 2", "_Sheet_Row"]
            
            # Form required to batch edits and save API calls
            with st.form("edit_table_form"):
                edited_df = st.data_editor(
                    df_active[view_cols],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "_Sheet_Row": None, # Hidden from user
                        "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True),
                    },
                    disabled=["Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", "Entry CMP / Range"] # Locked columns
                )
                
                if st.form_submit_button("💾 Save Changes to Database", type="primary"):
                    updates_made = 0
                    for idx, updated_row in edited_df.iterrows():
                        orig_row = df_active.loc[idx]
                        editable_cols = ["Status (Watch/Active/Closed)", "Stop Loss (SL)", "Target 1", "Target 2", "Exit Price"]
                        
                        for col in editable_cols:
                            # If the user changed the value in the UI
                            if str(updated_row[col]) != str(orig_row[col]):
                                col_idx = sheet_headers.index(col) + 1
                                worksheet.update_cell(updated_row['_Sheet_Row'], col_idx, updated_row[col])
                                updates_made += 1
                                
                    if updates_made > 0:
                        st.success(f"Successfully pushed {updates_made} updates to Google Sheets!")
                        st.rerun()
                    else:
                        st.info("No changes detected.")

    # === TAB 2: DEEP DIVE & JOURNAL ===
    with tab2:
        st.markdown("### Post-Trade Analysis")
        trade_list = df['Symbol / Asset'].tolist()
        selected_trade = st.selectbox("Select a trade to review:", reversed(trade_list)) # Reversed shows newest first
        
        if selected_trade:
            # Extract row data
            trade_data = df[df['Symbol / Asset'] == selected_trade].iloc[0]
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Status", trade_data.get('Status (Watch/Active/Closed)', 'N/A'))
            col2.metric("Entry Range", trade_data.get('Entry CMP / Range', 'N/A'))
            col3.metric("Exit Price", trade_data.get('Exit Price', 'Not Exited'))
            
            st.markdown("#### Performance Calculation")
            try:
                # Basic regex to pull the first number from the entry string (e.g. "160 - 170" becomes 160)
                entry_val = float(re.findall(r'[\d\.]+', str(trade_data['Entry CMP / Range']))[0])
                exit_val = float(str(trade_data['Exit Price']))
                pnl = exit_val - entry_val
                
                if pnl > 0:
                    st.success(f"🏆 Winning Trade! Net Points: +{round(pnl, 2)}")
                else:
                    st.error(f"📉 Losing Trade. Net Points: {round(pnl, 2)}")
            except:
                st.info("Performance will calculate automatically once an Exit Price is recorded.")
            
            st.markdown("---")
            st.markdown("#### Journal Logs")
            st.text_area("Pre-Trade Rationale", trade_data.get('Strategic Rationale (Why I took it)', 'No rationale logged.'), disabled=True)
            st.text_area("Emotional State", trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', 'No emotions logged.'), disabled=True)

    # === TAB 3: MANAGE DATA ===
    with tab3:
        st.markdown("### 🗑️ Delete Trades")
        st.caption("Select a trade below to permanently remove it from your Google Sheet.")
        
        delete_options = [(row['_Sheet_Row'], f"{row['Trade Date']} | {row['Symbol / Asset']} ({row['Status (Watch/Active/Closed)']})") for _, row in df.iterrows()]
        
        if delete_options:
            selected_del = st.selectbox("Select Trade to Delete", delete_options, format_func=lambda x: x[1])
            if st.button("Delete Trade", type="primary"):
                worksheet.delete_row(selected_del[0])
                st.success("Trade deleted successfully!")
                st.rerun()
else:
    st.info("Your database is currently empty. Use the sidebar to log your first trade!")
