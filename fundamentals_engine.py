import requests
import pandas as pd

# --- SECTORAL PE REFERENCE REGISTRY ---
INDUSTRY_PE_MAP = {
    "CHEMICALS": 24.8,
    "OIL & GAS": 15.2,
    "IT SERVICES": 27.4,
    "BANKING": 16.1,
    "FMCG": 44.3,
    "AUTO": 22.9,
    "PHARMA": 31.2,
    "POWER": 19.5,
    "FINANCE": 18.4,
    "INFRASTRUCTURE": 21.0,
    "METALS": 14.3,
    "GENERAL / MIXED": 20.0
}

def fetch_company_fundamentals(ticker_symbol, sector_category="GENERAL / MIXED"):
    """
    ULTIMATE CLOUD BYPASS: Uses TradingView's institutional scanner endpoint.
    This public API provides exact data and NEVER blocks cloud IPs (like Streamlit or AWS).
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    
    # Strip suffixes if they exist from older Yahoo logic
    if cleaned_ticker.endswith(".NS") or cleaned_ticker.endswith(".BO"):
        cleaned_ticker = cleaned_ticker[:-3]
        
    tv_ticker = f"NSE:{cleaned_ticker}"
    
    # TradingView Scanner Payload Map
    columns = [
        "price_earnings_ttm",        # 0: Stock P/E
        "price_earnings_forward",    # 1: Forward P/E
        "return_on_equity",          # 2: ROE
        "debt_to_equity",            # 3: Debt to Equity
        "operating_margin",          # 4: Proxy for EBITDA Margin
        "net_margin",                # 5: PAT Margin
        "total_revenue_fq",          # 6: Latest Quarter Revenue
        "net_income_fq"              # 7: Latest Quarter Net Income
    ]
    
    payload = {
        "symbols": {"tickers": [tv_ticker]},
        "columns": columns
    }
    
    try:
        # Hit the TradingView headless scanner (Ultra-fast, no cookies required)
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=8)
        
        if res.status_code == 200:
            data = res.json()
            if data.get("data"):
                # Extract the data array
                d = data["data"][0]["d"]
                
                pe = d[0]
                fpe = d[1]
                roe = d[2]
                dte = d[3]
                ebitda = d[4]
                pat = d[5]
                rev = d[6]
                net = d[7]
                
                sector_pe = INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0)
                
                q_perf = []
                if rev is not None and net is not None:
                    q_perf.append({
                        "Period": "Latest Qtr",
                        "Revenue (Cr)": round(rev / 10000000, 2),
                        "Net Income (Cr)": round(net / 10000000, 2)
                    })
                
                return {
                    "stock_pe": round(pe, 2) if pe is not None else "-",
                    "forward_pe": round(fpe, 2) if fpe is not None else "-",
                    "sector_pe": sector_pe,
                    "roe": f"{round(roe, 2)}%" if roe is not None else "-",
                    "debt_to_equity": round(dte, 2) if dte is not None else "-",
                    "ebitda_margin": f"{round(ebitda, 2)}%" if ebitda is not None else "-",
                    "pat_margin": f"{round(pat, 2)}%" if pat is not None else "-",
                    "quarterly_perf": q_perf
                }
    except Exception as e:
        print(f"TradingView Engine Error: {e}")
        
    # Absolute Fallback if network drops
    return {
        "stock_pe": "-", "forward_pe": "-", "sector_pe": INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0),
        "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
        "quarterly_perf": []
    }
