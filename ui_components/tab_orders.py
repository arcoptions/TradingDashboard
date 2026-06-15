import pandas as pd
import streamlit as st

import broker_api as api


ACTIVE_ORDER_STATUSES = ["TRANSIT", "PENDING", "PART_TRADED"]


def render():
    st.markdown("#### Dhan Live Orders")

    top_left, top_mid, top_right = st.columns([1.1, 1.2, 3.2])
    with top_left:
        show_active_only = st.checkbox("Active only", value=True, key="dhan_orders_active_only")
    with top_mid:
        auto_refresh = st.checkbox("Auto refresh", value=False, key="dhan_orders_auto_refresh")
    with top_right:
        if st.button("Refresh Orders", key="dhan_orders_refresh"):
            st.cache_data.clear()

    if auto_refresh:
        st.caption("Auto refresh is enabled. The view refreshes every 15 seconds while this tab is open.")

    df_orders, error_msg = api.fetch_dhan_orders()
    if error_msg:
        st.error(error_msg)
        return

    if df_orders.empty:
        st.info("No Dhan orders available for today.")
        return

    if show_active_only and "orderStatus" in df_orders.columns:
        df_orders = df_orders[df_orders["orderStatus"].astype(str).str.upper().isin(ACTIVE_ORDER_STATUSES)].copy()

    if df_orders.empty:
        st.info("No active Dhan orders right now.")
        return

    rename_map = {
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
    df_orders = df_orders.rename(columns=rename_map)

    preferred_cols = [
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
    display_cols = [col for col in preferred_cols if col in df_orders.columns]
    display_df = df_orders[display_cols].copy()

    numeric_cols = ["Qty", "Filled", "Pending Qty", "Price", "Trigger", "Avg Traded"]
    for col in numeric_cols:
        if col in display_df.columns:
            display_df[col] = pd.to_numeric(display_df[col], errors="coerce")

    st.caption(f"Orders loaded: {len(display_df)}")
    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Qty": st.column_config.NumberColumn("Qty", format="%d"),
            "Filled": st.column_config.NumberColumn("Filled", format="%d"),
            "Pending Qty": st.column_config.NumberColumn("Pending Qty", format="%d"),
            "Price": st.column_config.NumberColumn("Price", format="%.2f"),
            "Trigger": st.column_config.NumberColumn("Trigger", format="%.2f"),
            "Avg Traded": st.column_config.NumberColumn("Avg Traded", format="%.2f"),
        },
    )

    if auto_refresh:
        import time

        time.sleep(15)
        st.rerun()