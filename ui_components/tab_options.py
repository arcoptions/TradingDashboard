import streamlit as st
import pandas as pd
import database as db
import analytics
import derivatives_engine as de
import scoring_engine as se
from core_engines.nlp_router import SECTOR_MAP
from integrations.google_sheets import fetch_dataframe_safe

def render(worksheet, initial_df, sheet_headers, view_cols, table_column_config, disabled_cols):
    if initial_df.empty:
        st.info("No execution matches found.")
        return

    df_options = initial_df[initial_df["Trade Type (Eq/Option)"].str.lower().isin(["option", "fno"])].copy()
    if df_options.empty:
        st.info("No Options data found.")
        return

    sub_wl, sub_act, sub_cls = st.tabs(["Watchlist", "Active", "Closed"])
    
    with sub_wl:
        df_wl = df_options[df_options["Status (Watch/Active/Closed)"].isin(["Watchlist"])].copy().reset_index(drop=True)
        if not df_wl.empty: 
            st.data_editor(df_wl[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key="wl_Options", on_change=db.run_background_sync, kwargs={"df_filtered": df_wl, "state_key": "wl_Options", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
    
    with sub_act:
        df_act = df_options[df_options["Status (Watch/Active/Closed)"].isin(["Active"])].copy().reset_index(drop=True)
        if not df_act.empty: 
            st.data_editor(df_act[view_cols], use_container_width=True, hide_index=True, num_rows="dynamic", key="act_Options", on_change=db.run_background_sync, kwargs={"df_filtered": df_act, "state_key": "act_Options", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
    
    with sub_cls:
        df_cls = df_options[df_options["Status (Watch/Active/Closed)"].isin(["Closed"])].copy().reset_index(drop=True)
        if not df_cls.empty: 
            st.data_editor(df_cls[view_cols], use_container_width=True, hide_index=True, num_rows="fixed", key="cls_Options", on_change=db.run_background_sync, kwargs={"df_filtered": df_cls, "state_key": "cls_Options", "worksheet": worksheet, "sheet_headers": sheet_headers}, column_config=table_column_config, disabled=disabled_cols)
