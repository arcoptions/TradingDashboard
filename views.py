import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import json
import requests
import inspect
import time
from datetime import datetime
import plotly.express as px
import gspread 
import analytics
import database as db
import broker_api as api
import derivatives_engine as de 
import fundamentals_engine as fe 
import technicals_engine as te 
import scoring_engine as se 

SECTOR_MAP = {
    "RELIANCE": "Oil & Gas", "TCS": "IT Services", "HDFCBANK": "Banking", "ICICIBANK": "Banking", 
    "INFY": "IT Services", "HCLTECH": "IT Services", "WIPRO": "IT Services", "TECHM": "IT Services", "TATAELXSI": "IT Services",
    "ITC": "FMCG", "HUL": "FMCG", "NESTLEIND": "FMCG", "VBL": "FMCG", "BRITANNIA": "FMCG",
    "TATAMOTORS": "Auto", "M&M": "Auto", "TVSMOTOR": "Auto", "MARUTI": "Auto", "BAJAJ-AUTO": "Auto", 
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma", "DRREDDY": "Pharma", "DIVISLAB": "Pharma",
    "JSWENERGY": "Power", "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power",
    "UPL": "Chemicals", "PIIND": "Chemicals", "COALINDIA": "Metals / Mining", "TATASTEEL": "Metals"
}

INDEX_CONSTITUENTS = {
    "Nifty 50": ["RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "TCS", "LT", "BHARTIARTL", "SBIN", "BAJFINANCE", "AXISBANK", "HINDUNILVR", "HCLTECH", "MARUTI", "SUNPHARMA", "COALINDIA", "WIPRO", "TATASTEEL"],
    "Nifty Next 50": ["TRENT", "BEL", "HAL", "CHOLAFIN", "INDIGO", "SIEMENS", "VBL", "BANKBARODA", "BHEL", "PIDILITIND", "PNB", "DLF", "GAIL", "ZOMATO", "IRFC"],
    "Finnifty": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "BAJFINANCE", "CHOLAFIN", "PFC", "RECLTD", "BAJAJFINSV", "MUTHOOTFIN", "SHRIRAMFIN"],
    "Nifty Bank": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK", "BANKBARODA", "PNB", "AUBANK", "FEDERALBNK", "IDFCFIRSTB", "BANDHANBNK"],
    "Nifty IT": ["INFY", "TCS", "HCLTECH", "WIPRO", "TECHM", "LTIM", "COFORGE", "PERSISTENT", "MPHASIS", "TATAELXSI"],
    "Nifty FMCG": ["ITC", "HINDUNILVR", "NESTLEIND", "BRITANNIA", "TATACONSUM", "GODREJCP", "DABUR", "VBL", "MARICO", "COLPAL"],
    "Nifty Auto": ["TATAMOTORS", "M_M", "MARUTI", "BAJAJ_AUTO", "EICHERMOT", "TVSMOTOR", "HEROMOTOCO", "BOSCHLTD", "TIINDIA", "MRF"],
    "Nifty Energy": ["RELIANCE", "NTPC", "ONGC", "POWERGRID", "COALINDIA", "TATAPOWER", "IOC", "BPCL", "GAIL", "ADANIPOWER"],
    "Nifty Metal": ["TATASTEEL", "JSWSTEEL", "HINDALCO", "COALINDIA", "VEDL", "JINDALSTEL", "SAIL", "NMDC", "NATIONALUM"],
    "Nifty Pharma": ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "AUROPHARMA", "MANKIND", "TORNTPHARM", "ZYDUSLIFE"],
    "Nifty Healthcare": ["SUNPHARMA", "APOLLOHOSP", "MAXHEALTH", "CIPLA", "DRREDDY", "DIVISLAB", "LUPIN", "FORTIS", "METROPOLIS"],
    "Nifty Realty": ["DLF", "MACROTECH", "GODREJPROP", "PRESTIGE", "OBEROIRLTY", "PHOENIXLTD", "BRIGADE", "SOBHA", "SUNTECK"]
}

ASSET_ALIASES = {
    "COALINDIA": ["COALINDIA", "COAL INDIA", "CIL"],
    "OIL": ["OIL", "OIL INDIA", "OILINDIA"],
    "RELIANCE": ["RELIANCE", "RIL", "RELIANCE INDUSTRIES"],
    "M&M": ["M&M", "M & M", "MAHINDRA & MAHINDRA", "MAHINDRA"],
    "TATAMOTORS": ["TATAMOTORS", "TATA MOTORS"],
    "TCS": ["TCS", "TATA CONSULTANCY SERVICES"],
    "HDFCBANK": ["HDFCBANK", "HDFC BANK"],
    "ICICIBANK": ["ICICIBANK", "ICICI BANK"],
    "INFY": ["INFY", "INFOSYS"],
    "SUNPHARMA": ["SUNPHARMA", "SUN PHARMA"],
    "TATASTEEL": ["TATASTEEL", "TATA STEEL"],
    "WIPRO": ["WIPRO"]
}

KNOWN_ASSETS = set()
for aliases in ASSET_ALIASES.values(): KNOWN_ASSETS.update([a.upper() for a in aliases])
for stocks in INDEX_CONSTITUENTS.values():
    KNOWN_ASSETS.update([s.replace('_', '').upper() for s in stocks])
    KNOWN_ASSETS.update([s.replace('_', ' ').upper() for s in stocks])

def prox_color(val):
    if val == "-": return "color:#64748B;"
    return "color:#089981;" if float(val) > 0 else "color:#F23645;"

def render_tv_chart(symbol):
    tv_sym = str(symbol).split('-')[0].upper().replace("&", "_")
    tv_ticker = f"NSE:{tv_sym}" if tv_sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] else f"BSE:{tv_sym}"
    html = f"""
    <div class="tradingview-widget-container" style="height: 420px; width: 100%;">
      <div id="tv_chart" style="height: 420px; width: 100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{"autosize": true, "symbol": "{tv_ticker}", "interval": "D", "timezone": "Asia/Kolkata", "theme": "light", "style": "1", "locale": "in", "enable_publishing": false, "backgroundColor": "#ffffff", "gridColor": "#F1F5F9", "hide_top_toolbar": false, "container_id": "tv_chart"}});
      </script>
    </div>
    """
    components.html(html, height=420)

@st.cache_data(ttl=60)
def fetch_all_sectors_data():
    all_tickers = set()
    for stocks in INDEX_CONSTITUENTS.values():
        for s in stocks: all_tickers.add(f"NSE:{s}")
    payload = {"symbols": {"tickers": list(all_tickers)}, "columns": ["change", "close", "market_cap_basic"]}
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=5)
        if res.status_code == 200 and res.json().get("data"):
            return {item["s"].split(":")[1]: {"change": item["d"][0], "ltp": item["d"][1], "mcap": item["d"][2]} for item in res.json()["data"]}
    except Exception as e: print(e)
    return {}

@st.cache_data(ttl=15)
def batch_fetch_intelligence(symbols_list):
    results_map = {}
    if not symbols_list: return results_map
    clean_tickers = list(set([str(s).split('-')[0].strip().upper().replace("&", "_") for s in symbols_list]))
    tv_tickers = [f"NSE:{t}" for t in clean_tickers]
    
    tech_payload = {"symbols": {"tickers": tv_tickers}, "columns": ["close", "EMA20", "EMA50", "EMA200", "RSI", "volume", "average_volume_10d"]}
    fund_payload = {"symbols": {"tickers": tv_tickers}, "columns": ["price_earnings_ttm", "price_earnings_forward", "return_on_equity", "debt_to_equity", "operating_margin", "net_margin", "return_on_capital_employed"]}
    
    for t in clean_tickers:
        results_map[t] = {
            "f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"},
            "t": {"ltp": "-", "rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}
        }

    try:
        res_t = requests.post("https://scanner.tradingview.com/india/scan", json=tech_payload, timeout=6)
        if res_t.status_code == 200 and res_t.json().get("data"):
            for item in res_t.json()["data"]:
                t_raw = item["s"].split(":")[1]
                d = item["d"]
                if t_raw in results_map:
                    results_map[t_raw]["t"] = {
                        "ltp": round(d[0], 2) if d[0] is not None else "-",  
                        "rsi": round(d[4], 2) if d[4] is not None else "-",
                        "vol_spike": round((d[5] / d[6]) * 100, 2) if d[5] and d[6] and d[6] > 0 else "-",
                        "ema20_prox": round(((d[0] - d[1]) / d[1]) * 100, 2) if d[1] and d[0] else "-",
                        "ema50_prox": round(((d[0] - d[2]) / d[2]) * 100, 2) if d[2] and d[0] else "-",
                        "ema200_prox": round(((d[0] - d[3]) / d[3]) * 100, 2) if d[3] and d[0] else "-"
                    }
    except Exception as e: print(e)

    try:
        res_f = requests.post("https://scanner.tradingview.com/india/scan", json=fund_payload, timeout=6)
        if res_f.status_code == 200 and res_f.json().get("data"):
            for item in res_f.json()["data"]:
                t_raw = item["s"].split(":")[1]
                d = item["d"]
                if t_raw in results_map:
                    results_map[t_raw]["f"].update({
                        "stock_pe": round(d[0], 2) if d[0] is not None else "-",
                        "forward_pe": round(d[1], 2) if d[1] is not None else "-",
                        "roe": f"{round(d[2], 2)}%" if d[2] is not None else "-",
                        "debt_to_equity": round(d[3], 2) if d[3] is not None else "-",
                        "ebitda_margin": f"{round(d[4], 2)}%" if d[4] is not None else "-",
                        "pat_margin": f"{round(d[5], 2)}%" if d[5] is not None else "-",
                        "roce": f"{round(d[6], 2)}%" if d[6] is not None else "-"
                    })
    except Exception as e: print(e)

    return results_map

def format_index_display(name, raw_val):
    if not raw_val or raw_val == "-": return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>-</span>"
    parts = str(raw_val).split(",")
    if len(parts) == 3:
        lp, diff, pct = parts
        diff_f, pct_f = float(diff), float(pct)
        color = "#089981" if diff_f >= 0 else "#F23645" if diff_f < 0 else "#64748B"
        sign = "+" if diff_f > 0 else ""
        arrow = "▲" if diff_f >= 0 else "▼"
        return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp;&nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>{lp}</span> &nbsp;&nbsp; <span style='color: {color}; font-size: 14px; font-weight: 500;'>{sign}{diff_f:.2f} ({sign}{pct_f:.2f}%) {arrow}</span>"
    return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>{raw_val}</span>"

def render_top_ticker_tape(settings_sheet):
    try:
        nifty = format_index_display("NIFTY50", settings_sheet.acell('B10').value)
        st.markdown(f"<div class='index-tape'>{nifty}</div>", unsafe_allow_html=True)
    except: pass

def render_options_tracker(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    render_top_ticker_tape(settings_sheet)
    col_t1, col_t2 = st.columns([9, 1])
    with col_t1: st.markdown("### ARC Trading Terminal")
    with col_t2: 
        if st.button("UI Reset", use_container_width=True):
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)
            
    primary_watchlist_ws = worksheet.spreadsheet.sheet1
    
    # ─── FIX 1: API RATE LIMIT PROTECTOR FOR WATCHLIST ───
    try:
        initial_data = primary_watchlist_ws.get_all_records()
        sheet_headers = primary_watchlist_ws.row_values(1)
    except Exception as e:
        initial_data = []
        st.warning("⚠️ Google API Quota Reached. Please wait a few seconds before navigating to allow limits to reset.")

    initial_df = pd.DataFrame(initial_data) if initial_data else pd.DataFrame()

    if not initial_df.empty:
        initial_df['_Sheet_Row'] = range(2, len(initial_df) + 2)
        initial_df["Journal"] = False
        initial_df = analytics.compute_signal_indicators(initial_df)
        initial_df['Base Asset'] = initial_df['Symbol / Asset'].apply(lambda x: str(x).split('-')[0].strip().upper())
        initial_df['Sector/Industry'] = initial_df['Base Asset'].apply(lambda x: SECTOR_MAP.get(x, "General / Mixed"))

        batch_tickers = initial_df['Symbol / Asset'].tolist()
        intel_pool = batch_fetch_intelligence(batch_tickers)
        
        try: daily_token = settings_sheet.acell('B2').value
        except: daily_token = ""
            
        scores_col, decisions_col = [], []
        for idx, row in initial_df.iterrows():
            sym_key = str(row['Symbol / Asset']).split('-')[0].strip().upper().replace("&", "_")
            pool_data = intel_pool.get(sym_key, {"f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"}, "t": {"ltp": "-", "rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}})
            p_chg = float(row.get("Price Chg %", 0) or 0)
            o_chg = float(row.get("OI Chg %", 0) or 0)
            lbl, _ = de.compute_oi_buildup(p_chg, o_chg)
            t_type = row.get("Trade Type (Eq/Option)", "Equity")
            scr, dec, _ = se.generate_conviction_score(pool_data["f"], pool_data["t"], lbl, trade_type=t_type)
            scores_col.append(scr); decisions_col.append(dec)
            
        initial_df["Score"] = scores_col
        initial_df["Decision"] = decisions_col
        
        try:
            col_target = "Idea Source (Chartink/Telegram/X/Self)"
            raw_srcs = initial_df[col_target].astype(str).str.strip() if col_target in initial_df.columns else pd.Series()
            existing_sources = sorted(list(raw_srcs[(raw_srcs != "") & (raw_srcs != "nan") & (raw_srcs != "None")].unique()))
        except: existing_sources = []
        all_sources = sorted(list(set(["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chikou Trader", "Chartink", "Self/X"] + existing_sources)))
        
        min_d, max_d = datetime.today().date(), datetime.today().date()
        if "Trade Date" in initial_df.columns:
            initial_df["_Clean_Date"] = pd.to_datetime(initial_df["Trade Date"], errors='coerce').dt.date
            valid_dates = initial_df["_Clean_Date"].dropna().tolist()
            if valid_dates: min_d, max_d = min(valid_dates), max(valid_dates)
        else: initial_df["_Clean_Date"] = datetime.today().date()

        f_col1, f_col2, f_col3, f_col4 = st.columns([2.5, 2.5, 3, 2], gap="small")
        with f_col1: selected_sources = st.multiselect("Filter by Source", options=all_sources, default=[])
        with f_col2: selected_decisions = st.multiselect("Filter by Decision", options=["STRONG GO", "CAUTION", "NO-GO"], default=[])
        with f_col3: selected_date_range = st.date_input("Filter by Date Range", value=(min_d, max_d), min_value=min_d, max_value=max_d)
        with f_col4:
            st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
            if st.button("Sync Live Prices", use_container_width=True): api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)

        filtered_df = initial_df.copy()
        if selected_sources: filtered_df = filtered_df[filtered_df["Idea Source (Chartink/Telegram/X/Self)"].isin(selected_sources)]
        if selected_decisions: filtered_df = filtered_df[filtered_df["Decision"].isin(selected_decisions)]
        if isinstance(selected_date_range, tuple) and len(selected_date_range) == 2:
            filtered_df = filtered_df[(filtered_df["_Clean_Date"] >= selected_date_range[0]) & (filtered_df["_Clean_Date"] <= selected_date_range[1])]
        
        view_cols = [
            "Journal", "Base Asset", "Symbol / Asset", "Vs Entry", "Entry CMP / Range", 
            "Live Price", "Score", "Decision", "Add-On / Dip Levels", "Stop Loss (SL)", 
            "Target Status", "Target 1", "Target 2", "Exit Price", 
            "Idea Source (Chartink/Telegram/X/Self)", "Sector/Industry", "Trade Type (Eq/Option)", "Status (Watch/Active/Closed)", "_Sheet_Row"
        ]
        
        for col in view_cols:
            if col not in filtered_df.columns: filtered_df[col] = ""
            elif col not in ["Journal", "_Sheet_Row", "Score"]:
                filtered_df[col] = filtered_df[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})
                
        table_column_config = {
            "Journal": st.column_config.CheckboxColumn("Inspect", default=False),
            "Base Asset": st.column_config.TextColumn("Stock Name"),
            "Symbol / Asset": st.column_config.TextColumn("Contract"), 
            "Vs Entry": st.column_config.TextColumn("Vs Entry"),
            "Entry CMP / Range": st.column_config.TextColumn("Entry Range"),
            "Live Price": st.column_config.TextColumn("Live Price"),
            "Score": st.column_config.NumberColumn("Score", format="%d"),
            "Decision": st.column_config.TextColumn("Decision"),
            "Add-On / Dip Levels": st.column_config.TextColumn("Add-On / Dip Levels"),
            "Stop Loss (SL)": st.column_config.TextColumn("Stop Loss (SL)"),
            "Target Status": st.column_config.TextColumn("Target Status"),
            "Target 1": st.column_config.TextColumn("Target 1"),
            "Target 2": st.column_config.TextColumn("Target 2"),
            "Exit Price": st.column_config.TextColumn("Exit Price"),
            "Idea Source (Chartink/Telegram/X/Self)": st.column_config.SelectboxColumn("Source", options=all_sources, required=True),
            "Sector/Industry": st.column_config.TextColumn("Industry"),
            "Trade Type (Eq/Option)": st.column_config.SelectboxColumn("Type", options=["Equity", "Option"], required=True),
            "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True),
            "_Sheet_Row": None
        }
        disabled_cols = ["Decision", "Score", "Base Asset", "Sector/Industry", "Live Price", "Vs Entry", "Target Status"]
        
        if st.session_state.get("viewing_trade_row"):
            trade_rows = initial_df[initial_df['_Sheet_Row'] == st.session_state.viewing_trade_row]
            if not trade_rows.empty:
                trade_data = trade_rows.iloc[0]; sheet_row_id = int(trade_data['_Sheet_Row']); asset_symbol = trade_data['Symbol / Asset']
                base_ticker_raw = str(trade_data.get("Base Asset", str(asset_symbol).split('-')[0].strip())).upper()
                sym_key = base_ticker_raw.replace("&", "_")
                
                pool_data = intel_pool.get(sym_key, {"f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"}, "t": {"ltp": "-", "rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}})
                f_metrics = pool_data["f"]; t_metrics = pool_data["t"]
                
                head_c1, head_c2 = st.columns([2.5, 7.5], vertical_alignment="center")
                with head_c1:
                    if st.button("⬅️ Back to Terminal", use_container_width=True): 
                        st.session_state.viewing_trade = None
                        st.session_state.viewing_trade_row = None
                        st.rerun()
                with head_c2: st.markdown(f"<h3 style='margin:0; padding-left:10px;'>Research Analysis: {trade_data.get('Symbol / Asset', 'Unknown Asset')}</h3>", unsafe_allow_html=True)
                
                st.write("")
                tab_init_research, tab_psych_exec = st.tabs(["Initial Research", "Psychology & Execution"])
                
                with tab_init_research:
                    with st.container(border=True):
                        p_chg = float(trade_data.get("Price Chg %", 0) or 0)
                        o_chg = float(trade_data.get("OI Chg %", 0) or 0)
                        lbl, oi_color = de.compute_oi_buildup(p_chg, o_chg)
                        t_type = trade_data.get("Trade Type (Eq/Option)", "Equity")
                        scr, dec, flags = se.generate_conviction_score(f_metrics, t_metrics, lbl, trade_type=t_type)
                        v_color = "#089981" if dec == "STRONG GO" else "#D1A553" if dec == "CAUTION" else "#F23645"
                        sc1, sc2 = st.columns([1.5, 4.5])
                        sc1.markdown(f"<div style='text-align:center;'><span style='font-size:38px; font-weight:800; color:{v_color};'>{scr}/100</span><br><span style='font-size:16px; font-weight:700; color:{v_color};'>{dec}</span></div>", unsafe_allow_html=True)
                        sc2.markdown(f"<div style='font-size:13px; font-weight:500; color:#334155;'>{' | '.join(flags)}</div>", unsafe_allow_html=True)
                    
                    contract_meta = de.parse_option_contract(asset_symbol)
                    if contract_meta:
                        with st.container(border=True):
                            st.markdown("**Derivatives Profile & Live Greeks (Dhan Feed)**")
                            underlying_ltp_raw = t_metrics.get("ltp", "-")
                            underlying_px = float(underlying_ltp_raw) if underlying_ltp_raw != "-" else contract_meta['strike']
                            
                            dhan_chain_data = api.get_option_chain_metrics(asset_symbol, daily_token=daily_token)
                            if isinstance(dhan_chain_data, dict) and dhan_chain_data:
                                live_iv = float(dhan_chain_data.get('implied_volatility', 0))
                                live_delta = float(dhan_chain_data.get('delta', 0))
                                live_theta = float(dhan_chain_data.get('theta', 0))
                                strike_pcr = float(dhan_chain_data.get('strike_pcr', 0))
                                overall_pcr = float(dhan_chain_data.get('overall_pcr', 0))
                                best_ce = dhan_chain_data.get('best_ce', '-')
                                best_pe = dhan_chain_data.get('best_pe', '-')
                                api_success = (live_iv > 0 or live_delta != 0)
                            else:
                                live_iv, live_delta, live_theta, strike_pcr, overall_pcr = 0.0, 0.0, 0.0, 0.0, 0.0
                                best_ce, best_pe = "-", "-"
                                api_success = False

                            g1, g2, g3, g4, g5 = st.columns(5)
                            iv_display = f"{live_iv:.2f}%" if live_iv > 0 else "0DTE (Expiry)"
                            g1.metric("Delta", f"{live_delta:.5f}" if api_success else "Syncing...")
                            g2.metric("Theta", f"{live_theta:.2f} INR" if api_success else "Syncing...")
                            g3.metric("Underlying (Spot)", f"₹{underlying_px}")
                            g4.metric("Live IV", iv_display if api_success else "Syncing...")
                            g5.markdown(f"<span style='font-size:14px; font-weight:bold; color:#475569;'>OI Matrix</span><br><span style='font-size:18px; font-weight:bold; color:{oi_color};'>{lbl}</span>", unsafe_allow_html=True)
                                
                            st.markdown("---")
                            st.markdown("**ARC Options Proximity Intelligence & Strike Optimizers**")
                            
                            pc1, pc2, pc3, pc4 = st.columns([1.5, 1.5, 4.3, 2.7])
                            with pc1: st.metric("Strike-Level PCR", f"{strike_pcr:.2f}" if api_success else "0.0")
                            with pc2: st.metric("Overall Asset PCR", f"{overall_pcr:.2f}" if api_success else "0.0")
                            with pc3:
                                st.markdown(f"""
                                <div style='padding: 10px; border: 1px dashed #D1A553; border-radius: 6px; background-color: #FFFDF9; font-size:13px;'>
                                    <b>💡 Dhan Option Chain Target Optimizers:</b><br>
                                    🔹 <b>Optimal Call (CE):</b> {best_ce} <span style='color:#64748B;'>(OI Cluster)</span><br>
                                    🔹 <b>Optimal Put (PE):</b> {best_pe} <span style='color:#64748B;'>(OI Cluster)</span>
                                </div>
                                """, unsafe_allow_html=True)
                            with pc4:
                                st.markdown("<span style='font-size:13px; font-weight:bold; color:#0F172A;'>📰 News Feed</span>", unsafe_allow_html=True)
                                try:
                                    raw_log_ws = worksheet.spreadsheet.worksheet("Telegram_Raw_Logs")
                                    news_dataset = raw_log_ws.get_all_records()
                                except: news_dataset = []
                                
                                match_bullet_items = []
                                if news_dataset:
                                    target_clean = base_ticker_raw.replace(" ", "").upper()
                                    aliases = ASSET_ALIASES.get(target_clean, [target_clean])
                                    
                                    for entry in news_dataset:
                                        if any(kw in str(entry.get("Channel Source", "")).lower() for kw in ["beat the street", "news"]):
                                            text_chunk = str(entry.get("Raw Message Text", ""))
                                            text_upper = text_chunk.upper()
                                            text_normalized = text_upper.replace(" ", "")
                                            
                                            matched = False
                                            for alias in aliases:
                                                pattern = r'\b' + re.escape(alias.upper()) + r'\b'
                                                if re.search(pattern, text_upper) or alias.replace(" ", "") in text_normalized:
                                                    matched = True
                                                    break
                                            
                                            if matched:
                                                clean_snippet = text_chunk.replace('\n', ' ')[:65] + "..." if len(text_chunk) > 65 else text_chunk.replace('\n', ' ')
                                                match_bullet_items.append(f"<li style='font-size:11px; margin-bottom:4px; color:#334155;'><b>{entry.get('Timestamp','')[11:16]}</b>: {clean_snippet}</li>")
                                
                                if match_bullet_items:
                                    st.markdown(f"<ul style='padding-left:14px; margin:0;'>{''.join(match_bullet_items[:3])}</ul>", unsafe_allow_html=True)
                                else:
                                    st.markdown("<div style='font-size:11px; color:#64748B; padding-top:4px;'>No macro news updates found for this asset index.</div>", unsafe_allow_html=True)
                    
                    with st.container(border=True):
                        st.markdown("**Market Intelligence**")
                        f1, f2, f3, f4, f5, f6 = st.columns(6)
                        f1.metric("P/E", f_metrics['stock_pe']); f2.metric("ROE", f_metrics['roe']); f3.metric("ROCE", f_metrics['roce']); f4.metric("D/E", f"{f_metrics['debt_to_equity']}x"); f5.metric("EBITDA", f_metrics['ebitda_margin']); f6.metric("Inst.", f_metrics['inst_own'])
                        t1, t2, t3, t4, t5 = st.columns(5)
                        t1.metric("RSI", t_metrics['rsi']); t2.markdown(f"**20 EMA**<br><span style='{prox_color(t_metrics['ema20_prox'])}'>{t_metrics['ema20_prox']}%</span>", unsafe_allow_html=True); t3.markdown(f"**50 EMA**<br><span style='{prox_color(t_metrics['ema50_prox'])}'>{t_metrics['ema50_prox']}%</span>", unsafe_allow_html=True); t4.markdown(f"**200 EMA**<br><span style='{prox_color(t_metrics['ema200_prox'])}'>{t_metrics['ema200_prox']}%</span>", unsafe_allow_html=True); t5.metric("Vol Spike", f"{t_metrics['vol_spike']}%" if t_metrics['vol_spike'] != "-" else "-")
                    
                    with st.container(border=True):
                        st.markdown("**Interactive Chart**")
                        render_tv_chart(sym_key)
                
                with tab_psych_exec:
                    st.markdown("#### Psychology & Trade Rationale")
                    with st.container(border=True):
                        curr_rationale = str(trade_data.get('Strategic Rationale (Why I took it)', ''))
                        curr_emotions = str(trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', ''))
                        if curr_rationale.strip() and curr_rationale != 'nan': st.info(f"**Rationale:** {curr_rationale}")
                        if curr_emotions.strip() and curr_emotions != 'nan': st.warning(f"**Emotions:** {curr_emotions}")
                        
                        with st.expander("📝 Update Psychology Notes"):
                            with st.form("psychology_update_form"):
                                new_rationale = st.text_area("Execution Rationale", value=curr_rationale if curr_rationale != 'nan' else '')
                                new_emotions = st.text_area("Psychological State", value=curr_emotions if curr_emotions != 'nan' else '')
                                if st.form_submit_button("Save Notes", type="primary"):
                                    primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Strategic Rationale (Why I took it)") + 1, str(new_rationale))
                                    primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Emotions at Entry (FOMO, Calm, etc.)") + 1, str(new_emotions))
                                    st.rerun()
                                    
                    st.markdown("#### Execution & Asset Repair")
                    with st.container(border=True):
                        col1, col2, col3, col4, col5 = st.columns([1.5, 1.5, 1.5, 1.5, 4], gap="small")
                        col1.metric("Status", trade_data.get('Status (Watch/Active/Closed)', 'N/A'))
                        col2.metric("Entry Range", trade_data.get('Entry CMP / Range', 'N/A'))
                        col3.metric("Live Price", trade_data.get('Live Price', '-'))
                        col4.metric("Exit Price", trade_data.get('Exit Price', 'Pending'))
                        with col5:
                            try:
                                entry_val = float(re.findall(r'[\d\.]+', str(trade_data['Entry CMP / Range']))[0])
                                exit_val = float(str(trade_data['Exit Price']))
                                pnl = exit_val - entry_val
                                if pnl > 0: st.success(f"Net Points Captured: +{round(pnl, 2)}")
                                else: st.error(f"Net Points Lost: {round(pnl, 2)}")
                            except: st.info("Awaiting execution parameters.")
                            
                        with st.expander("🛠 Advanced Asset Repair Tool"):
                            fix_query = st.text_input("Search Official Master Database", value=str(trade_data['Symbol / Asset']).split()[0], key="fix_contract_query")
                            fix_results = api.search_instruments(fix_query)
                            if not fix_results.empty:
                                selected_fix = st.selectbox("Select Correct Contract:", fix_results['SEM_TRADING_SYMBOL'].tolist(), key="fix_contract_select")
                                if st.button("Save & Re-Link Asset", type="primary", use_container_width=True):
                                    fix_row = fix_results[fix_results['SEM_TRADING_SYMBOL'] == selected_fix].iloc[0]
                                    primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Symbol / Asset") + 1, str(fix_row['SEM_TRADING_SYMBOL']))
                                    primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Security ID") + 1, str(fix_row['SEM_SMST_SECURITY_ID']))
                                    primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Exchange") + 1, "NSE_EQ" if str(fix_row['SEM_EXM_EXCH_ID']) == "NSE" and str(fix_row['SEM_SEGMENT']) == "E" else "NSE_FNO")
                                    st.rerun()

                if st.button("Unlink Review Canvas", use_container_width=True):
                    st.session_state.viewing_trade = None; st.session_state.viewing_trade_row = None; st.rerun()
        else:
            df_stocks = filtered_df[filtered_df["Trade Type (Eq/Option)"].str.lower().isin(["equity", "stock"])].copy()
            df_options = filtered_df[filtered_df["Trade Type (Eq/Option)"].str.lower().isin(["option", "fno"])].copy()
            
            tab_options, tab_stocks, tab_study, tab_heatmap, tab_scanners, tab_telegram = st.tabs(["Options", "Stocks", "Stocks to Study", "Sector Heatmap", "Scanners", "Telegram Data"])
            
            def render_asset_dashboard(df_asset, asset_type):
                if df_asset.empty:
                    st.info(f"No execution matches found.")
                    return
                sub_wl, sub_act, sub_cls = st.tabs(["Watchlist", "Active", "Closed"])
                with sub_wl:
                    df_wl = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
                    if not df_wl.empty: st.data_editor(df_wl[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"wl_{asset_type}", on_change=db.run_background_sync, kwargs={f"df_filtered": df_wl, "state_key": f"wl_{asset_type}", "worksheet": primary_watchlist_ws, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                with sub_act:
                    df_act = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
                    if not df_act.empty: st.data_editor(df_act[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"act_{asset_type}", on_change=db.run_background_sync, kwargs={f"df_filtered": df_act, "state_key": f"act_{asset_type}", "worksheet": primary_watchlist_ws, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                with sub_cls:
                    df_cls = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
                    if not df_cls.empty: st.data_editor(df_cls[view_cols], use_container_width=True, hide_index=True, num_rows="fixed", key=f"cls_{asset_type}", on_change=db.run_background_sync, kwargs={f"df_filtered": df_cls, "state_key": f"cls_{asset_type}", "worksheet": primary_watchlist_ws, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)

            with tab_options: render_asset_dashboard(df_options, "Options")
            with tab_stocks: render_asset_dashboard(df_stocks, "Stocks")
            
            with tab_study:
                st.markdown("#### Macro Research Staging Deck (`Stocks to study`)")
                st.caption("Aggregated list of high-conviction insights extracted directly from news wires and automated tickers.")
                
                try:
                    study_ws_layer = worksheet.spreadsheet.worksheet("Stocks to study")
                except gspread.exceptions.WorksheetNotFound:
                    study_ws_layer = worksheet.spreadsheet.add_worksheet(title="Stocks to study", rows="3000", cols="5")
                    study_ws_layer.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
                    
                # ─── FIX 2: API RATE LIMIT PROTECTOR FOR STUDY TAB ───
                try:
                    study_vals = study_ws_layer.get_all_values()
                    if len(study_vals) > 1:
                        df_study_log = pd.DataFrame(study_vals[1:], columns=study_vals[0])
                        df_study_log = df_study_log[df_study_log["Timestamp"].astype(str).str.strip() != ""]
                    else:
                        df_study_log = pd.DataFrame()
                except Exception as e: 
                    df_study_log = pd.DataFrame()
                    st.warning("⚠️ Temporarily paused sync to respect Google Sheets API Read Quota.")
                
                if not df_study_log.empty:
                    st.dataframe(
                        df_study_log, 
                        use_container_width=True, 
                        hide_index=True,
                        column_config={
                            "Timestamp": st.column_config.TextColumn("Time", width="small"),
                            "Source": st.column_config.TextColumn("Wire Source", width="medium"),
                            "Asset Ticker": st.column_config.TextColumn("Asset", width="small"),
                            "Raw Text Message": st.column_config.TextColumn("News Narrative", width="large"),
                            "Staging Date": st.column_config.TextColumn("Logged", width="small")
                        }
                    )
                else:
                    st.info("No research items logged yet. New inbound entries from Beat The Street will display here automatically, or you can stage your old messages manually from the Telegram Data tab.")
            
            with tab_heatmap:
                if "active_heatmap_sector" not in st.session_state: st.session_state.active_heatmap_sector = None
                all_data = fetch_all_sectors_data()
                if not all_data: st.info("Market mapping data refreshing...")
                elif st.session_state.active_heatmap_sector is None:
                    sector_weights = {"Nifty 50": 100, "Nifty Bank": 80, "Nifty IT": 60, "Nifty Next 50": 50, "Nifty Auto": 40, "Nifty FMCG": 40, "Nifty Energy": 40, "Nifty Metal": 30, "Nifty Pharma": 30, "Finnifty": 30, "Nifty Healthcare": 20, "Nifty Realty": 10}
                    sector_data = []
                    for sec, stocks in INDEX_CONSTITUENTS.items():
                        chgs = [all_data[s]["change"] for s in stocks if s in all_data and all_data[s]["change"] is not None]
                        sector_data.append({"Sector": sec, "Change": sum(chgs)/len(chgs) if chgs else 0.0, "Weight": sector_weights.get(sec, 30)})
                    
                    fig = px.treemap(pd.DataFrame(sector_data), path=['Sector'], values='Weight', color='Change', custom_data=['Change'], color_continuous_scale=['#F23645', '#F8FAFC', '#089981'], color_continuous_midpoint=0)
                    fig.update_traces(textinfo="label+text", texttemplate="%{label}<br><b>%{customdata[0]:.2f}%</b>", textfont=dict(size=14), root_color="rgba(0,0,0,0)")
                    fig.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=460, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
                    if "on_select" in inspect.signature(st.plotly_chart).parameters:
                        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="treemap")
                        if event and event.get("selection", {}).get("points"):
                            st.session_state.active_heatmap_sector = event["selection"]["points"][0].get("label"); st.rerun()
                    else: st.plotly_chart(fig, use_container_width=True)
                else:
                    st.button("⬅️ Go back to Heat Map", type="primary", on_click=lambda: st.session_state.update({"active_heatmap_sector": None}))
                    rows = [{"Stock": s.replace('HINDUNILVR', 'HUL'), "Market Cap (Cr)": round(all_data[s]["mcap"]/10000000, 2) if all_data[s]["mcap"] else 0.0, "LTP (₹)": all_data[s]["ltp"], "Change %": all_data[s]["change"]} for s in INDEX_CONSTITUENTS[st.session_state.active_heatmap_sector] if s in all_data]
                    st.dataframe(pd.DataFrame(rows).sort_values(by="Market Cap (Cr)", ascending=False), use_container_width=True, hide_index=True)
            
            with tab_scanners:
                st.markdown("#### Automated Scan Feeds")
                # ─── FIX 3: API RATE LIMIT PROTECTOR FOR SCANNERS ───
                try:
                    scanner_data = scanner_sheet.get_all_records()
                except Exception as e:
                    scanner_data = []
                    st.warning("⚠️ Scanner feed temporarily paused to respect Google API limits.")
                
                df_scan = pd.DataFrame(scanner_data) if scanner_data else pd.DataFrame()
                
                if not df_scan.empty:
                    df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
                    df_scan = analytics.compute_scanner_signals(df_scan)
                    tab_ce1, tab_ce2, tab_pos = st.tabs(["CE1", "CE2", "Positional"])
                    scan_view_cols = ["Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time", "Status", "Notes / Analysis", "_Sheet_Row"]
                    scan_col_config = {"_Sheet_Row": None, "Status": st.column_config.SelectboxColumn("Status", options=["Monitoring", "Moved to Watchlist", "Discarded"], required=True)}

                    def render_scanner_tab(tab_obj, filter_name):
                        with tab_obj:
                            df_filtered = df_scan[df_scan["Scanner"] == filter_name].reset_index(drop=True)
                            if not df_filtered.empty:
                                m1, m2, m3, m4 = st.columns(4)
                                m1.metric("Total Triggers", len(df_filtered))
                                m2.metric("Holding Above", len(df_filtered[df_filtered['Vs Entry'] == '🟢 Above']))
                                m3.metric("Slipped Below", len(df_filtered[df_filtered['Vs Entry'] == '🔴 Below']))
                                m4.metric("Flat / Pending", len(df_filtered[df_filtered['Vs Entry'].isin(['⚪ At Entry', '-'])]))
                                st.write("")
                                st.data_editor(df_filtered[scan_view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"scan_{filter_name}", on_change=db.run_scanner_sync, kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}", "scanner_sheet": scanner_sheet, "scanner_headers": scanner_headers}, column_config=scan_col_config, disabled=["Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time"])
                            else: st.info(f"No active triggers for {filter_name}.")
                    
                    render_scanner_tab(tab_ce1, "CE1")
                    render_scanner_tab(tab_ce2, "CE2")
                    render_scanner_tab(tab_pos, "Positional")
                else:
                    st.info("Scanner database is currently empty.")

            with tab_telegram:
                st.markdown("#### Operational Staging Workspaces")
                # ─── FIX 4: API RATE LIMIT PROTECTOR FOR TELEGRAM LOGS ───
                try:
                    wb_obj = worksheet.spreadsheet
                    raw_log_ws = wb_obj.worksheet("Telegram_Raw_Logs")
                    raw_data_records = raw_log_ws.get_all_records()
                    df_raw_logs = pd.DataFrame(raw_data_records)
                except Exception as e:
                    df_raw_logs = pd.DataFrame()
                    st.warning("⚠️ Terminal raw logs feed paused. Background collection is still active.")
                
                if not df_raw_logs.empty:
                    df_raw_logs["_Row_ID"] = range(2, len(df_raw_logs) + 2)
                    df_pending = df_raw_logs[df_raw_logs["Parsing Status"].astype(str).str.strip().str.lower().isin(["pending review", "pending extraction", "pending parsing", "news ingested"])].copy()
                    
                    mentions_list, news_list, discussions_list = [], [], []
                    
                    for idx, row in df_pending.iterrows():
                        text = str(row['Raw Message Text'])
                        source = str(row['Channel Source'])
                        is_news_channel = any(kw in source.lower() for kw in ["beat the street", "news"])
                        
                        stock_mentioned = False
                        matched_symbol = ""
                        
                        text_upper = text.upper()
                        for master_ticker, aliases in ASSET_ALIASES.items():
                            for alias in aliases:
                                pattern = r'\b' + re.escape(alias.upper()) + r'\b'
                                if re.search(pattern, text_upper):
                                    stock_mentioned = True
                                    matched_symbol = master_ticker
                                    break
                            if stock_mentioned: break
                                    
                        if not stock_mentioned:
                            for index_asset in SECTOR_MAP.keys():
                                pattern = r'\b' + re.escape(index_asset) + r'\b'
                                if re.search(pattern, text_upper):
                                    stock_mentioned = True
                                    matched_symbol = index_asset
                                    break

                        if stock_mentioned:
                            t_sym, t_sec, t_exch_type = api.resolve_instrument(matched_symbol)
                            if t_sec:
                                row['Extracted_Symbol'] = t_sym
                                row['Exchange_Segment_Verified'] = t_exch_type
                                mentions_list.append(row)
                            else:
                                if is_news_channel: news_list.append(row)
                                else: discussions_list.append(row)
                        elif is_news_channel:
                            row['Extracted_Symbol'] = "-"
                            row['Exchange_Segment_Verified'] = ""
                            news_list.append(row)
                        else:
                            row['Extracted_Symbol'] = "-"
                            row['Exchange_Segment_Verified'] = ""
                            discussions_list.append(row)
                            
                    df_mentions = pd.DataFrame(mentions_list) if mentions_list else pd.DataFrame()
                    df_news = pd.DataFrame(news_list) if news_list else pd.DataFrame()
                    df_discussions = pd.DataFrame(discussions_list) if discussions_list else pd.DataFrame()
                    
                    watchlist_symbols = []
                    if not initial_df.empty:
                        watchlist_symbols += initial_df["Symbol / Asset"].astype(str).str.upper().tolist()
                        watchlist_symbols += initial_df["Base Asset"].astype(str).str.upper().tolist()

                    sub_mentions, sub_news, sub_discussions = st.tabs(["🎯 Stock Mentions", "📰 Exclusive News Log", "💬 General Discussions"])
                    
                    def render_bulk_table(df, tab_name):
                        if df.empty:
                            st.success(f"✨ {tab_name} Queue Clear!")
                            return
                        
                        df_display = df.copy()
                        df_display.insert(0, "Select", False)
                        
                        if tab_name == "Stock Mentions":
                            df_display["Status"] = df_display["Extracted_Symbol"].apply(lambda x: "⚠️ Duplicate" if str(x).upper() in watchlist_symbols else "🟢 Unique")
                        else:
                            df_display["Status"] = "ℹ️ Info"
                            
                        b1, b2, b3 = st.columns([1, 1, 1])
                        
                        edited_df = st.data_editor(
                            df_display, hide_index=True, use_container_width=True, key=f"editor_{tab_name}",
                            column_config={
                                "Select": st.column_config.CheckboxColumn("✓", width="small"),
                                "_Row_ID": None, "Parsing Status": None, "Exchange_Segment_Verified": None,
                                "Timestamp": st.column_config.TextColumn("Time", width="small"),
                                "Channel Source": st.column_config.TextColumn("Source", width="medium"),
                                "Raw Message Text": st.column_config.TextColumn("Message Content", width="large"),
                                "Extracted_Symbol": st.column_config.TextColumn("Asset Token", width="small"),
                                "Status": st.column_config.TextColumn("Status", width="small")
                            }
                        )
                        
                        selected_rows = edited_df[edited_df["Select"] == True]
                        
                        if b1.button("⚡ Stage Selected Rows", key=f"stg_{tab_name}", use_container_width=True) and not selected_rows.empty:
                            status_updates = []
                            
                            if tab_name == "News Feeds" or any(kw in str(selected_rows.iloc[0]['Channel Source']).lower() for kw in ["beat the street", "news"]):
                                try: target_study_ws = wb_obj.worksheet("Stocks to study")
                                except: 
                                    target_study_ws = wb_obj.add_worksheet(title="Stocks to study", rows="3000", cols="5")
                                    target_study_ws.append_row(["Timestamp", "Source", "Asset Ticker", "Raw Text Message", "Staging Date"])
                                
                                bulk_study_rows = []
                                for _, s_row in selected_rows.iterrows():
                                    bulk_study_rows.append([str(s_row['Timestamp']), str(s_row['Channel Source']), str(s_row['Extracted_Symbol']), str(s_row['Raw Message Text']), datetime.today().strftime("%Y-%m-%d")])
                                    status_updates.append({'range': f"D{s_row['_Row_ID']}", 'values': [["Staged to Study"]]})
                                if bulk_study_rows: target_study_ws.append_rows(bulk_study_rows)
                            else:
                                target_watchlist_ws = wb_obj.sheet1
                                bulk_watchlist_rows = []
                                for _, s_row in selected_rows.iterrows():
                                    if "Duplicate" in s_row["Status"]: continue 
                                    t_sym, t_sec, t_exch = api.resolve_instrument(s_row['Extracted_Symbol'])
                                    pre_parsed = analytics.parse_telegram_tip(s_row['Raw Message Text'])
                                    auto_derived_trade_type = "Equity" if "EQ" in str(s_row['Exchange_Segment_Verified']) else "Option"
                                    
                                    new_row = [""] * len(sheet_headers)
                                    def fill(col, val): 
                                        if col in sheet_headers: new_row[sheet_headers.index(col)] = str(val)
                                    fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                                    fill("Idea Source (Chartink/Telegram/X/Self)", s_row['Channel Source'])
                                    fill("Symbol / Asset", t_sym)
                                    fill("Trade Type (Eq/Option)", auto_derived_trade_type)
                                    fill("Exchange", t_exch)
                                    fill("Security ID", t_sec)
                                    fill("Status (Watch/Active/Closed)", "Watchlist")
                                    fill("Entry CMP / Range", pre_parsed.get('entry', ''))
                                    fill("Stop Loss (SL)", pre_parsed.get('sl', ''))
                                    fill("Target 1", pre_parsed.get('t1', ''))
                                    fill("Raw Tip Text", s_row['Raw Message Text'])
                                    bulk_watchlist_rows.append(new_row)
                                    status_updates.append({'range': f"D{s_row['_Row_ID']}", 'values': [["Successfully Staged"]]})
                                if bulk_watchlist_rows: target_watchlist_ws.append_rows(bulk_watchlist_rows)
                                
                            if status_updates:
                                raw_log_ws.batch_update(status_updates)
                                st.toast(f"Staged elements redirected successfully!")
                                time.sleep(0.5); st.rerun()

                        if b2.button("📦 Archive Selected Rows", key=f"arc_{tab_name}", use_container_width=True) and not selected_rows.empty:
                            try: archive_ws = wb_obj.worksheet("Telegram_Archive")
                            except: archive_ws = wb_obj.add_worksheet(title="Telegram_Archive", rows="2000", cols="4")
                            
                            arc_rows, status_updates = [], []
                            for _, s_row in selected_rows.iterrows():
                                arc_rows.append([str(s_row['Timestamp']), str(s_row['Channel Source']), str(s_row['Raw Message Text']), datetime.today().strftime("%Y-%m-%d")])
                                status_updates.append({'range': f"D{s_row['_Row_ID']}", 'values': [["Archived Data"]]})
                            if arc_rows:
                                archive_ws.append_rows(arc_rows)
                                wb_obj.worksheet("Telegram_Raw_Logs").batch_update(status_updates)
                                st.toast(f"Archived successfully.")
                                time.sleep(0.5); st.rerun()

                        if b3.button("🗑️ Discard Selected Rows", key=f"dsc_{tab_name}", use_container_width=True) and not selected_rows.empty:
                            status_updates = [{'range': f"D{s_row['_Row_ID']}", 'values': [["Discarded"]]} for _, s_row in selected_rows.iterrows()]
                            wb_obj.worksheet("Telegram_Raw_Logs").batch_update(status_updates)
                            st.toast(f"Discarded successfully.")
                            time.sleep(0.5); st.rerun()

                    with sub_mentions: render_bulk_table(df_mentions, "Stock Mentions")
                    with sub_news: render_bulk_table(df_news, "News Feeds")
                    with sub_discussions: render_bulk_table(df_discussions, "General Discussions")
                    
                else: st.info("System initializing tracking logs. Awaiting fresh inbound advisory data.")

# Empty fallback handler just to prevent Streamlit startup errors if old references exist
def render_chartink_scanners(*args, **kwargs):
    pass
