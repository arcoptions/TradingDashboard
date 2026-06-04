import asyncio
from telethon import TelegramClient, events
import gspread
from google.oauth2.service_account import Credentials
import datetime

# Internal Terminal Modules
import analytics
import broker_api as api
import database as db

# ─── TELEGRAM CREDS CONFIGURATION ───
# Obtain these from https://my.telegram.org
API_ID = 1234567          # Replace with your integer API ID
API_HASH = 'your_api_hash_string' 

# Mapped channel identifiers (Can be channel invite links, usernames, or unique numeric IDs)
TRACKED_CHANNELS = [
    'elephant_pro_signals', 
    'mr_chartist_alerts', 
    -1001234567890  # Numeric ID format example for private channels
]

def init_sheet_connection():
    """Initializes a clean standalone connection to the central tracker database."""
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"] if "gcp_service_account" in st.secrets else db.st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    sh = gc.open("Comprehensive Trading Tracker 2026")
    return sh.sheet1, sh.sheet1.row_values(1)

async def main():
    print("🚀 Initializing ARC Telegram Real-Time Ingestion Client...")
    worksheet, sheet_headers = init_sheet_connection()
    
    # Creates an automated user session layer
    client = TelegramClient('arc_terminal_session', API_ID, API_HASH)
    await client.start()
    print("✅ MTProto Channel Socket Stream Established.")

    @client.on(events.NewMessage(chats=TRACKED_CHANNELS))
    async def handler(event):
        raw_text = event.message.message
        if not raw_text:
            return
            
        # Extract sender group/channel entity name for attribution tracking
        chat_from = await event.get_chat()
        source_name = getattr(chat_from, 'title', getattr(chat_from, 'username', 'Telegram Channel'))
        
        print(f"📥 New Alert Ingested from [{source_name}]. Processing parsing engine...")
        
        try:
            # 1. Execute Regular Expression Token Extraction Matrix
            parsed_data = analytics.parse_telegram_tip(raw_text)
            
            # If the parser couldn't find a valid trading ticker, discard it to avoid cluttering the terminal
            if not parsed_data.get("symbol"):
                print("⚠️ Discarded: Message did not contain structure matching a clear asset symbol.")
                return
                
            # 2. Query Dhan Scrip Master to map exchange constraints, instrument definitions, and unique security IDs
            t_sym, t_sec, t_exch = api.resolve_instrument(parsed_data['symbol'])
            
            # 3. Construct a standard portfolio entry row perfectly matching the target database schema
            new_row = [""] * len(sheet_headers)
            
            def set_cell(col_name, val):
                if col_name in sheet_headers:
                    new_row[sheet_headers.index(col_name)] = str(val)
            
            # Population sequencing mapping directly to terminal workspace rules
            set_cell("Trade Date", datetime.date.today().strftime("%Y-%m-%d"))
            set_cell("Idea Source (Chartink/Telegram/X/Self)", source_name)
            set_cell("Symbol / Asset", t_sym)
            set_cell("Trade Type (Eq/Option)", parsed_data['trade_type'])
            set_cell("Exchange", t_exch)
            set_cell("Security ID", t_sec)
            set_cell("Status (Watch/Active/Closed)", "Watchlist") # All auto-ingested signals route directly to Watchlist
            set_cell("Entry CMP / Range", parsed_data['entry'])
            set_cell("Add-On / Dip Levels", parsed_data['add_levels'])
            set_cell("Stop Loss (SL)", parsed_data['sl'])
            set_cell("Target 1", parsed_data['t1'])
            set_cell("Target 2", parsed_data['t2'])
            set_cell("Time Frame", parsed_data['tf'])
            set_cell("Setup Rating", parsed_data['rating'])
            set_cell("Raw Tip Text", raw_text)
            
            # 4. Stream transaction straight into the Google Sheets database row index
            worksheet.append_row(new_row)
            print(f"🔥 Structured Tip Successfully Streamed to Tracker -> {t_sym} Watchlist Entry.")
            
        except Exception as err:
            print(f"❌ Ingestion Pipeline Failure: {err}")

    # Keep worker alive running indefinitely
    await client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
