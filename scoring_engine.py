def generate_conviction_score(f_metrics, t_metrics, oi_buildup_lbl, trade_type="Equity"):
    """
    ARC Dual-Scoring Engine Matrix: Dynamically adapts evaluation math based on asset class.
    Options prioritize near-term momentum, index trends, and option Greeks.
    Stocks prioritize fundamental margins, value ratios, capital efficiency, and structural trends.
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
    ema200 = parse_val(t_metrics.get("ema200_prox"))
    vol_spike = parse_val(t_metrics.get("vol_spike"))

    is_option = str(trade_type).strip().lower() in ["option", "fno"]

    if is_option:
        # ─── OPTIONS INTENSITY SCORING MATRIX (10% Fundamentals | 40% Technicals | 50% Derivatives) ───
        
        # 1. De-prioritized Fundamentals (10 Pts Max)
        if pe is not None and spe is not None and pe < spe: 
            score += 5
        if dte is not None and dte <= 1.0: 
            score += 5
        elif dte is not None and dte > 2.0:
            score -= 15
            flags.append("🚨 Options Risk: High Corporate Leverage on Underlying")

        # 2. Aggressive Technical Momentum (40 Pts Max)
        if rsi is not None:
            if 50 <= rsi <= 70: 
                score += 20
                flags.append("✅ Options: Strong Bullish RSI Momentum")
            elif rsi > 70: 
                score += 10
                flags.append("⚠️ Options: Technical RSI Overbought Zone")
            else:
                flags.append("🚨 Options: Bearish Momentum Floor")
                
        if ema20 is not None and ema20 > 0: 
            score += 10
            flags.append("✅ Options: Price Sustaining Above Velocity 20 EMA")
        if vol_spike is not None and vol_spike > 120: 
            score += 10
            flags.append("✅ Options: Heavy Institutional Footprint Volume Spike")

        # 3. Core Option Market Analytics (50 Pts Max)
        if oi_buildup_lbl:
            if "Long Buildup" in oi_buildup_lbl: 
                score += 50
                flags.append("🔥 Options: Aggressive Long Buildup Open Interest")
            elif "Short Covering" in oi_buildup_lbl: 
                score += 35
                flags.append("✅ Options: Bullish Short Covering Bounce")
            elif "Short Buildup" in oi_buildup_lbl: 
                score -= 25
                flags.append("🚨 Options: Dominant Short Sellers Accumulating")
        else:
            score += 20

    else:
        # ─── CASH EQUITIES SCORING MATRIX (30% Valuation | 30% Efficiency | 40% Structural Technicals) ───
        
        # 1. Valuation Profiles & Peer Scorecard (30 Pts Max)
        if pe is not None and spe is not None:
            if pe < spe: 
                score += 20
                flags.append("✅ Stock: Deep Value Relative to Sector P/E")
            else:
                score += 5
                flags.append("⚠️ Stock: Premium Valuation Multiples vs Peers")
        else:
            score += 10
            
        if dte is not None and dte <= 1.0: 
            score += 10
        elif dte is not None and dte > 1.5: 
            score -= 20
            flags.append("🚨 Stock Risk: Excessive Debt to Equity Ratio (>1.5x)")

        # 2. Long-Term Capital Efficiencies (30 Pts Max)
        if roe is not None and roe >= 15: 
            score += 15
            flags.append("✅ Stock: Compounding High Return on Equity (>15%)")
        if roce is not None and roce >= 15: 
            score += 15
            flags.append("✅ Stock: Exceptional Return on Capital Employed (>15%)")

        # 3. Core Trend & Accumulation Systems (40 Pts Max)
        if rsi is not None:
            if 45 <= rsi <= 65: 
                score += 15
                flags.append("✅ Stock: Optimal Accumulation Zone RSI")
            elif rsi > 65: 
                score += 5
                flags.append("⚠️ Stock: Momentum Extended Near Overbought Boundary")
                
        if ema20 is not None and ema20 > 0: 
            score += 10
            flags.append("✅ Stock: Pullback Holding Above Short-Term 20 EMA")
        if ema200 is not None and ema200 > 0: 
            score += 15
            flags.append("✅ Stock: High-Conviction Structural Uptrend Above 200 EMA")

    score = max(0, min(score, 100))
    
    if score >= 70: verdict = "STRONG GO"
    elif score >= 45: verdict = "CAUTION"
    else: verdict = "NO-GO"

    return score, verdict, flags
