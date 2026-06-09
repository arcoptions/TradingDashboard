def generate_conviction_score(f_metrics, t_metrics, oi_buildup_lbl, trade_type="Equity"):
    """
    ARC Dual-Scoring Engine Matrix: Dynamically adapts evaluation math based on asset class.
    Incorporates the Hybrid 100-Point System.
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
    ema50 = parse_val(t_metrics.get("ema50_prox"))
    ema200 = parse_val(t_metrics.get("ema200_prox"))
    vol_spike = parse_val(t_metrics.get("vol_spike"))

    is_option = str(trade_type).strip().lower() in ["option", "fno"]

    if is_option:
        # ─── OPTIONS SCORING (100 Pts Max) ───
        
        # 1. Underlying Technical Alignment (60 Pts)
        if ema20 is not None and ema50 is not None:
            if (ema20 > 0 and ema50 > 0) or (ema20 < 0 and ema50 < 0):
                score += 20
                flags.append("✅ Options: Aligned Underlying Trend (20 & 50 EMA)")
            else:
                flags.append("⚠️ Options: Conflicting Moving Averages")
        
        if rsi is not None:
            if rsi > 55 or rsi < 45:
                score += 20
                flags.append("✅ Options: Strong RSI Momentum")
            else:
                flags.append("⚠️ Options: Choppy/Flat RSI (45-55)")

        if vol_spike is not None and vol_spike > 150:
            score += 20
            flags.append("✅ Options: Underlying Volume Breakout (>1.5x)")

        # 2. Derivatives & OI Structure (40 Pts)
        if oi_buildup_lbl:
            lbl_upper = oi_buildup_lbl.upper()
            if "LONG BUILDUP" in lbl_upper or "SHORT BUILDUP" in lbl_upper:
                score += 40
                flags.append(f"🔥 Options: Strong Directional OI ({oi_buildup_lbl})")
            elif "SHORT COVERING" in lbl_upper or "LONG UNWINDING" in lbl_upper:
                score += 20
                flags.append(f"✅ Options: Reversal OI ({oi_buildup_lbl})")
        else:
            score += 10 # Baseline if missing

        # VETO Checks explicitly surfaced to UI
        flags.append("🚨 [VETO]: Max Premium Risk <= 2%?")
        flags.append("🚨 [VETO]: Strict Stop Loss Defined?")
        flags.append("🚨 [VETO]: F&O Ban List / Liquidity Check?")

    else:
        # ─── EQUITY SCORING (100 Pts Max) ───
        
        # 1. Trend & Structure (45 Pts)
        if ema200 is not None and ema200 > 0:
            score += 15
            flags.append("✅ Stock: Long-Term Uptrend (>200 EMA)")
        
        if ema50 is not None and ema50 > 0:
            score += 15
            flags.append("✅ Stock: Medium-Term Uptrend (>50 EMA)")
            
        if ema20 is not None and ema20 > 0:
            score += 15
            flags.append("✅ Stock: Short-Term Uptrend (>20 EMA)")
            
        if ema20 is not None and ema50 is not None and ema50 > ema20 > 0:
            flags.append("🔥 Stock: Perfect EMA Stack Alignment")

        # 2. Volume & Momentum (25 Pts)
        if vol_spike is not None and vol_spike > 150:
            score += 15
            flags.append("✅ Stock: Volume Breakout (>1.5x)")
            
        if rsi is not None:
            if 50 <= rsi <= 75:
                score += 10
                flags.append("✅ Stock: Optimal Momentum (RSI 50-75)")
            elif rsi > 75:
                flags.append("⚠️ Stock: Overbought (RSI > 75)")

        # 3. Fundamentals (30 Pts)
        if pe is not None and spe is not None:
            if pe < spe:
                score += 10
                flags.append("✅ Stock: Undervalued vs Sector")
        elif pe is not None and pe < 30:
            score += 10
            
        if (roe is not None and roe >= 15) or (roce is not None and roce >= 15):
            score += 10
            flags.append("✅ Stock: Strong Profitability (ROE/ROCE > 15%)")
            
        if dte is not None and dte <= 1.0:
            score += 10
            flags.append("✅ Stock: Safe Leverage (D/E <= 1.0)")

        # VETO Checks explicitly surfaced to UI
        flags.append("🚨 [VETO]: Risk:Reward >= 1:2?")
        flags.append("🚨 [VETO]: Is Event Risk / Earnings Clear?")

    # Enforce strict bounds
    score = max(0, min(score, 100))
    
    # Verdict Thresholds
    if score >= 75:
        verdict = "STRONG GO"
    elif score >= 55:
        verdict = "CAUTION"
    elif score >= 35:
        verdict = "LOW CONVICTION"
    else:
        verdict = "NO-GO"

    return score, verdict, flags
