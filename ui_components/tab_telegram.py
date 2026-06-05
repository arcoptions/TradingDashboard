import streamlit as st
import pandas as pd
from datetime import datetime
from integrations.google_sheets import fetch_dataframe_safe

def render(sh, watchlist_symbols, sheet_headers):
    st.markdown("#### 📱 Telegram Inbound Data Deck")
    
    # 1. Fetch raw operational stream data
    df_raw = fetch_dataframe_safe("Raw Data")
    
    if df_raw.empty:
        st.info("No raw inbound tracking items found in the source logs.")
        return
        
    # Inject UI selection state safely if not present
    if "Stage?" not in df_raw.columns:
        df_raw.insert(0, "Stage?", False)
    else:
        df_raw["Stage?"] = df_raw["Stage?"].astype(bool)

    st.caption("Select high-conviction alerts from your operational streams to promote them to the staging decks.")

    # 2. CRITICAL FIX: Explicitly capture mutated state into a variable
    edited_df = st.data_editor(
        df_raw,
        key="telegram_data_editor",
        use_container_width=True,
        hide_index=True,
        column_config={
            "Stage?": st.column_config.CheckboxColumn("Select", default=False),
            "Timestamp": st.column_config.TextColumn("Time", disabled=True),
            "Source": st.column_config.TextColumn("Channel Source", disabled=True),
            "Asset Ticker": st.column_config.TextColumn("Asset Ticker", disabled=True),
            "Raw Text Message": st.column_config.TextColumn("Raw Stream Message", disabled=True)
        }
    )

    # 3. Execution Control Bar
    col_act, _ = st.columns([3, 7])
    with col_act:
        stage_btn = st.button("🚀 Stage Selected Rows", use_container_width=True, type="primary")
        
    if stage_btn:
        # Isolate rows marked for promotion
        selected_rows = edited_df[edited_df["Stage?"] == True]
        
        if selected_rows.empty:
            st.warning("Action Deferred: Please select at least one row using the checkboxes.")
        else:
            try:
                # Establish connection to the target research sheet
                study_ws = sh.worksheet("Stocks to study")
                
                current_date = datetime.now().strftime("%Y-%m-%d")
                rows_to_append = []
                
                # Format payload rows matching target structural expectations
                for idx, row in selected_rows.iterrows():
                    rows_to_append.append([
                        str(row.get("Timestamp", "")),
                        str(row.get("Source", "")),
                        str(row.get("Asset Ticker", "")),
                        str(row.get("Raw Text Message", "")),
                        current_date
                    ])
                
                # Commit transactional array to Google Sheets
                study_ws.append_rows(rows_to_append, value_input_option="USER_ENTERED")
                
                st.success(f"Pipeline Verified: Successfully promoted {len(rows_to_append)} rows to 'Stocks to study'!")
                
                # Clear analytical data caches to force immediate rendering refresh
                fetch_dataframe_safe.clear()
                st.rerun()
                
            except Exception as e:
                st.error(f"Pipeline Exception Encountered: Could not write records to workspace. {e}")
