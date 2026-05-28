import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from dhanhq import dhanhq, DhanContext # <-- Added DhanContext here

st.set_page_config(page_title="Master Trading Journal", layout="wide")
st.title("📈 Master Trading Dashboard & Journal")

# --- AUTHENTICATION VAULT ---
try:
    # Google Sheets Connection
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    worksheet = sh.sheet1
    
    # Dhan API Connection (Updated Syntax)
    client_id = st.secrets["dhan"]["client_id"]
    access_token = st.secrets["dhan"]["access_token"]
    dhan_context = DhanContext(client_id, access_token) # <-- Wrapped in DhanContext
    dhan = dhanhq(dhan_context)
except Exception as e:
    st.error(f"System Connection Failed: {e}")
    st.stop()

# --- LIVE MARKET DATA FUNCTION ---
def get_live_price(exchange, security_id):
    if not security_id or str(security_id).strip() == "":
        return 0.0
    try:
        # DhanHQ v2 requires a dictionary format for the request
        req_dict = {str(exchange): [int(str(security_id).strip())]}
        quote = dhan.ticker_data(req_dict)
        
        # Parse the JSON response
        ltp = quote.get('data', {}).get(str(exchange), {}).get(str(security_id).strip(), {}).get('last_price', 0.0)
        return float(ltp)
    except Exception as e:
        return 0.0

# --- SIDEBAR: LOG A NEW TRADE ---
st.sidebar.header("📝 Log a New Tip or Trade")
with st.sidebar.form("entry_form"):
    date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
    source = st.selectbox("Source", ["Chartink", "Elephant Pro", "Mr Chartist", "IndianTraderXP", "Self/X"])
    symbol = st.text_input("Symbol / Asset (e.g., SRF 2600 CE)")
    trade_type = st.selectbox("Trade Type", ["Equity", "Option"])
    
    st.markdown("### Backend API Details")
    st.caption("Enter the Dhan Security ID to track live prices.")
    exchange = st.selectbox("Exchange", ["NSE_EQ", "NSE_FNO", "BSE_EQ", "BSE_FNO"])
    sec_id = st.text_input("Security ID (Number only)")
    
    status = st.selectbox("Status", ["Watchlist", "Active", "Closed"])
    
    st.markdown("### Execution Plan")
    entry_range = st.text_input("Entry CMP / Range")
    add_levels = st.text_input("Add-On / Dip Levels")
    sl = st.text_input("Stop Loss (SL)")
    t1 = st.text_input("Target 1")
    t2 = st.text_input("Target 2")
    
    st.markdown("### 🧠 Psychological State")
    rationale = st.text_area("Why are you taking this trade?")
    emotions = st.text_input("Emotions right now")
    
    submitted = st.form_submit_button("Log Trade")
    if submitted:
        # Pushes exactly 18 columns of data to your Google Sheet
        new_row = [
            date, source, symbol, trade_type, exchange, sec_id, status, 
            entry_range, add_levels, sl, t1, t2, "", "", "", rationale, emotions, ""
        ]
        worksheet.append_row(new_row)
        st.sidebar.success(f"Successfully logged {symbol}!")
        st.rerun()

# --- MAIN DASHBOARD: ACTIVE TRADES ---
st.header("Active Watchlist & Trades")

# Pull data from Google Sheets
data = worksheet.get_all_records()
if data:
    df = pd.DataFrame(data)
    
    # Filter only for Active/Watchlist
    if 'Status (Watch/Active/Closed)' in df.columns:
        df_active = df[df["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])].copy()
        
        if not df_active.empty:
            # Fetch live prices dynamically
            df_active["Live Price (CMP)"] = df_active.apply(
                lambda row: get_live_price(row.get("Exchange", "NSE_EQ"), row.get("Security ID", "")), axis=1
            )
            
            # Select specific columns to display cleanly on the website
            view_cols = [
                "Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", 
                "Status (Watch/Active/Closed)", "Entry CMP / Range", 
                "Live Price (CMP)", "Stop Loss (SL)", "Target 1"
            ]
            st.dataframe(df_active[view_cols], use_container_width=True)
        else:
            st.info("No active trades. Take a breather!")
