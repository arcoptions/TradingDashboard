import yfinance as yf
import pandas as pd
import requests

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
    Connects to Yahoo Finance using an emulated browser session to bypass cloud provider IP blocks.
    Automatically formats Indian equities to their native exchange trackers (.NS).
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    
    if not cleaned_ticker.endswith(".NS") and not cleaned_ticker.endswith(".BO"):
        cleaned_ticker += ".NS"
        
    try:
        # Create an emulated desktop browser session to prevent Yahoo from dropping the request
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive'
        })
        
        stock = yf.Ticker(cleaned_ticker, session=session)
        info = stock.info
        
        # 1. Valuation Metrics Extraction
        stock_pe = info.get("trailingPE") or info.get("forwardPE")
        forward_pe = info.get("forwardPE")
        sector_pe = INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0)
        
        # 2. Capital Efficiency & Profitability Margins
        roe = info.get("returnOnEquity")
        ebitda_margin = info.get("ebitdaMargins")
        pat_margin = info.get("profitMargins")
        
        # 3. Leverage Ratios
        debt_to_equity = info.get("debtToEquity")
        
        # 4. Quarterly Balance Sheet Trends (YoY Matrix)
        financials = stock.quarterly_financials
        quarterly_perf = []
        
        if financials is not None and not financials.empty:
            target_columns = financials.columns[:2]
            for col in target_columns:
                q_name = col.strftime("%b-%Y") if hasattr(col, "strftime") else str(col)
                rev = financials.loc["Total Revenue"].iloc[financials.columns.get_loc(col)] if "Total Revenue" in financials.index else 0
                net_inc = financials.loc["Net Income"].iloc[financials.columns.get_loc(col)] if "Net Income" in financials.index else 0
                
                rev_crores = round(rev / 10000000, 2) if rev and not pd.isna(rev) else "-"
                net_crores = round(net_inc / 10000000, 2) if net_inc and not pd.isna(net_inc) else "-"
                
                quarterly_perf.append({
                    "Period": q_name,
                    "Revenue (Cr)": rev_crores,
                    "Net Income (Cr)": net_crores
                })
                
        return {
            "stock_pe": round(stock_pe, 2) if stock_pe else "-",
            "forward_pe": round(forward_pe, 2) if forward_pe else "-",
            "sector_pe": sector_pe,
            "roe": f"{round(roe * 100, 2)}%" if roe else "-",
            "debt_to_equity": round(debt_to_equity / 100, 2) if debt_to_equity else "-",
            "ebitda_margin": f"{round(ebitda_margin * 100, 2)}%" if ebitda_margin else "-",
            "pat_margin": f"{round(pat_margin * 100, 2)}%" if pat_margin else "-",
            "quarterly_perf": quarterly_perf
        }
        
    except Exception:
        return {
            "stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0,
            "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
            "quarterly_perf": []
        }
