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
    Advanced NLP Token Analyzer.
    Isolates hashtags, prefixed announcements, and standard aliases while
    mitigating false positive corporate substring matches.
    """
    if not text:
        return "-"
        
    text_upper = str(text).upper().strip()
    
    # 1. Hashtag Extraction (e.g., #IDEA, #UNIVCABLE)
    hashtag_match = re.search(r'#([A-Z0-9_]+)', text_upper)
    if hashtag_match:
        return hashtag_match.group(1).replace('_', '')
        
    # 2. News Prefix Extraction (e.g., "TVS MOTOR : HLX...", "TATA STEEL ; Tata...")
    first_line = text_upper.split('\n')[0].strip()
    prefix_match = re.match(r'^([A-Z0-9\s&]+)\s*[:;]', first_line)
    if prefix_match:
        candidate = prefix_match.group(1).strip()
        if len(candidate.split()) <= 4 and candidate not in ["UPDATE", "NEWS", "ALERT"]:
            return candidate

    # 3. Buy/Sell Signal Extraction (e.g., "BUY VETO AT 140")
    signal_match = re.search(r'\b(?:BUY|SELL|ADD|SHORT)\s+([A-Z0-9&]+)\b', text_upper)
    if signal_match:
        return signal_match.group(1)
    
    # 4. Standard Dictionary & Alias Match with robust boundaries
    sanitized_text = re.sub(r'[^A-Z0-9\s&]', ' ', text_upper)
    sanitized_text = " " + " ".join(sanitized_text.split()) + " "
    
    for master_ticker, aliases in ASSET_ALIASES.items():
        for alias in aliases:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(alias.upper()) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, sanitized_text):
                # Mitigate false positives for shared corporate names
                if alias == "HDFC" and "HDFC SECURITIES" in sanitized_text: continue
                if alias == "HDFC" and "HDFC AMC" in sanitized_text: continue
                if alias == "ICICI" and "ICICI LOMBARD" in sanitized_text: continue
                if alias == "ICICI" and "ICICI PRUDENTIAL" in sanitized_text: continue
                return master_ticker

    # 5. Structural Fallback Scanner for general constituents
    for index_asset in SECTOR_MAP.keys():
        spaced_variation = re.sub(r'([A-Z]+)(BANK|MOTORS|MOTOR|STEEL|PHARMA|IND|INDIA|ELXSI)', r'\1 \2', index_asset)
        for variant in [index_asset, spaced_variation]:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(variant) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, sanitized_text):
                return index_asset

    return "-"
