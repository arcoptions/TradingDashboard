import requests

def fetch_technicals(ticker_symbol):
    """
    Fetches Technical Proximities and the new Volume Spike % metric 
    (Proxy for Institutional Delivery Volume).
    """
    cleaned_ticker = str(ticker_symbol).strip().upper()
    if cleaned_ticker.endswith(".NS") or cleaned_ticker.endswith(".BO"):
        tv_ticker = cleaned_ticker[:-3]
    else:
        tv_ticker = cleaned_ticker

    payload = {
        "symbols": {"tickers": [f"NSE:{tv_ticker}"]},
        "columns": ["close", "EMA20", "EMA50", "EMA200", "RSI", "volume", "average_volume_10d"]
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
            vol = d[5]
            avg_vol = d[6]

            def calc_prox(val):
                if val and close: 
                    return round(((close - val) / val) * 100, 2)
                return "-"

            vol_spike = "-"
            if vol and avg_vol and avg_vol > 0:
                vol_spike = f"{round((vol / avg_vol) * 100, 2)}%"

            return {
                "rsi": round(rsi, 2) if rsi else "-",
                "ema20_prox": calc_prox(ema20),
                "ema50_prox": calc_prox(ema50),
                "ema200_prox": calc_prox(ema200),
                "vol_spike": vol_spike
            }
    except Exception as e:
        print(f"TV Technical Engine Error: {e}")

    return {"rsi": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-", "vol_spike": "-"}
