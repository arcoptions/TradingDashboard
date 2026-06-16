import streamlit as st
import pandas as pd
import requests
import database as db
import analytics
from integrations.google_sheets import fetch_dataframe_safe, init_sheet_connection, fetch_settings_dict
import broker_api as api
from core_engines.nlp_router import FNO_SYMBOLS
from datetime import datetime
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

def render(scanner_sheet, scanner_headers):
    # Global top-level control layout alignment
    c1, c2, c3 = st.columns([6, 2, 2], vertical_alignment="bottom")
    c1.markdown("#### Automated Scan Feeds")
    execute_promote = c3.button("Promote Selected", type="primary", use_container_width=True, key="promote_scanners_top")
    
    df_scan = fetch_dataframe_safe("Scanners")
    
    if not df_scan.empty:
        df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
        df_scan = analytics.compute_scanner_signals(df_scan)
        
        all_tickers = df_scan["Symbol"].unique().tolist()
        scan_scores = run_tv_screener(all_tickers)
        df_scores = pd.DataFrame(scan_scores) if scan_scores else pd.DataFrame()
        
        if not df_scores.empty: df_scan = df_scan.merge(df_scores, left_on='Symbol', right_on='Asset', how='left')
        else: df_scan["Universal Score"] = 0
            
        df_scan["Universal Score"] = df_scan["Universal Score"].fillna(0).astype(int)
        df_scan.insert(0, "Promote", False)
        df_scan.insert(1, "Inspect", False)
        
        tab_ce1, tab_ce2, tab_pos = st.tabs(["CE1", "CE2", "Positional"])
        scan_view_cols = ["Promote", "Inspect", "Universal Score", "Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time", "Status", "Notes / Analysis", "_Sheet_Row"]
        scan_col_config = {
            "Promote": st.column_config.CheckboxColumn("Promote", width="small"),
            "Inspect": st.column_config.CheckboxColumn("Inspect", width="small"),
            "Universal Score": st.column_config.ProgressColumn("Sys Score", format="%d/3", min_value=0, max_value=3),
            "_Sheet_Row": None, 
            "Status": st.column_config.SelectboxColumn("Status", options=["Monitoring", "Moved to Watchlist", "Discarded"], required=True)
        }

        edited_dfs = {}

        def render_scanner_tab(tab_obj, filter_name):
            with tab_obj:
                df_filtered = df_scan[df_scan["Scanner"] == filter_name].reset_index(drop=True)
                if not df_filtered.empty:
                    m1, m2, m3, m4 = st.columns(4)
                    
                    holding_above = len(df_filtered[df_filtered['Vs Entry'].astype(str).str.contains('Above', na=False)])
                    slipped_below = len(df_filtered[df_filtered['Vs Entry'].astype(str).str.contains('Below', na=False)])
                    flat_pending = len(df_filtered[df_filtered['Vs Entry'].astype(str).str.contains('At Entry', na=False) | (df_filtered['Vs Entry'].astype(str) == '-')])
                    
                    m1.metric("Total Triggers", len(df_filtered))
                    m2.metric("Holding Above", holding_above)
                    m3.metric("Slipped Below", slipped_below)
                    m4.metric("Flat / Pending", flat_pending)
                    
                    st.write("")
                    
                    edited_scan = st.data_editor(
                        df_filtered[scan_view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", 
                        key=f"scan_{filter_name}", on_change=db.run_scanner_sync, 
                        kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}", "scanner_sheet": scanner_sheet, "scanner_headers": scanner_headers}, 
                        column_config=scan_col_config, disabled=["Universal Score", "Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time"]
                    )
                    edited_dfs[filter_name] = edited_scan
                    
                    # Capture Live User Interaction on Inspect Toggle
                    if not edited_scan.empty and "Inspect" in edited_scan.columns:
                        inspect_triggers = edited_scan[edited_scan["Inspect"] == True]
                        if not inspect_triggers.empty:
                            target_row = inspect_triggers.iloc[0]
                            target_symbol = str(target_row['Symbol']).upper().strip()
                            
                            # Auto-detect options if originating from CE1/CE2
                            is_fno_asset = target_symbol in FNO_SYMBOLS or "CE" in filter_name.upper()
                            
                            st.session_state.viewing_scanner_row_data = {
                                "Symbol / Asset": target_symbol,
                                "Entry CMP / Range": str(target_row.get('Trigger Price', '')),
                                "Idea Source (Chartink/Telegram/X/Self)": f"Scanner ({filter_name})",
                                "Trade Type (Eq/Option)": "Option" if is_fno_asset else "Equity",
                                "Exchange": "NSE_FNO" if is_fno_asset else "NSE_EQ",
                                "Status (Watch/Active/Closed)": "Watchlist",
                                "_Sheet_Row": -1
                            }
                            st.rerun()
                else: 
                    st.info(f"No active triggers for {filter_name}.")
                    edited_dfs[filter_name] = pd.DataFrame()
        
        render_scanner_tab(tab_ce1, "CE1")
        render_scanner_tab(tab_ce2, "CE2")
        render_scanner_tab(tab_pos, "Positional")
        
        # Global promotion processing loop
        if execute_promote:
            all_selected_frames = [df[df["Promote"] == True] for df in edited_dfs.values() if not df.empty and "Promote" in df.columns]
            
            if not all_selected_frames:
                st.warning("Please check rows to promote first.")
                return
                
            all_selected_rows = pd.concat(all_selected_frames)
            
            if all_selected_rows.empty:
                st.warning("Please check rows to promote first.")
                return
                
            sh, watchlist_ws, _, _, _, _ = init_sheet_connection()
            main_headers = watchlist_ws.row_values(1)
            bulk_watchlist_rows = []
            
            daily_token = fetch_settings_dict().get("Dhan Access Token", "")
            
            for _, row in all_selected_rows.iterrows():
                sym = str(row['Symbol']).upper().strip()
                
                # Fetch scanner name before evaluating FNO logic
                try: source_scanner = df_scan.loc[df_scan['_Sheet_Row'] == row['_Sheet_Row'], 'Scanner'].iloc[0]
                except: source_scanner = "Scanners"
                
                # --- FIXED: Auto-detect options based on Scanner category ---
                is_fno = sym in FNO_SYMBOLS or "CE" in source_scanner.upper()
                
                t_sym, t_sec, t_exch = api.resolve_instrument(sym)
                contract_symbol = sym
                
                if is_fno:
                    try:
                        chain_data = api.get_option_chain_metrics(sym, daily_token=daily_token)
                        if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                            contract_symbol = f"{sym} {chain_data['best_ce']} (Auto-Scanner)"
                    except Exception as e:
                        # Gracefully skip auto-finding best CE if option chain metrics fails
                        pass
                        
                new_row = [""] * len(main_headers)
                def fill(col, val): 
                    if col in main_headers: new_row[main_headers.index(col)] = str(val)
                fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                fill("Idea Source (Chartink/Telegram/X/Self)", f"Scanner ({source_scanner})")
                fill("Symbol / Asset", contract_symbol if is_fno else (t_sym or sym))
                fill("Trade Type (Eq/Option)", "Option" if is_fno else "Equity")
                fill("Exchange", t_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
                fill("Security ID", t_sec or "")
                fill("Status (Watch/Active/Closed)", "Watchlist")
                fill("Entry CMP / Range", str(row.get('Trigger Price', '')))
                bulk_watchlist_rows.append(new_row)
                
            if bulk_watchlist_rows:
                watchlist_ws.append_rows(bulk_watchlist_rows)
                fetch_dataframe_safe.clear()
                st.toast(f"Promoted {len(bulk_watchlist_rows)} scan targets to Watchlist!")
                time.sleep(1); st.rerun()

    else: 
        st.info("Scanner database is currently empty.")
