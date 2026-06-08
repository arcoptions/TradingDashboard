import os
import json
import toml
import time
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import streamlit as st
from gspread.exceptions import APIError

def get_secrets():
    try:
        return st.secrets
    except Exception:
        if os.path.exists("secrets.toml"):
            with open("secrets.toml", "r") as f: return toml.load(f)
        elif os.path.exists(".streamlit/secrets.toml"):
            with open(".streamlit/secrets.toml", "r") as f: return toml.load(f)
        return None

@st.cache_resource(ttl=3000) # Re-authenticates every 50 minutes to avoid the strict 1-hour Google OAuth expiry
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
    max_retries = 4
    delay = 1.5
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            # Catch standard 429 quota blockades and pause the thread safely
            if ("429" in str(e) or "Quota" in str(e) or (hasattr(e, 'response') and e.response is not None and e.response.status_code == 429)) and attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2.0
                continue
            raise e
        except Exception as e:
            # If a generic network failure occurs, try again before collapsing
            if attempt < max_retries - 1:
                time.sleep(delay)
                delay *= 2.0
                continue
            raise e

@st.cache_resource(ttl=600) # Holds the spreadsheet metadata for 10 minutes to prevent 429 Quota errors
def get_spreadsheet():
    gc = get_gspread_client()
    return execute_with_quota_retry(gc.open, "Comprehensive Trading Tracker 2026")

@st.cache_resource(ttl=600)
def init_sheet_connection():
    sh = get_spreadsheet()
    
    watchlist_ws = sh.sheet1
    try: scanner_ws = execute_with_quota_retry(sh.worksheet, "Scanners")
    except: scanner_ws = None
    try: settings_ws = execute_with_quota_retry(sh.worksheet, "Settings")
    except: settings_ws = None

    try: 
        study_ws = execute_with_quota_retry(sh.worksheet, "Stocks to study")
    except Exception:
        study_ws = execute_with_quota_retry(sh.add_worksheet, title="Stocks to study", rows="3000", cols="5")
        execute_with_quota_retry(study_ws.append_row, ["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
        
    try: 
        raw_ws = execute_with_quota_retry(sh.worksheet, "Telegram_Raw_Logs")
    except Exception:
        raw_ws = execute_with_quota_retry(sh.add_worksheet, title="Telegram_Raw_Logs", rows="5000", cols="5")
        execute_with_quota_retry(raw_ws.append_row, ["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])
        
    return sh, watchlist_ws, study_ws, raw_ws, scanner_ws, settings_ws

# CACHE HELD FOR 1 HOUR: Only resets when a CRUD operation triggers .clear()
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_dataframe_safe(sheet_title, is_sheet1=False):
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sh = get_spreadsheet()
            worksheet = sh.sheet1 if is_sheet1 else execute_with_quota_retry(sh.worksheet, sheet_title)
            vals = execute_with_quota_retry(worksheet.get_all_values)
            
            if len(vals) > 1:
                df = pd.DataFrame(vals[1:], columns=vals[0])
                # Filter out completely empty rows
                return df[df[df.columns[0]].astype(str).str.strip() != ""]
            return pd.DataFrame()
        except Exception:
            if attempt < max_retries - 1:
                time.sleep(1.5 ** attempt)
                continue
            return pd.DataFrame()

# CACHE HELD FOR 1 HOUR: Protects the sidebar from constantly pinging the API
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_settings_cell(cell_id):
    try:
        sh = get_spreadsheet()
        settings_ws = execute_with_quota_retry(sh.worksheet, "Settings")
        if settings_ws:
            return execute_with_quota_retry(settings_ws.acell, cell_id).value
    except: pass
    return None
