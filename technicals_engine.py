import requests

def fetch_technicals(ticker_symbol):
    """
    Fetches real-time technical momentum indicators and calculates Moving Average Proximity.
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    if cleaned_ticker.endswith(".NS") or cleaned_ticker.endswith(".BO"):
        tv_ticker = cleaned_ticker[:-3]
    else:
        tv_ticker = cleaned_ticker

    payload = {
        "symbols": {"tickers": [f"NSE:{tv_ticker}"]},
        "columns": ["close", "EMA20", "EMA50", "EMA200", "RSI"]
    }

    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=5)
        if res.status_code == 200 and res.json().get("data"):
            d = res.json()["data"][0]["d"]
            close = d[0]
            ema20 = d[1]
            ema50 = d[2]
            ema200 = d[3]
            rsi = d[4]

            # Calculates percentage distance from the moving average
            def calc_prox(val):
                if val and close: 
                    return round(((close - val) / val) * 100, 2)
                return "-"

            return {
                "rsi": round(rsi, 2) if rsi else "-",
                "ema20_prox": calc_prox(ema20),
                "ema50_prox": calc_prox(ema50),
                "ema200_prox": calc_prox(ema200)
            }
    except Exception as e:
        print(f"TV Technical Engine Error: {e}")

    return {"rsi": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}
