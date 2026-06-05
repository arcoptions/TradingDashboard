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

FNO_SYMBOLS = {
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT", "ADANIPORTS", "ALKEM", "AMBUJACEM", 
    "APOLLOHOSP", "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATUL", "AUBANK", "AUROPHARMA", "AXISBANK", 
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BALRAMCHIN", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BEL", "BERGEPAINT", 
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BOSCHLTD", "BPCL", "BRITANNIA", "BSOFT", "CANBK", "CANFINHOME", 
    "CHAMBLFERT", "CHOLAFIN", "CIPLA", "COALINDIA", "COFORGE", "COLPAL", "CONCOR", "COROMANDEL", "CROMPTON", "CUB", 
    "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR", "DIVISLAB", "DIXON", "DLF", "DRREDDY", "EICHERMOT", "ESCORTS", 
    "EXIDEIND", "FEDERALBNK", "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP", "GODREJPROP", "GRANULES", "GRASIM", 
    "GUJGASLTD", "HAL", "HAVELLS", "HCLTECH", "HDFCAMC", "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", 
    "HINDPETRO", "HINDUNILVR", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA", "IDFC", "IDFCFIRSTB", "IEX", "IGL", 
    "INDHOTEL", "INDIACEM", "INDIAMART", "INDIGO", "INDUSINDBK", "INDUSTOWER", "INFY", "INTELLECT", "IOC", "IPCALAB", 
    "IRCTC", "ITC", "JINDALSTEL", "JKCEMENT", "JSWSTEEL", "JUBLFOOD", "KOTAKBANK", "L&TFH", "LALPATHLAB", "LAURUSLABS", 
    "LICHSGFIN", "LT", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN", "MANAPPURAM", "MARICO", "MARUTI", "MCDOWELL-N", "MCX", 
    "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS", "MRF", "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR", 
    "NESTLEIND", "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "ONGC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET", "PFC", 
    "PIDILITIND", "PIIND", "PNB", "POLYCAB", "POWERGRID", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "RELIANCE", 
    "SAIL", "SBICARD", "SBILIFE", "SBIN", "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SRF", "SUNPHARMA", "SUNTV", "SYNGENE", 
    "TATACHEM", "TATACOMM", "TATACONSUM", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM", "TITAN", "TORNTPHARM", 
    "TRENT", "TVSMOTOR", "UBL", "ULTRACEMCO", "UPL", "VEDL", "VOLTAS", "WIPRO", "ZEEL", "ZYDUSLIFE", "NIFTY", "BANKNIFTY", "FINNIFTY"
}

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
    if not text: return "-"
    text_upper = str(text).upper().strip()
    
    hashtag_match = re.search(r'#([A-Z0-9_]+)', text_upper)
    if hashtag_match: return hashtag_match.group(1).replace('_', '')
        
    first_line = text_upper.split('\n')[0].strip()
    prefix_match = re.match(r'^([A-Z0-9\s&]+)\s*[:;]', first_line)
    if prefix_match:
        candidate = prefix_match.group(1).strip()
        if len(candidate.split()) <= 4 and candidate not in ["UPDATE", "NEWS", "ALERT"]:
            return candidate

    IGNORE_LIST = ["MORE", "HTTPS", "HTTP", "BLOCK", "CALL", "PUT", "CE", "PE", "OPTION", "THE", "A", "AN"]
    signal_match = re.search(r'\b(?:BUY|SELL|ADD|SHORT)\s+([A-Z0-9&]+)\b', text_upper)
    if signal_match: 
        candidate = signal_match.group(1)
        if candidate not in IGNORE_LIST: return candidate
    
    sanitized_text = re.sub(r'[^A-Z0-9\s&]', ' ', text_upper)
    sanitized_text = " " + " ".join(sanitized_text.split()) + " "
    
    for master_ticker, aliases in ASSET_ALIASES.items():
        for alias in aliases:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(alias.upper()) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, sanitized_text):
                if alias == "HDFC" and ("HDFC SECURITIES" in sanitized_text or "HDFC AMC" in sanitized_text): continue
                if alias == "ICICI" and ("ICICI LOMBARD" in sanitized_text or "ICICI PRUDENTIAL" in sanitized_text): continue
                return master_ticker

    for index_asset in SECTOR_MAP.keys():
        spaced_variation = re.sub(r'([A-Z]+)(BANK|MOTORS|MOTOR|STEEL|PHARMA|IND|INDIA|ELXSI)', r'\1 \2', index_asset)
        for variant in [index_asset, spaced_variation]:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(variant) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, sanitized_text): return index_asset

    return "-"

def parse_trade_metrics(text):
    text = str(text).upper()
    metrics = {"strike": "", "option_type": "", "entry": "", "sl": "", "target_1": "", "target_2": ""}
    
    opt_match = re.search(r'(\d{2,5})\s*(CE|PE|CALL|PUT)', text)
    if opt_match:
        metrics["strike"] = opt_match.group(1)
        metrics["option_type"] = "CE" if "CE" in opt_match.group(2) or "CALL" in opt_match.group(2) else "PE"
    else:
        opt_match_rev = re.search(r'(CE|PE|CALL|PUT)\s*(\d{2,5})', text)
        if opt_match_rev:
            metrics["option_type"] = "CE" if "CE" in opt_match_rev.group(1) or "CALL" in opt_match_rev.group(1) else "PE"
            metrics["strike"] = opt_match_rev.group(2)
            
    entry_match = re.search(r'(?:CMP|AT|@|GIVEN AT)\s*([\d\.]+)(?:\s*-\s*([\d\.]+))?', text)
    if entry_match: metrics["entry"] = f"{entry_match.group(1)}-{entry_match.group(2)}" if entry_match.group(2) else entry_match.group(1)
        
    sl_match = re.search(r'SL\s*(?:AT\s*)?([\d\.]+)', text)
    if sl_match: metrics["sl"] = sl_match.group(1)
        
    tgt_match = re.search(r'TARGET(?:S)?\s*([\d\.]+)(?:\s*[-/]\s*([\d\.]+))?', text)
    if tgt_match:
        metrics["target_1"] = tgt_match.group(1)
        if tgt_match.group(2): metrics["target_2"] = tgt_match.group(2)
        
    return metrics
