import re
import pandas as pd

def parse_telegram_tip(text):
    data = {"symbol": "", "trade_type": "Equity", "entry": "", "add_levels": "", "sl": "", "t1": "", "t2": ""}
    if not text: return data
    
    clean_text = " ".join([line.strip() for line in text.split('\n') if line.strip()])
    option_match = re.search(r'([A-Z\&]+)\s*(\d+)\s*(ce|pe|call|put)', clean_text, re.IGNORECASE)
    if option_match:
        opt_type = option_match.group(3).upper()
        if opt_type == 'CALL': opt_type = 'CE'
        if opt_type == 'PUT': opt_type = 'PE'
        data["symbol"] = f"{option_match.group(1).upper()} {option_match.group(2)} {opt_type}"
        data["trade_type"] = "Option"
    else:
        equity_match = re.search(r'\b([A-Z\&]+)\b', clean_text)
        if equity_match: data["symbol"] = equity_match.group(1).upper()
            
    range_match = re.search(r'range\s+([\d\.-]+)', clean_text, re.IGNORECASE)
    if range_match: 
        data["entry"] = range_match.group(1)
    else:
        cmp_match = re.search(r'cmp\s+([\d\.]+)', clean_text, re.IGNORECASE)
        if cmp_match: 
            data["entry"] = cmp_match.group(1)
        else:
            at_match = re.search(r'\bat\s+([\d\.-]+)', clean_text, re.IGNORECASE)
            if at_match: data["entry"] = at_match.group(1)
            
    sl_match = re.search(r'SL\s+(?:AT\s+)?([\d\.]+\s*(?:clsb)?)', clean_text, re.IGNORECASE)
    if sl_match: data["sl"] = sl_match.group(1)
        
    target_match = re.search(r'Target\s*([-:\s]+)?([\d\.\s\+-]+)', clean_text, re.IGNORECASE)
    if target_match:
        targets = re.findall(r'([\d\.]+)', target_match.group(2))
        if len(targets) > 0: data["t1"] = targets[0]
        if len(targets) > 1: data["t2"] = targets[1]
            
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
            if not digits:
                signals.append("-")
                continue
            trigger_price = float(digits[0])
            if live_price > trigger_price: signals.append("🟢 Above")
            elif live_price < trigger_price: signals.append("🔴 Below")
            else: signals.append("⚪ At Entry")
        except: signals.append("-")
    df['Vs Entry'] = signals
    return df
