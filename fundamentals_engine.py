import yfinance as yf
import pandas as pd

# --- SECTORAL PE REFERENCE REGISTRY ---
# Benchmarks typical NSE sector averages to identify valuation spreads
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
    Connects to Yahoo Finance to pull corporate balance sheets and valuation ratios.
    Automatically handles Indian equity extensions (.NS) programmatically.
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    
    # yfinance requires suffix '.NS' for National Stock Exchange of India entries
    if not cleaned_ticker.endswith(".NS") and not cleaned_ticker.endswith(".BO"):
        cleaned_ticker += ".NS"
        
    try:
        # Instantiate the tracker object
        stock = yf.Ticker(cleaned_ticker)
        info = stock.info
        
        # 1. Valuation Metrics Extraction
        stock_pe = info.get("trailingPE", None)
        forward_pe = info.get("forwardPE", None)
        sector_pe = INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0)
        
        # 2. Capital Efficiency & Margins
        roe = info.get("returnOnEquity", None)
        ebitda_margin = info.get("ebitdaMargins", None)
        pat_margin = info.get("profitMargins", None) # Profit After Tax margin
        
        # 3. Leverage Stress Indicators
        # yfinance returns debt-to-equity as a percentage format (e.g., 125.5 for 1.25x)
        debt_to_equity = info.get("debtToEquity", None)
        
        # 4. Quarterly Growth Parsing (YoY Engine)
        # Pulls the official historical earnings declaration registry
        financials = stock.quarterly_financials
        quarterly_perf = []
        
        if financials is not None and not financials.empty:
            # Safely grab the 2 most recent reporting periods
            target_columns = financials.columns[:2]
            for col in target_columns:
                q_name = col.strftime("%b-%Y") if hasattr(col, "strftime") else str(col)
                
                # Extract corporate lines safely from the index headers
                rev = financials.loc["Total Revenue"].iloc[financials.columns.get_loc(col)] if "Total Revenue" in financials.index else 0
                net_inc = financials.loc["Net Income"].iloc[financials.columns.get_loc(col)] if "Net Income" in financials.index else 0
                
                # Convert raw numeric fields into cleaner Crore representations
                rev_crores = round(rev / 10000000, 2) if rev else "-"
                net_crores = round(net_inc / 10000000, 2) if net_inc else "-"
                
                quarterly_perf.append({
                    "period": q_name,
                    "revenue": rev_crores,
                    "net_income": net_crores
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
        # Graceful fallback data dictionary if ticker connection timeouts drop active requests
        return {
            "stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0,
            "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
            "quarterly_perf": []
        }
