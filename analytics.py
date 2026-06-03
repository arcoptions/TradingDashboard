import re
import pandas as pd

def parse_telegram_tip(text):
    data = {"symbol": "", "trade_type": "Option", "entry": "", "add_levels": "", "sl": "", "t1": "", "t2": "", "tf": "", "rating": "", "raw_text": text}
    if not text: return data
    
    # Clean string processing
    clean_text = " ".join([line.strip() for line in text.split('\n') if line.strip()])
    
    # 1. Distinguish between Derivative Contracts vs Spot Equity
    option_match = re.search(r'([A-Z\&]+)\s*(\d+)\s*(ce|pe|call|put)', clean_text, re.IGNORECASE)
    if option_match:
        opt_type = option_match.group(3).upper()
        if opt_type == 'CALL': opt_type = 'CE'
        if opt_type == 'PUT': opt_type = 'PE'
        data["symbol"] = f"{option_match.group(1).upper()} {option_match.group(2)} {opt_type}"
        data["trade_type"] = "Option"
    else:
        # Equity Extraction Routing
        equity_match = re.search(r'(?:BUY|TRADEBUY)\s+([A-Z\&]+)', clean_text, re.IGNORECASE)
        if equity_match:
            data["symbol"] = equity_match.group(1).upper()
        else:
            fallback_ticker = re.search(r'\b([A-Z\&]{4,})\b', clean_text)
            if fallback_ticker: data["symbol"] = fallback_ticker.group(1).upper()
        data["trade_type"] = "Equity"
            
    # 2. Extract Entry Price Parameters
    range_match = re.search(r'range\s+([\d\.-]+)', clean_text, re.IGNORECASE)
    if range_match: 
        data["entry"] = range_match.group(1)
    else:
        cmp_match = re.search(r'(?:cmp|at)\s+([\d\.]+)', clean_text, re.IGNORECASE)
        if cmp_match: 
            data["entry"] = cmp_match.group(1)
        elif data["trade_type"] == "Equity" and data["symbol"]:
            # Direct numeric fallback for strings like: "SKMEGGPROD 226"
            num_after_sym = re.search(rf'{data["symbol"]}\s+([\d\.]+)', clean_text, re.IGNORECASE)
            if num_after_sym: data["entry"] = num_after_sym.group(1)
            
    # 3. Extract Risk Management Levels (SL)
    sl_match = re.search(r'SL\s+(?:AT\s+)?([\d\.]+\s*(?:clsb)?)', clean_text, re.IGNORECASE)
    if sl_match: 
        data["sl"] = sl_match.group(1)
    
    # 4. Extract Multi-Target Parameters
    target_match = re.search(r'Target\s*([-:\s]+)?([\d\.\s\+-]+)', clean_text, re.IGNORECASE)
    if target_match:
        targets = re.findall(r'([\d\.]+)', target_match.group(2))
        if len(targets) > 0: data["t1"] = targets[0]
        if len(targets) > 1: data["t2"] = targets[1]
        
    # 5. Extract Investment Horizons (Time Frame)
    tf_match = re.search(r'TF-\s*([^S]+?)(?=\s*SETUP RATING|$)', clean_text, re.IGNORECASE)
    if tf_match: 
        data["tf"] = tf_match.group(1).strip().strip('-').strip()

    # 6. Extract System Configurations (Setup Rating)
    rating_match = re.search(r'SETUP RATING-\s*([\d\.]+)', clean_text, re.IGNORECASE)
    if rating_match: 
        data["rating"] = rating_match.group(1).strip()
            
    return data

def compute_signal_indicators(df):
    if df.empty: return df
    signals, target_signals = [], []
    for idx, row in df.iterrows():
        try:
            live_val = str(row.get('Live Price', '')).strip()
            range_val = str(row.get('Entry CMP / Range', '')).strip()
            if live_val in ['', 'nan', 'None'] or range_val in ['', 'nan', 'None']:
                signals.append("-")
            else:
                live_price = float(live_val)
                digits = re.findall(r'[\d\.]+', range_val)
                if not digits: signals.append("-")
                else:
                    min_entry = min([float(d) for d in digits])
                    if live_price > min_entry: signals.append("🟢 Above")
                    elif live_price < min_entry: signals.append("🔴 Below")
                    else: signals.append("⚪ At Entry")
        except: signals.append("-")

        try:
            live_val = str(row.get('Live Price', '')).strip()
            t1_val = str(row.get('Target 1', '')).strip()
            if live_val in ['', 'nan', 'None'] or t1_val in ['', 'nan', 'None']:
                target_signals.append("-")
            else:
                live_price = float(live_val)
                t1_digits = re.findall(r'[\d\.]+', t1_val)
                if not t1_digits: target_signals.append("-")
                else:
                    t1_price = float(t1_digits[0])
                    if live_price >= t1_price: target_signals.append("🎯 Reached")
                    else: target_signals.append("⏳ Pending")
        except: target_signals.append("-")
            
    df['Vs Entry'] = signals
    df['Target Status'] = target_signals
    return df

def compute_scanner_signals(df):
    if df.empty: return df
    signals = []
    for idx, row in df.iterrows():
        try:
            live_val = str(row.get('Live Price', '')).strip()
            trigger_val = str(row.get('Trigger Price', '')).strip()
            if live_val in ['', 'nan', 'None'] or trigger_val in ['', 'nan', 'None']:
                signals.append("-")
                continue
            live_price = float(live_val)
            digits = re.findall(r'[\d\.]+', trigger_val)
            if not digits: signals.append("-")
            else:
                trigger_price = float(digits[0])
                if live_price > trigger_price: signals.append("🟢 Above")
                elif live_price < trigger_price: signals.append("🔴 Below")
                else: signals.append("⚪ At Entry")
        except: signals.append("-")
    df['Vs Entry'] = signals
    return df
