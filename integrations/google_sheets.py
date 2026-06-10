import os
import json
import toml
import time
import random
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import streamlit as st
from gspread.exceptions import APIError

_LAST_SUCCESS_DATAFRAMES = {}
_LAST_FETCH_ERRORS = {}


def _sheet_cache_key(sheet_title, is_sheet1=False):
    return "Sheet1" if is_sheet1 else str(sheet_title)


def _is_quota_error(err):
    err_text = str(err).lower()
    if "429" in err_text or "quota" in err_text or "rate" in err_text:
        return True
    if hasattr(err, "response") and err.response is not None:
        code = getattr(err.response, "status_code", None)
        if code in (429, 500, 502, 503, 504):
            return True
    return False

def get_secrets():
    try:
        return st.secrets
    except Exception:
        if os.path.exists("secrets.toml"):
            with open("secrets.toml", "r") as f: return toml.load(f)
        elif os.path.exists(".streamlit/secrets.toml"):
            with open(".streamlit/secrets.toml", "r") as f: return toml.load(f)
        return None

@st.cache_resource(ttl=3000) 
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
    max_retries = 4
    delay = 1.5
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            if _is_quota_error(e) and attempt < max_retries - 1:
                time.sleep(delay + random.uniform(0, 0.6))
                delay *= 2.0
                continue
            raise e
        except Exception as e:
            if _is_quota_error(e) and attempt < max_retries - 1:
                time.sleep(delay + random.uniform(0, 0.6))
                delay *= 2.0
                continue
            raise e

@st.cache_resource(ttl=600) 
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

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_dataframe_safe(sheet_title, is_sheet1=False):
    cache_key = _sheet_cache_key(sheet_title, is_sheet1=is_sheet1)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            sh = get_spreadsheet()
            worksheet = sh.sheet1 if is_sheet1 else execute_with_quota_retry(sh.worksheet, sheet_title)
            vals = execute_with_quota_retry(worksheet.get_all_values)
            
            if len(vals) > 1:
                df = pd.DataFrame(vals[1:], columns=vals[0])
                filtered = df[df[df.columns[0]].astype(str).str.strip() != ""]
                _LAST_SUCCESS_DATAFRAMES[cache_key] = filtered.copy(deep=True)
                _LAST_FETCH_ERRORS[cache_key] = ""
                return filtered

            empty_df = pd.DataFrame()
            _LAST_SUCCESS_DATAFRAMES[cache_key] = empty_df
            _LAST_FETCH_ERRORS[cache_key] = ""
            return empty_df
        except Exception as e:
            _LAST_FETCH_ERRORS[cache_key] = str(e)
            if attempt < max_retries - 1:
                time.sleep(1.5 ** attempt)
                continue

            cached_df = _LAST_SUCCESS_DATAFRAMES.get(cache_key)
            if cached_df is not None:
                return cached_df.copy(deep=True)
            return pd.DataFrame()


def get_last_fetch_error(sheet_title="Sheet1"):
    return _LAST_FETCH_ERRORS.get(str(sheet_title), "")

# --- FIXED: Downloads the entire Settings page in 1 API Call instead of spamming 3 ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_settings_dict():
    try:
        sh = get_spreadsheet()
        settings_ws = execute_with_quota_retry(sh.worksheet, "Settings")
        if settings_ws:
            vals = execute_with_quota_retry(settings_ws.get_all_values)
            if len(vals) > 0:
                return {str(row[0]).strip(): str(row[1]).strip() for row in vals if len(row) >= 2}
    except: pass
    return {}

# --- RESTORED: Backwards compatibility for older UI tabs (Cached to prevent Quota Limits) ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_settings_cell(cell_id):
    try:
        sh = get_spreadsheet()
        settings_ws = execute_with_quota_retry(sh.worksheet, "Settings")
        if settings_ws:
            return execute_with_quota_retry(settings_ws.acell, cell_id).value
    except: pass
    return None
