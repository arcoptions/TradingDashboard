import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import threading
import time
from datetime import datetime, timezone, timedelta
from streamlit.runtime.scriptrunner import add_script_run_ctx

@st.cache_data(ttl=43200)
def get_dhan_scrip_master(v=12):
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty: return df
        return df[df['SEM_EXM_EXCH_ID'] == 'NSE']
    except: return pd.DataFrame()

def search_instruments(query):
    scrip_df = get_dhan_scrip_master()
    if not query or scrip_df.empty: return pd.DataFrame()
    cleaned_query = str(query).replace('-', ' ').replace('_', ' ').upper()
    terms = cleaned_query.split()
    if 'SEARCH_STRING' not in scrip_df.columns:
        normalized_trading_sym = scrip_df['SEM_TRADING_SYMBOL'].fillna('').str.replace('-', ' ', regex=False).str.replace('_', ' ', regex=False)
        normalized_custom_sym = scrip_df['SEM_CUSTOM_SYMBOL'].fillna('').str.replace('-', ' ', regex=False).str.replace('_', ' ', regex=False)
        scrip_df['SEARCH_STRING'] = normalized_trading_sym.str.upper() + " " + normalized_custom_sym.str.upper()
    mask = pd.Series([True] * len(scrip_df))
    for term in terms: mask = mask & scrip_df['SEARCH_STRING'].str.contains(term, regex=False)
    results = scrip_df[mask].copy()
    if not results.empty and 'SEM_EXPIRY_DATE' in results.columns:
        results['Parsed_Expiry'] = pd.to_datetime(results['SEM_EXPIRY_DATE'], errors='coerce')
        results = results.sort_values(by=['Parsed_Expiry', 'SEM_TRADING_SYMBOL'], ascending=[True, True])
    return results.head(200)

def resolve_instrument(parsed_sym):
    scrip_df = get_dhan_scrip_master()
    parsed_sym = str(parsed_sym).strip().upper()
    if not parsed_sym or scrip_df.empty: return parsed_sym, "", "NSE_EQ"
    if len(parsed_sym.split()) == 1:
        eq_match = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == parsed_sym) & (scrip_df['SEM_SEGMENT'] == 'E')]
        if not eq_match.empty:
            return str(eq_match.iloc[0]['SEM_TRADING_SYMBOL']), str(eq_match.iloc[0]['SEM_SMST_SECURITY_ID']), "NSE_EQ"
    results = search_instruments(parsed_sym)
    if not results.empty:
        row = results.iloc[0]
        exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
        ret_exch = "NSE_EQ" if exch == "NSE" and seg == "E" else "NSE_FNO"
        return str(row['SEM_TRADING_SYMBOL']), str(row['SEM_SMST_SECURITY_ID']), ret_exch
    return parsed_sym, "", "NSE_EQ"

def execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers, background_client_id=None):
    try:
        daily_token = settings_sheet.acell('B2').value
        if not daily_token: return "Missing Dynamic Authorization Token"
    except Exception as e: return f"Database Read Failure: {e}"
        
    payload = {"NSE_EQ": [], "NSE_FNO": [], "BSE_EQ": [], "BSE_FNO": [], "IDX_I": [13]}
    row_map = [] 
    
    try:
        opt_data = worksheet.get_all_records()
        if opt_data:
            df_opt = pd.DataFrame(opt_data)
            if not df_opt.empty and "Status (Watch/Active/Closed)" in df_opt.columns:
                df_opt['_Sheet_Row'] = range(2, len(df_opt) + 2)
                for idx, row in df_opt[df_opt["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])].iterrows():
                    exch, sec_id = str(row.get("Exchange", "")).strip(), str(row.get("Security ID", "")).strip()
                    if exch in payload and sec_id.isdigit():
                        payload[exch].append(int(sec_id))
                        row_map.append({"type": "opt", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": sec_id})

        scan_data = scanner_sheet.get_all_records()
        if scan_data:
            df_scan = pd.DataFrame(scan_data)
            if not df_scan.empty and "Status" in df_scan.columns:
                df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
                for idx, row in df_scan[df_scan["Status"].isin(["Monitoring", "Moved to Watchlist"])].iterrows():
                    symbol = str(row.get("Symbol", "")).strip()
                    if symbol:
                        t_sym, sec_id, exch = resolve_instrument(symbol)
                        if exch in payload and sec_id.isdigit():
                            payload[exch].append(int(sec_id))
                            row_map.append({"type": "scan", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": sec_id})
    except Exception as e: return f"DataFrame Parse Failure: {e}"

    payload = {k: list(set(v)) for k, v in payload.items() if v}
    if not payload: return "No targets mapped"
        
    client_id_to_use = background_client_id if background_client_id else st.secrets["dhan"]["dhan_client_id"]
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'access-token': daily_token, 'client-id': client_id_to_use}
    
    url = "https://api.dhan.co/v2/marketfeed/ohlc"
    try: response = requests.post(url, headers=headers, json=payload, timeout=15)
    except Exception as e: return f"HTTP Connection Timeout: {e}"
    
    if response.status_code == 200:
        data = response.json().get("data", {})
        opt_updates, scan_updates = [], []
        opt_col_idx, scan_col_idx = sheet_headers.index("Live Price") + 1, scanner_headers.index("Live Price") + 1
        
        for item in row_map:
            exch, sec_id = item["exch"], item["sec_id"]
            if exch in data and sec_id in data[exch]:
                last_price = data[exch][sec_id].get("last_price", "")
                if item["type"] == "opt": opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], opt_col_idx), 'values': [[str(last_price)]]})
                elif item["type"] == "scan": scan_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], scan_col_idx), 'values': [[str(last_price)]]})
        
        try:
            if opt_updates: worksheet.batch_update(opt_updates)
            if scan_updates: scanner_sheet.batch_update(scan_updates)
            
            def get_nifty_data():
                item = data.get("IDX_I", {}).get("13", {})
                lp = item.get("last_price")
                cp = item.get("ohlc", {}).get("close") 
                
                if lp and cp and float(cp) > 0:
                    lp_f = float(lp)
                    cp_f = float(cp)
                    diff = lp_f - cp_f
                    pct = (diff / cp_f) * 100
                    return f"{lp_f:.2f},{diff:.2f},{pct:.2f}"
                elif lp:
                    return f"{float(lp):.2f},0.00,0.00"
                return "-"

            # Safe bound writes
            settings_sheet.update_acell('B10', get_nifty_data())
            ist_now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
            settings_sheet.update_acell('B9', ist_now.strftime("%d-%b %I:%M %p"))
            
        except Exception as e: return f"Spreadsheet Write Failure: {e}"
        return "Success"
    return f"API Error: {response.status_code}"

def background_sync_loop(gcp_creds_dict, dhan_client_id):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    while True:
        sleep_timer = 60 
        now = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        
        if now.weekday() < 5:
            start_market = now.replace(hour=9, minute=15, second=0, microsecond=0)
            end_market = now.replace(hour=15, minute=30, second=0, microsecond=0)
            
            if start_market <= now <= end_market:
                try:
                    credentials = Credentials.from_service_account_info(gcp_creds_dict, scopes=scopes)
                    gc = gspread.authorize(credentials)
                    sh = gc.open("Comprehensive Trading Tracker 2026")
                    bg_worksheet, bg_scanner_sheet, bg_settings_sheet = sh.sheet1, sh.worksheet("Scanners"), sh.worksheet("Settings")
                    
                    try: sleep_timer = int(bg_settings_sheet.acell('B8').value)
                    except: pass
                    
                    execute_core_sync(bg_worksheet, bg_scanner_sheet, bg_settings_sheet, bg_worksheet.row_values(1), bg_scanner_sheet.row_values(1), background_client_id=dhan_client_id)
                except Exception: pass 
                
        time.sleep(sleep_timer)

@st.cache_resource
def start_cron_daemon_v8(_worksheet, _scanner_sheet, _settings_sheet, _sheet_headers, _scanner_headers):
    gcp_creds = dict(st.secrets["gcp_service_account"])
    dhan_id = st.secrets["dhan"]["dhan_client_id"]
    cron_worker = threading.Thread(target=background_sync_loop, args=(gcp_creds, dhan_id), daemon=True)
    add_script_run_ctx(cron_worker)
    cron_worker.start()
    return True

def fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    with st.spinner("Fetching live market data from Dhan..."):
        result = execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
        if result == "Success":
            st.success("Successfully updated live prices!")
            st.rerun()
        else: st.error(f"Sync Issue: {result}")
