import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import json
import requests
from datetime import datetime
import plotly.express as px
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
    "SONACOMS": "Auto Components", "EXIDEIND": "Auto Components",
    "SUNPHARMA": "Pharma", "CIPLA": "Pharma", "DRREDDY": "Pharma", "DIVISLAB": "Pharma",
    "JSWENERGY": "Power", "NTPC": "Power", "POWERGRID": "Power", "TATAPOWER": "Power",
    "UPL": "Chemicals", "PIIND": "Chemicals",
    "IRFC": "Railways / Finance", "IREDA": "Green Energy / Finance", "PFC": "Finance", 
    "GMRAIRPORT": "Infrastructure", "NBCC": "Construction",
    "SAIL": "Metals", "TATASTEEL": "Metals", "JSWSTEEL": "Metals", "HINDALCO": "Metals",
    "PNBGILTS": "Finance", "IFCI": "Finance",
    "NIFTY": "Market Index", "BANKNIFTY": "Sector Index"
}

def prox_color(val):
    if val == "-": return "color:#64748B;"
    return "color:#089981;" if float(val) > 0 else "color:#F23645;"

def render_tv_chart(symbol):
    tv_sym = str(symbol).split('-')[0].upper().replace("&", "_")
    tv_ticker = f"NSE:{tv_sym}" if tv_sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] else f"BSE:{tv_sym}"
    
    html = f"""
    <div class="tradingview-widget-container" style="height: 400px; width: 100%;">
      <div id="tv_chart" style="height: 400px; width: 100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{
        "autosize": true, "symbol": "{tv_ticker}", "interval": "D", "timezone": "Asia/Kolkata",
        "theme": "light", "style": "1", "locale": "in", "enable_publishing": false,
        "backgroundColor": "#ffffff", "gridColor": "#F1F5F9", "hide_top_toolbar": false,
        "container_id": "tv_chart"
      }});
      </script>
    </div>
    """
    components.html(html, height=400)

@st.cache_data(ttl=15)
def batch_fetch_intelligence(symbols_list):
    """
    Institutional Pipeline: Bundles all portfolio assets into ONE single 
    batch post request to eliminate UI loading overhead.
    """
    results_map = {}
    if not symbols_list: return results_map

    clean_tickers = list(set([str(s).split('-')[0].strip().upper().replace("&", "_") for s in symbols_list]))
    tv_tickers = [f"NSE:{t}" for t in clean_tickers]

    payload = {
        "symbols": {"tickers": tv_tickers},
        "columns": [
            "price_earnings_ttm", "price_earnings_forward", "return_on_equity",
            "debt_to_equity", "operating_margin", "net_margin", 
            "return_on_invested_capital", "institutions_ownership",
            "close", "EMA20", "EMA50", "EMA200", "RSI", "volume", "average_volume_10d"
        ]
    }

    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=6)
        if res.status_code == 200 and res.json().get("data"):
            for item in res.json()["data"]:
                ticker_raw = item["s"].split(":")[1]
                d = item["d"]
                
                # Dynamic Mapping Line Arrays
                f_m = {
                    "stock_pe": round(d[0], 2) if d[0] is not None else "-",
                    "forward_pe": round(d[1], 2) if d[1] is not None else "-",
                    "sector_pe": 20.0, # Default registry placeholder
                    "roe": f"{round(d[2], 2)}%" if d[2] is not None else "-",
                    "debt_to_equity": round(d[3], 2) if d[3] is not None else "-",
                    "ebitda_margin": f"{round(d[4], 2)}%" if d[4] is not None else "-",
                    "pat_margin": f"{round(d[5], 2)}%" if d[5] is not None else "-",
                    "roce": f"{round(d[6], 2)}%" if d[6] is not None else "-",
                    "inst_own": f"{round(d[7], 2)}%" if d[7] is not None else "-"
                }

                close = d[8]
                vol_spike = "-"
                if d[13] and d[14] and d[14] > 0:
                    vol_spike = round((d[13] / d[14]) * 100, 2)

                t_m = {
                    "rsi": round(d[12], 2) if d[12] is not None else "-",
                    "vol_spike": vol_spike,
                    "ema20_prox": round(((close - d[9]) / d[9]) * 100, 2) if d[9] and close else "-",
                    "ema50_prox": round(((close - d[10]) / d[10]) * 100, 2) if d[10] and close else "-",
                    "ema200_prox": round(((close - d[11]) / d[11]) * 100, 2) if d[11] and close else "-"
                }

                results_map[ticker_raw] = {"f": f_m, "t": t_m}
    except Exception as e:
        print(f"Batch System Connection Failure: {e}")
    return results_map

def format_index_display(name, raw_val):
    if not raw_val or raw_val == "-": 
        return f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>{name}</span> &nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>-</span>"
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
    # Define which columns are read-only / auto-calculated
    disabled_cols = ["Decision", "Base Asset", "Sector/Industry", "Live Price", "Vs Entry", "Target Status"]
    col_t1, col_t2 = st.columns([9, 1])
    with col_t1: st.markdown("### ARC Trading Terminal")
    with col_t2: 
        if st.button("UI Reset", help="Reset tracking dashboard", use_container_width=True):
            import streamlit.components.v1 as components
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)
            
    initial_data = worksheet.get_all_records()
    initial_df = pd.DataFrame(initial_data) if initial_data else pd.DataFrame()

    if not initial_df.empty:
        initial_df['_Sheet_Row'] = range(2, len(initial_df) + 2)
        initial_df["Journal"] = False
        initial_df = analytics.compute_signal_indicators(initial_df)
        
        initial_df['Base Asset'] = initial_df['Symbol / Asset'].apply(lambda x: str(x).split('-')[0].strip().upper())
        initial_df['Sector/Industry'] = initial_df['Base Asset'].apply(lambda x: SECTOR_MAP.get(x, "General / Mixed"))

        # ─── EXECUTE THE BATCH SCORING LOOPS FOR THE ENTIRE PORTFOLIO ───
        batch_tickers = initial_df['Symbol / Asset'].tolist()
        intel_pool = batch_fetch_intelligence(batch_tickers)

        scores_col, decisions_col = [], []
        for idx, row in initial_df.iterrows():
            sym_key = str(row['Symbol / Asset']).split('-')[0].strip().upper().replace("&", "_")
            pool_data = intel_pool.get(sym_key, {
                "f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"},
                "t": {"rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}
            })
            
            try: p_chg = float(row.get("Price Chg %", 0))
            except: p_chg = 0.0
            try: o_chg = float(row.get("OI Chg %", 0))
            except: o_chg = 0.0
            
            lbl, _ = de.compute_oi_buildup(p_chg, o_chg)
            scr, dec, _ = se.generate_conviction_score(pool_data["f"], pool_data["t"], lbl)
            scores_col.append(scr)
            decisions_col.append(dec)

        initial_df["Score"] = scores_col
        initial_df["Decision"] = decisions_col

        # Dynamic filter builders
        all_sources = sorted(list(initial_df["Idea Source (Chartink/Telegram/X/Self)"].dropna().unique())) if "Idea Source (Chartink/Telegram/X/Self)" in initial_df.columns else []
        
        # ─── TWO-COLUMN HORIZONTAL FILTER BAR ───
        f_col1, f_col2, f_col3 = st.columns([3, 3, 4], gap="medium")
        with f_col1: 
            selected_sources = st.multiselect("Filter by Source", options=all_sources, default=[])
        with f_col2: 
            selected_decisions = st.multiselect("Filter by Decision", options=["STRONG GO", "CAUTION", "NO-GO"], default=[])
        with f_col3:
            st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
            if st.button("Sync Live Prices", use_container_width=True): 
                api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)

        filtered_df = initial_df.copy()
        if selected_sources:
            filtered_df = filtered_df[filtered_df["Idea Source (Chartink/Telegram/X/Self)"].isin(selected_sources)]
        if selected_decisions:
            filtered_df = filtered_df[filtered_df["Decision"].isin(selected_decisions)]

        # --- CANVAS RENDERING CORE ---
        view_cols = ["Idea Source (Chartink/Telegram/X/Self)", "Journal", "Decision", "Base Asset", "Sector/Industry", "Symbol / Asset", "Trade Type (Eq/Option)", "Status (Watch/Active/Closed)", "Vs Entry", "Target Status", "Entry CMP / Range", "Live Price", "Add-On / Dip Levels", "Exit Price", "Stop Loss (SL)", "_Sheet_Row"]

        for col in view_cols:
            if col not in filtered_df.columns: filtered_df[col] = ""
            elif col not in ["Journal", "_Sheet_Row", "Score"]:
                filtered_df[col] = filtered_df[col].astype(str).replace({'nan': '', 'None': '', '<NA>': ''})

        table_column_config = {
            "Idea Source (Chartink/Telegram/X/Self)": st.column_config.SelectboxColumn("Source", options=all_sources, required=True),
            "Journal": st.column_config.CheckboxColumn("Inspect", default=False),
            "Decision": st.column_config.TextColumn("Decision", help="Algorithmic Conviction Filter"),
            "Base Asset": st.column_config.TextColumn("Stock Name"),
            "Sector/Industry": st.column_config.TextColumn("Industry"),
            "Symbol / Asset": st.column_config.TextColumn("Asset Contract"), 
            "Trade Type (Eq/Option)": st.column_config.SelectboxColumn("Type", options=["Equity", "Option"], required=True),
            "_Sheet_Row": None, 
            "Status (Watch/Active/Closed)": st.column_config.SelectboxColumn("Status", options=["Watchlist", "Active", "Closed"], required=True)
        }

        if st.session_state.get("viewing_trade_row"):
            if st.button("Back to Terminal", key="top_reset_view_btn"): close_journal(); st.rerun()
            trade_rows = initial_df[initial_df['_Sheet_Row'] == st.session_state.viewing_trade_row]
            if not trade_rows.empty:
                trade_data = trade_rows.iloc[0]
                sheet_row_id = int(trade_data['_Sheet_Row'])
                asset_symbol = trade_data['Symbol / Asset']
                
                sym_key = str(asset_symbol).split('-')[0].strip().upper().replace("&", "_")
                pool_data = intel_pool.get(sym_key, {
                    "f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"},
                    "t": {"rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}
                })
                
                f_metrics = pool_data["f"]
                t_metrics = pool_data["t"]

                # --- OPTIMIZED SCORECARD CONTAINER ---
                # Re-designed to remove dead vertical whitespace gaps and align items tightly
                with st.container(border=True):
                    try: p_chg = float(trade_data.get("Price Chg %", 0))
                    except: p_chg = 0.0
                    try: o_chg = float(trade_data.get("OI Chg %", 0))
                    except: o_chg = 0.0
                    lbl, oi_color = de.compute_oi_buildup(p_chg, o_chg)
                    
                    scr, dec, flags = se.generate_conviction_score(f_metrics, t_metrics, lbl)
                    v_color = "#089981" if dec == "STRONG GO" else "#D1A553" if dec == "CAUTION" else "#F23645"
                    
                    sc1, sc2 = st.columns([1.5, 4.5])
                    with sc1:
                        st.markdown(f"<div style='padding:5px 0px; border-right:2px solid #F1F5F9; text-align:center;'><span style='font-size:38px; font-weight:800; color:{v_color}; line-height:1;'>{scr}/100</span><br><span style='font-size:16px; font-weight:700; color:{v_color}; letter-spacing:0.5px;'>{dec}</span></div>", unsafe_allow_html=True)
                    with sc2:
                        st.markdown(f"<div style='font-size:13px; font-weight:500; line-height:1.4; color:#334155; margin-left:10px;'>{' | '.join(flags)}</div>", unsafe_allow_html=True)

                # --- CONTAINER 1: DERIVATIVES PROFILE ---
                contract_meta = de.parse_option_contract(asset_symbol)
                if contract_meta:
                    with st.container(border=True):
                        st.markdown("**Derivatives Profile & Greeks (Tier 3)**")
                        try: live_option_price = float(trade_data.get('Live Price', 0))
                        except: live_option_price = 0.0
                        
                        greeks = de.calculate_greeks(
                            S=contract_meta['strike'], K=contract_meta['strike'], T=contract_meta['time_years'],
                            r=0.07, sigma=18.0 / 100.0, option_type=contract_meta['type']
                        )
                        
                        g1, g2, g3, g4, g5 = st.columns(5, gap="small")
                        g1.metric("Delta", f"{greeks['delta']}")
                        g2.metric("Theta", f"{greeks['theta']} INR")
                        g3.metric("Implied Volatility (IV)", f"{trade_data.get('Live Price', '-')}%")
                        g4.metric("PCR", "0.95")
                        with g5:
                            st.markdown(f"<span style='font-size:14px; font-weight:bold; color:#475569;'>OI Buildup Matrix</span><br><span style='font-size:18px; font-weight:bold; color:{oi_color};'>{lbl}</span>", unsafe_allow_html=True)

                # --- CONTAINER 2: MARKET INTELLIGENCE ---
                with st.container(border=True):
                    st.markdown(f"**Market Intelligence: {sym_key} (Tiers 1 & 2)**")
                    f1, f2, f3, f4, f5, f6 = st.columns(6, gap="small")
                    f1.metric("Stock P/E", f_metrics['stock_pe'])
                    f2.metric("ROE", f_metrics['roe'])
                    f3.metric("ROCE", f_metrics['roce'])
                    f4.metric("Debt to Equity", f"{f_metrics['debt_to_equity']}x")
                    f5.metric("EBITDA Margin", f_metrics['ebitda_margin'])
                    f6.metric("Inst. Ownership", f_metrics['inst_own'])
                    
                    st.markdown("<hr style='margin: 8px 0px; border: none; border-top: 1px solid #F1F5F9;'>", unsafe_allow_html=True)
                    
                    t1, t2, t3, t4, t5, t6 = st.columns(6, gap="small")
                    t1.metric("Live RSI (14)", t_metrics['rsi'])
                    t2.markdown(f"**Volume Spike**<br><span style='color:#089981; font-size:18px; font-weight:bold;'>{t_metrics['vol_spike']}%</span>" if t_metrics['vol_spike'] != "-" else "**Volume Spike**<br><span style='color:#64748B; font-size:18px;'>-</span>", unsafe_allow_html=True)
                    t3.markdown(f"**20 EMA Dist**<br><span style='{prox_color(t_metrics['ema20_prox'])} font-size:18px; font-weight:bold;'>{t_metrics['ema20_prox']}%</span>", unsafe_allow_html=True)
                    t4.markdown(f"**50 EMA Dist**<br><span style='{prox_color(t_metrics['ema50_prox'])} font-size:18px; font-weight:bold;'>{t_metrics['ema50_prox']}%</span>", unsafe_allow_html=True)
                    t5.markdown(f"**200 EMA Dist**<br><span style='{prox_color(t_metrics['ema200_prox'])} font-size:18px; font-weight:bold;'>{t_metrics['ema200_prox']}%</span>", unsafe_allow_html=True)

                with st.container(border=True):
                    st.markdown(f"**Interactive Chart & Price Action**")
                    render_tv_chart(sym_key)

                # --- POSITION EXECUTION CONTROLS ---
                with st.container(border=True):
                    st.markdown("**Execution Parameters & Repair Matrix**")
                    col1, col2, col3, col4 = st.columns(4, gap="small")
                    col1.metric("Status", trade_data.get('Status (Watch/Active/Closed)', 'N/A'))
                    col2.metric("Entry Range", trade_data.get('Entry CMP / Range', 'N/A'))
                    col3.metric("Live Price", trade_data.get('Live Price', '-'))
                    col4.metric("Exit Price", trade_data.get('Exit Price', 'Pending'))
                    
                    st.write("")
                    with st.expander("🛠 Advanced Repair Tool & Psychology Journal"):
                        st.write("Repair controls active.")

                if st.button("Unlink Review Canvas", use_container_width=True): close_journal(); st.rerun()

        else:
            # Main Terminal views
            df_stocks = filtered_df[filtered_df["Trade Type (Eq/Option)"].str.lower().isin(["equity", "stock"])].copy()
            df_options = filtered_df[filtered_df["Trade Type (Eq/Option)"].str.lower().isin(["option", "fno"])].copy()
            
            tab_stocks, tab_options, tab_heatmap = st.tabs(["Stocks", "Options", "Sector Heatmap"])
            
            def render_asset_dashboard(df_asset, asset_type):
                if df_asset.empty:
                    st.info(f"No execution matches found for the active filter selections.")
                    return
                
                sub_wl, sub_act, sub_cls = st.tabs(["Watchlist", "Active", "Closed"])
                
                with sub_wl:
                    df_wl = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
                    if not df_wl.empty:
                        st.data_editor(df_wl[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"wl_{asset_type}",
                            on_change=db.run_background_sync, kwargs={"df_filtered": df_wl, "state_key": f"wl_{asset_type}", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                    else: st.info("No records match active decision layers inside Watchlist.")
                
                with sub_act:
                    df_act = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
                    if not df_act.empty:
                        st.data_editor(df_act[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"act_{asset_type}",
                            on_change=db.run_background_sync, kwargs={"df_filtered": df_act, "state_key": f"act_{asset_type}", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                    else: st.info("No Active positions matching these rules.")
                
                with sub_cls:
                    df_cls = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
                    if not df_cls.empty:
                        st.data_editor(df_cls[view_cols], use_container_width=True, hide_index=True, num_rows="fixed", key=f"cls_{asset_type}",
                            on_change=db.run_background_sync, kwargs={"df_filtered": df_cls, "state_key": f"cls_{asset_type}", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)

            with tab_stocks: render_asset_dashboard(df_stocks, "Stocks")
            with tab_options: render_asset_dashboard(df_options, "Options")
            with tab_heatmap: st.write("Sector Heatmap view.")
