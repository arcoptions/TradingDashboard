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
    Direct API Interceptor: Bypasses the fragile yfinance library to hit Yahoo's raw 
    backend JSON endpoints directly. This prevents Streamlit Cloud IP blocking.
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    
    # Format for Indian Equities
    if not cleaned_ticker.endswith(".NS") and not cleaned_ticker.endswith(".BO"):
        cleaned_ticker += ".NS"
        
    try:
        # Hitting the raw 'query2' backend endpoint directly
        url = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{cleaned_ticker}?modules=summaryDetail,financialData,defaultKeyStatistics,incomeStatementHistoryQuarterly"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f"API Blocked or Unavailable: Status {response.status_code}")
            
        data = response.json()
        result = data.get("quoteSummary", {}).get("result", [])
        
        if not result:
            raise Exception("Ticker data not found in Yahoo backend.")
            
        core_data = result[0]
        summary = core_data.get("summaryDetail", {})
        financials = core_data.get("financialData", {})
        
        # 1. Valuation Metrics Extraction
        stock_pe = summary.get("trailingPE", {}).get("raw")
        forward_pe = summary.get("forwardPE", {}).get("raw")
        sector_pe = INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0)
        
        # 2. Capital Efficiency & Profitability Margins
        roe = financials.get("returnOnEquity", {}).get("raw")
        ebitda_margin = financials.get("ebitdaMargins", {}).get("raw")
        pat_margin = financials.get("profitMargins", {}).get("raw")
        
        # 3. Leverage Ratios (Raw returns as percentage e.g., 125.5 for 1.25x)
        debt_to_equity = financials.get("debtToEquity", {}).get("raw")
        
        # 4. Quarterly Balance Sheet Trends (YoY Matrix)
        quarterly_perf = []
        income_stmt = core_data.get("incomeStatementHistoryQuarterly", {}).get("incomeStatementHistory", [])
        
        # Safely grab the 2 most recent reporting periods
        for q in income_stmt[:2]:
            date_str = q.get("endDate", {}).get("fmt", "Unknown")
            rev = q.get("totalRevenue", {}).get("raw", 0)
            net_inc = q.get("netIncome", {}).get("raw", 0)
            
            # Convert raw numeric fields into cleaner Crore representations
            rev_crores = round(rev / 10000000, 2) if rev else "-"
            net_crores = round(net_inc / 10000000, 2) if net_inc else "-"
            
            quarterly_perf.append({
                "Period": date_str,
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
        
    except Exception as e:
        # Graceful fallback data dictionary if the network request drops
        print(f"Fundamental Engine Override: {e}")
        return {
            "stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0,
            "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
            "quarterly_perf": []
        }
