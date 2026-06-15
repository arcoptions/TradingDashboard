import asyncio
import os
import toml
import threading
import sys
import time
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import gspread
from google.oauth2.service_account import Credentials
import datetime

# ─── MASTER DICTIONARIES FOR BACKGROUND NLP ───
ASSET_ALIASES = {
    "COALINDIA": ["COALINDIA", "COAL INDIA", "CIL"],
    "RELIANCE": ["RELIANCE", "RIL", "RELIANCE INDUSTRIES"],
    "M&M": ["M&M", "M & M", "MAHINDRA"],
    "TATAMOTORS": ["TATAMOTORS", "TATA MOTORS"],
    "TCS": ["TCS", "TATA CONSULTANCY SERVICES"],
    "HDFCBANK": ["HDFCBANK", "HDFC BANK"],
    "ICICIBANK": ["ICICIBANK", "ICICI BANK"],
    "INFY": ["INFY", "INFOSYS"],
    "SUNPHARMA": ["SUNPHARMA", "SUN PHARMA"],
    "TATASTEEL": ["TATASTEEL", "TATA STEEL"],
    "WIPRO": ["WIPRO"],
    "OIL": ["OIL", "OIL INDIA", "OILINDIA"]
}

SECTOR_MAP_KEYS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HCLTECH", "WIPRO", "TECHM", 
    "TATAELXSI", "ITC", "HUL", "NESTLEIND", "VBL", "BRITANNIA", "TATAMOTORS", "M&M", 
    "TVSMOTOR", "MARUTI", "BAJAJ-AUTO", "SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", 
    "JSWENERGY", "NTPC", "POWERGRID", "TATAPOWER", "UPL", "PIIND", "COALINDIA", 
    "TATASTEEL", "OIL"
]

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
    
    watchlist_ws = sh.sheet1
    
    try: study_ws = sh.worksheet("Stocks to study")
    except gspread.exceptions.WorksheetNotFound:
        study_ws = sh.add_worksheet(title="Stocks to study", rows="3000", cols="6")
        study_ws.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])

    try: raw_ws = sh.worksheet("Telegram_Raw_Logs")
    except gspread.exceptions.WorksheetNotFound:
        raw_ws = sh.add_worksheet(title="Telegram_Raw_Logs", rows="5000", cols="5")
        raw_ws.append_row(["Timestamp", "Channel Source", "Raw Message Text", "Parsing Status"])
        
    return sh, watchlist_ws, study_ws, raw_ws, watchlist_ws.row_values(1)


async def run_backfill_routine(client, sh, watchlist_ws, study_ws, raw_ws, sheet_headers, tracked_channels):
    """
    Backfill missing messages from tracked channels (past 48 hours) without re-logging duplicates.
    Runs once on startup before the main listener activates.
    """
    import broker_api as api
    import analytics
    
    try:
        # Get all existing logged messages to avoid re-processing
        existing_logs = raw_ws.get_all_records()
        existing_contents = {
            str(r.get("Raw Message Text", "")).strip().lower()
            for r in existing_logs
            if r.get("Raw Message Text")
        }
        print(f"📋 Dedup cache loaded: {len(existing_contents)} existing messages")
        
        cached_bases = []
        try:
            existing_records = watchlist_ws.get_all_records()
            cached_bases = [
                str(r.get('Symbol / Asset', '')).upper().split('-')[0].split(' ')[0].strip()
                for r in existing_records
            ]
        except:
            cached_bases = []

        # Fetch recent messages from each tracked channel
        backfill_count = 0
        for channel in tracked_channels:
            try:
                entity = await client.get_entity(channel)
                history = await client.get_messages(entity, limit=100)
                
                for msg in history:
                    if not msg.message:
                        continue
                    
                    raw_text = msg.message.strip()
                    content_key = raw_text.lower()
                    
                    # Skip if already logged
                    if content_key in existing_contents:
                        continue
                    
                    # Get source name
                    title_token = getattr(entity, 'title', '')
                    username_token = getattr(entity, 'username', '')
                    if "BeatTheStreet" in username_token or "Beat The Street" in title_token:
                        source_name = "Beat The Street"
                    else:
                        source_name = title_token if title_token else (username_token if username_token else str(channel))
                    
                    timestamp_str = msg.date.strftime("%Y-%m-%d %H:%M:%S")
                    
                    try:
                        # Route through same logic as live handler
                        if source_name == "Beat The Street":
                            text_upper = raw_text.upper()
                            text_norm = text_upper.replace(" ", "")
                            matched_symbol = ""
                            
                            for master_ticker, aliases in ASSET_ALIASES.items():
                                for alias in aliases:
                                    pattern = r'\b' + re.escape(alias.upper()) + r'\b'
                                    if re.search(pattern, text_upper) or alias.replace(" ", "") in text_norm:
                                        matched_symbol = master_ticker
                                        break
                                if matched_symbol:
                                    break
                            
                            if not matched_symbol:
                                for index_asset in SECTOR_MAP_KEYS:
                                    pattern = r'\b' + re.escape(index_asset.upper()) + r'\b'
                                    if re.search(pattern, text_upper):
                                        matched_symbol = index_asset
                                        break
                            
                            if matched_symbol:
                                t_sym, t_sec, _ = api.resolve_instrument(matched_symbol)
                                if t_sec:
                                    study_ws.append_row([
                                        timestamp_str, source_name, t_sym, raw_text,
                                        datetime.date.today().strftime("%Y-%m-%d")
                                    ])
                                    raw_ws.append_row([
                                        timestamp_str, source_name, raw_text,
                                        "Backfilled -> Stocks to Study"
                                    ])
                                    backfill_count += 1
                            else:
                                raw_ws.append_row([timestamp_str, source_name, raw_text, "Backfilled -> News Ingested"])
                                backfill_count += 1
                        else:
                            # Advisory tip routing
                            pre_parsed = analytics.parse_telegram_tip(raw_text)
                            t_symbol = str(pre_parsed.get("symbol", "UNKNOWN")).upper().strip()
                            t_sym, t_sec, t_exch = (
                                api.resolve_instrument(t_symbol)
                                if t_symbol != "UNKNOWN"
                                else ("", "", "")
                            )
                            
                            if t_sec:
                                base_to_check = t_sym.split('-')[0].split(' ')[0].strip()
                                if base_to_check not in cached_bases:
                                    try:
                                        from core_engines.nlp_router import FNO_SYMBOLS
                                    except:
                                        FNO_SYMBOLS = []
                                    
                                    is_fno = (
                                        base_to_check in FNO_SYMBOLS
                                        or pre_parsed.get('trade_type') == 'Option'
                                    )
                                    contract_symbol = t_sym
                                    auto_derived_type = "Option" if is_fno else "Equity"
                                    final_exch = "NSE_FNO" if is_fno else t_exch
                                    
                                    new_row = [""] * len(sheet_headers)
                                    def fill(col, val):
                                        if col in sheet_headers:
                                            new_row[sheet_headers.index(col)] = str(val)
                                    
                                    fill("Trade Date", datetime.date.today().strftime("%Y-%m-%d"))
                                    fill("Idea Source (Chartink/Telegram/X/Self)", source_name)
                                    fill("Symbol / Asset", contract_symbol)
                                    fill("Trade Type (Eq/Option)", auto_derived_type)
                                    fill("Exchange", final_exch)
                                    fill("Security ID", t_sec)
                                    fill("Status (Watch/Active/Closed)", "Watchlist")
                                    fill("Entry CMP / Range", pre_parsed.get('entry', ''))
                                    fill("Stop Loss (SL)", pre_parsed.get('sl', ''))
                                    fill("Target 1", pre_parsed.get('t1', ''))
                                    fill("Raw Tip Text", raw_text)
                                    
                                    watchlist_ws.append_row(new_row)
                                    cached_bases.append(base_to_check)
                                    raw_ws.append_row([
                                        timestamp_str, source_name, raw_text,
                                        "Backfilled -> Watchlist"
                                    ])
                                    backfill_count += 1
                            else:
                                raw_ws.append_row([
                                    timestamp_str, source_name, raw_text,
                                    "Backfilled -> Discussion"
                                ])
                                backfill_count += 1
                    except Exception as backfill_err:
                        print(f"⚠️ Backfill routing error for {source_name}: {backfill_err}")
            except Exception as ch_err:
                print(f"⚠️ Could not backfill channel {channel}: {ch_err}")
        
        if backfill_count > 0:
            print(f"✅ Backfill complete: {backfill_count} messages recovered and routed")
        else:
            print("ℹ️ No new messages to backfill (all recent messages already logged)")
    
    except Exception as backfill_fatal:
        print(f"❌ Backfill routine failed: {backfill_fatal}")


async def run_telegram_listener():
    secrets = get_secrets()
    if not secrets: return

    import broker_api as api
    import analytics

    API_ID = int(os.environ.get("TELEGRAM_API_ID", secrets.get("telegram", {}).get("api_id", 1234567)))
    API_HASH = os.environ.get("TELEGRAM_API_HASH", secrets.get("telegram", {}).get("api_hash", "your_api_hash"))
    SESSION_STRING = os.environ.get("TELEGRAM_SESSION_STRING", secrets.get("telegram", {}).get("session_string", ""))

    TRACKED_CHANNELS = [
        -1003141350480, -1003858490010, -3858490010, -1001320942683, -1005281196022, -5281196022,
        -1003800707569, -1003770951544, 'Shortterm01', -1003148687413, -1003121140019,
        'The_ChartWizard', -1003770810999, -1003109328674, 'SwingWisely', -1003101198634,
        'BeatTheStreetNews'
    ]
    
    try:
        sh, watchlist_ws, study_ws, raw_ws, sheet_headers = init_sheet_connection(secrets)
        print("✅ Core Infrastructure Automated Routers Armed.")
    except Exception as e:
        print(f"⚠️ Initialization issue: {e}")
        return

    while True:
        try:
            client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
            await client.start()
            
            # Run backfill once on startup to recover missing tips
            print("🔄 Starting backfill routine to recover missing tips...")
            await run_backfill_routine(client, sh, watchlist_ws, study_ws, raw_ws, sheet_headers, TRACKED_CHANNELS)
            print("✅ Backfill complete. Activating real-time listener...")

            @client.on(events.NewMessage(chats=TRACKED_CHANNELS))
            async def handler(event):
                nonlocal sh, watchlist_ws, study_ws, raw_ws, sheet_headers
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
                    if not watchlist_ws: 
                        sh, watchlist_ws, study_ws, raw_ws, sheet_headers = init_sheet_connection(secrets)
                    
                    # Simply log the raw message with pending status - let UI process it
                    raw_ws.append_row([timestamp_str, source_name, raw_text, "pending review"])
                            
                except Exception as log_err: 
                    print(f"⚠️ Message logging error: {log_err}")

            await client.run_until_disconnected()
        except Exception as loop_err:
            await asyncio.sleep(10)

if __name__ == '__main__':
    web_thread = threading.Thread(target=run_health_server, daemon=True)
    web_thread.start()
    asyncio.run(run_telegram_listener())
