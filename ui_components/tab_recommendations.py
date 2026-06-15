import streamlit as st
import pandas as pd
from datetime import datetime


def render(watchlist_df, intel_pool):
    """
    Display ranked recommendations for LONG, SHORT, and OPTIONS trades.
    Considers score, sector strength, technicals, and OI buildup.
    """
    st.markdown("#### Ranked Trading Recommendations")

    if watchlist_df is None or watchlist_df.empty:
        st.info("No watchlist data available for recommendations.")
        return

    filtered_df = watchlist_df[
        watchlist_df["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])
    ].copy()

    if filtered_df.empty:
        st.info("No active positions in watchlist.")
        return

    tab_long, tab_short, tab_options = st.tabs(["LONG Candidates", "SHORT Candidates", "OPTIONS Candidates"])

    with tab_long:
        long_candidates = filtered_df[
            (filtered_df["Trade Type (Eq/Option)"].astype(str).str.lower().isin(["equity", "stock"]))
            & (filtered_df["Recommendation"].astype(str).str.contains("LONG", case=False, na=False))
        ].copy().reset_index(drop=True)

        if not long_candidates.empty:
            long_candidates = long_candidates.sort_values(
                by=["Score", "Sector Strength %"],
                ascending=False,
            ).reset_index(drop=True)

            long_candidates.insert(0, "Rank", range(1, len(long_candidates) + 1))

            display_cols = [
                "Rank",
                "Base Asset",
                "Score",
                "Decision",
                "Sector Strength %",
                "Entry CMP / Range",
                "Live Price",
                "Stop Loss (SL)",
                "Target 1",
                "Target 2",
            ]
            display_cols = [c for c in display_cols if c in long_candidates.columns]

            col_config = {
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Score": st.column_config.NumberColumn("Score", format="%d"),
                "Sector Strength %": st.column_config.NumberColumn("Sector Heat %", format="%.2f"),
                "Entry CMP / Range": st.column_config.TextColumn("Entry"),
                "Live Price": st.column_config.TextColumn("LTP"),
                "Stop Loss (SL)": st.column_config.TextColumn("SL"),
                "Target 1": st.column_config.TextColumn("T1"),
                "Target 2": st.column_config.TextColumn("T2"),
                "Base Asset": st.column_config.TextColumn("Stock"),
                "Decision": st.column_config.TextColumn("Signal"),
            }

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Candidates", len(long_candidates))
            avg_score = long_candidates["Score"].astype(float).mean()
            c2.metric("Avg Score", f"{avg_score:.0f}")
            strong_count = len(long_candidates[long_candidates["Decision"] == "STRONG GO"])
            c3.metric("Strong GO", strong_count)

            st.dataframe(
                long_candidates[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config=col_config,
            )
        else:
            st.info("No LONG candidates found matching current criteria.")

    with tab_short:
        short_candidates = filtered_df[
            (filtered_df["Trade Type (Eq/Option)"].astype(str).str.lower().isin(["equity", "stock"]))
            & (filtered_df["Recommendation"].astype(str).str.contains("SHORT", case=False, na=False))
        ].copy().reset_index(drop=True)

        if not short_candidates.empty:
            short_candidates = short_candidates.sort_values(
                by=["Score", "Sector Strength %"],
                ascending=False,
            ).reset_index(drop=True)

            short_candidates.insert(0, "Rank", range(1, len(short_candidates) + 1))

            display_cols = [
                "Rank",
                "Base Asset",
                "Score",
                "Decision",
                "Sector Strength %",
                "Entry CMP / Range",
                "Live Price",
                "Stop Loss (SL)",
                "Target 1",
                "Target 2",
            ]
            display_cols = [c for c in display_cols if c in short_candidates.columns]

            col_config = {
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Score": st.column_config.NumberColumn("Score", format="%d"),
                "Sector Strength %": st.column_config.NumberColumn("Sector Heat %", format="%.2f"),
                "Entry CMP / Range": st.column_config.TextColumn("Entry"),
                "Live Price": st.column_config.TextColumn("LTP"),
                "Stop Loss (SL)": st.column_config.TextColumn("SL"),
                "Target 1": st.column_config.TextColumn("T1"),
                "Target 2": st.column_config.TextColumn("T2"),
                "Base Asset": st.column_config.TextColumn("Stock"),
                "Decision": st.column_config.TextColumn("Signal"),
            }

            c1, c2, c3 = st.columns(3)
            c1.metric("Total Candidates", len(short_candidates))
            avg_score = short_candidates["Score"].astype(float).mean()
            c2.metric("Avg Score", f"{avg_score:.0f}")
            strong_count = len(short_candidates[short_candidates["Decision"] == "STRONG GO"])
            c3.metric("Strong GO", strong_count)

            st.dataframe(
                short_candidates[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config=col_config,
            )
        else:
            st.info("No SHORT candidates found matching current criteria.")

    with tab_options:
        options_candidates = filtered_df[
            (filtered_df["Trade Type (Eq/Option)"].astype(str).str.lower().isin(["option", "fno"]))
            & (filtered_df["Recommendation"].astype(str).isin(["LONG CE", "LONG PE"]))
        ].copy().reset_index(drop=True)

        if not options_candidates.empty:
            options_candidates = options_candidates.sort_values(
                by=["Score", "Sector Strength %"],
                ascending=False,
            ).reset_index(drop=True)

            options_candidates.insert(0, "Rank", range(1, len(options_candidates) + 1))

            display_cols = [
                "Rank",
                "Symbol / Asset",
                "Recommendation",
                "Score",
                "Decision",
                "Sector Strength %",
                "Entry CMP / Range",
                "Live Price",
                "Stop Loss (SL)",
                "Target 1",
                "Target 2",
            ]
            display_cols = [c for c in display_cols if c in options_candidates.columns]

            col_config = {
                "Rank": st.column_config.NumberColumn("Rank", width="small"),
                "Recommendation": st.column_config.TextColumn("Trade"),
                "Score": st.column_config.NumberColumn("Score", format="%d"),
                "Sector Strength %": st.column_config.NumberColumn("Sector Heat %", format="%.2f"),
                "Entry CMP / Range": st.column_config.TextColumn("Entry"),
                "Live Price": st.column_config.TextColumn("LTP"),
                "Stop Loss (SL)": st.column_config.TextColumn("SL"),
                "Target 1": st.column_config.TextColumn("T1"),
                "Target 2": st.column_config.TextColumn("T2"),
                "Symbol / Asset": st.column_config.TextColumn("Contract"),
                "Decision": st.column_config.TextColumn("Signal"),
            }

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Candidates", len(options_candidates))
            ce_count = len(options_candidates[options_candidates["Recommendation"] == "LONG CE"])
            c2.metric("Call (CE) Ideas", ce_count)
            pe_count = len(options_candidates[options_candidates["Recommendation"] == "LONG PE"])
            c3.metric("Put (PE) Ideas", pe_count)
            avg_score = options_candidates["Score"].astype(float).mean()
            c4.metric("Avg Score", f"{avg_score:.0f}")

            st.dataframe(
                options_candidates[display_cols],
                use_container_width=True,
                hide_index=True,
                column_config=col_config,
            )
        else:
            st.info("No OPTIONS candidates found matching current criteria.")

    with st.expander("📊 How Rankings Work"):
        st.markdown(
            """
            **Ranking Methodology:**
            - **LONG Equity:** Ranked by Score (desc) → Sector Strength (desc). LONG recommendation requires score ≥75, bullish trend, positive momentum.
            - **SHORT Equity:** Ranked by Score (desc) → Sector Strength (desc). SHORT recommendation requires score ≥60, bearish trend, negative momentum.
            - **OPTIONS (CE/PE):** Ranked by Score (desc) → Sector Strength (desc). CE for bullish setups, PE for bearish. Requires score ≥65 with supporting technicals.
            
            **Filters:**
            - Only "Watchlist" and "Active" items are shown.
            - Only items with non-empty SL and T1 are recommended.
            - Sector strength factors heavily into CE/PE selection and conviction.
            """
        )
