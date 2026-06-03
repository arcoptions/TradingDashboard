import requests
import pandas as pd
import yfinance as yf

# --- SECTORAL PE REFERENCE REGISTRY ---
INDUSTRY_PE_MAP = {
    "CHEMICALS": 24.8, "OIL & GAS": 15.2, "IT SERVICES": 27.4, "BANKING": 16.1,
    "FMCG": 44.3, "AUTO": 22.9, "PHARMA": 31.2, "POWER": 19.5,
    "FINANCE": 18.4, "INFRASTRUCTURE": 21.0, "METALS": 14.3, "GENERAL / MIXED": 20.0
}

def fetch_company_fundamentals(ticker_symbol, sector_category="GENERAL / MIXED"):
    """
    HYBRID ENGINE: 
    1. TradingView API for 100% reliable core valuation ratios.
    2. Secure yfinance session for historical QoQ absolute earnings tables.
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    
    if cleaned_ticker.endswith(".NS") or cleaned_ticker.endswith(".BO"):
        tv_ticker = cleaned_ticker[:-3]
    else:
        tv_ticker = cleaned_ticker
        
    yf_ticker = f"{tv_ticker}.NS"

    # Baseline payload structure
    metrics = {
        "stock_pe": "-", "forward_pe": "-", "sector_pe": INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0),
        "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
        "quarterly_perf": []
    }

    # ─── PART 1: TRADINGVIEW (For Unblockable Core Ratios) ───
    tv_payload = {
        "symbols": {"tickers": [f"NSE:{tv_ticker}"]},
        "columns": [
            "price_earnings_ttm", "price_earnings_forward", "return_on_equity",
            "debt_to_equity", "operating_margin", "net_margin"
        ]
    }
    
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=tv_payload, timeout=5)
        if res.status_code == 200 and res.json().get("data"):
            d = res.json()["data"][0]["d"]
            metrics["stock_pe"] = round(d[0], 2) if d[0] is not None else "-"
            metrics["forward_pe"] = round(d[1], 2) if d[1] is not None else "-"
            metrics["roe"] = f"{round(d[2], 2)}%" if d[2] is not None else "-"
            metrics["debt_to_equity"] = round(d[3], 2) if d[3] is not None else "-"
            metrics["ebitda_margin"] = f"{round(d[4], 2)}%" if d[4] is not None else "-"
            metrics["pat_margin"] = f"{round(d[5], 2)}%" if d[5] is not None else "-"
    except Exception as e:
        print(f"TV Engine Error: {e}")

    # ─── PART 2: YFINANCE SECURE SESSION (For QoQ Earnings Comparison) ───
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36'
        })
        
        stock = yf.Ticker(yf_ticker, session=session)
        q_fin = stock.quarterly_financials
        
        if q_fin is not None and not q_fin.empty:
            # Slice the top 2 columns (Latest Quarter and Previous Quarter)
            target_cols = q_fin.columns[:2]
            
            for col in target_cols:
                q_name = col.strftime("%b %Y") if hasattr(col, "strftime") else str(col)
                rev = q_fin.loc["Total Revenue", col] if "Total Revenue" in q_fin.index else None
                net = q_fin.loc["Net Income", col] if "Net Income" in q_fin.index else None
                
                metrics["quarterly_perf"].append({
                    "Period": q_name,
                    "Revenue": f"₹{round(rev/10000000, 2)} Cr" if pd.notna(rev) else "-",
                    "Net Income": f"₹{round(net/10000000, 2)} Cr" if pd.notna(net) else "-"
                })
    except Exception as e:
        print(f"YF Table Error: {e}")
        
    return metrics
