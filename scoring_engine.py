def generate_conviction_score(f_metrics, t_metrics, oi_buildup_lbl):
    """
    The ARC Master Brain: Evaluates Fundamentals, Technicals, and Derivatives 
    to issue a mathematical Go / No-Go Verdict.
    """
    score = 0
    max_score = 100
    flags = []

    # Utility to safely strip strings for mathematical comparison
    def parse_val(v):
        try:
            return float(str(v).replace('%', '').replace('x', '').replace(',', ''))
        except: 
            return None

    pe = parse_val(f_metrics.get("stock_pe"))
    spe = parse_val(f_metrics.get("sector_pe"))
    roe = parse_val(f_metrics.get("roe"))
    roce = parse_val(f_metrics.get("roce"))
    dte = parse_val(f_metrics.get("debt_to_equity"))

    rsi = parse_val(t_metrics.get("rsi"))
    ema20 = parse_val(t_metrics.get("ema20_prox"))
    vol_spike = parse_val(t_metrics.get("vol_spike"))

    # 1. VALUATION METRICS (20 Pts)
    if pe and spe:
        if pe < spe: 
            score += 20
            flags.append("✅ Undervalued vs Sector P/E")
        else: 
            score += 5
            flags.append("⚠️ Valuation exceeds Sector P/E")

    # 2. CAPITAL EFFICIENCY (20 Pts)
    if roe and roe >= 15: 
        score += 10
        flags.append("✅ Strong ROE (>15%)")
    if roce and roce >= 15: 
        score += 10
        flags.append("✅ Strong ROCE (>15%)")

    # 3. SOLVENCY & LEVERAGE (10 Pts)
    if dte is not None:
        if dte <= 1.0: 
            score += 10
        elif dte > 2.0: 
            score -= 10
            flags.append("🚨 High Corporate Leverage Warning")

    # 4. TECHNICAL MOMENTUM (30 Pts)
    if rsi:
        if 45 <= rsi <= 70: 
            score += 10
            flags.append("✅ Bullish RSI Momentum")
        elif rsi > 70: 
            score += 5
            flags.append("⚠️ RSI Approaching Overbought")
        else: 
            flags.append("🚨 Bearish RSI Momentum")

    if ema20 and ema20 > 0: 
        score += 10
        flags.append("✅ Price sustaining above 20-Day EMA")
        
    if vol_spike and vol_spike > 100: 
        score += 10
        flags.append("✅ Heavy Institutional Volume Spike Detected")

    # 5. DERIVATIVES & SMART MONEY (20 Pts)
    if "Long Buildup" in oi_buildup_lbl: 
        score += 20
        flags.append("✅ Options: Massive Long Buildup")
    elif "Short Covering" in oi_buildup_lbl: 
        score += 15
        flags.append("✅ Options: Bullish Short Covering Bounce")
    elif "Short Buildup" in oi_buildup_lbl: 
        score -= 15
        flags.append("🚨 Options: Aggressive Short Sellers Active")

    # Format the Output Verdict
    score = max(0, min(score, 100)) # Clamp bounds
    
    if score >= 75: 
        verdict, color = "🟢 STRONG GO", "#089981"
    elif score >= 50: 
        verdict, color = "🟡 CAUTION / HOLD", "#D1A553"
    else: 
        verdict, color = "🔴 NO-GO", "#F23645"

    return score, verdict, color, flags
