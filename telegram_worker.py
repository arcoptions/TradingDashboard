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
    
    try: raw_worksheet = sh.worksheet("Telegram_Raw_Logs")
    except gspread.exceptions.WorksheetNotFound:
        raw_worksheet = sh.add_worksheet(title="Telegram_Raw_Logs", rows="5000", cols="5")
        raw_worksheet.append_row(["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])

    try: sandbox_worksheet = sh.worksheet("Telegram_Sandbox")
    except gspread.exceptions.WorksheetNotFound:
        sandbox_worksheet = sh.add_worksheet(title="Telegram_Sandbox", rows="2000", cols="15")
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

    import broker_api as api
    import analytics

    API_ID = int(os.environ.get("TELEGRAM_API_ID", secrets.get("telegram", {}).get("api_id", 1234567)))
    API_HASH = os.environ.get("TELEGRAM_API_HASH", secrets.get("telegram", {}).get("api_hash", "your_api_hash"))
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", secrets.get("telegram", {}).get("session_string", ""))

    TRACKED_CHANNELS = [
        -1003141350480,       # Derivates Mr Chartist
        -1003858490010,       # Elephant pro
        -1001320942683,       # Sunil
        -1005281196022,       # Test (Supergroup Layout)
        -5281196022,          # Test (Basic Group Layout)
        -1003800707569,       # Momentum to multibagger
        -1003770951544,       # Investing corner
        'Shortterm01',        # Shortterm
        -1003148687413,       # Equities Intra and Shortterm
        -1003121140019,       # Equities positional
        'The_ChartWizard',    # The chart wizard
        -1003770810999,       # Family May 2026
        -1003109328674,       # Automater alerts Mr Chartist
        'SwingWisely',        # Swingwise
        -1003101198634,       # Commodities Mr Chartist
        'BeatTheStreetNews'   # Isolated Global Social-Media News Engine
    ]
    
    try:
        raw_worksheet, sandbox_worksheet, sheet_headers = init_sheet_connection(secrets)
        print("✅ Core Infrastructure Layers Synchronized.")
    except Exception as e:
        print(f"⚠️ Initialization anomaly: {e}.")
        raw_worksheet, sandbox_worksheet, sheet_headers = None, None, []

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            print("🚀 ARC Ingestion Router Processing...")

            @client.on(events.NewMessage(chats=TRACKED_CHANNELS))
            async def handler(event):
                nonlocal raw_worksheet, sandbox_worksheet, sheet_headers
                raw_text = event.message.message
                if not raw_text: return
                    
                chat_from = await event.get_chat()
                title_token = getattr(chat_from, 'title', '')
                username_token = getattr(chat_from, 'username', '')
                
                if "BeatTheStreet" in username_token or "Beat The Street" in title_token:
                    source_name = "Beat The Street"
                else:
                    source_name = title_token if title_token else (username_token if username_token else str(event.chat_id))
                    
                timestamp_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                try:
                    if not raw_worksheet:
                        secrets_retry = get_secrets()
                        raw_worksheet, sandbox_worksheet, sheet_headers = init_sheet_connection(secrets_retry)
                    
                    # ─── AUTOMATED INGESTION FOR ADVISORY CHANNELS ───
                    if source_name != "Beat The Street":
                        pre_parsed = analytics.parse_telegram_tip(raw_text)
                        t_symbol = str(pre_parsed.get("symbol", "UNKNOWN")).upper().strip()
                        
                        # Verify against Dhan Master via resolve_instrument
                        t_sym, t_sec, t_exch = api.resolve_instrument(t_symbol) if t_symbol != "UNKNOWN" else ("", "", "")
                        
                        if t_sec:  # Valid trade asset verified by Dhan Master
                            new_row_payload = [""] * len(sheet_headers)
                            def fill(col, val): 
                                if col in sheet_headers: new_row_payload[sheet_headers.index(col)] = str(val)
                                    
                            fill("Trade Date", datetime.date.today().strftime("%Y-%m-%d"))
                            fill("Idea Source (Chartink/Telegram/X/Self)", source_name)
                            fill("Symbol / Asset", t_sym)
                            fill("Trade Type (Eq/Option)", pre_parsed.get('trade_type', 'Option'))
                            fill("Exchange", t_exch)
                            fill("Security ID", t_sec)
                            fill("Status (Watch/Active/Closed)", "Watchlist")
                            fill("Entry CMP / Range", pre_parsed.get('entry', ''))
                            fill("Stop Loss (SL)", pre_parsed.get('sl', ''))
                            fill("Target 1", pre_parsed.get('t1', ''))
                            fill("Raw Tip Text", raw_text)
                            
                            sandbox_worksheet.append_row(new_row_payload)
                            raw_worksheet.append_row([timestamp_str, source_name, raw_text, "Automatically Staged"])
                            print(f"⚡ Autopilot Success: Directed {t_sym} straight to tracking sheets.")
                        else:
                            # Not a tradable counter asset, log to standard review queues
                            raw_worksheet.append_row([timestamp_str, source_name, raw_text, "Pending Review"])
                    else:
                        # News channel data goes straight to exclusive news log
                        raw_worksheet.append_row([timestamp_str, source_name, raw_text, "News Ingested"])
                        
                except Exception as log_err:
                    print(f"⚠️ Operational loop exception: {log_err}")

            await client.run_until_disconnected()
        except Exception as loop_err:
            print(f"⚠️ Socket mapping dropped: {loop_err}. Auto-restarting in 10s...")
            await asyncio.sleep(10)

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()
    asyncio.run(run_telegram_listener())
