import streamlit as st
import pandas as pd
import database as db
import analytics
from integrations.google_sheets import fetch_dataframe_safe

def render(scanner_sheet, scanner_headers):
    st.markdown("#### Automated Scan Feeds")
    df_scan = fetch_dataframe_safe("Scanners")
    
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
