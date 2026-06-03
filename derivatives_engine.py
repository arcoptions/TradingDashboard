import math
from datetime import datetime, date, timedelta
import calendar

# =====================================================================
# CORE MATHEMATICAL FUNCTIONS (No external libraries needed)
# =====================================================================

def norm_cdf(x):
    """
    Calculates the Cumulative Distribution Function (CDF) for a standard normal distribution.
    This is required for the Black-Scholes formula to determine probability.
    Using math.erf (Error Function) keeps this lightweight without needing scipy.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def norm_pdf(x):
    """
    Calculates the Probability Density Function (PDF).
    Used primarily to calculate Theta (time decay) and Vega (volatility sensitivity).
    """
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x**2)

# =====================================================================
# BLACK-SCHOLES PRICING & GREEKS ENGINE
# =====================================================================

def calculate_greeks(S, K, T, r, sigma, option_type="CE"):
    """
    Calculates Delta and Theta using the Black-Scholes model.
    S: Spot Price (Current price of the stock)
    K: Strike Price of the option
    T: Time to Expiry (in years)
    r: Risk-free rate (e.g., 0.07 for 7%)
    sigma: Implied Volatility (as a decimal, e.g., 0.32 for 32%)
    """
    # If the option has expired (T <= 0), Greeks lock into their terminal states
    if T <= 0:
        return {"delta": 1.0 if option_type == "CE" else -1.0, "theta": 0.0, "iv": sigma}
    
    # Prevent division by zero if volatility drops completely
    if sigma <= 0.001:
        sigma = 0.001

    # d1 and d2 are the core intermediate variables in Black-Scholes
    d1 = (math.log(S / K) + (r + (sigma**2) / 2.0) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if option_type == "CE": # Call Option Greeks
        delta = norm_cdf(d1)
        # Annualized Theta Equation for Calls
        theta_annual = (- (S * norm_pdf(d1) * sigma) / (2.0 * math.sqrt(T)) 
                        - r * K * math.exp(-r * T) * norm_cdf(d2))
    else: # Put Option Greeks
        delta = norm_cdf(d1) - 1.0
        # Annualized Theta Equation for Puts
        theta_annual = (- (S * norm_pdf(d1) * sigma) / (2.0 * math.sqrt(T)) 
                        + r * K * math.exp(-r * T) * norm_cdf(-d2))

    # We divide by 365 to see how many exactly Rupees the premium loses per day
    theta_daily = theta_annual / 365.0
    return {"delta": round(delta, 3), "theta": round(theta_daily, 2)}

def implied_volatility(target_price, S, K, T, r, option_type="CE"):
    """
    Backs out Implied Volatility (IV) using Newton-Raphson numerical root-finding.
    Since we know the Live Option Price (target_price), we reverse-engineer the math
    to find out what Volatility the market is pricing in.
    """
    if T <= 0 or target_price <= 0:
        return 0.0
    
    # Initial estimate using Brenn-Subrahmanyam approximation
    sigma = math.sqrt(2.0 * math.pi / T) * (target_price / S)
    if sigma <= 0:
        sigma = 0.30 # Default to 30% IV if math breaks

    # Iterative refinement loop (Maximum 100 tries to find the exact IV)
    for i in range(100):
        d1 = (math.log(S / K) + (r + (sigma**2) / 2.0) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        
        # Calculate theoretical price based on current sigma guess
        if option_type == "CE":
            price = S * norm_cdf(d1) - K * math.exp(-r * T) * norm_cdf(d2)
        else:
            price = K * math.exp(-r * T) * norm_cdf(-d2) - S * norm_cdf(-d1)
            
        # Vega is the derivative of price with respect to volatility
        vega = S * math.sqrt(T) * norm_pdf(d1)
        
        if vega < 1e-6: # Stop if Vega is too small (prevents math errors)
            break
            
        diff = price - target_price
        if abs(diff) < 1e-4: # If our calculated price matches live price, we found the IV!
            return round(sigma * 100, 2)
            
        # Adjust sigma guess based on the error margin
        sigma = sigma - diff / vega
        if sigma <= 0:
            sigma = 0.001
            
    return round(sigma * 100, 2)

# =====================================================================
# CONTRACT PARSING & EXPIRY LOGIC (LAST TUESDAY)
# =====================================================================

def get_last_tuesday(year, month):
    """
    Finds the exact date of the Last Tuesday of a given month and year.
    """
    # Find the last day of the month
    last_day = calendar.monthrange(year, month)[1]
    last_date = date(year, month, last_day)
    
    # weekday() returns 0 for Monday, 1 for Tuesday... 6 for Sunday
    # We find how many days to subtract to reach the most recent Tuesday (1)
    offset = (last_date.weekday() - 1) % 7
    last_tuesday = last_date - timedelta(days=offset)
    
    return last_tuesday

def parse_option_contract(contract_string):
    """
    Deconstructs strings like 'UPL-Jun2026-660-CE' into variables.
    """
    try:
        parts = str(contract_string).split('-')
        if len(parts) < 4:
            return None
        
        ticker = parts[0].strip().upper()
        expiry_str = parts[1].strip() # e.g., 'Jun2026'
        strike = float(parts[2].strip())
        opt_type = parts[3].strip().upper() # CE or PE
        
        # Map month abbreviations to integer values
        months_map = {"JAN":1, "FEB":2, "MAR":3, "APR":4, "MAY":5, "JUN":6, 
                      "JUL":7, "AUG":8, "SEP":9, "OCT":10, "NOV":11, "DEC":12}
        
        month_name = "".join([c for c in expiry_str if c.isalpha()]).upper()[:3]
        year_digits = "".join([c for c in expiry_str if c.isdigit()])
        
        exp_month = months_map.get(month_name, 6) # Default to 6 if parsing fails
        exp_year = int(year_digits) if year_digits else 2026
        
        # Determine the exact Expiry Date (Last Tuesday)
        expiry_date = get_last_tuesday(exp_year, exp_month)
            
        # Get today's date (We will hardcode this to June 4, 2026 based on your context)
        current_date = date(2026, 6, 4) 
        days_to_expiry = (expiry_date - current_date).days
        
        # If the option has already expired, lock it to 0
        if days_to_expiry < 0:
            days_to_expiry = 0
            
        T_years = days_to_expiry / 365.0
        
        return {
            "underlying": ticker, 
            "strike": strike, 
            "type": opt_type, 
            "time_years": T_years, 
            "days": days_to_expiry,
            "expiry_date": expiry_date.strftime("%Y-%m-%d")
        }
    except Exception as e:
        return None

# =====================================================================
# MOMENTUM MATRIX
# =====================================================================

def compute_oi_buildup(price_change_pct, oi_change_pct):
    """
    Identifies Institutional Footprints by comparing Price and Open Interest.
    """
    if abs(price_change_pct) < 0.05 and abs(oi_change_pct) < 0.05:
        return "⚪ Neutral / Flat", "#64748B"
    
    if price_change_pct >= 0 and oi_change_pct >= 0:
        return "🟢 Long Buildup", "#089981"
    elif price_change_pct < 0 and oi_change_pct >= 0:
        return "🔴 Short Buildup", "#F23645"
    elif price_change_pct >= 0 and oi_change_pct < 0:
        return "🔵 Short Covering", "#2962FF"
    else:
        return "🟠 Long Unwinding", "#FF9800"
