import streamlit as st
import pandas as pd
import requests
from datetime import datetime
from integrations.google_sheets import fetch_dataframe_safe, init_sheet_connection, fetch_settings_cell
import broker_api as api
from core_engines.nlp_router import FNO_SYMBOLS

@st.cache_data(ttl=60, show_spinner=False)
def run_tv_screener(tickers):
    """Batch requests TradingView to mathematically grade all incubator stocks."""
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
                
                ltp = d[0] if d[0] else 0
                ema20 = d[1] if d[1] else 0
                rsi = d[2] if d[2] else 0
                vol = d[3] if d[3] else 0
                avg_vol = d[4] if d[4] else 1 
                
                if ema20 > 0 and ltp > 0: prox = ((ltp - ema20) / ema20) * 100
                else: prox = 999
                
                vol_spike = (vol / avg_vol) * 100 if avg_vol > 0 else 0
                
                is_rsi_good = 55 <= rsi <= 75
                is_prox_good = 0 <= prox <= 6.0
                is_vol_good = vol_spike >= 150
                score = sum([is_rsi_good, is_prox_good, is_vol_good])
                
                results.append({
                    "Asset": ticker, "LTP": round(ltp, 2), "RSI": round(rsi, 2), "EMA 20 Prox": f"{round(prox, 2)}%",
                    "Vol Spike": f"{round(vol_spike, 0)}%", "Universal Score": int(score)
                })
    except: pass
    return results

def render(*args, **kwargs):
    c1, c2 = st.columns([8, 2])
    c1.markdown("#### Macro Research Staging Deck (`Stocks to study`)")
    if c2.button("🔄 Refresh Data", key="refresh_study"):
        fetch_dataframe_safe.clear()
        st.rerun()
        
    df_study_log = fetch_dataframe_safe("Stocks to study")
    
    if df_study_log.empty:
        st.info("No research items logged yet.")
        return

    # Run background scoring
    all_tickers = df_study_log["Asset Ticker"].unique().tolist()
    scan_results = run_tv_screener(all_tickers)
    df_scores = pd.DataFrame(scan_results) if scan_results else pd.DataFrame()
    
    if not df_scores.empty:
        df_display = df_study_log.merge(df_scores, left_on='Asset Ticker', right_on='Asset', how='left')
    else:
        df_display = df_study_log.copy()
        df_display["Universal Score"] = 0

    df_display.insert(0, "Promote to Watchlist", False)
    
    st.markdown("Review macro discussions and execution scores. Check the box to auto-promote an asset to the execution desk.")
    edited_df = st.data_editor(
        df_display, 
        use_container_width=True, 
        hide_index=True,
        column_config={
            "Promote to Watchlist": st.column_config.CheckboxColumn("Promote 🚀", width="small"),
            "Universal Score": st.column_config.ProgressColumn("Sys Score", format="%d/3", min_value=0, max_value=3),
            "Timestamp": st.column_config.TextColumn("Time", width="small"),
            "Source": st.column_config.TextColumn("Wire Source", width="medium"),
            "Asset Ticker": st.column_config.TextColumn("Asset", width="small"),
            "Raw Text Message": st.column_config.TextColumn("News Narrative", width="large")
        }
    )
    
    selected_rows = edited_df[edited_df["Promote to Watchlist"] == True]
    
    if st.button("⚡ Execute Promotion to Main Watchlist", type="primary", use_container_width=True):
        if selected_rows.empty:
            st.warning("Please select at least one row.")
            return
            
        sh, watchlist_ws, _, _, _, _ = init_sheet_connection()
        sheet_headers = watchlist_ws.row_values(1)
        bulk_watchlist_rows = []
        daily_token = fetch_settings_cell('B2') or ""
        
        for _, row in selected_rows.iterrows():
            sym = str(row['Asset Ticker']).upper()
            is_fno = sym in FNO_SYMBOLS
            t_sym, t_sec, t_exch = api.resolve_instrument(sym)
            contract_symbol = sym
            
            if is_fno:
                chain_data = api.get_option_chain_metrics(sym, daily_token=daily_token)
                if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                    contract_symbol = f"{sym} {chain_data['best_ce']} (Auto)"
                    
            new_row = [""] * len(sheet_headers)
            def fill(col, val): 
                if col in sheet_headers: new_row[sheet_headers.index(col)] = str(val)
                
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
            st.toast(f"Successfully promoted {len(bulk_watchlist_rows)} stocks to Watchlist!")
            fetch_dataframe_safe.clear()
            time.sleep(1)
            st.rerun()
