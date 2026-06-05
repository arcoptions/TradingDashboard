import asyncio
import os
import toml
import threading
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import gspread
from google.oauth2.service_account import Credentials
import datetime

# Internal Terminal Modules
import analytics
import broker_api as api

# ─── LIGHTWEIGHT WEB SERVER FOR RENDER FREE TIER ───
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ARC Ingestion Engine Operational")
        except Exception as e: print(f"⚠️ Health Server GET exception: {e}")
        
    def do_HEAD(self):
        try:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
        except Exception as e: print(f"⚠️ Health Server HEAD exception: {e}")
        
    def log_message(self, format, *args): return 

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
        print(f"🌐 Internal Health Server bound successfully to port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ CRITICAL: Failed to bind Health Server on port {port}: {e}")

def get_secrets():
    if os.path.exists("secrets.toml"):
        with open("secrets.toml", "r") as f: return toml.load(f)
    elif os.path.exists(".streamlit/secrets.toml"):
        with open(".streamlit/secrets.toml", "r") as f: return toml.load(f)
    else:
        if os.environ.get("TELEGRAM_SESSION_STRING"): return {"env_fallback": True}
        return None

def init_sheet_connection(secrets):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    if "gcp_service_account" in secrets: creds_dict = secrets["gcp_service_account"]
    else:
        gcp_env = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if gcp_env:
            import json
            creds_dict = json.loads(gcp_env)
        else: raise ValueError("Missing Google Service Account credentials mapping.")

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    
    # 1. Ensure Raw Logs Tab Exists (The Observation Deck)
    try:
        raw_worksheet = sh.worksheet("Telegram_Raw_Logs")
    except gspread.exceptions.WorksheetNotFound:
        print("📁 Creating isolated staging tab: 'Telegram_Raw_Logs'...")
        raw_worksheet = sh.add_worksheet(title="Telegram_Raw_Logs", rows="2000", cols="5")
        raw_worksheet.append_row(["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])

    # 2. Ensure Sandbox Tab Exists (The Extractor Pipeline)
    try:
        sandbox_worksheet = sh.worksheet("Telegram_Sandbox")
    except gspread.exceptions.WorksheetNotFound:
        print("📁 Creating isolated staging tab: 'Telegram_Sandbox'...")
        sandbox_worksheet = sh.add_worksheet(title="Telegram_Sandbox", rows="1000", cols="15")
        sandbox_worksheet.append_row([
            "Trade Date", "Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", 
            "Trade Type (Eq/Option)", "Exchange", "Security ID", "Status (Watch/Active/Closed)", 
            "Entry CMP / Range", "Add-On / Dip Levels", "Stop Loss (SL)", "Target 1", 
            "Target 2", "Time Frame", "Setup Rating", "Raw Tip Text"
        ])
        
    return raw_worksheet, sandbox_worksheet, sandbox_worksheet.row_values(1)

async def run_telegram_listener():
    secrets = get_secrets()
    if not secrets: return

    API_ID = int(os.environ.get("TELEGRAM_API_ID", secrets.get("telegram", {}).get("api_id", 1234567)))
    API_HASH = os.environ.get("TELEGRAM_API_HASH", secrets.get("telegram", {}).get("api_hash", "your_api_hash"))
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", secrets.get("telegram", {}).get("session_string", ""))

    # ─── MASTER CHANNEL DECK ───
    # Public channels use string usernames. Private web links require the -100 prefix.
    TRACKED_CHANNELS = [
        -1003141350480, # Derivates Mr Chartist
        -1003858490010, # Elephant pro
        -1001320942683, # Sunil
        -1005281196022, # Test
        -5281196022, # Test
        -1003800707569, # Momentum to multibagger
        -1003770951544, # Investing corner
        'Shortterm01',  # Shortterm (Public)
        -1003148687413, # Equities Intra and Shortterm
        -1003121140019, # Equities positional
        'The_ChartWizard', # The chart wizard (Public)
        -1003770810999, # Family May 2026
        -1003109328674, # Automater alerts Mr Chartist
        'SwingWisely',  # Swingwise (Public)
        -1003101198634,  # Commodities Mr Chartist
        'BeatTheStreetnews' #BeatTheStreetNews
    ]
    
    try:
        raw_worksheet, sandbox_worksheet, sheet_headers = init_sheet_connection(secrets)
        print("✅ Google Sheets connection established.")
    except Exception as e:
        print(f"⚠️ Sheets linking error: {e}.")
        raw_worksheet, sandbox_worksheet, sheet_headers = None, None, []

    while True:
        try:
            print("🔌 Connecting socket stream to Telegram MTProto network...")
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            print("✅ Connection verified. Listening for real-time market data...")

            @client.on(events.NewMessage(chats=TRACKED_CHANNELS))
            async def handler(event):
                nonlocal raw_worksheet, sandbox_worksheet, sheet_headers
                raw_text = event.message.message
                if not raw_text: return
                    
                chat_from = await event.get_chat()
                source_name = getattr(chat_from, 'title', getattr(chat_from, 'username', str(event.chat_id)))
                timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"📥 Incoming broadcast captured from [{source_name}]")
                
                # --- PHASE 1: Immediate Observation Deck Logging ---
                try:
                    if not raw_worksheet:
                        secrets_retry = get_secrets()
                        raw_worksheet, sandbox_worksheet, sheet_headers = init_sheet_connection(secrets_retry)
                    raw_worksheet.append_row([timestamp_str, source_name, raw_text, "Pending Extraction"])
                except Exception as log_err:
                    print(f"⚠️ Raw logging failure: {log_err}")

                # --- PHASE 2: Pipeline Extraction Logic ---
                try:
                    parsed_data = analytics.parse_telegram_tip(raw_text)
                    if not parsed_data or not parsed_data.get("symbol"): 
                        raw_worksheet.update_cell(raw_worksheet.filled_rows, 4, "Dropped: Unstructured Format")
                        return
                        
                    t_sym, t_sec, t_exch = api.resolve_instrument(parsed_data.get("symbol"))
                    new_row = [""] * len(sheet_headers)
                    
                    def set_cell(col_name, val):
                        if col_name in sheet_headers: new_row[sheet_headers.index(col_name)] = str(val)
                    
                    set_cell("Trade Date", datetime.date.today().strftime("%Y-%m-%d"))
                    set_cell("Idea Source (Chartink/Telegram/X/Self)", source_name)
                    set_cell("Symbol / Asset", t_sym)
                    set_cell("Trade Type (Eq/Option)", parsed_data.get('trade_type', 'Option'))
                    set_cell("Exchange", t_exch)
                    set_cell("Security ID", t_sec)
                    set_cell("Status (Watch/Active/Closed)", "Watchlist") 
                    set_cell("Entry CMP / Range", parsed_data.get('entry', ''))
                    set_cell("Add-On / Dip Levels", parsed_data.get('add_levels', ''))
                    set_cell("Stop Loss (SL)", parsed_data.get('sl', ''))
                    set_cell("Target 1", parsed_data.get('t1', ''))
                    set_cell("Target 2", parsed_data.get('t2', ''))
                    set_cell("Time Frame", parsed_data.get('tf', ''))
                    set_cell("Setup Rating", parsed_data.get('rating', ''))
                    set_cell("Raw Tip Text", raw_text)
                    
                    sandbox_worksheet.append_row(new_row)
                    raw_worksheet.update_cell(raw_worksheet.filled_rows, 4, "Staged: Successfully Mapped")
                    
                except Exception as err:
                    print(f"❌ Pipeline extraction error: {str(err)}")

            await client.run_until_disconnected()
            
        except Exception as loop_err:
            print(f"⚠️ Socket execution network loop interruption: {loop_err}")
            await asyncio.sleep(15)

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()
    try:
        asyncio.run(run_telegram_listener())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as fatal_err:
        while True: time.sleep(3600)
