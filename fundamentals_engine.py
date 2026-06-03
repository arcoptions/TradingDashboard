import requests

# --- SECTORAL PE REFERENCE REGISTRY ---
INDUSTRY_PE_MAP = {
    "CHEMICALS": 24.8, "OIL & GAS": 15.2, "IT SERVICES": 27.4, "BANKING": 16.1,
    "FMCG": 44.3, "AUTO": 22.9, "PHARMA": 31.2, "POWER": 19.5,
    "FINANCE": 18.4, "INFRASTRUCTURE": 21.0, "METALS": 14.3, "GENERAL / MIXED": 20.0
}

def fetch_company_fundamentals(ticker_symbol, sector_category="GENERAL / MIXED"):
    """
    Upgraded TradingView Engine: Now extracts ROCE and Institutional Ownership
    to complete the Tier 1 missing data matrix.
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    if cleaned_ticker.endswith(".NS") or cleaned_ticker.endswith(".BO"):
        tv_ticker = cleaned_ticker[:-3]
    else:
        tv_ticker = cleaned_ticker

    metrics = {
        "stock_pe": "-", "forward_pe": "-", "sector_pe": INDUSTRY_PE_MAP.get(str(sector_category).upper(), 20.0),
        "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-",
        "roce": "-", "inst_own": "-"
    }

    tv_payload = {
        "symbols": {"tickers": [f"NSE:{tv_ticker}"]},
        "columns": [
            "price_earnings_ttm", "price_earnings_forward", "return_on_equity",
            "debt_to_equity", "operating_margin", "net_margin", 
            "return_on_invested_capital", "institutions_ownership"
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
            metrics["roce"] = f"{round(d[6], 2)}%" if d[6] is not None else "-"
            metrics["inst_own"] = f"{round(d[7], 2)}%" if d[7] is not None else "-"
    except Exception as e:
        print(f"TV Fundamental Engine Error: {e}")
        
    return metrics
