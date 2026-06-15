import pandas as pd
import streamlit as st

import broker_api as api


ACTIVE_ORDER_STATUSES = ["TRANSIT", "PENDING", "PART_TRADED"]
ACTIVE_POSITION_TYPES = ["LONG", "SHORT"]


def render():
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
        rename_map = {
        "tradingSymbol": "Symbol",
        "positionType": "Position",
        "exchangeSegment": "Segment",
        "productType": "Product",
        "netQty": "Net Qty",
        "buyQty": "Buy Qty",
        "sellQty": "Sell Qty",
        "buyAvg": "Buy Avg",
        "sellAvg": "Sell Avg",
        "costPrice": "Cost Price",
        "unrealizedProfit": "Unrealized P&L",
        "realizedProfit": "Realized P&L",
        "drvOptionType": "Option Type",
        "drvStrikePrice": "Strike",
        "drvExpiryDate": "Expiry",
        "securityId": "Security ID",
        }
        df_positions = df_positions.rename(columns=rename_map)

        preferred_cols = [
        "Symbol",
        "Position",
        "Segment",
        "Product",
        "Net Qty",
        "Buy Qty",
        "Sell Qty",
        "Buy Avg",
        "Sell Avg",
        "Cost Price",
        "Unrealized P&L",
        "Realized P&L",
        "Option Type",
        "Strike",
        "Expiry",
        "Security ID",
        ]
        display_cols = [col for col in preferred_cols if col in df_positions.columns]
        display_df = df_positions[display_cols].copy()

        numeric_cols = [
            "Net Qty",
            "Buy Qty",
            "Sell Qty",
            "Buy Avg",
            "Sell Avg",
            "Cost Price",
            "Unrealized P&L",
            "Realized P&L",
            "Strike",
        ]
        for col in numeric_cols:
            if col in display_df.columns:
                display_df[col] = pd.to_numeric(display_df[col], errors="coerce")

        total_unrealized = display_df["Unrealized P&L"].sum() if "Unrealized P&L" in display_df.columns else 0.0
        total_realized = display_df["Realized P&L"].sum() if "Realized P&L" in display_df.columns else 0.0
        metric_a, metric_b, metric_c = st.columns(3)
        metric_a.metric("Open Positions", len(display_df))
        metric_b.metric("Unrealized P&L", f"{total_unrealized:,.2f}")
        metric_c.metric("Realized P&L", f"{total_realized:,.2f}")

        st.dataframe(
            display_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Net Qty": st.column_config.NumberColumn("Net Qty", format="%d"),
                "Buy Qty": st.column_config.NumberColumn("Buy Qty", format="%d"),
                "Sell Qty": st.column_config.NumberColumn("Sell Qty", format="%d"),
                "Buy Avg": st.column_config.NumberColumn("Buy Avg", format="%.2f"),
                "Sell Avg": st.column_config.NumberColumn("Sell Avg", format="%.2f"),
                "Cost Price": st.column_config.NumberColumn("Cost Price", format="%.2f"),
                "Unrealized P&L": st.column_config.NumberColumn("Unrealized P&L", format="%.2f"),
                "Realized P&L": st.column_config.NumberColumn("Realized P&L", format="%.2f"),
                "Strike": st.column_config.NumberColumn("Strike", format="%.2f"),
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