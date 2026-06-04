import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import threading
import time
import json
from datetime import datetime, timezone, timedelta
from streamlit.runtime.scriptrunner import add_script_run_ctx

SECTOR_SYMBOLS = {
    "Financial Services": {"symbol": "NIFTY FIN SERVICE", "weight": 35.0},
    "IT": {"symbol": "NIFTY IT", "weight": 14.5}, 
    "Oil & Gas / Energy": {"symbol": "NIFTY ENERGY", "weight": 12.0},
    "FMCG": {"symbol": "NIFTY FMCG", "weight": 9.0},
    "Auto": {"symbol": "NIFTY AUTO", "weight": 7.0},
    "Pharma": {"symbol": "NIFTY PHARMA", "weight": 5.0},
    "Metal": {"symbol": "NIFTY METAL", "weight": 4.0},
    "Realty": {"symbol": "NIFTY REALTY", "weight": 1.0},
    "Media": {"symbol": "NIFTY MEDIA", "weight": 0.5}
}

@st.cache_data(ttl=43200)
def get_dhan_scrip_master(v=19):
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty: return df
        return df[df['SEM_EXM_EXCH_ID'].isin(['NSE', 'IDX'])]
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

def get_option_chain_metrics(asset_symbol, daily_token=None):
    """
    Directly queries Dhan's v2 Option Chain API to fetch live institutional Greeks and IV.
    """
    import derivatives_engine as de
    contract_meta = de.parse_option_contract(asset_symbol)
    if not contract_meta: return {}
    
    underlying = contract_meta["underlying"]
    strike = float(contract_meta["strike"])
    opt_type = contract_meta["type"].lower() # Dhan API uses lowercase 'ce' or 'pe'
    expiry_date = contract_meta["expiry_date"]
    
    scrip_df = get_dhan_scrip_master()
    if scrip_df.empty: return {}
    
    underlying_df = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == underlying) & (scrip_df['SEM_SEGMENT'] == 'E')]
    if underlying_df.empty:
        underlying_df = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == underlying) & (scrip_df['SEM_EXM_EXCH_ID'] == 'IDX')]
        
    if underlying_df.empty: return {}
    
    underlying_id = int(underlying_df.iloc[0]['SEM_SMST_SECURITY_ID'])
    exch = underlying_df.iloc[0]['SEM_EXM_EXCH_ID']
    underlying_seg = "IDX_I" if exch == 'IDX' else "NSE_EQ"
    
    if not daily_token:
        daily_token = st.secrets["dhan"].get("access_token", "")
        
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'access-token': daily_token,
        'client-id': st.secrets["dhan"]["dhan_client_id"]
    }
    
    # Strictly matching Dhan documentation casing
    payload = {
        "UnderlyingScrip": underlying_id,
        "UnderlyingSeg": underlying_seg,
        "Expiry": expiry_date
    }
    
    try:
        url = "https://api.dhan.co/v2/optionchain"
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200 and res.json().get("data"):
            data_obj = res.json()["data"]
            oc_dict = data_obj.get("oc", {})
            
            for strike_str, strike_data in oc_dict.items():
                node_strike = float(strike_str)
                if abs(node_strike - strike) < 0.1:
                    target_node = strike_data.get(opt_type)
                    if target_node:
                        greeks = target_node.get("greeks", {})
                        return {
                            "implied_volatility": float(target_node.get("impliedVolatility", 0)),
                            "delta": float(greeks.get("delta", 0)),
                            "theta": float(greeks.get("theta", 0))
                        }
    except Exception as e:
        print(f"Dhan Option Chain Fetch Error: {e}")
    return {}

def execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers, background_client_id=None):
    try:
        daily_token = settings_sheet.acell('B2').value
        if not daily_token: return "Missing Dynamic Authorization Token"
    except Exception as e: return f"Database Read Failure: {e}"
    
    scrip_df = get_dhan_scrip_master()
    idx_ids = [13] 
    sector_lookup = {}
    
    if not scrip_df.empty:
        idx_df = scrip_df[scrip_df['SEM_EXM_EXCH_ID'] == 'IDX']
        for sector_name, data in SECTOR_SYMBOLS.items():
            match = idx_df[idx_df['SEM_TRADING_SYMBOL'] == data['symbol']]
            if not match.empty:
                sec_id = int(match.iloc[0]['SEM_SMST_SECURITY_ID'])
                idx_ids.append(sec_id)
                sector_lookup[sec_id] = {"name": sector_name, "weight": data["weight"]}
        
    payload = {"NSE_EQ": [], "NSE_FNO": [], "BSE_EQ": [], "BSE_FNO": [], "IDX_I": idx_ids}
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
    
    url = "https://api.dhan.co/v2/marketfeed/quote"
    try: response = requests.post(url, headers=headers, json=payload, timeout=15)
    except Exception as e: return f"HTTP Connection Timeout: {e}"
    
    if response.status_code == 200:
        data = response.json().get("data", {})
        opt_updates, scan_updates = [], []
        
        opt_col_idx = sheet_headers.index("Live Price") + 1
        scan_col_idx = scanner_headers.index("Live Price") + 1
        
        price_chg_col_idx = sheet_headers.index("Price Chg %") + 1 if "Price Chg %" in sheet_headers else None
        oi_chg_col_idx = sheet_headers.index("OI Chg %") + 1 if "OI Chg %" in sheet_headers else None
        
        for item in row_map:
            exch, sec_id = item["exch"], item["sec_id"]
            if exch in data and sec_id in data[exch]:
                sec_data = data[exch][sec_id]
                last_price = sec_data.get("last_price", "")
                
                lp = float(last_price) if last_price else 0.0
                pc = float(sec_data.get("previous_close") or sec_data.get("ohlc", {}).get("close") or lp)
                price_chg = round(((lp - pc) / pc * 100), 2) if pc > 0 else 0.0
                
                oi = float(sec_data.get("open_interest", 0))
                prev_oi = float(sec_data.get("previous_open_interest") or sec_data.get("previous_oi") or oi)
                oi_chg = round(((oi - prev_oi) / prev_oi * 100), 2) if prev_oi > 0 else 0.0
                
                if item["type"] == "opt": 
                    opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], opt_col_idx), 'values': [[str(last_price)]]})
                    if price_chg_col_idx and oi_chg_col_idx:
                        opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], price_chg_col_idx), 'values': [[str(price_chg)]]})
                        opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], oi_chg_col_idx), 'values': [[str(oi_chg)]]})
                        
                elif item["type"] == "scan": 
                    scan_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], scan_col_idx), 'values': [[str(last_price)]]})
        
        try:
            if opt_updates: worksheet.batch_update(opt_updates)
            if scan_updates: scanner_sheet.batch_update(scan_updates)
            
            try:
                raw_json = settings_sheet.acell('B12').value
                existing_heatmap = json.loads(raw_json) if raw_json and str(raw_json).strip() not in ["", "-"] else []
                old_sector_map = {item["sector"]: float(item["change"]) for item in existing_heatmap}
            except: 
                old_sector_map = {}
            
            hardcoded_eod = {
                "Financial Services": 0.38, "IT": -5.57, "Oil & Gas / Energy": 0.02,
                "FMCG": -1.01, "Auto": 0.05, "Pharma": 0.33,
                "Metal": -0.17, "Realty": -1.39, "Media": -0.50 
            }
            
            if not old_sector_map or all(abs(v) < 0.01 for v in old_sector_map.values()):
                old_sector_map = hardcoded_eod
                
            now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
            is_market_closed = now_ist.hour >= 16 or now_ist.hour < 9 or now_ist.weekday() >= 5
            
            def get_index_metrics(s_id, sector_name=None):
                item = data.get("IDX_I", {}).get(str(s_id), {})
                if not item: item = data.get("NSE_IDX", {}).get(str(s_id), {})
                
                lp = item.get("last_price")
                if not lp: return None, None, None
                
                lp_f = float(lp)
                cp_f = lp_f
                ohlc_c = item.get("ohlc", {}).get("close")
                
                if ohlc_c and float(ohlc_c) > 0 and abs(float(ohlc_c) - lp_f) > 0.01:
                    cp_f = float(ohlc_c)
                    
                diff = lp_f - cp_f
                pct = (diff / cp_f) * 100 if cp_f > 0 else 0.0
                
                if is_market_closed or abs(pct) < 0.01:
                    if sector_name and sector_name in old_sector_map:
                        pct = old_sector_map[sector_name]
                        diff = (pct / 100) * lp_f 
                        
                return lp_f, diff, pct
            
            lp_n50, diff_n50, pct_n50 = get_index_metrics(13)
            if lp_n50 is not None:
                if abs(pct_n50) < 0.01:
                    try:
                        old_n50 = float(settings_sheet.acell('B10').value.split(',')[2])
                        if abs(old_n50) > 0.01: pct_n50 = old_n50; diff_n50 = (pct_n50 / 100) * lp_n50
                    except: pass
                settings_sheet.update_acell('B10', f"{lp_n50:.2f},{diff_n50:.2f},{pct_n50:.2f}")

            heatmap_arr = []
            for sec_id, info in sector_lookup.items():
                lp_sec, diff_sec, pct_sec = get_index_metrics(sec_id, sector_name=info["name"])
                if pct_sec is not None:
                    heatmap_arr.append({
                        "sector": info["name"],
                        "change": round(pct_sec, 2),
                        "weight": info["weight"]
                    })
            
            if heatmap_arr:
                settings_sheet.update_acell('B12', json.dumps(heatmap_arr))

            settings_sheet.update_acell('B9', now_ist.strftime("%d-%b %I:%M %p"))
            
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
def start_cron_daemon_v12(_worksheet, _scanner_sheet, _settings_sheet, _sheet_headers, _scanner_headers):
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
