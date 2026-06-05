import os
import json
import toml
import time
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import streamlit as st
from gspread.exceptions import APIError

# --- SESSION LAYER METADATA CACHE ---
if "cached_spreadsheet_instance" not in st.session_state:
    st.session_state.cached_spreadsheet_instance = None

def get_secrets():
    try:
        return st.secrets
    except Exception:
        if os.path.exists("secrets.toml"):
            with open("secrets.toml", "r") as f: return toml.load(f)
        elif os.path.exists(".streamlit/secrets.toml"):
            with open(".streamlit/secrets.toml", "r") as f: return toml.load(f)
        return None

@st.cache_resource
def get_gspread_client():
    secrets = get_secrets()
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    if "gcp_service_account" in secrets: 
        creds_dict = dict(secrets["gcp_service_account"])
    else:
        gcp_env = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if gcp_env: creds_dict = json.loads(gcp_env)
        else: raise ValueError("Missing Google Service Account credentials mapping.")

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(credentials)

def execute_with_quota_retry(func, *args, **kwargs):
    """Wraps core sheet transactions in an exponential backoff circuit breaker."""
    max_retries = 5
    delay = 2.0
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            # Catch standard 429 quota blockades or internal rate errors
            if ("429" in str(e) or (e.response is not None and e.response.status_code == 429)) and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2.0
                continue
            raise e
        except Exception as e:
            raise e

def get_cached_spreadsheet():
    """Manages cross-module spreadsheet instance handles to optimize read usage."""
    if st.session_state.cached_spreadsheet_instance is None:
        gc = get_gspread_client()
        st.session_state.cached_spreadsheet_instance = execute_with_quota_retry(
            gc.open, "Comprehensive Trading Tracker 2026"
        )
    return st.session_state.cached_spreadsheet_instance

@st.cache_resource
def init_sheet_connection():
    sh = get_cached_spreadsheet()
    
    watchlist_ws = sh.sheet1
    try: scanner_ws = execute_with_quota_retry(sh.worksheet, "Scanners")
    except: scanner_ws = None
    try: settings_ws = execute_with_quota_retry(sh.worksheet, "Settings")
    except: settings_ws = None

    try: 
        study_ws = execute_with_quota_retry(sh.worksheet, "Stocks to study")
        first_row = execute_with_quota_retry(study_ws.row_values, 1)
        if not first_row:
            execute_with_quota_retry(study_ws.append_row, ["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
    except gspread.exceptions.WorksheetNotFound:
        study_ws = execute_with_quota_retry(sh.add_worksheet, title="Stocks to study", rows="3000", cols="5")
        execute_with_quota_retry(study_ws.append_row, ["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
        
    try: 
        raw_ws = execute_with_quota_retry(sh.worksheet, "Telegram_Raw_Logs")
    except gspread.exceptions.WorksheetNotFound:
        raw_ws = execute_with_quota_retry(sh.add_worksheet, title="Telegram_Raw_Logs", rows="5000", cols="5")
        execute_with_quota_retry(raw_ws.append_row, ["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])
        
    return sh, watchlist_ws, study_ws, raw_ws, scanner_ws, settings_ws

@st.cache_data(ttl=15, show_spinner=False)
def fetch_dataframe_safe(sheet_title, is_sheet1=False):
    try:
        sh = get_cached_spreadsheet()
        worksheet = sh.sheet1 if is_sheet1 else execute_with_quota_retry(sh.worksheet, sheet_title)
        vals = execute_with_quota_retry(worksheet.get_all_values)
        
        if len(vals) > 1:
            df = pd.DataFrame(vals[1:], columns=vals[0])
            return df[df[df.columns[0]].astype(str).str.strip() != ""]
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=30, show_spinner=False)
def fetch_settings_cell(cell_id):
    try:
        sh = get_cached_spreadsheet()
        settings_ws = execute_with_quota_retry(sh.worksheet, "Settings")
        if settings_ws:
            cell_node = execute_with_quota_retry(settings_ws.acell, cell_id)
            return cell_node.value
    except: pass
    return None
