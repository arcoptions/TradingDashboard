import pandas as pd
import streamlit as st
import requests
import sqlite3
import gspread

import broker_api as api
from integrations.google_sheets import fetch_dataframe_safe, fetch_settings_dict, init_sheet_connection


ACTIVE_ORDER_STATUSES = ["TRANSIT", "PENDING", "PART_TRADED"]
ACTIVE_POSITION_TYPES = ["LONG", "SHORT"]


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
        def _fetch_option_ltp_map(df_src):
            exch_key_map = {
                "NSE_FNO": "NSE_FNO",
                "NSE_EQ": "NSE_EQ",
                "BSE_EQ": "BSE_EQ",
                "IDX_I": "IDX_I",
                "MCX_COMM": "MCX_COMM",
            }
            payload = {}
            for _, p_row in df_src.iterrows():
                exch = str(p_row.get("exchangeSegment", "")).strip().upper()
                sec_id = str(p_row.get("securityId", "")).strip()
                if not exch or not sec_id.isdigit():
                    continue
                api_exch = exch_key_map.get(exch)
                if not api_exch:
                    continue
                payload.setdefault(api_exch, set()).add(int(sec_id))

            payload = {k: sorted(list(v)) for k, v in payload.items() if v}
            if not payload:
                return {}

            try:
                settings = fetch_settings_dict()
                token = settings.get("Dhan Access Token", "")
                client_id = st.secrets["dhan"].get("dhan_client_id", "")
                if not token or not client_id:
                    return {}

                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "access-token": token,
                    "client-id": client_id,
                }
                resp = requests.post(
                    "https://api.dhan.co/v2/marketfeed/quote",
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
                if resp.status_code != 200:
                    return {}

                q_data = resp.json().get("data", {})
                out = {}
                for exch, sec_nodes in q_data.items():
                    if not isinstance(sec_nodes, dict):
                        continue
                    for sec_id, node in sec_nodes.items():
                        last_price = node.get("last_price", "")
                        key = (str(exch).upper(), str(sec_id))
                        out[key] = last_price
                return out
            except Exception:
                return {}

        def _is_blank(v):
            s = str(v).strip().lower()
            return s in ["", "-", "none", "nan"]

        # Fetch watchlist to get score, recommendation, and targets
        try:
            df_watchlist = fetch_dataframe_safe("Sheet1", is_sheet1=True)
        except Exception:
            df_watchlist = pd.DataFrame()

        def _fetch_localdb_watchlist_map():
            out = {}
            try:
                conn = sqlite3.connect("arc_trading.db")
                conn.row_factory = sqlite3.Row
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT symbol, base_asset, score, recommendation, stop_loss, target_1, target_2
                    FROM watchlist_items
                    WHERE status IN ('Watchlist', 'Active')
                    """
                )
                rows = cur.fetchall()
                conn.close()
                for row in rows:
                    entry = {
                        "Score": row["score"] if row["score"] is not None else "-",
                        "Recommendation": row["recommendation"] if row["recommendation"] is not None else "-",
                        "SL": row["stop_loss"] if row["stop_loss"] is not None else "-",
                        "T1": row["target_1"] if row["target_1"] is not None else "-",
                        "T2": row["target_2"] if row["target_2"] is not None else "-",
                    }
                    sym = str(row["symbol"] or "").strip().upper()
                    base = str(row["base_asset"] or "").strip().upper()
                    if sym:
                        out[sym] = entry
                    if base:
                        out[base] = entry
            except Exception:
                return {}
            return out

        localdb_map = _fetch_localdb_watchlist_map()

        def _fetch_underlying_stock_ltp_map(base_symbols):
            resolved = []
            for b in base_symbols:
                b_sym = str(b).strip().upper()
                if not b_sym:
                    continue
                _, sec_id, exch = api.resolve_instrument(b_sym)
                if sec_id and str(sec_id).isdigit() and exch:
                    resolved.append((b_sym, str(sec_id), str(exch).upper()))

            if not resolved:
                return {}

            payload = {}
            for _, sec_id, exch in resolved:
                payload.setdefault(exch, set()).add(int(sec_id))
            payload = {k: sorted(list(v)) for k, v in payload.items() if v}
            if not payload:
                return {}

            try:
                settings = fetch_settings_dict()
                token = settings.get("Dhan Access Token", "")
                client_id = st.secrets["dhan"].get("dhan_client_id", "")
                if not token or not client_id:
                    return {}
                headers = {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "access-token": token,
                    "client-id": client_id,
                }
                resp = requests.post(
                    "https://api.dhan.co/v2/marketfeed/quote",
                    headers=headers,
                    json=payload,
                    timeout=10,
                )
                if resp.status_code != 200:
                    return {}
                data = resp.json().get("data", {})
                ltp_by_key = {}
                for b_sym, sec_id, exch in resolved:
                    node = data.get(exch, {}).get(sec_id, {})
                    lp = node.get("last_price", "")
                    if lp not in ["", None, "None"]:
                        ltp_by_key[b_sym] = lp
                return ltp_by_key
            except Exception:
                return {}

        # Prepare positions data
        df_positions_custom = df_positions.copy()
        df_positions_custom["Symbol"] = df_positions_custom.get("tradingSymbol", "")
        
        # Extract base symbol (remove expiry/strike info for options)
        df_positions_custom["BaseSymbol"] = df_positions_custom["Symbol"].str.split('-').str[0].str.strip()
        
        # Join with watchlist data
        if not df_watchlist.empty:
            # Create lookup from watchlist (match by contract symbol and base symbol)
            watchlist_lookup = {}
            for idx, row in df_watchlist.iterrows():
                sym = str(row.get("Symbol / Asset", "")).strip().upper()
                base = str(row.get("Base Asset", "")).strip().upper()
                if _is_blank(base) and sym:
                    base = sym.split('-')[0].strip().upper()
                if _is_blank(base) and sym:
                    base = sym.split(' ')[0].strip().upper()
                
                score = row.get("Score", "-")
                recommendation = row.get("Recommendation", "-")
                sl = str(row.get("Stop Loss (SL)", "")).strip()
                t1 = str(row.get("Target 1", "")).strip()
                t2 = str(row.get("Target 2", "")).strip()
                stock_ltp = str(row.get("Live Price", "")).strip()
                
                entry = {
                    "Score": score,
                    "Recommendation": recommendation,
                    "SL": sl,
                    "T1": t1,
                    "T2": t2,
                    "Stock LTP": stock_ltp,
                    "_wl_row": idx + 2,
                }

                keys = []
                if sym:
                    keys.extend([sym, sym.split('-')[0].strip().upper(), sym.split(' ')[0].strip().upper()])
                if base:
                    keys.append(base)

                for key in [k for k in keys if k and not _is_blank(k)]:
                    prev = watchlist_lookup.get(key, {})
                    # Prefer entries that have score/recommendation present
                    if not prev or (_is_blank(prev.get("Score", "-")) and not _is_blank(score)):
                        watchlist_lookup[key] = entry

            def _get_watchlist_entry(pos_row):
                s_key = str(pos_row.get("Symbol", "")).strip().upper()
                b_key = str(pos_row.get("BaseSymbol", "")).strip().upper()
                return watchlist_lookup.get(s_key) or watchlist_lookup.get(b_key) or {}
            
            # Match positions with watchlist
            df_positions_custom["Score"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("Score", "-"), axis=1)
            df_positions_custom["Recommendation"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("Recommendation", "-"), axis=1)
            df_positions_custom["SL"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("SL", "-"), axis=1)
            df_positions_custom["T1"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("T1", "-"), axis=1)
            df_positions_custom["T2"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("T2", "-"), axis=1)
            df_positions_custom["Stock LTP"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("Stock LTP", "-"), axis=1)
            df_positions_custom["_wl_row"] = df_positions_custom.apply(lambda r: _get_watchlist_entry(r).get("_wl_row", None), axis=1)
        
        # Fallback to intel_pool for stock LTP if not in watchlist (from TradingView)
        def get_stock_ltp_from_pool(row):
            ltp_from_wl = row.get("Stock LTP", "-")
            if ltp_from_wl and ltp_from_wl != "-":
                return ltp_from_wl
            
            if intel_pool is None:
                return "-"
            
            base_sym = str(row.get("BaseSymbol", "")).strip().upper().replace("&", "_")
            pool_data = intel_pool.get(base_sym, {})
            ltp = pool_data.get("t", {}).get("ltp", "-")
            return str(ltp) if ltp != "-" else "-"

        # Fallback to local DB for score/recommendation/targets
        def fill_from_localdb(row, field_name):
            cur_val = row.get(field_name, "-")
            if not _is_blank(cur_val):
                return cur_val
            sym = str(row.get("Symbol", "")).strip().upper()
            base = str(row.get("BaseSymbol", "")).strip().upper()
            if sym in localdb_map and not _is_blank(localdb_map[sym].get(field_name, "-")):
                return localdb_map[sym].get(field_name, "-")
            if base in localdb_map and not _is_blank(localdb_map[base].get(field_name, "-")):
                return localdb_map[base].get(field_name, "-")
            return cur_val

        # Option contract LTP from Dhan quote API (securityId + exchangeSegment)
        quote_ltp_map = _fetch_option_ltp_map(df_positions_custom)

        def get_option_ltp(row):
            exch = str(row.get("exchangeSegment", "")).strip().upper()
            sec_id = str(row.get("securityId", "")).strip()
            if not exch or not sec_id:
                return "-"
            val = quote_ltp_map.get((exch, sec_id), "")
            if val in [None, "", "None"]:
                return "-"
            return str(val)
        
        if not df_watchlist.empty:
            df_positions_custom["Stock LTP"] = df_positions_custom.apply(get_stock_ltp_from_pool, axis=1)
        else:
            df_positions_custom["Score"] = "-"
            df_positions_custom["Recommendation"] = "-"
            df_positions_custom["SL"] = "-"
            df_positions_custom["T1"] = "-"
            df_positions_custom["T2"] = "-"
            df_positions_custom["_wl_row"] = None
            # Still try to fetch stock LTP from intel_pool even if watchlist is unavailable
            df_positions_custom["Stock LTP"] = df_positions_custom.apply(get_stock_ltp_from_pool, axis=1)

        # Fill missing score/recommendation/targets from local DB snapshot
        df_positions_custom["Score"] = df_positions_custom.apply(lambda r: fill_from_localdb(r, "Score"), axis=1)
        df_positions_custom["Recommendation"] = df_positions_custom.apply(lambda r: fill_from_localdb(r, "Recommendation"), axis=1)
        df_positions_custom["SL"] = df_positions_custom.apply(lambda r: fill_from_localdb(r, "SL"), axis=1)
        df_positions_custom["T1"] = df_positions_custom.apply(lambda r: fill_from_localdb(r, "T1"), axis=1)
        df_positions_custom["T2"] = df_positions_custom.apply(lambda r: fill_from_localdb(r, "T2"), axis=1)

        # Extra fallback for stock LTP from Dhan underlying quotes (helps symbols like LT, M&M)
        missing_stock_ltp_mask = df_positions_custom["Stock LTP"].apply(_is_blank)
        missing_bases = df_positions_custom.loc[missing_stock_ltp_mask, "BaseSymbol"].dropna().astype(str).str.upper().unique().tolist()
        underlying_ltp_map = _fetch_underlying_stock_ltp_map(missing_bases)
        if underlying_ltp_map:
            df_positions_custom.loc[missing_stock_ltp_mask, "Stock LTP"] = df_positions_custom.loc[missing_stock_ltp_mask, "BaseSymbol"].apply(
                lambda x: str(underlying_ltp_map.get(str(x).strip().upper(), "-"))
            )

        df_positions_custom["Option LTP"] = df_positions_custom.apply(get_option_ltp, axis=1)
        
        # Calculate Avg Qty and Avg Price
        df_positions_custom["Avg Qty"] = pd.to_numeric(df_positions_custom.get("netQty", 0), errors="coerce").fillna(0).astype(int)
        df_positions_custom["Avg Price"] = pd.to_numeric(df_positions_custom.get("buyAvg", 0), errors="coerce").fillna(0)
        
        # Calculate if target is reached
        def check_target_reached(row):
            try:
                opt_ltp = pd.to_numeric(row.get("Option LTP", "-"), errors="coerce")
                stock_ltp = pd.to_numeric(row.get("Stock LTP", "-"), errors="coerce")
                ltp = opt_ltp if not pd.isna(opt_ltp) else stock_ltp
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
            "Stock LTP",
            "Option LTP",
            "SL",
            "T1",
            "T2",
            "Target Reached",
        ]
        
        display_df = df_positions_custom[display_cols].copy()
        
        # Format numeric columns
        numeric_cols = ["Avg Qty", "Avg Price", "Stock LTP", "Option LTP", "SL", "T1", "T2"]
        for col in numeric_cols:
            if col in display_df.columns:
                display_df[col] = pd.to_numeric(display_df[col], errors="coerce")

        column_cfg = {
            "Symbol": st.column_config.TextColumn("Symbol", width="medium"),
            "Score": st.column_config.NumberColumn("Score", format="%d"),
            "Recommendation": st.column_config.TextColumn("Recommendation", width="small"),
            "Avg Qty": st.column_config.NumberColumn("Avg Qty", format="%d"),
            "Avg Price": st.column_config.NumberColumn("Avg Price", format="%.2f"),
            "Stock LTP": st.column_config.NumberColumn("Stock LTP", format="%.2f"),
            "Option LTP": st.column_config.NumberColumn("Option LTP", format="%.2f"),
            "SL": st.column_config.NumberColumn("SL", format="%.2f"),
            "T1": st.column_config.NumberColumn("T1", format="%.2f"),
            "T2": st.column_config.NumberColumn("T2", format="%.2f"),
            "Target Reached": st.column_config.TextColumn("Target Reached", width="small"),
        }

        edit_enabled = st.checkbox("Enable SL/T1/T2 editing", key="dhan_positions_edit_targets")
        if edit_enabled:
            edited_df = st.data_editor(
                display_df,
                use_container_width=True,
                hide_index=True,
                key="dhan_positions_editor",
                column_config=column_cfg,
                disabled=["Symbol", "Score", "Recommendation", "Avg Qty", "Avg Price", "Stock LTP", "Option LTP", "Target Reached"],
            )

            if st.button("Save SL/Targets to Watchlist", key="save_dhan_targets"):
                try:
                    if df_watchlist.empty:
                        st.warning("Watchlist data is unavailable right now. Please retry after sync.")
                    else:
                        sheet_headers = df_watchlist.columns.tolist()
                        if "Stop Loss (SL)" not in sheet_headers or "Target 1" not in sheet_headers or "Target 2" not in sheet_headers:
                            st.error("Watchlist headers missing SL/T1/T2 columns.")
                        else:
                            sl_col = sheet_headers.index("Stop Loss (SL)") + 1
                            t1_col = sheet_headers.index("Target 1") + 1
                            t2_col = sheet_headers.index("Target 2") + 1

                            updates = []
                            for idx, new_row in edited_df.iterrows():
                                old_row = display_df.iloc[idx]
                                wl_row = df_positions_custom.iloc[idx].get("_wl_row")
                                if pd.isna(wl_row):
                                    continue

                                wl_row = int(wl_row)
                                for col_name, col_idx in [("SL", sl_col), ("T1", t1_col), ("T2", t2_col)]:
                                    old_val = str(old_row.get(col_name, "")).strip()
                                    new_val = str(new_row.get(col_name, "")).strip()
                                    if old_val != new_val:
                                        updates.append({
                                            "range": gspread.utils.rowcol_to_a1(wl_row, col_idx),
                                            "values": [[new_val]],
                                        })

                            if not updates:
                                st.info("No SL/T1/T2 changes detected.")
                            else:
                                sh, watchlist_ws, _, _, _, _ = init_sheet_connection()
                                watchlist_ws.batch_update(updates)
                                st.success(f"Saved {len(updates)} updates to Watchlist.")
                                fetch_dataframe_safe.clear()
                                st.rerun()
                except Exception as save_err:
                    st.error(f"Could not save updates: {save_err}")
        else:
            st.dataframe(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config=column_cfg,
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