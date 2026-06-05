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

# Explicitly mapping key token variants with spaces to resolve space-boundary drops
ASSET_ALIASES = {
    "COALINDIA": ["COALINDIA", "COAL INDIA", "CIL"],
    "OIL": ["OIL", "OIL INDIA", "OILINDIA"],
    "RELIANCE": ["RELIANCE", "RIL", "RELIANCE INDUSTRIES"],
    "M&M": ["M&M", "M & M", "MAHINDRA & MAHINDRA", "MAHINDRA"],
    "TATAMOTORS": ["TATAMOTORS", "TATA MOTORS", "TATA MOTOR"],
    "TVSMOTOR": ["TVSMOTOR", "TVS MOTOR", "TVS"],
    "AXISBANK": ["AXISBANK", "AXIS BANK", "AXIS"],
    "TCS": ["TCS", "TATA CONSULTANCY SERVICES", "TATA CONSULTANCY"],
    "HDFCBANK": ["HDFCBANK", "HDFC BANK", "HDFC"],
    "ICICIBANK": ["ICICIBANK", "ICICI BANK", "ICICI"],
    "INFY": ["INFY", "INFOSYS"],
    "SUNPHARMA": ["SUNPHARMA", "SUN PHARMA"],
    "TATASTEEL": ["TATASTEEL", "TATA STEEL"],
    "WIPRO": ["WIPRO"],
    "NTPC": ["NTPC"],
    "ITC": ["ITC"],
    "TATAELXSI": ["TATAELXSI", "TATA ELXSI"]
}

def extract_asset_from_text(text):
    """
    Advanced NLP Token Analyzer.
    Deploys non-capturing character lookarounds to find explicit asset names
    while systematically preventing short-token substring leakage.
    """
    if not text:
        return False
        
    text_upper = str(text).upper()
    
    # Phase 1: High-Priority Intent & Alias Extraction
    # Utilizes lookarounds instead of \b to match text bound to hashes (#OIL) or markdown (**OIL**)
    for master_ticker, aliases in ASSET_ALIASES.items():
        for alias in aliases:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(alias.upper()) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, text_upper):
                return master_ticker
                
    # Phase 2: Structural Fallback Scanner with Automated Spatial Segmentation
    for index_asset in SECTOR_MAP.keys():
        # Generates space segment variations on the fly (e.g., "TATASTEEL" -> "TATA STEEL")
        spaced_variation = re.sub(r'([A-Z]+)(BANK|MOTORS|MOTOR|STEEL|PHARMA|IND|INDIA|ELXSI)', r'\1 \2', index_asset)
        
        for variant in [index_asset, spaced_variation]:
            pattern = r'(?:^|[^A-Z0-9])' + re.escape(variant) + r'(?:$|[^A-Z0-9])'
            if re.search(pattern, text_upper):
                return index_asset

    return False
