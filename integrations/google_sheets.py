import os
import json
import toml
import gspread
import pandas as pd
from google.oauth2.service_account import Credentials
import streamlit as st

def get_secrets():
    """Retrieve secrets prioritizing Streamlit secrets, then TOML, then Env Variables."""
    try:
        return st.secrets
    except Exception:
        if os.path.exists("secrets.toml"):
            with open("secrets.toml", "r") as f: return toml.load(f)
        elif os.path.exists(".streamlit/secrets.toml"):
            with open(".streamlit/secrets.toml", "r") as f: return toml.load(f)
        return None

def init_sheet_connection():
    """Authenticates and maps all essential Google Sheets tabs, healing missing tabs instantly."""
    secrets = get_secrets()
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    if "gcp_service_account" in secrets: 
        creds_dict = dict(secrets["gcp_service_account"])
    else:
        gcp_env = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if gcp_env: creds_dict = json.loads(gcp_env)
        else: raise ValueError("Missing Google Service Account credentials mapping.")

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    
    # 1. Core Worksheets
    watchlist_ws = sh.sheet1
    try: scanner_ws = sh.worksheet("Scanners")
    except: scanner_ws = None
    try: settings_ws = sh.worksheet("Settings")
    except: settings_ws = None

    # 2. Self-Healing Tab: Stocks to Study
    try: 
        study_ws = sh.worksheet("Stocks to study")
    except gspread.exceptions.WorksheetNotFound:
        study_ws = sh.add_worksheet(title="Stocks to study", rows="3000", cols="5")
        study_ws.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
        
    # 3. Self-Healing Tab: Telegram Raw Logs
    try: 
        raw_ws = sh.worksheet("Telegram_Raw_Logs")
    except gspread.exceptions.WorksheetNotFound:
        raw_ws = sh.add_worksheet(title="Telegram_Raw_Logs", rows="5000", cols="5")
        raw_ws.append_row(["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])
        
    return sh, watchlist_ws, study_ws, raw_ws, scanner_ws, settings_ws

def fetch_dataframe_safe(worksheet):
    """Fetches sheet data with rate-limit protection and blank-header bypass."""
    try:
        vals = worksheet.get_all_values()
        if len(vals) > 1:
            df = pd.DataFrame(vals[1:], columns=vals[0])
            # Filter out completely empty rows
            return df[df[df.columns[0]].astype(str).str.strip() != ""]
        return pd.DataFrame()
    except Exception as e:
        print(f"Sheet Fetch Error: {e}")
        return pd.DataFrame()
