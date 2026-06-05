import streamlit as st
import pandas as pd
from datetime import datetime
import streamlit.components.v1 as components
import requests
import json
import plotly.express as px

# --- MODULE IMPORTS ---
from integrations.google_sheets import init_sheet_connection, fetch_dataframe_safe, fetch_settings_cell
from core_engines.nlp_router import SECTOR_MAP
import broker_api as api
import analytics
import scoring_engine as se
import derivatives_engine as de

# UI COMPONENTS
from ui_components import tab_options, tab_stocks, tab_study, tab_telegram, tab_scanners

st.set_page_config(page_title="ARC Trading Terminal", layout="wide", page_icon="📈")

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

def render_top_ticker_tape():
    nifty_val = fetch_settings_cell('B10')
    if nifty_val:
        nifty = format_index_display("NIFTY50", nifty_val)
        st.markdown(f"<div class='index-tape'>{nifty}</div>", unsafe_allow_html=True)

def main():
    try:
        sh, watchlist_ws, study_ws, raw_ws, scanner_ws, settings_ws = init_sheet_connection()
    except Exception as e:
        st.error(f"Critical Systems Error: Could not connect to Google Data Core. {e}")
        return

    render_top_ticker_tape()

    col_t1, col_t2 = st.columns([9, 1])
    with col_t1: st.markdown("### ARC Trading Terminal")
    with col_t2: 
        if st.button("UI Reset", use_container_width=True):
            components.html("<script>window.parent.localStorage.clear(); window.parent.location.reload();</script>", height=0, width=0)

    df_watchlist = fetch_dataframe_safe("Sheet1", is_sheet1=True)
    sheet_headers = df_watchlist.columns.tolist() if not df_watchlist.empty else []
    
    if df_watchlist.empty:
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
        if st.button("Sync Live Prices", use_container_width=True): 
            api.fetch_live_prices(watchlist_ws, scanner_ws, settings_ws, sheet_headers, scanner_ws.row_values(1) if scanner_ws else [])

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
        raw_json = fetch_settings_cell('B12')
        sec_data_list = []
        if raw_json:
            try: sec_data_list = json.loads(raw_json)
            except: pass

        if not sec_data_list and not df_watchlist.empty:
            fallback_df = df_watchlist.copy()
            fallback_df['Price Chg %'] = pd.to_numeric(fallback_df['Price Chg %'], errors='coerce').fillna(0)
            grouped = fallback_df.groupby('Sector/Industry').agg({'Price Chg %': 'mean', 'Symbol / Asset': 'count'}).reset_index()
            grouped.columns = ['sector', 'change', 'weight']
            df_sectors = grouped
        elif sec_data_list:
            df_sectors = pd.DataFrame(sec_data_list)
            df_sectors.columns = [c.lower() for c in df_sectors.columns]
        else:
            df_sectors = pd.DataFrame()

        if df_sectors.empty:
            st.info("Market performance matrices initializing. Tap 'Sync Live Prices' to update vectors.")
        else:
            df_sectors['weight'] = pd.to_numeric(df_sectors['weight'], errors='coerce').fillna(1)
            df_sectors['change'] = pd.to_numeric(df_sectors['change'], errors='coerce').fillna(0)
            
            fig = px.treemap(
                df_sectors, 
                path=['sector'], 
                values='weight', 
                color='change', 
                custom_data=['change'], 
                color_continuous_scale=['#F23645', '#F8FAFC', '#089981'], 
                color_continuous_midpoint=0
            )
            # FIX: Restored proper d3-format binding syntax for Plotly %{customdata[0]:+.2f}%
            fig.update_traces(textinfo="label+text", texttemplate="%{label}<br><b>%{customdata[0]:+.2f}%</b>", textfont=dict(size=14), root_color="rgba(0,0,0,0)")
            fig.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=460, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)

    with t_scan:
        if scanner_ws: 
            scan_headers = scanner_ws.row_values(1) if scanner_ws else []
            tab_scanners.render(scanner_ws, scan_headers)

    with t_study: tab_study.render(study_ws)
    with t_tel: tab_telegram.render(sh, watchlist_symbols, sheet_headers)

if __name__ == "__main__":
    main()
