import streamlit as st
import pandas as pd
from integrations.google_sheets import fetch_dataframe_safe

def render(study_ws):
    st.markdown("#### Macro Research Staging Deck (`Stocks to study`)")
    st.caption("Aggregated list of high-conviction insights extracted directly from news wires and automated tickers.")
    
    df_study_log = fetch_dataframe_safe(study_ws)
    
    if not df_study_log.empty:
        st.dataframe(
            df_study_log, 
            use_container_width=True, 
            hide_index=True,
            column_config={
                "Timestamp": st.column_config.TextColumn("Time", width="small"),
                "Source": st.column_config.TextColumn("Wire Source", width="medium"),
                "Asset Ticker": st.column_config.TextColumn("Asset", width="small"),
                "Raw Text Message": st.column_config.TextColumn("News Narrative", width="large"),
                "Staging Date": st.column_config.TextColumn("Logged", width="small")
            }
        )
    else:
        st.info("No research items logged yet. New inbound entries from Beat The Street will display here automatically, or you can stage your old messages manually from the Telegram Data tab.")
