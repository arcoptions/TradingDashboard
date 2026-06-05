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

# Added new mappings for requested assets
ASSET_ALIASES = {
    "COALINDIA": ["COALINDIA", "COAL INDIA", "CIL"],
    "OIL": ["OIL", "OIL INDIA", "OILINDIA"],
    "RELIANCE": ["RELIANCE", "RIL", "RELIANCE INDUSTRIES"],
    "M&M": ["M&M", "M & M", "MAHINDRA & MAHINDRA", "MAHINDRA"],
    "TATAMOTORS": ["TATAMOTORS", "TATA MOTORS", "TATA MOTOR"],
    "TVSMOTOR": ["TVSMOTOR", "TVS MOTOR", "TVS"],
    "AXISBANK": ["AXISBANK", "AXIS BANK", "AXIS"],
    "TCS": ["TCS", "TATA CONSULTANCY SERVICES"],
    "HDFCBANK": ["HDFCBANK", "HDFC BANK", "HDFC"],
    "ICICIBANK": ["ICICIBANK", "ICICI BANK", "ICICI"],
    "INFY": ["INFY", "INFOSYS"],
    "SUNPHARMA": ["SUNPHARMA", "SUN PHARMA"],
    "TATASTEEL": ["TATASTEEL", "TATA STEEL"],
    "WIPRO": ["WIPRO"],
    "NTPC": ["NTPC"],
    "ITC": ["ITC"],
    "TATAELXSI": ["TATAELXSI", "TATA ELXSI"],
    "UNIVCABLE": ["UNIVCABLE", "UNIVERSAL CABLES", "UNIVERSAL CABLE"],
    "IDEA": ["IDEA", "VODAFONE IDEA", "VI"]
}

def extract_asset_from_text(text):
    """
    Robust NLP Token Analyzer with a sanitization layer.
    Strips out special clutter symbols, markdown syntax, and emojis before 
    running strict regular expression character boundaries.
    """
    if not text:
        return False
        
    # 1. Standardize text to uppercase
    text_upper = str(text).upper()
    
    # 2. Robust Sanitization: Replace noise symbols and punctuation with blank spaces
    # This turns "#UNIVCABLE" or "IDEA:" into " UNIVCABLE " and " IDEA "
    sanitized_text = re.sub(r'[^A-Z0-9\s&]', ' ', text_upper)
    
    # Compress internal whitespace down to single gaps
    sanitized_text = " " + " ".join(sanitized_text.split()) + " "
    
    # Phase 1: Scan master priority aliases dictionary
    for master_ticker, aliases in ASSET_ALIASES.items():
        for alias in aliases:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(alias.upper()) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, sanitized_text):
                return master_ticker
                
    # Phase 2: Structural Fallback Scanner for general constituents
    for index_asset in SECTOR_MAP.keys():
        spaced_variation = re.sub(r'([A-Z]+)(BANK|MOTORS|MOTOR|STEEL|PHARMA|IND|INDIA|ELXSI)', r'\1 \2', index_asset)
        
        for variant in [index_asset, spaced_variation]:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(variant) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, sanitized_text):
                return index_asset

    return False
