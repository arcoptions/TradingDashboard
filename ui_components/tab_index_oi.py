import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import plotly.graph_objects as go

import local_db


INDEX_UNDERLYINGS = ["NIFTY", "SENSEX"]


def _format_lakhs(value):
    try:
        return f"{float(value) / 100000:.2f}L"
    except Exception:
        return "-"


def _build_index_chart(df_live, title):
    fig = go.Figure()
    fig.add_bar(name="Call OI", x=df_live["strike"], y=df_live["call_oi"], marker_color="#F23645")
    fig.add_bar(name="Put OI", x=df_live["strike"], y=df_live["put_oi"], marker_color="#089981")
    fig.update_layout(
        barmode="group",
        height=420,
        title=title,
        margin=dict(t=40, l=10, r=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def render(interval_seconds=60):
    components.html(
        f"""
        <script>
            setTimeout(function () {{
                window.parent.location.reload();
            }}, {interval_seconds * 1000});
        </script>
        """,
        height=0,
    )
    st.markdown("### Minute-by-minute OI Change")
    st.caption("Live Nifty and Sensex OI snapshots refresh automatically every minute.")

    for underlying in INDEX_UNDERLYINGS:
        st.markdown(f"#### {underlying} OI")
        latest_rows = local_db.query_latest_oi_chain(underlying)
        if not latest_rows:
            st.info(f"No OI snapshots available yet for {underlying}.")
            continue

        df_live = pd.DataFrame(latest_rows)

        expiry = ""
        if "expiry" in df_live.columns:
            expiry_series = df_live["expiry"].fillna("").astype(str)
            non_empty_expiries = expiry_series[expiry_series.str.strip() != ""]
            if not non_empty_expiries.empty:
                expiry = non_empty_expiries.iloc[0]
                df_live = df_live[df_live["expiry"].fillna("").astype(str) == expiry].copy()
            df_live = df_live.drop(columns=["expiry"])

        if df_live.empty:
            st.info(f"No usable OI snapshots available yet for {underlying}.")
            continue

        latest_ts = str(df_live["timestamp"].iloc[0]) if "timestamp" in df_live.columns else "-"
        st.caption(f"Latest snapshot: {latest_ts} | Expiry: {expiry or '-'}")

        c1, c2 = st.columns([1.7, 1.3])
        with c1:
            st.plotly_chart(_build_index_chart(df_live, f"{underlying} Open Interest"), use_container_width=True)
        with c2:
            total_call = df_live["call_oi"].sum() if "call_oi" in df_live.columns else 0
            total_put = df_live["put_oi"].sum() if "put_oi" in df_live.columns else 0
            total_call_chg = df_live["call_oi_change"].sum() if "call_oi_change" in df_live.columns else 0
            total_put_chg = df_live["put_oi_change"].sum() if "put_oi_change" in df_live.columns else 0
            pcr = round(total_put / total_call, 2) if total_call else 0.0

            st.metric("Total Call OI", _format_lakhs(total_call))
            st.metric("Total Put OI", _format_lakhs(total_put))
            st.metric("PCR", f"{pcr:.2f}")
            st.metric("Call OI Change", _format_lakhs(total_call_chg))
            st.metric("Put OI Change", _format_lakhs(total_put_chg))

        st.dataframe(
            df_live[[c for c in ["strike", "call_oi", "put_oi", "call_oi_change", "put_oi_change", "timestamp"] if c in df_live.columns]].tail(12),
            use_container_width=True,
            hide_index=True,
        )
