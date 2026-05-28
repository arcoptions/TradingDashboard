import re
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from dhanhq import dhanhq, DhanContext

st.set_page_config(page_title="Master Trading Journal", layout="wide")
st.title("📈 Master Trading Dashboard & Journal")

# --- 1. NLP PARSER: EXTRACT DATA FROM RAW TEXT ---
def parse_telegram_tip(text):
    data = {"symbol": "", "trade_type": "Equity", "entry": "", "add_levels": "", "sl": "", "t1": "", "t2": ""}
    if not text:
        return data
        
    option_match = re.search(r'([A-Z\&]+)\s+(\d+)\s+(ce|pe|CE|PE)', text)
    if option_match:
        data["symbol"] = f"{option_match.group(1)} {option_match.group(2)} {option_match.group(3).upper()}"
        data["trade_type"] = "Option"
    else:
        equity_match = re.search(r'^([A-Z\&]+)\b', text)
        if equity_match:
            data["symbol"] = equity_match.group(1)
            
    range_match = re.search(r'range\s+([\d\.-]+)', text, re.IGNORECASE)
    if range_match:
        data["entry"] = range_match.group(1)
    else:
        cmp_match = re.search(r'cmp\s+([\d\.]+)', text, re.IGNORECASE)
        if cmp_match:
            data["entry"] = cmp_match.group(1)
            
    add_match = re.search(r'add more\s*(?:levels?)?[-\s]*([\d\.\s-]+?)(?:\s+if comes|\.|\s+SL)', text, re.IGNORECASE)
    if add_match:
        data["add_levels"] = add_match.group(1).strip('- ')
        
    sl_match = re.search(r'SL\s+([\d\.]+\s*(?:clsb)?)', text, re.IGNORECASE)
    if sl_match:
        data["sl"] = sl_match.group(1)
        
    target_match = re.search(r'Target\s+([\d\.\s-]+)', text, re.IGNORECASE)
    if target_match:
        targets = re.findall(r'([\d\.]+)', target_match.group(1))
        if len(targets) > 0:
            data["t1"] = targets[0]
        if len(targets) > 1:
            data["t2"] = targets[1]
            
    return data

# --- 2. AUTO-DOWNLOAD SCRIP MASTER ---
# Adding version=2 breaks the old broken cache and forces a fresh download
@st.cache_data(ttl=43200)
def get_dhan_scrip_master(version=2):
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty:
            st.error("Dhan CSV downloaded empty. Retrying...")
        return df
    except Exception as e:
        st.error(f"Failed to download instrument list: {e}")
        return pd.DataFrame()

scrip_df = get_dhan_scrip_master(version=2)

# --- 3. AUTHENTICATION VAULT ---
try:
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    worksheet = sh.sheet1
    
    client_id = st.secrets["dhan"]["client_id"]
    access_token = st.secrets["dhan"]["access_token"]
    dhan_context = DhanContext(client_id, access_token)
    dhan = dhanhq(dhan_context)
except Exception as e:
    st.error(f"System Connection Failed: {e}")
    st.stop()

# --- 4. LIVE MARKET DATA FUNCTION ---
def get_live_price(exchange, security_id):
    if not security_id or str(security_id).strip() == "":
        return "No ID"
    try:
        req_dict = {str(exchange): [int(float(str(security_id).strip()))]}
        quote = dhan.ticker_data(securities=req_dict)
        ltp = quote.get('data', {}).get(str(exchange), {}).get(str(security_id).strip(), {}).get('last_price', "API Error")
        return ltp if ltp != "API Error" else "Check ID"
    except Exception as e:
        return "Error"

# --- 5. SIDEBAR: QUICK PASTE & LOGGING ---
st.sidebar.header("📝 Log a New Tip or Trade")

st.sidebar.markdown("### ⚡ Quick Paste Tip")
raw_tip = st.sidebar.text_area("Paste raw Telegram text here:")
parsed_data = parse_telegram_tip(raw_tip)

st.sidebar.markdown("### 🔍 Find Instrument")
search_query = st.sidebar.text_input("Search (e.g., GMRINFRA 100 CE)", value=parsed_data["symbol"])

auto_symbol = ""
auto_sec_id = ""
auto_exch = "NSE_EQ"

if search_query and not scrip_df.empty:
    search_terms = search_query.upper().split()
    mask = pd.Series([True] * len(scrip_df))
    for term in search_terms:
        mask = mask & scrip_df['SEM_CUSTOM_SYMBOL'].fillna('').str.upper().str.contains(term, regex=False)
    
    results = scrip_df[mask].head(30)
    
    if not results.empty:
        selected_display = st.sidebar.selectbox("Select Exact Contract expiry:", results['SEM_CUSTOM_SYMBOL'].tolist())
        row = results[results['SEM_CUSTOM_SYMBOL'] == selected_display].iloc[0]
        auto_symbol = str(row['SEM_CUSTOM_SYMBOL'])
        auto_sec_id = str(row['SEM_SMST_SECURITY_ID'])
        
        exch = str(row['SEM_EXM_EXCH_ID'])
        seg = str(row['SEM_SEGMENT'])
        if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
        elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"
        elif exch == "BSE" and seg == "E": auto_exch = "BSE_EQ"
        elif exch == "BSE" and seg == "D": auto_exch = "BSE_FNO"
    else:
        st.sidebar.warning("No instruments found. Try tweaking the search.")

with st.sidebar.form("entry_form"):
    date = st.date_input("Date", datetime.today()).strftime("%Y-%m-%d")
    source = st.selectbox("Source", ["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chartink", "Self/X"])
    
    st.markdown("### Trade Details")
    symbol = st.text_input("Symbol / Asset", value=auto_symbol if auto_symbol else parsed_data["symbol"])
    
    trade_options = ["Option", "Equity"]
    try:
        tt_idx = trade_options.index(parsed_data["trade_type"])
    except:
        tt_idx = 0
    trade_type = st.selectbox("Trade Type", trade_options, index=tt_idx)
    
    st.markdown("### Backend API Details")
    exch_options = ["NSE_EQ", "NSE_FNO", "BSE_EQ", "BSE_FNO"]
    try:
        default_exch_index = exch_options.index(auto_exch)
    except:
        default_exch_index = 0
        
    exchange = st.selectbox("Exchange", exch_options, index=default_exch_index)
    sec_id = st.text_input("Security ID (Number only)", value=auto_sec_id)
    
    status = st.selectbox("Status", ["Watchlist", "Active", "Closed"])
    
    st.markdown("### Execution Plan")
    entry_range = st.text_input("Entry CMP / Range", value=parsed_data["entry"])
    add_levels = st.text_input("Add-On / Dip Levels", value=parsed_data["add_levels"])
    sl = st.text_input("Stop Loss (SL)", value=parsed_data["sl"])
    t1 = st.text_input("Target 1", value=parsed_data["t1"])
    t2 = st.text_input("Target 2", value=parsed_data["t2"])
    
    st.markdown("### 🧠 Psychological State")
    rationale = st.text_area("Why are you taking this trade?")
    emotions = st.text_input("Emotions right now")
    
    submitted = st.form_submit_button("Log Trade")
    if submitted:
        new_row = [
            date, source, symbol, trade_type, exchange, sec_id, status, 
            entry_range, add_levels, sl, t1, t2, "", "", "", rationale, emotions, ""
        ]
        worksheet.append_row(new_row)
        st.sidebar.success(f"Successfully logged {symbol}!")
        st.rerun()

# --- 6. MAIN DASHBOARD: ACTIVE TRADES ---
st.header("Active Watchlist & Trades")

data = worksheet.get_all_records()
if data:
    df = pd.DataFrame(data)
    
    if 'Status (Watch/Active/Closed)' in df.columns:
        df_active = df[df["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])].copy()
        
        if not df_active.empty:
            df_active["Live Price (CMP)"] = df_active.apply(
                lambda row: get_live_price(row.get("Exchange", "NSE_EQ"), row.get("Security ID", "")), axis=1
            )
            
            view_cols = [
                "Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", 
                "Status (Watch/Active/Closed)", "Entry CMP / Range", 
                "Live Price (CMP)", "Stop Loss (SL)", "Target 1", "Target 2"
            ]
            st.dataframe(df_active[view_cols], use_container_width=True)
        else:
            st.info("No active trades. Take a breather!")
