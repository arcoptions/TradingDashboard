import asyncio
import os
import toml
import threading
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
        """Responds to Render and Keep-Alive pings to prevent sleep mode."""
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ARC Ingestion Engine Operational")
        
    def log_message(self, format, *args):
        return # Suppress standard log clutter in your terminal window

def run_health_server():
    port = int(os.environ.get("PORT", 10000)) # Render assigns this dynamically
    server = HTTPServer(("0.0.0.0", port), HealthCheckServer)
    print(f"🌐 Internal Health Server bound to port {port}")
    server.serve_forever()

# ─── TELEGRAM CONFIGURATION ───
API_ID = 1234567          # Replace with your integer API ID
API_HASH = 'your_api_hash' # Replace with your API Hash
SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING")

TRACKED_CHANNELS = [
    'elephant_pro_signals', 
    'mr_chartist_alerts'
]

def get_secrets():
    """Safely extracts secrets whether hosted on Streamlit or Render."""
    # 1. Try the Render-friendly root path first
    if os.path.exists("secrets.toml"):
        with open("secrets.toml", "r") as f:
            return toml.load(f)
            
    # 2. Fallback to Streamlit's hidden directory (for local testing)
    elif os.path.exists(".streamlit/secrets.toml"):
        with open(".streamlit/secrets.toml", "r") as f:
            return toml.load(f)
            
    # 3. Crash gracefully if neither exist
    else:
        print("❌ Secrets file not found. Ensure 'secrets.toml' is uploaded to Render.")
        return None

def init_sheet_connection(secrets):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    return sh.sheet1, sh.sheet1.row_values(1)

async def main():
    if not SESSION_STRING:
        print("❌ CRITICAL ERROR: TELEGRAM_SESSION_STRING environment variable is missing.")
        return

    print("🚀 Initializing ARC Telegram Cloud Ingestion Client...")
    secrets = get_secrets()
    worksheet, sheet_headers = init_sheet_connection(secrets)
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    print("✅ MTProto Channel Socket Stream Established.")

    @client.on(events.NewMessage(chats=TRACKED_CHANNELS))
    async def handler(event):
        raw_text = event.message.message
        if not raw_text: return
            
        chat_from = await event.get_chat()
        source_name = getattr(chat_from, 'title', getattr(chat_from, 'username', 'Telegram Channel'))
        
        print(f"📥 New Alert Ingested from [{source_name}].")
        
        try:
            parsed_data = analytics.parse_telegram_tip(raw_text)
            if not parsed_data.get("symbol"): return
                
            t_sym, t_sec, t_exch = api.resolve_instrument(parsed_data['symbol'])
            new_row = [""] * len(sheet_headers)
            
            def set_cell(col_name, val):
                if col_name in sheet_headers:
                    new_row[sheet_headers.index(col_name)] = str(val)
            
            set_cell("Trade Date", datetime.date.today().strftime("%Y-%m-%d"))
            set_cell("Idea Source (Chartink/Telegram/X/Self)", source_name)
            set_cell("Symbol / Asset", t_sym)
            set_cell("Trade Type (Eq/Option)", parsed_data['trade_type'])
            set_cell("Exchange", t_exch)
            set_cell("Security ID", t_sec)
            set_cell("Status (Watch/Active/Closed)", "Watchlist") 
            set_cell("Entry CMP / Range", parsed_data['entry'])
            set_cell("Add-On / Dip Levels", parsed_data['add_levels'])
            set_cell("Stop Loss (SL)", parsed_data['sl'])
            set_cell("Target 1", parsed_data['t1'])
            set_cell("Target 2", parsed_data['t2'])
            set_cell("Time Frame", parsed_data['tf'])
            set_cell("Setup Rating", parsed_data['rating'])
            set_cell("Raw Tip Text", raw_text)
            
            worksheet.append_row(new_row)
            print(f"🔥 Structured Tip Streamed to Tracker -> {t_sym} Watchlist Entry.")
            
        except Exception as err:
            print(f"❌ Ingestion Pipeline Failure: {err}")

    await client.run_until_disconnected()

if __name__ == '__main__':
    # Start the dummy web server in a separate background thread
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()
    
    # Run the main asynchronous Telegram engine
    asyncio.run(main())
