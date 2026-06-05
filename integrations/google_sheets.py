import os
import json
import toml
import time
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import streamlit as st

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

@st.cache_resource
def init_sheet_connection():
    gc = get_gspread_client()
    sh = gc.open("Comprehensive Trading Tracker 2026")
    
    watchlist_ws = sh.sheet1
    try: scanner_ws = sh.worksheet("Scanners")
    except: scanner_ws = None
    try: settings_ws = sh.worksheet("Settings")
    except: settings_ws = None

    try: 
        study_ws = sh.worksheet("Stocks to study")
        if not study_ws.row_values(1):
            study_ws.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
    except gspread.exceptions.WorksheetNotFound:
        study_ws = sh.add_worksheet(title="Stocks to study", rows="3000", cols="5")
        study_ws.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
        
    try: 
        raw_ws = sh.worksheet("Telegram_Raw_Logs")
    except gspread.exceptions.WorksheetNotFound:
        raw_ws = sh.add_worksheet(title="Telegram_Raw_Logs", rows="5000", cols="5")
        raw_ws.append_row(["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])
        
    return sh, watchlist_ws, study_ws, raw_ws, scanner_ws, settings_ws

@st.cache_data(ttl=15, show_spinner=False)
def fetch_dataframe_safe(sheet_title, is_sheet1=False):
    gc = get_gspread_client()
    sh = gc.open("Comprehensive Trading Tracker 2026")
    max_retries = 3
    for attempt in range(max_retries):
        try:
            worksheet = sh.sheet1 if is_sheet1 else sh.worksheet(sheet_title)
            vals = worksheet.get_all_values()
            if len(vals) > 1:
                df = pd.DataFrame(vals[1:], columns=vals[0])
                return df[df[df.columns[0]].astype(str).str.strip() != ""]
            return pd.DataFrame()
        except gspread.exceptions.APIError as e:
            if "429" in str(e) and attempt < max_retries - 1:
                time.sleep(1.5 ** attempt) 
                continue
            return pd.DataFrame()
        except Exception as e:
            return pd.DataFrame()

@st.cache_data(ttl=30, show_spinner=False)
def fetch_settings_cell(cell_id):
    try:
        _, _, _, _, _, settings_ws = init_sheet_connection()
        if settings_ws: return settings_ws.acell(cell_id).value
    except: pass
    return None
