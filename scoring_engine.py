def generate_conviction_score(f_metrics, t_metrics, oi_buildup_lbl):
    """
    The ARC Master Brain: Evaluates Fundamentals, Technicals, and Derivatives 
    to issue a mathematical Go / No-Go Verdict.
    """
    score = 0
    flags = []

    def parse_val(v):
        if v is None or str(v).strip() in ["", "-", "None"]:
            return None
        try:
            return float(str(v).replace('%', '').replace('x', '').replace(',', '').strip())
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
    if pe is not None and spe is not None:
        if pe < spe: 
            score += 20
            flags.append("✅ Undervalued vs Sector P/E")
        else: 
            score += 5
            flags.append("⚠️ Valuation exceeds Sector P/E")
    else:
        score += 10  # Neutral baseline if unavailable

    # 2. CAPITAL EFFICIENCY (20 Pts)
    if roe is not None and roe >= 15: 
        score += 10
        flags.append("✅ Strong ROE (>15%)")
    if roce is not None and roce >= 15: 
        score += 10
        flags.append("✅ Strong ROCE (>15%)")

    # 3. SOLVENCY & LEVERAGE (10 Pts)
    if dte is not None:
        if dte <= 1.0: 
            score += 10
        elif dte > 2.0: 
            score -= 10
            flags.append("🚨 High Corporate Leverage Warning")
    else:
        score += 5

    # 4. TECHNICAL MOMENTUM (30 Pts)
    if rsi is not None:
        if 45 <= rsi <= 70: 
            score += 15
            flags.append("✅ Bullish RSI Momentum")
        elif rsi > 70: 
            score += 5
            flags.append("⚠️ RSI Approaching Overbought")
        else: 
            flags.append("🚨 Bearish RSI Momentum")

    if ema20 is not None and ema20 > 0: 
        score += 10
        flags.append("✅ Price sustaining above 20-Day EMA")
        
    if vol_spike is not None and vol_spike > 100: 
        score += 5
        flags.append("✅ Heavy Institutional Volume Spike Detected")

    # 5. DERIVATIVES & SMART MONEY (20 Pts)
    if oi_buildup_lbl:
        if "Long Buildup" in oi_buildup_lbl: 
            score += 20
            flags.append("✅ Options: Massive Long Buildup")
        elif "Short Covering" in oi_buildup_lbl: 
            score += 15
            flags.append("✅ Options: Bullish Short Covering Bounce")
        elif "Short Buildup" in oi_buildup_lbl: 
            score -= 15
            flags.append("🚨 Options: Aggressive Short Sellers Active")

    score = max(0, min(score, 100))
    
    if score >= 70: 
        verdict = "STRONG GO"
    elif score >= 45: 
        verdict = "CAUTION"
    else: 
        verdict = "NO-GO"

    return score, verdict, flags
