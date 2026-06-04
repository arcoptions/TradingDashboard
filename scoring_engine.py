def generate_conviction_score(f_metrics, t_metrics, oi_buildup_lbl, trade_type="Equity"):
    """
    ARC Dual-Scoring Engine Matrix: Dynamically adapts evaluation math based on asset class.
    """
    score = 0
    flags = []

    def parse_val(v):
        if v is None or str(v).strip() in ["", "-", "None"]: return None
        try: return float(str(v).replace('%', '').replace('x', '').replace(',', '').strip())
        except: return None

    pe = parse_val(f_metrics.get("stock_pe"))
    spe = parse_val(f_metrics.get("sector_pe"))
    roe = parse_val(f_metrics.get("roe"))
    roce = parse_val(f_metrics.get("roce"))
    dte = parse_val(f_metrics.get("debt_to_equity"))

    rsi = parse_val(t_metrics.get("rsi"))
    ema20 = parse_val(t_metrics.get("ema20_prox"))
    ema200 = parse_val(t_metrics.get("ema200_prox"))
    vol_spike = parse_val(t_metrics.get("vol_spike"))

    is_option = str(trade_type).strip().lower() in ["option", "fno"]

    if is_option:
        # ─── OPTIONS SCORING (10% Fundamentals | 40% Technicals | 50% Derivatives) ───
        
        # 1. De-emphasized Fundamentals (10 Pts Max)
        if pe is not None and spe is not None and pe < spe: score += 5
        if dte is not None and dte <= 1.5: score += 5
        
        # 2. Aggressive Technical Momentum (40 Pts Max)
        if rsi is not None:
            if 50 <= rsi <= 70: 
                score += 20
                flags.append("✅ Options: Strong Momentum (RSI 50-70)")
            elif rsi > 70: 
                score += 10
                flags.append("⚠️ Options: Overbought (RSI > 70)")
            else:
                flags.append("🚨 Options: Weak Momentum (RSI < 50)")
                
        if ema20 is not None and ema20 > 0: 
            score += 10
            flags.append("✅ Options: Above 20 EMA")
        if vol_spike is not None and vol_spike > 120: 
            score += 10
            flags.append("✅ Options: High Volume Spike")

        # 3. Core Option Market Analytics (50 Pts Max)
        if oi_buildup_lbl:
            if "Long Buildup" in oi_buildup_lbl: 
                score += 50
                flags.append("🔥 Options: Heavy Long Buildup")
            elif "Short Covering" in oi_buildup_lbl: 
                score += 35
                flags.append("✅ Options: Short Covering Bounce")
            elif "Short Buildup" in oi_buildup_lbl: 
                score -= 25
                flags.append("🚨 Options: Short Sellers Active")
        else:
            score += 20
            
    else:
        # ─── STOCKS SCORING (40% Fundamentals | 60% Technicals) ───
        
        # 1. Valuation Profiles & Peer Scorecard (40 Pts Max)
        if pe is not None and spe is not None:
            if pe < spe: 
                score += 15
                flags.append("✅ Stock: Undervalued vs Sector")
            else: 
                score += 5
                flags.append("⚠️ Stock: Overvalued vs Sector")
        else: score += 10
            
        if roe is not None and roe >= 15: 
            score += 10
            flags.append("✅ Stock: Strong ROE (>15%)")
        if roce is not None and roce >= 15: 
            score += 10
            flags.append("✅ Stock: Strong ROCE (>15%)")
        if dte is not None and dte <= 1.0: 
            score += 5

        # 2. Core Trend & Accumulation Systems (60 Pts Max)
        if rsi is not None:
            if 45 <= rsi <= 65: 
                score += 25
                flags.append("✅ Stock: Optimal Accumulation RSI")
            elif rsi > 65: 
                score += 10
                flags.append("⚠️ Stock: Extended RSI")
                
        if ema20 is not None and ema20 > 0: 
            score += 15
            flags.append("✅ Stock: Holding 20 EMA")
        if ema200 is not None and ema200 > 0: 
            score += 10
            flags.append("✅ Stock: Long-Term Uptrend (Above 200 EMA)")
        if vol_spike is not None and vol_spike > 100:
            score += 10
            flags.append("✅ Stock: Inst. Volume Detected")

    score = max(0, min(score, 100))
    if score >= 70: verdict = "STRONG GO"
    elif score >= 45: verdict = "CAUTION"
    else: verdict = "NO-GO"

    return score, verdict, flags
