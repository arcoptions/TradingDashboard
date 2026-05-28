import re
import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from dhanhq import dhanhq

st.set_page_config(page_title="Master Trading Journal", layout="wide")
st.title("📈 ARC Trading Dashboard & Journal")

# --- 1. NLP PARSER: EXTRACT DATA FROM RAW TEXT ---
def parse_telegram_tip(text):
    data = {"symbol": "", "trade_type": "Equity", "entry": "", "add_levels": "", "sl": "", "t1": "", "t2": ""}
    if not text:
        return data
        
    option_match = re.search(r'([A-Z\&]+)\s+(\d+)\s+(ce|pe|call|put)', text, re.IGNORECASE)
    if option_match:
        opt_type = option_match.group(3).upper()
        if opt_type == 'CALL': opt_type = 'CE'
        if opt_type == 'PUT': opt_type = 'PE'
        data["symbol"] = f"{option_match.group(1).upper()} {option_match.group(2)} {opt_type}"
        data["trade_type"] = "Option"
    else:
        equity_match = re.search(r'^([A-Z\&]+)\b', text)
        if equity_match:
            data["symbol"] = equity_match.group(1).upper()
            
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
@st.cache_data(ttl=43200)
def get_dhan_scrip_master(version=5): # Bumped version to break old cache
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty:
            return df
        
        # Strictly filter out BSE to prevent API errors
        df = df[df['SEM_EXM_EXCH_ID'] == 'NSE']
        return df
    except Exception as e:
        return pd.DataFrame()

scrip_df = get_dhan_scrip_master(version=5)

# --- 3. AUTHENTICATION VAULT ---
try:
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    worksheet = sh.sheet1
    
    # Restored to Stable Dhan API Initialization
    client_id = st.secrets["dhan"]["client_id"]
    access_token = st.secrets["dhan"]["access_token"]
    dhan = dhanhq(client_id, access_token)
except Exception as e:
    st.error(f"System Connection Failed: {e}")
    st.stop()

# --- 4. LIVE MARKET DATA FUNCTION ---
def get_live_price(exchange, security_id):
    if pd.isna(security_id) or str(security_id).strip() == "":
        return "No ID"
    try:
        sec_id_str = str(int(float(str(security_id).strip())))
        exch_str = str(exchange)
        
        # Restored to Stable get_market_quote method
        quote = dhan.get_market_quote(exch_str, sec_id_str)
        
        if isinstance(quote, dict) and 'data' in quote:
            ltp = quote['data'].get('LTP', 0.0)
            if float(ltp) == 0.0:
                return "Market Closed"
            return float(ltp)
        else:
            return "API Empty"
            
    except Exception as e:
        # Instead of failing silently, display the exact Python error on the dashboard
        err_msg = str(e).replace("\n", " ")
        return f"Err: {err_msg}"[:20]

# --- 5. SIDEBAR: QUICK PASTE & LOGGING ---
st.sidebar.header("📝 Log a New Tip or Trade")

st.sidebar.markdown("### ⚡ Quick Paste Tip")
raw_tip = st.sidebar.text_area("Paste raw Telegram text here:")
parsed_data = parse_telegram_tip(raw_tip)

st.sidebar.markdown("### 🔍 Find Instrument")
search_query = st.sidebar.text_input("Search (e.g., GMRAIRPORT 100 CE)", value=parsed_data["symbol"])

auto_symbol = ""
auto_sec_id = ""
auto_exch = "NSE_EQ"

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
        
        exch = str(row['SEM_EXM_EXCH_ID'])
        seg = str(row['SEM_SEGMENT'])
        if exch == "NSE" and seg == "E": auto_exch = "NSE_EQ"
        elif exch == "NSE" and seg == "D": auto_exch = "NSE_FNO"
    else:
        st.sidebar.warning("No instruments found on NSE. Try tweaking the search.")

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
    exch_
