import re

SECTOR_MAP = {
    "RELIANCE": "Oil & Gas", "TCS": "IT Services", "HDFCBANK": "Banking", "ICICIBANK": "Banking", 
    "INFY": "IT Services", "HCLTECH": "IT Services", "WIPRO": "IT Services", "TECHM": "IT Services", "TATAELXSI": "IT Services",
    "ITC": "FMCG", "HUL": "FMCG", "NESTLEIND": "FMCG", "VBL": "FMCG", "BRITANNIA": "FMCG",
    "TATAMOTORS": "Auto", "M&M": "Auto", "TVSMOTOR": "Auto", "MARUTI": "Auto", "BAJAJ-AUTO": "Auto", 
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma", "DRREDDY": "Pharma", "DIVISLAB": "Pharma",
    "JSWENERGY": "Power", "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power",
    "UPL": "Chemicals", "PIIND": "Chemicals", "COALINDIA": "Metals / Mining", "TATASTEEL": "Metals", "OIL": "Oil & Gas"
}

INDEX_CONSTITUENTS = {
    "Nifty 50": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "TCS", "LT", "BHARTIARTL", "SBIN", "BAJFINANCE", "AXISBANK", "HINDUNILVR", "HCLTECH", "MARUTI", "SUNPHARMA", "COALINDIA", "WIPRO", "TATASTEEL", "OIL"],
    "Nifty Next 50": ["TRENT", "BEL", "HAL", "CHOLAFIN", "INDIGO", "SIEMENS", "VBL", "BANKBARODA", "BHEL", "PIDILITIND", "PNB", "DLF", "GAIL", "ZOMATO", "IRFC"],
    "Finnifty": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "CHOLAFIN", "PFC", "RECLTD", "BAJAJFINSV", "MUTHOOTFIN", "SHRIRAMFIN"],
    "Nifty Bank": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB", "AUBANK", "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK"],
    "Nifty IT": ["INFY", "TCS", "HCLTECH", "WIPRO", "TECHM", "LTIM", "COFORGE", "PERSISTENT", "MPHASIS", "TATAELXSI"],
    "Nifty FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "GODREJCP", "DABUR", "VBL", "MARICO", "COLPAL"],
    "Nifty Auto": ["TATAMOTORS", "M_M", "MARUTI", "BAJAJ_AUTO", "EICHERMOT", "TVSMOTOR", "HEROMOTOCO", "BOSCHLTD", "TIINDIA", "MRF"],
    "Nifty Energy": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "COALINDIA", "TATAPOWER", "IOC", "BPCL", "GAIL", "ADANIPOWER"],
    "Nifty Metal": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "COALINDIA", "VEDL", "JINDALSTEL", "SAIL", "NMDC", "NATIONALUM"],
    "Nifty Pharma": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "AUROPHARMA", "MANKIND", "TORNTPHARM", "ZYDUSLIFE"],
    "Nifty Healthcare": ["SUNPHARMA", "APOLLOHOSP", "MAXHEALTH", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "FORTIS", "METROPOLIS"],
    "Nifty Realty": ["DLF", "MACROTECH", "GODREJPROP", "PRESTIGE", "OBEROIRLTY", "PHOENIXLTD", "BRIGADE", "SOBHA", "SUNTECK"]
}

ASSET_ALIASES = {
    "COALINDIA": ["COALINDIA", "COAL INDIA", "CIL"],
    "OIL": ["OIL", "OIL INDIA", "OILINDIA"],
    "RELIANCE": ["RELIANCE", "RIL", "RELIANCE INDUSTRIES"],
    "M&M": ["M&M", "M & M", "MAHINDRA & MAHINDRA", "MAHINDRA"],
    "TATAMOTORS": ["TATAMOTORS", "TATA MOTORS"],
    "TCS": ["TCS", "TATA CONSULTANCY SERVICES"],
    "HDFCBANK": ["HDFCBANK", "HDFC BANK"],
    "ICICIBANK": ["ICICIBANK", "ICICI BANK"],
    "INFY": ["INFY", "INFOSYS"],
    "SUNPHARMA": ["SUNPHARMA", "SUN PHARMA"],
    "TATASTEEL": ["TATASTEEL", "TATA STEEL"],
    "WIPRO": ["WIPRO"]
}

KNOWN_ASSETS = set()
for aliases in ASSET_ALIASES.values(): KNOWN_ASSETS.update([a.upper() for a in aliases])
for stocks in INDEX_CONSTITUENTS.values():
    KNOWN_ASSETS.update([s.replace('_', '').upper() for s in stocks])
    KNOWN_ASSETS.update([s.replace('_', ' ').upper() for s in stocks])

def extract_asset_from_text(text):
    """
    Scans raw text using word-boundaries to find a valid corporate asset.
    Returns the master symbol (e.g., 'COALINDIA') if found, otherwise False.
    """
    text_upper = text.upper()
    text_normalized = text_upper.replace(" ", "")
    
    # 1. Check strict Alias groupings
    for master_ticker, aliases in ASSET_ALIASES.items():
        for alias in aliases:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(alias.upper()) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, text_upper) or alias.replace(" ", "") in text_normalized:
                return master_ticker
                
    # 2. Check general sector mappings as a fallback
    for index_asset in SECTOR_MAP.keys():
        pattern = r'(?:^|[^A-Z0-9])' + re.escape(index_asset) + r'(?:$|[^A-Z0-9])'
        if re.search(pattern, text_upper) or index_asset in text_upper.split():
            return index_asset

    return False
