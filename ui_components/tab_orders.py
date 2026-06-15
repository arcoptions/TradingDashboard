import pandas as pd
import streamlit as st

import broker_api as api
from integrations.google_sheets import fetch_dataframe_safe


ACTIVE_ORDER_STATUSES = ["TRANSIT", "PENDING", "PART_TRADED"]
ACTIVE_POSITION_TYPES = ["LONG", "SHORT"]


def render():
    st.markdown("#### Dhan Live Positions")
def render(intel_pool=None):
    st.markdown("#### Dhan Live Positions")

    top_left, top_mid, top_right = st.columns([1.1, 1.2, 3.2])
    with top_left:
        show_active_only = st.checkbox("Active only", value=True, key="dhan_positions_active_only")
    with top_mid:
        auto_refresh = st.checkbox("Auto refresh", value=False, key="dhan_positions_auto_refresh")
    with top_right:
        if st.button("Refresh Dhan Data", key="dhan_positions_refresh"):
            st.cache_data.clear()

    if auto_refresh:
        st.caption("Auto refresh is enabled. The view refreshes every 15 seconds while this tab is open.")

    df_positions, error_msg = api.fetch_dhan_positions()
    if error_msg:
        st.error(error_msg)
        return

    if not df_positions.empty and show_active_only and "positionType" in df_positions.columns:
        df_positions = df_positions[df_positions["positionType"].astype(str).str.upper().isin(ACTIVE_POSITION_TYPES)].copy()
        if "netQty" in df_positions.columns:
            df_positions = df_positions[df_positions["netQty"].fillna(0) != 0].copy()

    if df_positions.empty:
        st.info("No active Dhan positions right now.")
    else:
        # Fetch watchlist to get score, recommendation, and targets
        try:
            df_watchlist = fetch_dataframe_safe("Sheet1", is_sheet1=True)
        except Exception:
            df_watchlist = pd.DataFrame()

        # Prepare positions data
        df_positions_custom = df_positions.copy()
        df_positions_custom["Symbol"] = df_positions_custom.get("tradingSymbol", "")
        
        # Extract base symbol (remove expiry/strike info for options)
        df_positions_custom["BaseSymbol"] = df_positions_custom["Symbol"].str.split('-').str[0].str.strip()
        
        # Join with watchlist data
        if not df_watchlist.empty:
            # Create lookup from watchlist (match by Symbol or Base Asset)
            watchlist_lookup = {}
            for _, row in df_watchlist.iterrows():
                sym = str(row.get("Symbol / Asset", "")).strip().upper()
                base = str(row.get("Base Asset", "")).strip().upper()
                
                score = row.get("Score", "-")
                recommendation = row.get("Recommendation", "-")
                sl = str(row.get("Stop Loss (SL)", "")).strip()
                t1 = str(row.get("Target 1", "")).strip()
                t2 = str(row.get("Target 2", "")).strip()
                ltp = str(row.get("Live Price", "")).strip()
                
                entry = {
                    "Score": score,
                    "Recommendation": recommendation,
                    "SL": sl,
                    "T1": t1,
                    "T2": t2,
                    "LTP": ltp,
                }
                
                if sym:
                    watchlist_lookup[sym] = entry
                if base:
                    watchlist_lookup[base] = entry
            
            # Match positions with watchlist
            df_positions_custom["Score"] = df_positions_custom["BaseSymbol"].apply(
                lambda x: watchlist_lookup.get(x.upper(), {}).get("Score", "-")
            )
            df_positions_custom["Recommendation"] = df_positions_custom["BaseSymbol"].apply(
                lambda x: watchlist_lookup.get(x.upper(), {}).get("Recommendation", "-")
            )
            df_positions_custom["SL"] = df_positions_custom["BaseSymbol"].apply(
                lambda x: watchlist_lookup.get(x.upper(), {}).get("SL", "-")
            )
            df_positions_custom["T1"] = df_positions_custom["BaseSymbol"].apply(
                lambda x: watchlist_lookup.get(x.upper(), {}).get("T1", "-")
            )
            df_positions_custom["T2"] = df_positions_custom["BaseSymbol"].apply(
                lambda x: watchlist_lookup.get(x.upper(), {}).get("T2", "-")
            )
            df_positions_custom["LTP"] = df_positions_custom["BaseSymbol"].apply(
                lambda x: watchlist_lookup.get(x.upper(), {}).get("LTP", "-")
            )
        
        # Fallback to intel_pool for LTP if not in watchlist (from TradingView)
        def get_ltp_from_pool(row):
            ltp_from_wl = row.get("LTP", "-")
            if ltp_from_wl and ltp_from_wl != "-":
                return ltp_from_wl
            
            if intel_pool is None:
                return "-"
            
            base_sym = str(row.get("BaseSymbol", "")).strip().upper().replace("&", "_")
            pool_data = intel_pool.get(base_sym, {})
            ltp = pool_data.get("t", {}).get("ltp", "-")
            return str(ltp) if ltp != "-" else "-"
        
        if not df_watchlist.empty:
            df_positions_custom["LTP"] = df_positions_custom.apply(get_ltp_from_pool, axis=1)
        else:
            df_positions_custom["Score"] = "-"
            df_positions_custom["Recommendation"] = "-"
            df_positions_custom["SL"] = "-"
            df_positions_custom["T1"] = "-"
            df_positions_custom["T2"] = "-"
            # Still try to fetch LTP from intel_pool even if watchlist is unavailable
            df_positions_custom["LTP"] = df_positions_custom.apply(get_ltp_from_pool, axis=1)
        
        # Calculate Avg Qty and Avg Price
        df_positions_custom["Avg Qty"] = pd.to_numeric(df_positions_custom.get("netQty", 0), errors="coerce").fillna(0).astype(int)
        df_positions_custom["Avg Price"] = pd.to_numeric(df_positions_custom.get("buyAvg", 0), errors="coerce").fillna(0)
        
        # Calculate if target is reached
        def check_target_reached(row):
            try:
                ltp = pd.to_numeric(row["LTP"], errors="coerce")
                t1 = pd.to_numeric(row["T1"], errors="coerce")
                t2 = pd.to_numeric(row["T2"], errors="coerce")
                position = str(row.get("positionType", "")).upper()
                
                if pd.isna(ltp):
                    return "-"
                
                reached = []
                if not pd.isna(t1) and t1 > 0:
                    if position == "LONG" and ltp >= t1:
                        reached.append("T1 ✓")
                    elif position == "SHORT" and ltp <= t1:
                        reached.append("T1 ✓")
                
                if not pd.isna(t2) and t2 > 0:
                    if position == "LONG" and ltp >= t2:
                        reached.append("T2 ✓")
                    elif position == "SHORT" and ltp <= t2:
                        reached.append("T2 ✓")
                
                return ", ".join(reached) if reached else "No"
            except Exception:
                return "-"
        
        df_positions_custom["Target Reached"] = df_positions_custom.apply(check_target_reached, axis=1)
        
        # Display columns in requested order
        display_cols = [
            "Symbol",
            "Score",
            "Recommendation",
            "Avg Qty",
            "Avg Price",
            "LTP",
            "SL",
            "T1",
            "T2",
            "Target Reached",
        ]
        
        display_df = df_positions_custom[display_cols].copy()
        
        # Format numeric columns
        numeric_cols = ["Avg Qty", "Avg Price", "LTP", "SL", "T1", "T2"]
        for col in numeric_cols:
            if col in display_df.columns:
                display_df[col] = pd.to_numeric(display_df[col], errors="coerce")

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Symbol": st.column_config.TextColumn("Symbol", width="medium"),
                "Score": st.column_config.NumberColumn("Score", format="%d"),
                "Recommendation": st.column_config.TextColumn("Recommendation", width="small"),
                "Avg Qty": st.column_config.NumberColumn("Avg Qty", format="%d"),
                "Avg Price": st.column_config.NumberColumn("Avg Price", format="%.2f"),
                "LTP": st.column_config.NumberColumn("LTP", format="%.2f"),
                "SL": st.column_config.NumberColumn("SL", format="%.2f"),
                "T1": st.column_config.NumberColumn("T1", format="%.2f"),
                "T2": st.column_config.NumberColumn("T2", format="%.2f"),
                "Target Reached": st.column_config.TextColumn("Target Reached", width="small"),
            },
        )

    with st.expander("Today\'s Dhan Orders"):
        df_orders, order_error = api.fetch_dhan_orders()
        if order_error:
            st.error(order_error)
        elif df_orders.empty:
            st.info("No Dhan orders available for today.")
        else:
            if "orderStatus" in df_orders.columns:
                df_orders = df_orders[df_orders["orderStatus"].astype(str).str.upper().isin(ACTIVE_ORDER_STATUSES)].copy()

            if df_orders.empty:
                st.info("No active Dhan orders right now.")
            else:
                order_rename_map = {
                    "tradingSymbol": "Symbol",
                    "transactionType": "Side",
                    "orderStatus": "Status",
                    "exchangeSegment": "Segment",
                    "productType": "Product",
                    "orderType": "Order Type",
                    "quantity": "Qty",
                    "filledQty": "Filled",
                    "remainingQuantity": "Pending Qty",
                    "price": "Price",
                    "triggerPrice": "Trigger",
                    "averageTradedPrice": "Avg Traded",
                    "createTime": "Created",
                    "updateTime": "Updated",
                    "orderId": "Order ID",
                    "securityId": "Security ID",
                    "omsErrorDescription": "OMS Error",
                }
                df_orders = df_orders.rename(columns=order_rename_map)
                order_cols = [
                    "Updated",
                    "Symbol",
                    "Side",
                    "Status",
                    "Segment",
                    "Product",
                    "Order Type",
                    "Qty",
                    "Filled",
                    "Pending Qty",
                    "Price",
                    "Trigger",
                    "Avg Traded",
                    "Created",
                    "Order ID",
                    "Security ID",
                    "OMS Error",
                ]
                visible_order_cols = [col for col in order_cols if col in df_orders.columns]
                st.dataframe(df_orders[visible_order_cols], use_container_width=True, hide_index=True)

    if auto_refresh:
        import time

        time.sleep(15)
        st.rerun()