import re
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

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

def search_instruments(query):
    scrip_df = get_dhan_scrip_master()
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
        results = results.sort_values(by=['Parsed_Expiry', 'SEM_TRADING_SYMBOL'], ascending=[True, True])
        
    return results.head(200)

def resolve_instrument(parsed_sym):
    scrip_df = get_dhan_scrip_master()
    parsed_sym = str(parsed_sym).strip().upper()
    if not parsed_sym or scrip_df.empty:
        return parsed_sym, "", "NSE_EQ"
        
    if len(parsed_sym.split()) == 1:
        eq_match = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == parsed_sym) & (scrip_df['SEM_SEGMENT'] == 'E')]
        if not eq_match.empty:
            row = eq_match.iloc[0]
            return str(row['SEM_TRADING_SYMBOL']), str(row['SEM_SMST_SECURITY_ID']), "NSE_EQ"

    results = search_instruments(parsed_sym)
    if not results.empty:
        row = results.iloc[0]
        sym = str(row['SEM_TRADING_SYMBOL'])
        sec = str(row['SEM_SMST_SECURITY_ID'])
        exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
        if exch == "NSE" and seg == "E": return sym, sec, "NSE_EQ"
        elif exch == "NSE" and seg == "D": return sym, sec, "NSE_FNO"
        
    return parsed_sym, "", "NSE_EQ"

# --- 3. DATABASE INITIALIZATION ---
@st.cache_resource
def init_db():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    
    worksheet = sh.sheet1
    sheet_headers = worksheet.row_values(1)
    for col in ["Live Price", "Exit Price"]:
        if col not in sheet_headers:
            worksheet.update_cell(1, len(sheet_headers) + 1, col)
            sheet_headers.append(col)
            
    worksheet_list = [ws.title for ws in sh.worksheets()]
    if "Scanners" in worksheet_list:
        scanner_sheet = sh.worksheet("Scanners")
    else:
        scanner_sheet = sh.add_worksheet(title="Scanners", rows="1000", cols="10")
        scanner_sheet.append_row(["Date Added", "Scanner", "Symbol", "Trigger Price", "Trigger Time", "Status", "Notes / Analysis", "Live Price"])
        
    scanner_headers = scanner_sheet.row_values(1)
    if "Live Price" not in scanner_headers:
        scanner_sheet.update_cell(1, len(scanner_headers) + 1, "Live Price")
        scanner_headers.append("Live Price")
        
    if "Settings" in worksheet_list:
        settings_sheet = sh.worksheet("Settings")
    else:
        settings_sheet = sh.add_worksheet(title="Settings", rows="10", cols="2")
        settings_sheet.update([["Key", "Value"], ["Dhan Access Token", ""]], "A1:B2")
        
    return worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers

# --- 4. DUAL-ENGINE LIVE DATA SYNC ---
def fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    if "dhan" not in st.secrets:
        st.error("Missing API Keys: Check your secrets configuration.")
        return
        
    try:
        daily_token = settings_sheet.acell('B2').value
        if not daily_token:
            st.error("No token found for today! Please paste your new Dhan token in the '⚙️ Daily Setup' sidebar.")
            return
    except Exception as e:
        st.error(f"Could not read token from settings: {e}")
        return
        
    payload = {"NSE_EQ": [], "NSE_FNO": [], "BSE_EQ": [], "BSE_FNO": []}
    row_map = [] 
    skipped_assets = [] 
    
    opt_data = worksheet.get_all_records()
    if opt_data:
        df_opt = pd.DataFrame(opt_data)
        df_opt['_Sheet_Row'] = range(2, len(df_opt) + 2)
        active_opt = df_opt[df_opt["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])]
        
        for idx, row in active_opt.iterrows():
            exch = str(row.get("Exchange", "")).strip()
            sec_id = str(row.get("Security ID", "")).strip()
            if exch in payload and sec_id.isdigit():
                payload[exch].append(int(sec_id))
                row_map.append({"type": "opt", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": sec_id})
            else:
                skipped_assets.append(row.get("Symbol / Asset", "Unknown Option"))

    scan_data = scanner_sheet.get_all_records()
    if scan_data:
        df_scan = pd.DataFrame(scan_data)
        df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
        active_scan = df_scan[df_scan["Status"].isin(["Monitoring", "Moved to Watchlist"])]
        
        for idx, row in active_scan.iterrows():
            symbol = str(row.get("Symbol", "")).strip()
            if symbol:
                t_sym, sec_id, exch = resolve_instrument(symbol)
                if exch in payload and sec_id.isdigit():
                    payload[exch].append(int(sec_id))
                    row_map.append({"type": "scan", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": sec_id})
                else:
                    skipped_assets.append(f"{symbol} (Scan)")

    payload = {k: list(set(v)) for k, v in payload.items() if v}
    if not payload: 
        st.warning("Could not sync. No valid Security IDs found in database.")
        return
        
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'access-token': daily_token, 
        'client-id': st.secrets["dhan"]["dhan_client_id"] 
    }
    
    with st.spinner("Fetching live market data from Dhan..."):
        try:
            url = "https://api.dhan.co/v2/marketfeed/ohlc"
            response = requests.post(url, headers=headers, json=payload)
            
            if response.status_code == 200:
                data = response.json().get("data", {})
                opt_updates = []
                scan_updates = []
                
                opt_col_idx = sheet_headers.index("Live Price") + 1
                scan_col_idx = scanner_headers.index("Live Price") + 1
                
                synced_count = 0
                for item in row_map:
                    exch = item["exch"]
                    sec_id = item["sec_id"]
                    if exch in data and sec_id in data[exch]:
                        last_price = data[exch][sec_id].get("last_price", "")
                        if item["type"] == "opt":
                            opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], opt_col_idx), 'values': [[str(last_price)]]})
                        elif item["type"] == "scan":
                            scan_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], scan_col_idx), 'values': [[str(last_price)]]})
                        synced_count += 1
                
                if opt_updates: worksheet.batch_update(opt_updates)
                if scan_updates: scanner_sheet.batch_update(scan_updates)
                
                if synced_count > 0:
                    if skipped_assets: st.warning(f"Synced {synced_count} assets. Skipped missing IDs: {', '.join(skipped_assets[:3])}...")
                    else: st.success(f"Successfully updated live prices for {synced_count} assets!")
                    st.rerun()
                else:
                    st.warning("No price data matched your Security IDs.")
            elif response.status_code == 401:
                st.error("Authentication Failed: Your token has expired or is invalid. Please paste today's token in the '⚙️ Daily Setup' menu.")
            else: st.error(f"Dhan API Error: {response.text}")
        except Exception as e: st.error(f"Request Failed: {e}")

# --- 5. BACKGROUND BACKGROUND WORKERS ---
def run_background_sync(df_filtered, state_key, worksheet, sheet_headers):
    if state_key in st.session_state and not df_filtered.empty:
        editor_state = st.session_state[state_key]
        
        edited_rows = editor_state.get("edited_rows", {})
        for idx, changes in list(edited_rows.items()):
            if "Journal" in changes and changes["Journal"] is True:
                sym = df_filtered.iloc[idx]['Symbol / Asset']
                row_id = df_filtered.iloc[idx]['_Sheet_Row']
                st.session_state.viewing_trade = sym
                st.session_state.viewing_trade_row = int(row_id)
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
                        if col_name == "Symbol / Asset":
                            t_sym, t_sec, t_exch = resolve_instrument(str(new_val))
                            worksheet.update_cell(sheet_row, sheet_headers.index("Symbol / Asset") + 1, t_sym)
                            worksheet.update_cell(sheet_row, sheet_headers.index("Security ID") + 1, t_sec)
                            worksheet.update_cell(sheet_row, sheet_headers.index("Exchange") + 1, t_exch)
                        else:
                            col_idx = sheet_headers.index(col_name) + 1
                            worksheet.update_cell(sheet_row, col_idx, str(new_val))

def run_scanner_sync(df_filtered, state_key, scanner_sheet, scanner_headers):
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
