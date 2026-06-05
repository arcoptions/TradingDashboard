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
import database as db

# ─── LIGHTWEIGHT WEB SERVER FOR RENDER FREE TIER ───
class HealthCheckServer(BaseHTTPRequestHandler):
    def do_GET(self):
        """Responds to standard browser and Render health check pings."""
        try:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ARC Ingestion Engine Operational")
        except Exception as e:
            print(f"⚠️ Health Server GET handling exception: {e}")
        
    def do_HEAD(self):
        """Responds to UptimeRobot HEAD requests to keep the service awake."""
        try:
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
        except Exception as e:
            print(f"⚠️ Health Server HEAD handling exception: {e}")
        
    def log_message(self, format, *args):
        return # Suppress log pollution in Render terminal windows

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
        print(f"🌐 Internal Health Server bound successfully to port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"❌ CRITICAL: Failed to bind Health Server on port {port}: {e}")

def get_secrets():
    """Safely extracts secrets from local files or environment configuration blocks."""
    if os.path.exists("secrets.toml"):
        with open("secrets.toml", "r") as f:
            return toml.load(f)
    elif os.path.exists(".streamlit/secrets.toml"):
        with open(".streamlit/secrets.toml", "r") as f:
            return toml.load(f)
    else:
        # Fallback to check if credentials exist directly in environment variables
        if os.environ.get("TELEGRAM_SESSION_STRING"):
            return {"env_fallback": True}
        print("❌ Secrets file not found. Falling back to environment variables configuration.")
        return None

def init_sheet_connection(secrets):
    """Initializes Google Sheets connection and maps out the sandbox pipeline."""
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    
    if "gcp_service_account" in secrets:
        creds_dict = secrets["gcp_service_account"]
    else:
        # Try to parse directly from environment variable string if present
        gcp_env = os.environ.get("GCP_SERVICE_ACCOUNT_JSON")
        if gcp_env:
            import json
            creds_dict = json.loads(gcp_env)
        else:
            raise ValueError("Missing Google Service Account credentials mapping.")

    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc = gspread.authorize(credentials)
    
    sh = gc.open("Comprehensive Trading Tracker 2026")
    sandbox_tab_name = "Telegram_Sandbox"
    
    try:
        worksheet = sh.worksheet(sandbox_tab_name)
    except gspread.exceptions.WorksheetNotFound:
        print(f"📁 Creating isolated staging tab: '{sandbox_tab_name}'...")
        worksheet = sh.add_worksheet(title=sandbox_tab_name, rows="1000", cols="20")
        default_headers = [
            "Trade Date", "Idea Source (Chartink/Telegram/X/Self)", "Symbol / Asset", 
            "Trade Type (Eq/Option)", "Exchange", "Security ID", "Status (Watch/Active/Closed)", 
            "Entry CMP / Range", "Add-On / Dip Levels", "Stop Loss (SL)", "Target 1", 
            "Target 2", "Time Frame", "Setup Rating", "Raw Tip Text"
        ]
        worksheet.append_row(default_headers)
        
    sheet_headers = worksheet.row_values(1)
    return worksheet, sheet_headers

async def run_telegram_listener():
    """Main execution loop for connection resilience and ingestion management."""
    secrets = get_secrets()
    if not secrets:
        print("❌ Ingestion initialization halted: Missing credential mapping configurations.")
        return

    # Dynamic lookup: Env vars take priority, fallback to secrets file, fallback to default tokens
    API_ID = int(os.environ.get("TELEGRAM_API_ID", secrets.get("telegram", {}).get("api_id", 1234567)))
    API_HASH = os.environ.get("TELEGRAM_API_HASH", secrets.get("telegram", {}).get("api_hash", "your_api_hash"))
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", secrets.get("telegram", {}).get("session_string", ""))

    if not SESSION_STRING or API_ID == 1234567:
        print("⚠️ CRITICAL CONFIGURATION NOTICE: Using dummy/empty placeholders for API_ID or Session String.")
        print("👉 Please ensure TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_SESSION_STRING are set in Render's Environment Variables.")

    # Replace the previous list in telegram_worker.py with your complete operational matrix
TRACKED_CHANNELS = [
    'Derivatives (F&O)- Investology',
    'Elephant Pro',
    'Investing Korner',
    'Momentum to Multibagger - Chikoutrader',
    'Shortterm01',
    'Equities (Intra & ShortTerm)- Investology',
    'Equities Positional- Investology V2',
    'Family May 2026',
    'Automated ALerts V2',
    'Commodities- Investology V2',
    'Test'
]
    
    try:
        worksheet, sheet_headers = init_sheet_connection(secrets)
        print("✅ Google Sheets connection established and bound to Sandbox environment.")
    except Exception as e:
        print(f"⚠️ Google Sheets linking error: {e}. Worker will retry connection loop shortly.")
        worksheet, sheet_headers = None, []

    while True:
        try:
            print("🔌 Connecting socket stream to Telegram MTProto network...")
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            print("✅ Connection verified. Listening for incoming real-time market data...")

            @client.on(events.NewMessage(chats=TRACKED_CHANNELS))
            async def handler(event):
                nonlocal worksheet, sheet_headers
                raw_text = event.message.message
                if not raw_text: return
                    
                chat_from = await event.get_chat()
                source_name = getattr(chat_from, 'title', getattr(chat_from, 'username', 'Telegram Channel'))
                print(f"📥 Incoming raw execution broadcast captured from [{source_name}]")
                
                try:
                    # Double check worksheet mapping connectivity safety net
                    if not worksheet:
                        secrets_retry = get_secrets()
                        worksheet, sheet_headers = init_sheet_connection(secrets_retry)

                    parsed_data = analytics.parse_telegram_tip(raw_text)
                    if not parsed_data or not parsed_data.get("symbol"): 
                        print("⚠️ Parser notification: Stream skipped. No actionable ticker tokens mapped.")
                        return
                        
                    t_sym, t_sec, t_exch = api.resolve_instrument(parsed_data.get("symbol"))
                    new_row = [""] * len(sheet_headers)
                    
                    def set_cell(col_name, val):
                        if col_name in sheet_headers:
                            new_row[sheet_headers.index(col_name)] = str(val)
                    
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
                    
                    worksheet.append_row(new_row)
                    print(f"🔥 Core Buffer Staging Success: Actionable entry logged for {t_sym}.")
                    
                except Exception as err:
                    print(f"❌ Pipeline processing exception: {str(err)}")
                    print("💡 Core process isolated. Engine remains online.")

            await client.run_until_disconnected()
            
        except Exception as loop_err:
            print(f"⚠️ Socket execution network loop interruption: {loop_err}")
            print("⏳ Re-initializing core interface loop in 15 seconds...")
            await asyncio.sleep(15)

if __name__ == '__main__':
    print("🎬 Initializing ARC Cloud Ingestion Infrastructure...")
    
    # Step 1: Immediately deploy the web health check server to pass Render port scanning
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()
    print("🌐 Web safety server launched. Infrastructure online check active.")
    
    # Step 2: Spin up the continuous processing runtime loop
    try:
        asyncio.run(run_telegram_listener())
    except KeyboardInterrupt:
        print("🛑 Process terminated by administrative command.")
        sys.exit(0)
    except Exception as fatal_err:
        print(f"💥 Main runtime processing exception encountered: {fatal_err}")
        # Prevent container from dropping instantly to preserve diagnostic port interface
        while True:
            time.sleep(3600)
