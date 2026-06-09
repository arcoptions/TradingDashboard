import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import threading
import time
import json
import datetime
from datetime import timezone, timedelta
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

def robust_api_call(func, *args, **kwargs):
    """Wraps individual API requests with an exponential backoff loop to bypass 429 Quota errors."""
    delay = 1.5
    for attempt in range(4):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if ("429" in str(e) or "Quota" in str(e)) and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise e

@st.cache_data(ttl=43200)
def get_dhan_scrip_master():
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        if df.empty: return df
        return df[df['SEM_EXM_EXCH_ID'].isin(['NSE', 'IDX'])]
    except: return pd.DataFrame()

def search_instruments(query):
    scrip_df = get_dhan_scrip_master()
    if not query or scrip_df.empty: return pd.DataFrame()
    cleaned_query = str(query).replace('-', ' ').replace('_', ' ').upper().strip()
    
    # FIX: Prioritize an absolute exact symbol match first to prevent leaky extraction anomalies
    exact_match = scrip_df[scrip_df['SEM_TRADING_SYMBOL'] == cleaned_query]
    if not exact_match.empty:
        return exact_match.head(1)
        
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
    
    # Strict single-token extraction validator
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
    import derivatives_engine as de
    contract_meta = de.parse_option_contract(asset_symbol)
    if not contract_meta: return {}
    
    underlying = contract_meta["underlying"]
    strike = float(contract_meta["strike"])
    opt_type = contract_meta["type"].lower()
    fallback_expiry = contract_meta["expiry_date"]
    
    scrip_df = get_dhan_scrip_master()
    if scrip_df.empty: return {}
    
    underlying_df = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == underlying) & (scrip_df['SEM_SEGMENT'] == 'E')]
    if underlying_df.empty:
        underlying_df = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == underlying) & (scrip_df['SEM_EXM_EXCH_ID'] == 'IDX')]
    if underlying_df.empty: return {}
    
    underlying_id = int(underlying_df.iloc[0]['SEM_SMST_SECURITY_ID'])
    exch = underlying_df.iloc[0]['SEM_EXM_EXCH_ID']
    underlying_seg = "IDX_I" if exch == 'IDX' else "NSE_EQ"
    
    if not daily_token: daily_token = st.secrets["dhan"].get("access_token", "")
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'access-token': daily_token, 'client-id': st.secrets["dhan"]["dhan_client_id"]}

    valid_expiry = fallback_expiry
    try:
        exp_res = requests.post("https://api.dhan.co/v2/optionchain/expirylist", headers=headers, json={"UnderlyingScrip": underlying_id, "UnderlyingSeg": underlying_seg}, timeout=5)
        if exp_res.status_code == 200 and exp_res.json().get("data"):
            exp_list = exp_res.json()["data"]
            parsed_dt = datetime.datetime.strptime(fallback_expiry, "%Y-%m-%d")
            matching_expiries = [e for e in exp_list if datetime.datetime.strptime(e, "%Y-%m-%d").year == parsed_dt.year and datetime.datetime.strptime(e, "%Y-%m-%d").month == parsed_dt.month]
            if matching_expiries: valid_expiry = max(matching_expiries)
    except: pass
    
    try:
        res = requests.post("https://api.dhan.co/v2/optionchain", headers=headers, json={"UnderlyingScrip": underlying_id, "UnderlyingSeg": underlying_seg, "Expiry": valid_expiry}, timeout=10)
        if res.status_code == 200 and res.json().get("data"):
            data_obj = res.json()["data"]
            oc_dict = data_obj.get("oc", {})
            total_call_oi, total_put_oi = 0.0, 0.0
            metrics_map = {"implied_volatility": 0.0, "delta": 0.0, "theta": 0.0, "strike_pcr": 0.0, "overall_pcr": 1.0, "best_ce": "-", "best_pe": "-"}
            ce_pool, pe_pool = [], []
            
            for strike_str, strike_data in oc_dict.items():
                node_strike = float(strike_str)
                ce_node, pe_node = strike_data.get("ce", {}), strike_data.get("pe", {})
                c_oi = float(ce_node.get("oi", 0) if ce_node else 0)
                p_oi = float(pe_node.get("oi", 0) if pe_node else 0)
                total_call_oi += c_oi; total_put_oi += p_oi
                
                if c_oi > 0: ce_pool.append({"strike": node_strike, "oi": c_oi})
                if p_oi > 0: pe_pool.append({"strike": node_strike, "oi": p_oi})
                
                if abs(node_strike - strike) < 0.1:
                    target_node = strike_data.get(opt_type)
                    if target_node:
                        metrics_map.update({
                            "implied_volatility": float(target_node.get("implied_volatility", 0.0)),
                            "delta": float(target_node.get("greeks", {}).get("delta", 0)),
                            "theta": float(target_node.get("greeks", {}).get("theta", 0)),
                            "strike_pcr": round(p_oi / c_oi, 2) if c_oi > 0 else 0.0
                        })
            metrics_map["overall_pcr"] = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0.0
            if ce_pool: metrics_map["best_ce"] = sorted(ce_pool, key=lambda x: x["oi"], reverse=True)[0]["strike"]
            if pe_pool: metrics_map["best_pe"] = sorted(pe_pool, key=lambda x: x["oi"], reverse=True)[0]["strike"]
            return metrics_map
    except: pass
    return {}

def execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers, background_client_id=None):
    """Executes live price sync and heals rows that are missing metadata."""
    try:
        daily_token = robust_api_call(settings_sheet.acell, 'B2').value
        if not daily_token: return "Missing dynamic authorization token"
    except Exception as e: return f"Database connection error: {e}"
    
    scrip_df = get_dhan_scrip_master()
    payload = {"NSE_EQ": [], "NSE_FNO": [], "IDX_I": [13]}
    row_map = []
    sheet1_heal_updates = []
    
    try:
        opt_data = robust_api_call(worksheet.get_all_records)
        if opt_data:
            df_opt = pd.DataFrame(opt_data)
            if not df_opt.empty:
                df_opt['_Sheet_Row'] = range(2, len(df_opt) + 2)
                
                # Filter for active watchlist rows
                active_rows = df_opt[df_opt["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])]
                
                exch_idx = sheet_headers.index("Exchange") + 1
                sec_idx = sheet_headers.index("Security ID") + 1
                type_idx = sheet_headers.index("Trade Type (Eq/Option)") + 1
                
                for _, row in active_rows.iterrows():
                    symbol = str(row.get("Symbol / Asset", "")).strip()
                    exch = str(row.get("Exchange", "")).strip()
                    sec_id = str(row.get("Security ID", "")).strip()
                    
                    # ─── FIX: AUTO-HEAL BLANK ROWS LACKING METADATA ───
                    if not exch or not sec_id or sec_id in ["", "-", "None"]:
                        t_sym, t_sec, t_exch = resolve_instrument(symbol)
                        if t_sec:
                            exch, sec_id = t_exch, t_sec
                            auto_type = "Equity" if "EQ" in t_exch else "Option"
                            sheet1_heal_updates.append({'range': gspread.utils.rowcol_to_a1(row['_Sheet_Row'], exch_idx), 'values': [[t_exch]]})
                            sheet1_heal_updates.append({'range': gspread.utils.rowcol_to_a1(row['_Sheet_Row'], sec_idx), 'values': [[t_sec]]})
                            sheet1_heal_updates.append({'range': gspread.utils.rowcol_to_a1(row['_Sheet_Row'], type_idx), 'values': [[auto_type]]})
                            
                    if exch in payload and str(sec_id).isdigit():
                        payload[exch].append(int(sec_id))
                        row_map.append({"type": "opt", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": str(sec_id)})

        # Process automated scanner sheets safely
        if scanner_sheet:
            scan_data = robust_api_call(scanner_sheet.get_all_records)
            if scan_data:
                df_scan = pd.DataFrame(scan_data)
                if not df_scan.empty:
                    df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
                    for _, row in df_scan[df_scan["Status"].isin(["Monitoring", "Moved to Watchlist"])].iterrows():
                        symbol = str(row.get("Symbol", "")).strip()
                        if symbol:
                            _, sec_id, exch = resolve_instrument(symbol)
                            if exch in payload and str(sec_id).isdigit():
                                payload[exch].append(int(sec_id))
                                row_map.append({"type": "scan", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": str(sec_id)})
    except Exception as e: return f"Staging exception: {e}"

    # Push healing updates back to Google Sheets instantly
    if sheet1_heal_updates:
        try: robust_api_call(worksheet.batch_update, sheet1_heal_updates)
        except: pass

    payload = {k: list(set(v)) for k, v in payload.items() if v}
    if not payload or (len(payload) == 1 and not payload.get("IDX_I")): return "No active sync rows mapped"
        
    client_id_to_use = background_client_id if background_client_id else st.secrets["dhan"]["dhan_client_id"]
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'access-token': daily_token, 'client-id': client_id_to_use}
    
    try: response = requests.post("https://api.dhan.co/v2/marketfeed/quote", headers=headers, json=payload, timeout=15)
    except Exception as e: return f"HTTP Timeout: {e}"
    
    if response.status_code == 200:
        data = response.json().get("data", {})
        opt_updates, scan_updates, settings_updates = [], [], []
        opt_col_idx = sheet_headers.index("Live Price") + 1
        
        scan_col_idx = scanner_headers.index("Live Price") + 1 if scanner_headers and "Live Price" in scanner_headers else None
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
                prev_oi = float(sec_data.get("previous_open_interest") or oi)
                oi_chg = round(((oi - prev_oi) / prev_oi * 100), 2) if prev_oi > 0 else 0.0
                
                if item["type"] == "opt": 
                    opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], opt_col_idx), 'values': [[str(last_price)]]})
                    if price_chg_col_idx and oi_chg_col_idx:
                        opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], price_chg_col_idx), 'values': [[str(price_chg)]]})
                        opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], oi_chg_col_idx), 'values': [[str(oi_chg)]]})
                elif item["type"] == "scan" and scan_col_idx: 
                    scan_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], scan_col_idx), 'values': [[str(last_price)]]})
        try:
            if opt_updates: robust_api_call(worksheet.batch_update, opt_updates)
            if scan_updates and scanner_sheet: robust_api_call(scanner_sheet.batch_update, scan_updates)
            
            # ─── BATCH HEATMAP PAYLOAD ENGINE (Fixes the API spam) ───
            idx_item = data.get("IDX_I", {}).get("13", {})
            lp_n50 = float(idx_item.get("last_price", 0.0))
            if lp_n50 > 0:
                ohlc_close = float(idx_item.get("ohlc", {}).get("close", lp_n50))
                diff_n50 = lp_n50 - ohlc_close
                pct_n50 = (diff_n50 / ohlc_close) * 100 if ohlc_close > 0 else 0.0
                settings_updates.append({'range': 'B10', 'values': [[f"{lp_n50:.2f},{diff_n50:.2f},{pct_n50:.2f}"]]})
                
            # Process remaining sector indices
            heatmap_arr = []
            idx_master = data.get("IDX_I", {})
            for name, info in SECTOR_SYMBOLS.items():
                match_rows = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == info["symbol"]) & (scrip_df['SEM_EXM_EXCH_ID'] == 'IDX')]
                if not match_rows.empty:
                    s_id = str(match_rows.iloc[0]['SEM_SMST_SECURITY_ID'])
                    if s_id in idx_master:
                        node = idx_master[s_id]
                        n_lp = float(node.get("last_price", 0.0))
                        n_pc = float(node.get("ohlc", {}).get("close", n_lp))
                        n_pct = round(((n_lp - n_pc) / n_pc * 100), 2) if n_pc > 0 else 0.0
                        heatmap_arr.append({"sector": name, "change": n_pct, "weight": info["weight"]})
            
            if heatmap_arr: 
                settings_updates.append({'range': 'B12', 'values': [[json.dumps(heatmap_arr)]]})
            
            # Format strictly to Indian Standard Time (UTC+5:30)
            ist_time = (datetime.datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%d-%b %I:%M %p")
            settings_updates.append({'range': 'B9', 'values': [[ist_time]]})
            
            # Push the combined payload to Google once
            if settings_updates:
                robust_api_call(settings_sheet.batch_update, settings_updates)

        except Exception as e: return f"Sheets transmission exception: {e}"
        return "Success"
    return f"API Status Failure Code: {response.status_code}"

def background_sync_loop(gcp_creds_dict, dhan_client_id):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    while True:
        sleep_timer = 60 
        now = datetime.datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        
        # ─── UPDATED: Market hours now safely cover 9:00 AM to 3:30 PM ───
        if now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 30):
            try:
                credentials = Credentials.from_service_account_info(gcp_creds_dict, scopes=scopes)
                gc = gspread.authorize(credentials)
                sh = gc.open("Comprehensive Trading Tracker 2026")
                settings_ws = sh.worksheet("Settings")
                
                # ─── FIXED: Dynamically fetches user's chosen speed from Google Sheets ───
                try:
                    user_speed = robust_api_call(settings_ws.acell, 'B8').value
                    if user_speed and str(user_speed).isdigit():
                        sleep_timer = int(user_speed)
                except:
                    pass
                
                try: scanner_ws = sh.worksheet("Scanners")
                except: scanner_ws = None
                
                try: sheet1_headers = sh.sheet1.row_values(1)
                except: sheet1_headers = []
                
                try: scan_headers = scanner_ws.row_values(1) if scanner_ws else []
                except: scan_headers = []

                res = execute_core_sync(sh.sheet1, scanner_ws, settings_ws, sheet1_headers, scan_headers, background_client_id=dhan_client_id)
                print(f"Background Sync Output: {res}")
            except Exception as loop_err: 
                print(f"Daemon Background Sync Aborted Safely: {loop_err}")
            
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
    with st.spinner("Refreshed price feeds synchronizing from Dhan..."):
        result = execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
        return result
