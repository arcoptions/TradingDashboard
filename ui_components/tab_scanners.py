import streamlit as st
import pandas as pd
import database as db
import analytics
from integrations.google_sheets import fetch_dataframe_safe, init_sheet_connection, fetch_settings_cell
import broker_api as api
from core_engines.nlp_router import FNO_SYMBOLS
from datetime import datetime
import time

def render(scanner_sheet, scanner_headers):
    st.markdown("#### Automated Scan Feeds")
    df_scan = fetch_dataframe_safe("Scanners")
    
    if not df_scan.empty:
        df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
        df_scan = analytics.compute_scanner_signals(df_scan)
        
        # Inject promotion checkbox
        df_scan.insert(0, "Promote", False)
        
        tab_ce1, tab_ce2, tab_pos = st.tabs(["CE1", "CE2", "Positional"])
        scan_view_cols = ["Promote", "Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time", "Status", "Notes / Analysis", "_Sheet_Row"]
        scan_col_config = {
            "Promote": st.column_config.CheckboxColumn("Promote 🚀", width="small"),
            "_Sheet_Row": None, 
            "Status": st.column_config.SelectboxColumn("Status", options=["Monitoring", "Moved to Watchlist", "Discarded"], required=True)
        }

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
                    
                    edited_scan = st.data_editor(
                        df_filtered[scan_view_cols], 
                        use_container_width=True, hide_index=True, num_rows="dynamic", 
                        key=f"scan_{filter_name}", on_change=db.run_scanner_sync, 
                        kwargs={"df_filtered": df_filtered, "state_key": f"scan_{filter_name}", "scanner_sheet": scanner_sheet, "scanner_headers": scanner_headers}, 
                        column_config=scan_col_config, 
                        disabled=["Date Added", "Symbol", "Trigger Price", "Live Price", "Vs Entry", "Trigger Time"]
                    )
                    
                    selected_rows = edited_scan[edited_scan["Promote"] == True]
                    if st.button(f"⚡ Promote Selected {filter_name} Scans to Watchlist", key=f"btn_{filter_name}", use_container_width=True):
                        if selected_rows.empty:
                            st.warning("Please select at least one row to promote.")
                            return
                            
                        sh, watchlist_ws, _, _, _, _ = init_sheet_connection()
                        main_headers = watchlist_ws.row_values(1)
                        bulk_watchlist_rows = []
                        daily_token = fetch_settings_cell('B2') or ""
                        
                        for _, row in selected_rows.iterrows():
                            sym = str(row['Symbol']).upper().strip()
                            is_fno = sym in FNO_SYMBOLS
                            t_sym, t_sec, t_exch = api.resolve_instrument(sym)
                            contract_symbol = sym
                            
                            if is_fno:
                                chain_data = api.get_option_chain_metrics(sym, daily_token=daily_token)
                                if chain_data and chain_data.get('best_ce') and chain_data.get('best_ce') != "-":
                                    contract_symbol = f"{sym} {chain_data['best_ce']} (Auto-Scanner)"
                                    
                            new_row = [""] * len(main_headers)
                            def fill(col, val): 
                                if col in main_headers: new_row[main_headers.index(col)] = str(val)
                                
                            fill("Trade Date", datetime.today().strftime("%Y-%m-%d"))
                            fill("Idea Source (Chartink/Telegram/X/Self)", f"Scanner ({filter_name})")
                            fill("Symbol / Asset", contract_symbol if is_fno else (t_sym or sym))
                            fill("Trade Type (Eq/Option)", "Option" if is_fno else "Equity")
                            fill("Exchange", t_exch or ("NSE_FNO" if is_fno else "NSE_EQ"))
                            fill("Security ID", t_sec or "")
                            fill("Status (Watch/Active/Closed)", "Watchlist")
                            fill("Entry CMP / Range", str(row.get('Trigger Price', '')))
                            
                            bulk_watchlist_rows.append(new_row)
                            
                        if bulk_watchlist_rows:
                            watchlist_ws.append_rows(bulk_watchlist_rows)
                            st.toast(f"Successfully promoted {len(bulk_watchlist_rows)} scan targets to Watchlist!")
                            fetch_dataframe_safe.clear()
                            time.sleep(1)
                            st.rerun()
                else: 
                    st.info(f"No active triggers for {filter_name}.")
        
        render_scanner_tab(tab_ce1, "CE1")
        render_scanner_tab(tab_ce2, "CE2")
        render_scanner_tab(tab_pos, "Positional")
    else:
        st.info("Scanner database is currently empty.")
