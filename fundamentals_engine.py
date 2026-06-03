import requests
import pandas as pd
import threading

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

class YahooEngine:
    """
    Singleton connection engine that steals and caches Yahoo Finance browser 
    authentication tokens (crumbs) to bypass cloud-IP blocking protocols.
    """
    _session = None
    _crumb = None
    _lock = threading.Lock()

    @classmethod
    def get_auth(cls):
        with cls._lock:
            if cls._session is None or cls._crumb is None:
                cls._session = requests.Session()
                # Camouflage the request as a standard Windows 10 Chrome desktop browser
                cls._session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                    'Accept': 'application/json, text/plain, */*',
                    'Accept-Language': 'en-US,en;q=0.9',
                })
                try:
                    # 1. Acquire cookies
                    cls._session.get('https://fc.yahoo.com', timeout=5)
                    # 2. Acquire authentication crumb
                    res = cls._session.get('https://query1.finance.yahoo.com/v1/test/getcrumb', timeout=5)
                    if res.status_code == 200:
                        cls._crumb = res.text.strip()
                except Exception:
                    pass
        return cls._session, cls._crumb

def fetch_company_fundamentals(ticker_symbol, sector_category="GENERAL / MIXED"):
    """
    Dual-engine scraper. Attempts deep financial extraction first. If blocked, 
    falls back to lightweight P/E extraction to prevent blank UI canvases.
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    if not cleaned_ticker.endswith(".NS") and not cleaned_ticker.endswith(".BO"):
        cleaned_ticker += ".NS"
        
    # Baseline empty payload
    payload = {
        "stock_pe": "-", "forward_pe": "-", "sector_pe": INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0),
        "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
        "quarterly_perf": []
    }
    
    session, crumb = YahooEngine.get_auth()
    
    # ─── PRIMARY ENGINE: DEEP BALANCE SHEET EXTRACTION ───
    try:
        url_deep = f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{cleaned_ticker}"
        params = {"modules": "summaryDetail,financialData,defaultKeyStatistics,incomeStatementHistoryQuarterly"}
        if crumb: 
            params["crumb"] = crumb
            
        res_deep = session.get(url_deep, params=params, timeout=8)
        
        if res_deep.status_code == 200:
            result = res_deep.json().get("quoteSummary", {}).get("result", [])
            if result:
                core = result[0]
                summary = core.get("summaryDetail", {})
                financials = core.get("financialData", {})
                
                # Valuation Multiples
                pe = summary.get("trailingPE", {}).get("raw")
                fpe = summary.get("forwardPE", {}).get("raw")
                if pe: payload["stock_pe"] = round(pe, 2)
                if fpe: payload["forward_pe"] = round(fpe, 2)
                
                # Capital Efficiency & Margins
                roe = financials.get("returnOnEquity", {}).get("raw")
                ebitda = financials.get("ebitdaMargins", {}).get("raw")
                pat = financials.get("profitMargins", {}).get("raw")
                if roe: payload["roe"] = f"{round(roe * 100, 2)}%"
                if ebitda: payload["ebitda_margin"] = f"{round(ebitda * 100, 2)}%"
                if pat: payload["pat_margin"] = f"{round(pat * 100, 2)}%"
                
                # Leverage Risk
                dte = financials.get("debtToEquity", {}).get("raw")
                if dte: payload["debt_to_equity"] = round(dte / 100, 2)
                
                # Quarterly Revenue Tracker
                q_hist = core.get("incomeStatementHistoryQuarterly", {}).get("incomeStatementHistory", [])
                for q in q_hist[:2]:
                    date_str = q.get("endDate", {}).get("fmt", "Unknown")
                    rev = q.get("totalRevenue", {}).get("raw", 0)
                    net = q.get("netIncome", {}).get("raw", 0)
                    payload["quarterly_perf"].append({
                        "Period": date_str,
                        "Revenue (Cr)": round(rev / 10000000, 2) if rev else "-",
                        "Net Income (Cr)": round(net / 10000000, 2) if net else "-"
                    })
                return payload 
    except Exception:
        pass 
        
    # ─── SECONDARY ENGINE: LIGHTWEIGHT QUOTE FALLBACK ───
    try:
        url_light = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={cleaned_ticker}"
        res_light = session.get(url_light, timeout=8)
        
        if res_light.status_code == 200:
            result = res_light.json().get("quoteResponse", {}).get("result", [])
            if result:
                data = result[0]
                pe = data.get("trailingPE")
                fpe = data.get("forwardPE")
                
                if pe: payload["stock_pe"] = round(pe, 2)
                if fpe: payload["forward_pe"] = round(fpe, 2)
                
                # Flag the user that deep fields were protected by the firewall
                payload["ebitda_margin"] = "Secured behind cloud firewall"
                payload["pat_margin"] = "Secured behind cloud firewall"
    except Exception:
        pass
        
    return payload
