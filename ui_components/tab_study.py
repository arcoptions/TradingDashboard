import streamlit as st
import pandas as pd
import requests
from integrations.google_sheets import fetch_dataframe_safe

@st.cache_data(ttl=60, show_spinner=False)
def run_tv_screener(tickers):
    """Batch requests TradingView to mathematically grade all incubator stocks."""
    results = []
    clean_tickers = [str(t).strip().upper().replace("&", "_") for t in tickers if str(t).strip() != "-" and str(t).strip() != ""]
    if not clean_tickers: return []
    
    tv_tickers = [f"NSE:{t}" for t in set(clean_tickers)]
    payload = {"symbols": {"tickers": tv_tickers}, "columns": ["close", "EMA20", "RSI", "volume", "average_volume_10d"]}
    
    try:
        res = requests.post("https://scanner.tradingview.com/india/scan", json=payload, timeout=6)
        if res.status_code == 200 and res.json().get("data"):
            for item in res.json()["data"]:
                ticker = item["s"].split(":")[1]
                d = item["d"]
                
                ltp = d[0] if d[0] else 0
                ema20 = d[1] if d[1] else 0
                rsi = d[2] if d[2] else 0
                vol = d[3] if d[3] else 0
                avg_vol = d[4] if d[4] else 1 # Prevent division by zero
                
                if ema20 > 0 and ltp > 0:
                    prox = ((ltp - ema20) / ema20) * 100
                else: prox = 999
                
                vol_spike = (vol / avg_vol) * 100 if avg_vol > 0 else 0
                
                # --- STRICT EXECUTION ALGORITHM ---
                is_rsi_good = 55 <= rsi <= 75
                is_prox_good = 0 <= prox <= 6.0
                is_vol_good = vol_spike >= 150
                
                score = sum([is_rsi_good, is_prox_good, is_vol_good])
                
                results.append({
                    "Asset": ticker,
                    "LTP": round(ltp, 2),
                    "RSI": round(rsi, 2),
                    "EMA 20 Prox": f"{round(prox, 2)}%",
                    "Vol Spike": f"{round(vol_spike, 0)}%",
                    "Checks Passed": int(score),
                    "Score": score
                })
    except Exception as e:
        print(f"Screener Error: {e}")
        
    return results


def render(*args, **kwargs):
    c1, c2 = st.columns([8, 2])
    c1.markdown("#### Macro Research Staging Deck (`Stocks to study`)")
    if c2.button("🔄 Refresh Data", key="refresh_study"):
        fetch_dataframe_safe.clear()
        st.rerun()
        
    st.caption("Aggregated list of high-conviction insights extracted directly from news wires and automated tickers.")
    
    df_study_log = fetch_dataframe_safe("Stocks to study")
    
    if df_study_log.empty:
        st.info("No research items logged yet. New inbound entries from Beat The Street will display here automatically.")
        return

    # ─── AUTOMATED CONVERGENCE SCREENER UI ───
    with st.expander("⚡ Run Automated A+ Convergence Screener", expanded=False):
        st.markdown("Scans the raw fundamental news list below against live technical indicators to find setups that are **ready to trade right now**.")
        
        if st.button("🔍 Filter 150+ Stocks Now", type="primary"):
            with st.spinner("Querying TradingView API and applying technical constraints..."):
                all_tickers = df_study_log["Asset Ticker"].unique().tolist()
                scan_results = run_tv_screener(all_tickers)
                
                if scan_results:
                    df_scan = pd.DataFrame(scan_results).sort_values(by="Score", ascending=False)
                    
                    # Core Filter: Only show stocks passing at least 2 out of 3 strict checks
                    df_qualified = df_scan[df_scan["Score"] >= 2].copy()
                    
                    if not df_qualified.empty:
                        st.success(f"Filtered {len(all_tickers)} raw ideas down to {len(df_qualified)} high-probability execution setups.")
                        
                        # Merge the latest fundamental news narrative to the surviving technical stocks
                        latest_news = df_study_log.drop_duplicates(subset=['Asset Ticker'], keep='last')
                        df_qualified = df_qualified.merge(latest_news[['Asset Ticker', 'Raw Text Message']], left_on='Asset', right_on='Asset Ticker', how='left')
                        
                        st.dataframe(
                            df_qualified[["Asset", "Checks Passed", "RSI", "EMA 20 Prox", "Vol Spike", "Raw Text Message"]],
                            use_container_width=True,
                            hide_index=True,
                            column_config={
                                "Checks Passed": st.column_config.ProgressColumn("Technical Match", format="%d/3", min_value=0, max_value=3),
                                "Raw Text Message": st.column_config.TextColumn("Fundamental Catalyst", width="large")
                            }
                        )
                        st.info("👉 **Next Step:** Manually move these surviving tickers to your main Watchlist, open the **Trade Inspector**, and locate the Optimal CE strike.")
                    else:
                        st.warning("No stocks currently meet the strict A+ technical execution criteria. Let the news incubate further until the charts align.")
                else:
                    st.error("Could not fetch technical data. Please try again.")

    st.markdown("---")
    
    # Render the standard un-filtered database
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
