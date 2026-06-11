import os
import streamlit as st
import pandas as pd
from datetime import datetime, timezone, timedelta
import streamlit.components.v1 as components
import requests
import inspect
import json
import time
import plotly.express as px

# --- MODULE IMPORTS ---
from integrations.google_sheets import init_sheet_connection, fetch_dataframe_safe, fetch_settings_dict, get_last_fetch_error
from core_engines.nlp_router import SECTOR_MAP, INDEX_CONSTITUENTS
import broker_api as api
import analytics
import scoring_engine as se
import derivatives_engine as de

# UI COMPONENTS
from ui_components import tab_options, tab_stocks, tab_study, tab_telegram, tab_scanners, trade_inspector
try:
    import modals
except ImportError:
    pass

st.set_page_config(page_title="ARC Trading Terminal", layout="wide", page_icon="📈", initial_sidebar_state="expanded")

st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        [data-testid="stToolbar"] {display: none !important;} 
        footer {visibility: hidden;}
        .block-container {padding-top: 2rem; padding-bottom: 0rem;}
        :root {
            --arc-gold-light: #F9E7BE;
            --arc-gold-mid: #D1A553;
            --arc-gold-dark: #B88A3B;
            --arc-text-dark: #1A202C; 
        }
        div[data-testid="stSidebar"] .stButton > button,
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label,
        div[data-testid="stSidebar"] div[role="radiogroup"] label[data-testid="stRadioOption"] {
            width: 100% !important; min-width: 100% !important; max-width: 100% !important;
            height: 46px !important; min-height: 46px !important; max-height: 46px !important;
            box-sizing: border-box !important; margin: 6px 0px !important; padding: 10px 16px !important;
            border-radius: 6px !important; display: flex !important; align-items: center !important;
            justify-content: flex-start !important; text-align: left !important; font-size: 15px !important;
            cursor: pointer !important; transition: all 0.15s ease-in-out !important;
        }
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child {display: none !important;}
        div[data-testid="stSidebar"] .stButton > button p, div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label p {margin: 0 !important; font-size: 15px !important;}
        div[data-testid="stSidebar"] .stButton > button[kind="primary"], .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, var(--arc-gold-light) 0%, var(--arc-gold-mid) 100%) !important; color: var(--arc-text-dark) !important; border: 1px solid var(--arc-gold-dark) !important; font-weight: 700 !important;
        }
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-checked="true"] {background: linear-gradient(135deg, var(--arc-gold-light) 0%, var(--arc-gold-mid) 100%) !important; border: 1px solid var(--arc-gold-dark) !important;}
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {background: linear-gradient(135deg, var(--arc-gold-light) 0%, var(--arc-gold-mid) 100%) !important; color: var(--arc-text-dark) !important;}
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] span {color: var(--arc-text-dark) !important;}
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label:not([data-checked="true"]) {background-color: transparent !important; border: 1px solid #E2E8F0 !important;}
        .sync-timestamp-text {font-size: 12px !important; color: #64748B !important; text-align: right !important; margin-top: -6px !important; padding-bottom: 14px !important; width: 100%;}
        
        .index-tape {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 8px 0px; 
            background-color: transparent; 
            text-align: left; 
            margin-bottom: 10px;
            display: inline-flex;
            align-items: center;
        }
    </style>
""", unsafe_allow_html=True)

# ─── RESTORED: Application Global States ───
if "viewing_trade" not in st.session_state: st.session_state.viewing_trade = None
if "viewing_trade_row" not in st.session_state: st.session_state.viewing_trade_row = None
if "viewing_scanner_row_data" not in st.session_state: st.session_state.viewing_scanner_row_data = None
if "qp_key" not in st.session_state: st.session_state.qp_key = 0
if "target_hits" not in st.session_state: st.session_state.target_hits = 0
if "sl_hits" not in st.session_state: st.session_state.sl_hits = 0

@st.cache_data(ttl=60)
def fetch_all_sectors_data():
    all_tickers = set(["NSE:NIFTY"])
    for stocks in INDEX_CONSTITUENTS.values():
        for s in stocks: all_tickers.add(f"NSE:{s}")
        
    payload = {"symbols": {"tickers": list(all_tickers)}, "columns": ["change", "close", "change_abs", "market_cap_basic"]}
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=5)
        if res.status_code == 200 and res.json().get("data"):
            return {
                item["s"].split(":")[1]: {
                    "change_pct": item["d"][0], 
                    "ltp": item["d"][1], 
                    "change_abs": item["d"][2], 
                    "mcap": item["d"][3]
                } for item in res.json()["data"]
            }
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
    except: pass
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
    except: pass
    return results_map

def render_top_ticker_tape():
    all_data = fetch_all_sectors_data()
    if "NIFTY" in all_data:
        d = all_data["NIFTY"]
        lp, diff_f, pct_f = d.get("ltp", 0), d.get("change_abs", 0), d.get("change_pct", 0)
        
        color = "#089981" if diff_f >= 0 else "#F23645"
        sign = "+" if diff_f > 0 else ""
        arrow = "▲" if diff_f >= 0 else "▼"
        
        html = f"<span style='font-size: 15px; font-weight: 500; color: #475569;'>NIFTY50</span> &nbsp;&nbsp; <span style='font-weight: 600; font-size: 16px; color: #0F172A;'>{lp:.2f}</span> &nbsp;&nbsp; <span style='color: {color}; font-size: 14px; font-weight: 500;'>{sign}{diff_f:.2f} ({sign}{pct_f:.2f}%) {arrow}</span>"
        st.markdown(f"<div class='index-tape'>{html}</div>", unsafe_allow_html=True)

def main():
    try:
        sh, watchlist_ws, study_ws, raw_ws, scanner_ws, settings_ws = init_sheet_connection()

        # Daemon thread is cache-initialized once; avoid header reads on each rerun.
        api.start_cron_daemon_v12(watchlist_ws, scanner_ws, settings_ws, [], [])
        
    except Exception as e:
        st.error(f"Critical Systems Error: Could not connect to Google Data Core. {e}")
        return

    # --- SIDEBAR NAVIGATION ---
    with st.sidebar:
        if os.path.exists("logo.png"):
            st.image("logo.png", use_container_width=True)
        elif os.path.exists("assets/logo.png"):
            st.image("assets/logo.png", use_container_width=True)
        else:
            st.markdown("<h2 style='text-align: center;'>ARC Terminal</h2>", unsafe_allow_html=True)
        
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Log New Trade", type="primary", use_container_width=True): 
            try: modals.trade_entry_modal(watchlist_ws, watchlist_ws.row_values(1))
            except Exception as modal_err: st.error(f"Logging module unavailable. {modal_err}")
            
        st.markdown("<br>", unsafe_allow_html=True)
        st.divider()
        
        with st.expander("API & Sync Setup", expanded=False):
            try: 
                settings = fetch_settings_dict()
                saved_token = settings.get("Dhan Access Token", "")
                current_sync = settings.get("Sync Interval", "60")
            except: 
                saved_token, current_sync = "", "60"
                
            new_token = st.text_input("Dhan Token:", value=saved_token, type="password")
            sync_mapping = {"30": "30 Seconds", "60": "1 Minute", "180": "3 Minutes", "300": "5 Minutes", "900": "15 Minutes"}
            rev_mapping = {v: k for k, v in sync_mapping.items()}
            
            selected_sync = st.selectbox("Background Sync Speed:", list(sync_mapping.values()), index=list(sync_mapping.keys()).index(current_sync) if current_sync in sync_mapping else 1)
            
            if st.button("Save Settings", use_container_width=True):
                settings_ws.batch_update([
                    {'range': 'A2', 'values': [["Dhan Access Token"]]},
                    {'range': 'B2', 'values': [[new_token]]},
                    {'range': 'A8', 'values': [["Sync Interval"]]},
                    {'range': 'B8', 'values': [[rev_mapping[selected_sync]]]}
                ])
                fetch_settings_dict.clear() 
                st.success("Settings Locked.")
                st.rerun()

    # --- MAIN VIEW INITIALIZATION ---
    render_top_ticker_tape()

    col_t1, col_t2 = st.columns([9, 1])
    with col_t1: st.markdown("### ARC Trading Terminal")
    with col_t2: 
        if st.button("UI Reset", use_container_width=True):
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)

    df_watchlist = fetch_dataframe_safe("Sheet1", is_sheet1=True)
    sheet_headers = df_watchlist.columns.tolist() if not df_watchlist.empty else []
    
    if df_watchlist.empty:
        last_fetch_error = get_last_fetch_error("Sheet1")
        if last_fetch_error:
            st.warning("Could not read Google Sheets data right now (likely API quota/rate limit). Try again in 30-60 seconds or increase sync interval in API & Sync Setup.")
            if st.button("Retry Loading Data", use_container_width=False):
                fetch_dataframe_safe.clear()
                st.rerun()
        else:
            st.info("Primary tracking database is empty.")
        return

    df_watchlist['_Sheet_Row'] = range(2, len(df_watchlist) + 2)
    df_watchlist["Journal"] = False
    df_watchlist = analytics.compute_signal_indicators(df_watchlist)
    df_watchlist['Base Asset'] = df_watchlist['Symbol / Asset'].apply(lambda x: str(x).split('-')[0].strip().upper())
    df_watchlist['Sector/Industry'] = df_watchlist['Base Asset'].apply(lambda x: SECTOR_MAP.get(x, "General / Mixed"))

    batch_tickers = df_watchlist['Symbol / Asset'].tolist()
    intel_pool = batch_fetch_intelligence(batch_tickers)
    
    scores_col, decisions_col = [], []
    for idx, row in df_watchlist.iterrows():
        sym_key = str(row['Symbol / Asset']).split('-')[0].strip().upper().replace("&", "_")
        pool_data = intel_pool.get(sym_key, {"f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"}, "t": {"ltp": "-", "rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}})
        p_chg = float(row.get("Price Chg %", 0) or 0)
        o_chg = float(row.get("OI Chg %", 0) or 0)
        lbl, _ = de.compute_oi_buildup(p_chg, o_chg)
        t_type = row.get("Trade Type (Eq/Option)", "Equity")
        scr, dec, _ = se.generate_conviction_score(pool_data["f"], pool_data["t"], lbl, trade_type=t_type)
        scores_col.append(scr); decisions_col.append(dec)
        
    df_watchlist["Score"] = scores_col
    df_watchlist["Decision"] = decisions_col

    # --- INSPECTION ROUTING ENGINE ---
    viewing_trade = st.session_state.get("viewing_trade_row")
    viewing_scanner = st.session_state.get("viewing_scanner_row_data")

    if viewing_trade or viewing_scanner:
        try: saved_token = fetch_settings_dict().get("Dhan Access Token", "")
        except: saved_token = ""
        
        if viewing_trade:
            trade_rows = df_watchlist[df_watchlist['_Sheet_Row'] == viewing_trade]
            if not trade_rows.empty:
                trade_inspector.render(trade_rows.iloc[0], intel_pool, saved_token, watchlist_ws, sheet_headers)
            else:
                st.error("Row context lost.")
                st.session_state.viewing_trade_row = None
                st.rerun()
        else:
            trade_data = pd.Series(viewing_scanner)
            single_intel = batch_fetch_intelligence([trade_data["Symbol / Asset"]])
            intel_pool.update(single_intel)
            
            full_mock_row = pd.Series(index=sheet_headers, dtype=str)
            full_mock_row["Symbol / Asset"] = trade_data["Symbol / Asset"]
            full_mock_row["Idea Source (Chartink/Telegram/X/Self)"] = trade_data["Idea Source (Chartink/Telegram/X/Self)"]
            full_mock_row["Trade Type (Eq/Option)"] = trade_data["Trade Type (Eq/Option)"]
            full_mock_row["Exchange"] = trade_data["Exchange"]
            full_mock_row["Status (Watch/Active/Closed)"] = "Watchlist"
            full_mock_row["Entry CMP / Range"] = trade_data["Entry CMP / Range"]
            full_mock_row["_Sheet_Row"] = -1
            
            trade_inspector.render(full_mock_row, intel_pool, saved_token, watchlist_ws, sheet_headers)
        
        return

    # --- MAIN TERMINAL RENDER ALGORITHMS ---
    watchlist_symbols = df_watchlist["Symbol / Asset"].astype(str).str.upper().tolist() + df_watchlist["Base Asset"].astype(str).str.upper().tolist()

    try:
        col_target = "Idea Source (Chartink/Telegram/X/Self)"
        raw_srcs = df_watchlist[col_target].astype(str).str.strip() if col_target in df_watchlist.columns else pd.Series()
        existing_sources = sorted(list(raw_srcs[(raw_srcs != "") & (raw_srcs != "nan") & (raw_srcs != "None")].unique()))
    except: existing_sources = []
    all_sources = sorted(list(set(["Elephant Pro", "Mr Chartist", "IndianTraderXP", "Chikou Trader", "Chartink", "Self/X"] + existing_sources)))

    f_col1, f_col2, f_col3, f_col4 = st.columns([2.5, 2.5, 3, 2], gap="small")
    with f_col1: selected_sources = st.multiselect("Filter by Source", options=all_sources, default=[])
    with f_col2: selected_decisions = st.multiselect("Filter by Decision", options=["STRONG GO", "CAUTION", "NO-GO"], default=[])
    with f_col3: selected_date_range = st.date_input("Filter by Date Range", value=(datetime.today().date(), datetime.today().date()))
    with f_col4:
        st.markdown("<div style='height:24px;'></div>", unsafe_allow_html=True)
        
        # Initialize sync throttle state
        if "last_manual_sync_time" not in st.session_state:
            st.session_state.last_manual_sync_time = 0
        
        can_sync = time.time() - st.session_state.last_manual_sync_time >= 30  # Min 30s between manual syncs
        sync_button_disabled = not can_sync
        
        if st.button("Sync Live Prices", use_container_width=True, disabled=sync_button_disabled): 
            try:
                scan_headers = scanner_ws.row_values(1) if scanner_ws else []
            except Exception:
                scan_headers = []
            
            res = api.fetch_live_prices(watchlist_ws, scanner_ws, settings_ws, sheet_headers, scan_headers)
            st.session_state.last_manual_sync_time = time.time()  # Record sync time
            
            if res == "Success":
                fetch_dataframe_safe.clear()
                fetch_settings_dict.clear()
                st.rerun()
            else:
                st.error(f"Sync issue: {res}")
        
        if sync_button_disabled:
            seconds_remaining = int(30 - (time.time() - st.session_state.last_manual_sync_time))
            st.caption(f"⏱️ Available in {seconds_remaining}s")
            
        global_sync_time = fetch_settings_dict().get("New Timestamp", "-")
        if global_sync_time and global_sync_time != "-":
            st.markdown(f"<div style='text-align: right; font-size: 11px; color: #64748B; margin-top: -10px;'>Latest Sync: <b>{global_sync_time}</b></div>", unsafe_allow_html=True)

    filtered_df = df_watchlist.copy()
    if selected_sources: filtered_df = filtered_df[filtered_df["Idea Source (Chartink/Telegram/X/Self)"].isin(selected_sources)]
    if selected_decisions: filtered_df = filtered_df[filtered_df["Decision"].isin(selected_decisions)]

    view_cols = [
        "Journal", "Base Asset", "Symbol / Asset", "Vs Entry", "Entry CMP / Range", 
        "Live Price", "Score", "Decision", "Add-On / Dip Levels", "Stop Loss (SL)", 
        "Target Status", "Target 1", "Target 2", "Exit Price", 
        "Idea Source (Chartink/Telegram/X/Self)", "Sector/Industry", "Trade Type (Eq/Option)", "Status (Watch/Active/Closed)", "_Sheet_Row"
    ]
    
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

    t_opt, t_stk, t_htmap, t_scan, t_study, t_tel = st.tabs([
        "Options", "Stocks", "Sector Heatmap", "Scanners", "Stocks to Study", "Telegram Data"
    ])

    with t_opt: tab_options.render(watchlist_ws, filtered_df, sheet_headers, view_cols, table_column_config, disabled_cols)
    with t_stk: tab_stocks.render(watchlist_ws, filtered_df, sheet_headers, view_cols, table_column_config, disabled_cols)
    
    with t_htmap: 
        if "active_heatmap_sector" not in st.session_state: st.session_state.active_heatmap_sector = None
        all_tv_data = fetch_all_sectors_data()
        
        if not all_tv_data: 
            st.info("Market mapping data initializing via TradingView API...")
        elif st.session_state.active_heatmap_sector is None:
            sector_weights = {"Nifty 50": 100, "Nifty Bank": 80, "Nifty IT": 60, "Nifty Next 50": 50, "Nifty Auto": 40, "Nifty FMCG": 40, "Nifty Energy": 40, "Nifty Metal": 30, "Nifty Pharma": 30, "Finnifty": 30, "Nifty Healthcare": 20, "Nifty Realty": 10}
            sector_data = []
            
            for sec, stocks in INDEX_CONSTITUENTS.items():
                chgs = [all_tv_data[s]["change_pct"] for s in stocks if s in all_tv_data and all_tv_data[s]["change_pct"] is not None]
                avg_chg = sum(chgs)/len(chgs) if chgs else 0.0
                sector_data.append({"Sector": sec, "Change": avg_chg, "Weight": sector_weights.get(sec, 30)})
            
            df_sectors = pd.DataFrame(sector_data)
            fig = px.treemap(df_sectors, path=['Sector'], values='Weight', color='Change', custom_data=['Change'], color_continuous_scale=['#F23645', '#F8FAFC', '#089981'], color_continuous_midpoint=0)
            fig.update_traces(textinfo="label+text", texttemplate="%{label}<br><b>%{customdata[0]:+.2f}%</b>", textfont=dict(size=14), root_color="rgba(0,0,0,0)")
            fig.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=460, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            
            if "on_select" in inspect.signature(st.plotly_chart).parameters:
                event = st.plotly_chart(fig, use_container_width=True, on_select="rerun", key="treemap")
                if event and event.get("selection", {}).get("points"):
                    st.session_state.active_heatmap_sector = event["selection"]["points"][0].get("label"); st.rerun()
            else: st.plotly_chart(fig, use_container_width=True)
        else:
            st.button("⬅️ Go back to Heat Map", type="primary", on_click=lambda: st.session_state.update({"active_heatmap_sector": None}))
            rows = [{"Stock": s.replace('HINDUNILVR', 'HUL'), "Market Cap (Cr)": round(all_tv_data[s]["mcap"]/10000000, 2) if all_tv_data[s].get("mcap") else 0.0, "LTP (₹)": all_tv_data[s]["ltp"], "Change %": all_tv_data[s]["change_pct"]} for s in INDEX_CONSTITUENTS[st.session_state.active_heatmap_sector] if s in all_tv_data]
            st.dataframe(pd.DataFrame(rows).sort_values(by="Market Cap (Cr)", ascending=False), use_container_width=True, hide_index=True)

    with t_scan:
        if scanner_ws: 
            scan_headers = scanner_ws.row_values(1) if scanner_ws else []
            tab_scanners.render(scanner_ws, scan_headers)

    with t_study: tab_study.render()
    with t_tel: tab_telegram.render(sh, watchlist_symbols, sheet_headers)

if __name__ == "__main__":
    main()
