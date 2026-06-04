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
      new TradingView.widget({{"autosize": true, "symbol": "{tv_ticker}", "interval": "D", "timezone": "Asia/Kolkata", "theme": "light", "style": "1", "locale": "in", "enable_publishing": false, "backgroundColor": "#ffffff", "gridColor": "#F1F5F9", "hide_top_toolbar": false, "container_id": "tv_chart"}});
      </script>
    </div>
    """
    components.html(html, height=400)

@st.cache_data(ttl=60)
def fetch_live_heatmap():
    """Unblockable TradingView fetcher for Sectoral Heatmap Indices"""
    sectors = {
        "Financial Services": {"ticker": "NSE:NIFTY_FIN_SERVICE", "weight": 35.0},
        "IT": {"ticker": "NSE:NIFTY_IT", "weight": 14.5},
        "Oil & Gas / Energy": {"ticker": "NSE:NIFTY_ENERGY", "weight": 12.0},
        "FMCG": {"ticker": "NSE:NIFTY_FMCG", "weight": 9.0},
        "Auto": {"ticker": "NSE:NIFTY_AUTO", "weight": 7.0},
        "Pharma": {"ticker": "NSE:NIFTY_PHARMA", "weight": 5.0},
        "Metal": {"ticker": "NSE:NIFTY_METAL", "weight": 4.0},
        "Realty": {"ticker": "NSE:NIFTY_REALTY", "weight": 1.0},
        "Media": {"ticker": "NSE:NIFTY_MEDIA", "weight": 0.5}
    }
    payload = {"symbols": {"tickers": [v["ticker"] for v in sectors.values()]}, "columns": ["change"]}
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=5)
        if res.status_code == 200 and res.json().get("data"):
            data_map = {item["s"]: item["d"][0] for item in res.json()["data"]}
            return pd.DataFrame([{"sector": name, "change": round(data_map.get(info["ticker"], 0.0), 2), "weight": info["weight"]} for name, info in sectors.items()])
    except Exception as e: print(f"Heatmap Engine Error: {e}")
    return pd.DataFrame()

@st.cache_data(ttl=15)
def batch_fetch_intelligence(symbols_list):
    results_map = {}
    if not symbols_list: return results_map
    clean_tickers = list(set([str(s).split('-')[0].strip().upper().replace("&", "_") for s in symbols_list]))
    tv_tickers = [f"NSE:{t}" for t in clean_tickers]
    payload = {"symbols": {"tickers": tv_tickers}, "columns": ["price_earnings_ttm", "price_earnings_forward", "return_on_equity", "debt_to_equity", "operating_margin", "net_margin", "return_on_invested_capital", "institutions_ownership", "close", "EMA20", "EMA50", "EMA200", "RSI", "volume", "average_volume_10d"]}
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=6)
        if res.status_code == 200 and res.json().get("data"):
            for item in res.json()["data"]:
                ticker_raw = item["s"].split(":")[cite: 1]
                d = item["d"]
                f_m = {"stock_pe": round(d[0], 2) if d[0] is not None else "-", "forward_pe": round(d[cite: 1], 2) if d[cite: 1] is not None else "-", "sector_pe": 20.0, "roe": f"{round(d[2], 2)}%" if d[2] is not None else "-", "debt_to_equity": round(d[3], 2) if d[3] is not None else "-", "ebitda_margin": f"{round(d[4], 2)}%" if d[4] is not None else "-", "pat_margin": f"{round(d[5], 2)}%" if d[5] is not None else "-", "roce": f"{round(d[6], 2)}%" if d[6] is not None else "-", "inst_own": f"{round(d[7], 2)}%" if d[7] is not None else "-"}
                t_m = {"rsi": round(d[12], 2) if d[12] is not None else "-", "vol_spike": round((d[13] / d[14]) * 100, 2) if d[13] and d[14] and d[14] > 0 else "-", "ema20_prox": round(((d[8] - d[9]) / d[9]) * 100, 2) if d[9] and d[8] else "-", "ema50_prox": round(((d[8] - d[10]) / d[10]) * 100, 2) if d[10] and d[8] else "-", "ema200_prox": round(((d[8] - d[11]) / d[11]) * 100, 2) if d[11] and d[8] else "-"}
                results_map[ticker_raw] = {"f": f_m, "t": t_m}
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

def check_for_audio_alerts(df_act):
    current_targets = len(df_act[df_act['Target Status'] == '🎯 Reached'])
    sl_hits = 0
    for idx, row in df_act.iterrows():
        try:
            live = float(str(row.get('Live Price', '')).strip())
            sl_digits = re.findall(r'[\d\.]+', str(row.get('Stop Loss (SL)', '')).strip())
            if sl_digits and live <= float(sl_digits[0]): sl_hits += 1
        except: pass
    if "audio_initialized" not in st.session_state:
        st.session_state.target_hits = current_targets
        st.session_state.sl_hits = sl_hits
        st.session_state.audio_initialized = True
        return
    if current_targets > st.session_state.target_hits:
        st.markdown(f'<audio autoplay style="display:none;"><source src="https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3" type="audio/mpeg"></audio>', unsafe_allow_html=True)
        st.session_state.target_hits = current_targets
    if sl_hits > st.session_state.sl_hits:
        st.markdown(f'<audio autoplay style="display:none;"><source src="https://assets.mixkit.co/active_storage/sfx/2870/2870-preview.mp3" type="audio/mpeg"></audio>', unsafe_allow_html=True)
        st.session_state.sl_hits = sl_hits

def render_options_tracker(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    render_top_ticker_tape(settings_sheet)
    col_t1, col_t2 = st.columns([cite: 1])
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

        batch_tickers = initial_df['Symbol / Asset'].tolist()
        intel_pool = batch_fetch_intelligence(batch_tickers)
        
        scores_col, decisions_col = [], []
        for idx, row in initial_df.iterrows():
            sym_key = str(row['Symbol / Asset']).split('-')[0].strip().upper().replace("&", "_")
            pool_data = intel_pool.get(sym_key, {"f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"}, "t": {"rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}})
            p_chg = float(row.get("Price Chg %", 0) or 0)
            o_chg = float(row.get("OI Chg %", 0) or 0)
            lbl, _ = de.compute_oi_buildup(p_chg, o_chg)
            scr, dec, _ = se.generate_conviction_score(pool_data["f"], pool_data["t"], lbl)
            scores_col.append(scr); decisions_col.append(dec)
            
        initial_df["Score"] = scores_col
        initial_df["Decision"] = decisions_col
        
        try:
            col_target = "Idea Source (Chartink/Telegram/X/Self)"
            if col_target in initial_df.columns:
                raw_srcs = initial_df[col_target].astype(str).str.strip()
                existing_sources = sorted(list(raw_srcs[(raw_srcs != "") & (raw_srcs != "nan") & (raw_srcs != "None")].unique()))
            else: existing_sources = []
        except: existing_sources = []
        
        all_sources = sorted(list(set(["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chikou Trader", "Chartink", "Self/X"] + existing_sources)))
        
        # UI Filters
        f_col1, f_col2, f_col3 = st.columns([3, 3, 4], gap="medium")
        with f_col1: selected_sources = st.multiselect("Filter by Source", options=all_sources, default=[])
        with f_col2: selected_decisions = st.multiselect("Filter by Decision", options=["STRONG GO", "CAUTION", "NO-GO"], default=[])
        with f_col3:
            st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
            if st.button("Sync Live Prices", use_container_width=True): 
                api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)

        filtered_df = initial_df.copy()
        if selected_sources: filtered_df = filtered_df[filtered_df["Idea Source (Chartink/Telegram/X/Self)"].isin(selected_sources)]
        if selected_decisions: filtered_df = filtered_df[filtered_df["Decision"].isin(selected_decisions)]
        
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
        disabled_cols = ["Decision", "Score", "Base Asset", "Sector/Industry", "Live Price", "Vs Entry", "Target Status"]
        
        if st.session_state.get("viewing_trade_row"):
            if st.button("Back to Terminal"): 
                st.session_state.viewing_trade = None
                st.session_state.viewing_trade_row = None
                st.rerun()
                
            trade_rows = initial_df[initial_df['_Sheet_Row'] == st.session_state.viewing_trade_row]
            if not trade_rows.empty:
                trade_data = trade_rows.iloc[0]; sheet_row_id = int(trade_data['_Sheet_Row']); asset_symbol = trade_data['Symbol / Asset']
                sym_key = str(asset_symbol).split('-')[0].strip().upper().replace("&", "_")
                pool_data = intel_pool.get(sym_key, {"f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"}, "t": {"rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}})
                f_metrics = pool_data["f"]; t_metrics = pool_data["t"]
                
                with st.container(border=True):
                    p_chg = float(trade_data.get("Price Chg %", 0) or 0)
                    o_chg = float(trade_data.get("OI Chg %", 0) or 0)
                    lbl, oi_color = de.compute_oi_buildup(p_chg, o_chg)
                    scr, dec, flags = se.generate_conviction_score(f_metrics, t_metrics, lbl)
                    v_color = "#089981" if dec == "STRONG GO" else "#D1A553" if dec == "CAUTION" else "#F23645"
                    sc1, sc2 = st.columns([1.5, 4.5])
                    sc1.markdown(f"<div style='text-align:center;'><span style='font-size:38px; font-weight:800; color:{v_color};'>{scr}/100</span><br><span style='font-size:16px; font-weight:700; color:{v_color};'>{dec}</span></div>", unsafe_allow_html=True)
                    sc2.markdown(f"<div style='font-size:13px; font-weight:500; color:#334155;'>{' | '.join(flags)}</div>", unsafe_allow_html=True)
                
                contract_meta = de.parse_option_contract(asset_symbol)
                if contract_meta:
                    with st.container(border=True):
                        st.markdown("**Derivatives Profile & Greeks (Tier 3)**")
                        try: live_option_price = float(trade_data.get('Live Price', 0))
                        except: live_option_price = 0.0
                        greeks = de.calculate_greeks(S=contract_meta['strike'], K=contract_meta['strike'], T=contract_meta['time_years'], r=0.07, sigma=18.0 / 100.0, option_type=contract_meta['type'])
                        g1, g2, g3, g4, g5 = st.columns(5)
                        g1.metric("Delta", f"{greeks['delta']}")
                        g2.metric("Theta", f"{greeks['theta']} INR")
                        g3.metric("Implied Volatility", f"{trade_data.get('Live Price', '-')}%")
                        g4.metric("PCR", "0.95")
                        g5.markdown(f"<span style='font-size:14px; font-weight:bold; color:#475569;'>OI Matrix</span><br><span style='font-size:18px; font-weight:bold; color:{oi_color};'>{lbl}</span>", unsafe_allow_html=True)
                
                with st.container(border=True):
                    st.markdown("**Market Intelligence**")
                    f1, f2, f3, f4, f5, f6 = st.columns(6)
                    f1.metric("P/E", f_metrics['stock_pe']); f2.metric("ROE", f_metrics['roe']); f3.metric("ROCE", f_metrics['roce']); f4.metric("D/E", f"{f_metrics['debt_to_equity']}x"); f5.metric("EBITDA", f_metrics['ebitda_margin']); f6.metric("Inst.", f_metrics['inst_own'])
                    t1, t2, t3, t4, t5 = st.columns(5)
                    t1.metric("RSI", t_metrics['rsi']); t2.markdown(f"**20 EMA**<br><span style='{prox_color(t_metrics['ema20_prox'])}'>{t_metrics['ema20_prox']}%</span>", unsafe_allow_html=True); t3.markdown(f"**50 EMA**<br><span style='{prox_color(t_metrics['ema50_prox'])}'>{t_metrics['ema50_prox']}%</span>", unsafe_allow_html=True); t4.markdown(f"**200 EMA**<br><span style='{prox_color(t_metrics['ema200_prox'])}'>{t_metrics['ema200_prox']}%</span>", unsafe_allow_html=True); t5.metric("Vol Spike", f"{t_metrics['vol_spike']}%" if t_metrics['vol_spike'] != "-" else "-")
                
                with st.container(border=True):
                    st.markdown("**Interactive Chart**")
                    render_tv_chart(sym_key)
                    
                with st.container(border=True):
                    st.markdown("**Execution Parameters & Repair Matrix**")
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
                        except: st.info("Awaiting exit price.")
                    
                    with st.expander("🛠 Advanced Repair Tool & Psychology Journal"):
                        default_search = str(trade_data['Symbol / Asset']).split()[0]
                        fix_query = st.text_input("Search Official Master Database", value=default_search, key="fix_contract_query")
                        fix_results = api.search_instruments(fix_query)
                        if not fix_results.empty:
                            selected_fix = st.selectbox("Select Correct Contract:", fix_results['SEM_TRADING_SYMBOL'].tolist(), key="fix_contract_select")
                            if st.button("Save & Re-Link Asset", type="primary", use_container_width=True):
                                fix_row = fix_results[fix_results['SEM_TRADING_SYMBOL'] == selected_fix].iloc[0]
                                updated_symbol = str(fix_row['SEM_TRADING_SYMBOL'])
                                updated_sec_id = str(fix_row['SEM_SMST_SECURITY_ID'])
                                exch, seg = str(fix_row['SEM_EXM_EXCH_ID']), str(fix_row['SEM_SEGMENT'])
                                updated_exch = "NSE_EQ" if exch == "NSE" and seg == "E" else "NSE_FNO"
                                worksheet.update_cell(sheet_row_id, sheet_headers.index("Symbol / Asset") + 1, updated_symbol)
                                worksheet.update_cell(sheet_row_id, sheet_headers.index("Security ID") + 1, updated_sec_id)
                                worksheet.update_cell(sheet_row_id, sheet_headers.index("Exchange") + 1, updated_exch)
                                st.session_state.viewing_trade = updated_symbol
                                st.rerun()
                                
                        with st.form("psychology_update_form"):
                            curr_rationale = str(trade_data.get('Strategic Rationale (Why I took it)', ''))
                            curr_emotions = str(trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', ''))
                            new_rationale = st.text_area("Execution Rationale", value=curr_rationale if curr_rationale != 'nan' else '')
                            new_emotions = st.text_area("Psychological State", value=curr_emotions if curr_emotions != 'nan' else '')
                            if st.form_submit_button("Update Records", type="primary"):
                                worksheet.update_cell(sheet_row_id, sheet_headers.index("Strategic Rationale (Why I took it)") + 1, str(new_rationale))
                                worksheet.update_cell(sheet_row_id, sheet_headers.index("Emotions at Entry (FOMO, Calm, etc.)") + 1, str(new_emotions))
                                st.rerun()
                
                if st.button("Unlink Review Canvas", use_container_width=True):
                    st.session_state.viewing_trade = None
                    st.session_state.viewing_trade_row = None
                    st.rerun()
        else:
            df_stocks = filtered_df[filtered_df["Trade Type (Eq/Option)"].str.lower().isin(["equity", "stock"])].copy()
            df_options = filtered_df[filtered_df["Trade Type (Eq/Option)"].str.lower().isin(["option", "fno"])].copy()
            
            tab_stocks, tab_options, tab_heatmap = st.tabs(["Stocks", "Options", "Sector Heatmap"])
            
            def render_asset_dashboard(df_asset, asset_type):
                if df_asset.empty:
                    st.info(f"No execution matches found.")
                    return
                sub_wl, sub_act, sub_cls = st.tabs(["Watchlist", "Active", "Closed"])
                
                with sub_wl:
                    df_wl = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
                    if not df_wl.empty:
                        st.data_editor(df_wl[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"wl_{asset_type}", on_change=db.run_background_sync, kwargs={"df_filtered": df_wl, "state_key": f"wl_{asset_type}", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                    else: st.info("No records match active decision layers inside Watchlist.")
                
                with sub_act:
                    df_act = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
                    if not df_act.empty:
                        st.data_editor(df_act[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"act_{asset_type}", on_change=db.run_background_sync, kwargs={"df_filtered": df_act, "state_key": f"act_{asset_type}", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
                    else: st.info("No Active positions matching these rules.")
                
                with sub_cls:
                    df_cls = df_asset[df_asset["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
                    if not df_cls.empty:
                        st.data_editor(df_cls[view_cols], use_container_width=True, hide_index=True, num_rows="fixed", key=f"cls_{asset_type}", on_change=db.run_background_sync, kwargs={"df_filtered": df_cls, "state_key": f"cls_{asset_type}", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)

            with tab_stocks: render_asset_dashboard(df_stocks, "Stocks")
            with tab_options: render_asset_dashboard(df_options, "Options")
            with tab_heatmap: 
                st.markdown("#### Live NIFTY Sector Performance")
                st.caption("Powered by Institutional TradingView Engine")
                if st.button("Refresh Market Map", use_container_width=True, key="sync_heatmap"): 
                    fetch_live_heatmap.clear()
                
                df_heat = fetch_live_heatmap()
                if not df_heat.empty:
                    fig = px.treemap(df_heat, path=['sector'], values='weight', color='change', color_continuous_scale=['#F23645', '#F8FAFC', '#089981'], color_continuous_midpoint=0)
                    fig.update_traces(textinfo="label+text", texttemplate="%{label}<br><b>%{customdata[0]:.2f}%</b>", customdata=df_heat[['change']], textfont=dict(size=16))
                    fig.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=500)
                    st.plotly_chart(fig, use_container_width=True)
                else: 
                    st.info("Market map data is synchronizing...")

def render_chartink_scanners(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    render_top_ticker_tape(settings_sheet)
    col_t1, col_t2 = st.columns([cite: 1], vertical_alignment="bottom")
    with col_t1: st.markdown("### Automated Scan Feeds")
    with col_t2: 
        if st.button("UI Reset", help="Reset systems context layer", use_container_width=True):
            import streamlit.components.v1 as components
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)
            
    col1, col2 = st.columns([8, 2], vertical_alignment="bottom")
    with col1: st.write("")
    with col2:
        if st.button("Sync Live Prices", use_container_width=True, key="sync_scanner"):
            api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
            
    scanner_data = scanner_sheet.get_all_records()
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
                    st.data_editor(
                        df_filtered[scan_view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key=f"scan_{filter_name}",
                        on_change=db.run_scanner_sync, kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}", "scanner_sheet": scanner_sheet, "scanner_headers": scanner_headers},
                        column_config=scan_col_config, disabled=["Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time"]
                    )
                else: st.info(f"No active triggers for {filter_name}.")
        
        render_scanner_tab(tab_ce1, "CE1")
        render_scanner_tab(tab_ce2, "CE2")
        render_scanner_tab(tab_pos, "Positional")
