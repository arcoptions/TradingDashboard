import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from integrations.google_sheets import fetch_dataframe_safe, init_sheet_connection, fetch_settings_dict
import broker_api as api
from core_engines.nlp_router import FNO_SYMBOLS
import time

@st.cache_data(ttl=60, show_spinner=False)
def run_tv_screener(tickers):
    results = []
    clean_tickers = [str(t).strip().upper().replace("&", "_") for t in tickers if str(t).strip() != "-" and str(t).strip() != ""]
    if not clean_tickers: return []
    tv_tickers = [f"NSE:{t}" for t in set(clean_tickers)]
    payload = {"symbols": {"tickers": tv_tickers}, "columns": ["close", "EMA20", "RSI", "volume", "average_volume_10d"]}
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=6)
        if res.status_code == 200 and res.json().get("data"):
            for item in res.json()["data"]:
                ticker = item["s"].split(":")[1]
                d = item["d"]
                ltp, ema20, rsi, vol, avg_vol = d[0] or 0, d[1] or 0, d[2] or 0, d[3] or 0, d[4] or 1
                prox = ((ltp - ema20) / ema20) * 100 if ema20 > 0 and ltp > 0 else 999
                vol_spike = (vol / avg_vol) * 100 if avg_vol > 0 else 0
                score = sum([55 <= rsi <= 75, 0 <= prox <= 6.0, vol_spike >= 150])
                results.append({"Asset": ticker, "Universal Score": int(score)})
    except: pass
    return results

def render(*args, **kwargs):
    # FIXED: Reconfigured to upper toolbar alignment
    c1, c2, c3 = st.columns([6, 2, 2], vertical_alignment="bottom")
    c1.markdown("#### Macro Research Staging Deck (Stocks to study)")
    
    df_study_log = fetch_dataframe_safe("Stocks to study")
    
    # Placeholders for late execution bindings
    selected_rows = pd.DataFrame()
    
    with c2:
        if st.button("Refresh Data", key="refresh_study", use_container_width=True):
            fetch_dataframe_safe.clear(); st.rerun()
            
    if df_study_log.empty:
        st.info("No research items logged yet.")
        return

    all_tickers = df_study_log["Asset Ticker"].unique().tolist()
    scan_results = run_tv_screener(all_tickers)
    df_scores = pd.DataFrame(scan_results) if scan_results else pd.DataFrame()
    
    if not df_scores.empty:
        df_display = df_study_log.merge(df_scores, left_on='Asset Ticker', right_on='Asset', how='left')
    else:
        df_display = df_study_log.copy()
        df_display["Universal Score"] = 0
    df_display["Universal Score"] = df_display["Universal Score"].fillna(0).astype(int)
    df_display.insert(0, "Promote to Watchlist", False)
    
    # Render data grid
    edited_df = st.data_editor(
        df_display, use_container_width=True, hide_index=True,
        column_config={
            "Promote to Watchlist": st.column_config.CheckboxColumn("Promote", width="small"),
            "Universal Score": st.column_config.ProgressColumn("Sys Score", format="%d/3", min_value=0, max_value=3),
            "Timestamp": st.column_config.TextColumn("Time", width="small"),
            "Source": st.column_config.TextColumn("Wire Source", width="medium"),
            "Asset Ticker": st.column_config.TextColumn("Asset", width="small"),
            "Raw Text Message": st.column_config.TextColumn("News Narrative", width="large")
        }
    )
    
    selected_rows = edited_df[edited_df["Promote to Watchlist"] == True]
    
    # FIXED: Compact, highly visible execution selector placed directly on top
    with c3:
        if st.button("Promote Selected", type="primary", key="promote_study_top", use_container_width=True):
            if selected_rows.empty:
                st.warning("Select items below first.")
                return
            sh, watchlist_ws, _, _, _, _ = init_sheet_connection()
            main_headers = watchlist_ws.row_values(1)
            bulk_watchlist_rows = []
            
            try:
                daily_token = fetch_settings_dict().get("Dhan Access Token", "")
            except: 
                daily_token = ""
            
            for _, row in selected_rows.iterrows():
                sym = str(row['Asset Ticker']).upper()
                is_fno = sym in FNO_SYMBOLS
                t_sym, t_sec, t_exch = api.resolve_instrument(sym)
                contract_symbol = sym
                if is_fno:
                    chain_data = api.get_option_chain_metrics(sym, daily_token=daily_token)
                    if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                        contract_symbol = f"{sym} {chain_data['best_ce']} (Auto)"
                        
                new_row = [""] * len(main_headers)
                def fill(col, val): 
                    if col in main_headers: new_row[main_headers.index(col)] = str(val)
                fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                fill("Idea Source (Chartink/Telegram/X/Self)", str(row['Source']))
                fill("Symbol / Asset", contract_symbol if is_fno else (t_sym or sym))
                fill("Trade Type (Eq/Option)", "Option" if is_fno else "Equity")
                fill("Exchange", t_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
                fill("Security ID", t_sec or "")
                fill("Status (Watch/Active/Closed)", "Watchlist")
                fill("Raw Tip Text", str(row['Raw Text Message']))
                bulk_watchlist_rows.append(new_row)
                
            if bulk_watchlist_rows:
                watchlist_ws.append_rows(bulk_watchlist_rows)
                fetch_dataframe_safe.clear()
                st.toast("Promoted to main Watchlist")
                time.sleep(1); st.rerun()
