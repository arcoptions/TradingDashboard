from core_engines.nlp_router import INDEX_CONSTITUENTS


INDUSTRY_TO_HEATMAP = {
    "Banking": "Nifty Bank",
    "Financial Services": "Finnifty",
    "IT Services": "Nifty IT",
    "FMCG": "Nifty FMCG",
    "Auto": "Nifty Auto",
    "Oil & Gas": "Nifty Energy",
    "Power": "Nifty Energy",
    "Pharma": "Nifty Pharma",
    "Healthcare": "Nifty Healthcare",
    "Metals": "Nifty Metal",
    "Metals / Mining": "Nifty Metal",
    "Realty": "Nifty Realty",
    "Chemicals": "Nifty 50",
    "General / Mixed": "Nifty 50",
}


def _parse_float(value):
    if value is None:
        return None
    text = str(value).replace("%", "").replace(",", "").strip()
    if text in ["", "-", "None", "nan"]:
        return None
    try:
        return float(text)
    except Exception:
        return None


def build_sector_heatmap_map(all_tv_data):
    if not all_tv_data:
        return {}

    sector_strength = {}
    for sector_name, stocks in INDEX_CONSTITUENTS.items():
        values = [
            all_tv_data[symbol]["change_pct"]
            for symbol in stocks
            if symbol in all_tv_data and all_tv_data[symbol].get("change_pct") is not None
        ]
        sector_strength[sector_name] = round(sum(values) / len(values), 2) if values else 0.0
    return sector_strength


def get_sector_strength(industry_name, sector_strength_map):
    heatmap_bucket = INDUSTRY_TO_HEATMAP.get(str(industry_name or "").strip(), "Nifty 50")
    return sector_strength_map.get(heatmap_bucket, 0.0), heatmap_bucket


def generate_trade_recommendation(score, decision, trade_type, oi_buildup_label, sector_strength, technicals):
    rsi = _parse_float(technicals.get("rsi"))
    ema20 = _parse_float(technicals.get("ema20_prox"))
    ema50 = _parse_float(technicals.get("ema50_prox"))

    score = int(score or 0)
    sector_strength = float(sector_strength or 0.0)
    oi_label = str(oi_buildup_label or "").upper()
    is_option = str(trade_type or "").strip().lower() in ["option", "fno"]

    bullish_oi = "LONG BUILDUP" in oi_label or "SHORT COVERING" in oi_label
    bearish_oi = "SHORT BUILDUP" in oi_label or "LONG UNWINDING" in oi_label
    bullish_trend = (ema20 is not None and ema20 > 0) and (ema50 is None or ema50 > 0)
    bearish_trend = (ema20 is not None and ema20 < 0) and (ema50 is None or ema50 < 0)
    positive_momentum = rsi is not None and rsi >= 55
    negative_momentum = rsi is not None and rsi <= 45
    sector_bullish = sector_strength >= 0.5
    sector_bearish = sector_strength <= -0.5

    if is_option:
        if score >= 65 and (bullish_oi or bullish_trend or sector_bullish):
            return "LONG CE"
        if score >= 65 and (bearish_oi or bearish_trend or sector_bearish):
            return "LONG PE"
        if score >= 50:
            return "WATCH OPTION"
        return "AVOID"

    if score >= 75 and bullish_trend and positive_momentum and sector_bullish:
        return "LONG"
    if score >= 60 and bearish_trend and negative_momentum and sector_bearish:
        return "SHORT"
    if decision in ["STRONG GO", "CAUTION"]:
        return "WATCH"
    return "AVOID"
