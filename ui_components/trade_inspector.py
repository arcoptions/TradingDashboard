import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import re
import broker_api as api
import derivatives_engine as de
import scoring_engine as se

def prox_color(val):
    if val == "-": return "color:#64748B;"
    return "color:#089981;" if float(val) > 0 else "color:#F23645;"

def render_tv_chart(symbol):
    tv_sym = str(symbol).split('-')[0].upper().replace("&", "_")
    tv_ticker = f"NSE:{tv_sym}" if tv_sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"] else f"BSE:{tv_sym}"
    html = f"""
    <div class="tradingview-widget-container" style="height: 420px; width: 100%;">
      <div id="tv_chart" style="height: 420px; width: 100%;"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
      <script type="text/javascript">
      new TradingView.widget({{"autosize": true, "symbol": "{tv_ticker}", "interval": "D", "timezone": "Asia/Kolkata", "theme": "light", "style": "1", "locale": "in", "enable_publishing": false, "backgroundColor": "#ffffff", "gridColor": "#F1F5F9", "hide_top_toolbar": false, "container_id": "tv_chart"}});
      </script>
    </div>
    """
    components.html(html, height=420)

def render(trade_data, intel_pool, daily_token, primary_watchlist_ws, sheet_headers):
    # Default to -1 if missing, protecting scanner staging inspections
    sheet_row_id = int(trade_data.get('_Sheet_Row', -1))
    asset_symbol = trade_data.get('Symbol / Asset', 'Unknown Asset')
    base_ticker_raw = str(trade_data.get("Base Asset", str(asset_symbol).split('-')[0].strip())).upper()
    sym_key = base_ticker_raw.replace("&", "_")
    
    pool_data = intel_pool.get(sym_key, {"f": {"stock_pe": "-", "forward_pe": "-", "sector_pe": 20.0, "roe": "-", "debt_to_equity": "-", "ebitda_margin": "-", "pat_margin": "-", "roce": "-", "inst_own": "-"}, "t": {"ltp": "-", "rsi": "-", "vol_spike": "-", "ema20_prox": "-", "ema50_prox": "-", "ema200_prox": "-"}})
    f_metrics = pool_data["f"]
    t_metrics = pool_data["t"]

    head_c1, head_c2 = st.columns([2.5, 7.5], vertical_alignment="center")
    with head_c1:
        # THE UNIFIED BACK BUTTON
        if st.button("⬅️ Back to Terminal", key="terminal_escape_btn", use_container_width=True): 
            st.session_state.viewing_trade = None
            st.session_state.viewing_trade_row = None
            st.session_state.viewing_scanner_row_data = None
            st.rerun()
            
    with head_c2: 
        st.markdown(f"<h3 style='margin:0; padding-left:10px;'>Research Analysis: {asset_symbol}</h3>", unsafe_allow_html=True)
    
    st.write("")
    tab_init_research, tab_psych_exec = st.tabs(["Initial Research", "Psychology & Execution"])
    
    with tab_init_research:
        with st.container(border=True):
            p_chg = float(trade_data.get("Price Chg %", 0) or 0)
            o_chg = float(trade_data.get("OI Chg %", 0) or 0)
            lbl, oi_color = de.compute_oi_buildup(p_chg, o_chg)
            t_type = trade_data.get("Trade Type (Eq/Option)", "Equity")
            scr, dec, flags = se.generate_conviction_score(f_metrics, t_metrics, lbl, trade_type=t_type)
            v_color = "#089981" if dec == "STRONG GO" else "#D1A553" if dec == "CAUTION" else "#F23645"
            sc1, sc2 = st.columns([1.5, 4.5])
            sc1.markdown(f"<div style='text-align:center;'><span style='font-size:38px; font-weight:800; color:{v_color};'>{scr}/100</span><br><span style='font-size:16px; font-weight:700; color:{v_color};'>{dec}</span></div>", unsafe_allow_html=True)
            sc2.markdown(f"<div style='font-size:13px; font-weight:500; color:#334155;'>{' | '.join(flags)}</div>", unsafe_allow_html=True)
        
        contract_meta = de.parse_option_contract(asset_symbol)
        if contract_meta:
            with st.container(border=True):
                st.markdown("**Derivatives Profile & Live Greeks (Dhan Feed)**")
                underlying_ltp_raw = t_metrics.get("ltp", "-")
                underlying_px = float(underlying_ltp_raw) if underlying_ltp_raw != "-" else contract_meta['strike']
                
                dhan_chain_data = api.get_option_chain_metrics(asset_symbol, daily_token=daily_token)
                if isinstance(dhan_chain_data, dict) and dhan_chain_data:
                    live_iv = float(dhan_chain_data.get('implied_volatility', 0))
                    live_delta = float(dhan_chain_data.get('delta', 0))
                    live_theta = float(dhan_chain_data.get('theta', 0))
                    strike_pcr = float(dhan_chain_data.get('strike_pcr', 0))
                    overall_pcr = float(dhan_chain_data.get('overall_pcr', 0))
                    best_ce = dhan_chain_data.get('best_ce', '-')
                    best_pe = dhan_chain_data.get('best_pe', '-')
                    api_success = (live_iv > 0 or live_delta != 0)
                else:
                    live_iv, live_delta, live_theta, strike_pcr, overall_pcr = 0.0, 0.0, 0.0, 0.0, 0.0
                    best_ce, best_pe = "-", "-"
                    api_success = False

                g1, g2, g3, g4, g5 = st.columns(5)
                iv_display = f"{live_iv:.2f}%" if live_iv > 0 else "0DTE (Expiry)"
                g1.metric("Delta", f"{live_delta:.5f}" if api_success else "Syncing...")
                g2.metric("Theta", f"{live_theta:.2f} INR" if api_success else "Syncing...")
                g3.metric("Underlying (Spot)", f"₹{underlying_px}")
                g4.metric("Live IV", iv_display if api_success else "Syncing...")
                g5.markdown(f"<span style='font-size:14px; font-weight:bold; color:#475569;'>OI Matrix</span><br><span style='font-size:18px; font-weight:bold; color:{oi_color};'>{lbl}</span>", unsafe_allow_html=True)
                    
                st.markdown("---")
                st.markdown("**ARC Options Proximity Intelligence & Strike Optimizers**")
                
                pc1, pc2, pc3, pc4 = st.columns([1.5, 1.5, 4.3, 2.7])
                with pc1: st.metric("Strike-Level PCR", f"{strike_pcr:.2f}" if api_success else "0.0")
                with pc2: st.metric("Overall Asset PCR", f"{overall_pcr:.2f}" if api_success else "0.0")
                with pc3:
                    st.markdown(f"""
                    <div style='padding: 10px; border: 1px dashed #D1A553; border-radius: 6px; background-color: #FFFDF9; font-size:13px;'>
                        <b>💡 Dhan Option Chain Target Optimizers:</b><br>
                        🔹 <b>Optimal Call (CE):</b> {best_ce} <span style='color:#64748B;'>(OI Cluster)</span><br>
                        🔹 <b>Optimal Put (PE):</b> {best_pe} <span style='color:#64748B;'>(OI Cluster)</span>
                    </div>
                    """, unsafe_allow_html=True)
                with pc4:
                    st.markdown("<span style='font-size:13px; font-weight:bold; color:#0F172A;'>📰 News Feed</span>", unsafe_allow_html=True)
                    
                    from core_engines.nlp_router import ASSET_ALIASES
                    from integrations.google_sheets import fetch_dataframe_safe
                    
                    df_news_dataset = fetch_dataframe_safe("Telegram_Raw_Logs")
                    
                    match_bullet_items = []
                    if not df_news_dataset.empty:
                        target_clean = base_ticker_raw.replace(" ", "").upper()
                        aliases = ASSET_ALIASES.get(target_clean, [target_clean])
                        
                        for _, entry in df_news_dataset.iterrows():
                            if any(kw in str(entry.get("Channel Source", "")).lower() for kw in ["beat the street", "news"]):
                                text_chunk = str(entry.get("Raw Message Text", ""))
                                text_upper = text_chunk.upper()
                                text_normalized = text_upper.replace(" ", "")
                                
                                matched = False
                                for alias in aliases:
                                    pattern = r'(?:^|[^A-Z0-9])' + re.escape(alias.upper()) + r'(?:$|[^A-Z0-9])'
                                    if re.search(pattern, text_upper) or alias.replace(" ", "") in text_normalized:
                                        matched = True
                                        break
                                
                                if matched:
                                    clean_snippet = text_chunk.replace('\n', ' ')[:65] + "..." if len(text_chunk) > 65 else text_chunk.replace('\n', ' ')
                                    match_bullet_items.append(f"<li style='font-size:11px; margin-bottom:4px; color:#334155;'><b>{str(entry.get('Timestamp',''))[11:16]}</b>: {clean_snippet}</li>")
                    
                    if match_bullet_items:
                        st.markdown(f"<ul style='padding-left:14px; margin:0;'>{''.join(match_bullet_items[:3])}</ul>", unsafe_allow_html=True)
                    else:
                        st.markdown("<div style='font-size:11px; color:#64748B; padding-top:4px;'>No macro news updates found for this asset index.</div>", unsafe_allow_html=True)
        
        with st.container(border=True):
            st.markdown("**Market Intelligence**")
            f1, f2, f3, f4, f5, f6 = st.columns(6)
            f1.metric("P/E", f_metrics['stock_pe']); f2.metric("ROE", f_metrics['roe']); f3.metric("ROCE", f_metrics['roce']); f4.metric("D/E", f"{f_metrics['debt_to_equity']}x"); f5.metric("EBITDA", f_metrics['ebitda_margin']); f6.metric("Inst.", f_metrics['inst_own'])
            t1, t2, t3, t4, t5 = st.columns(5)
            t1.metric("RSI", t_metrics['rsi']); t2.markdown(f"**20 EMA**<br><span style='{prox_color(t_metrics['ema20_prox'])}'>{t_metrics['ema20_prox']}%</span>", unsafe_allow_html=True); t3.markdown(f"**50 EMA**<br><span style='{prox_color(t_metrics['ema50_prox'])}'>{t_metrics['ema50_prox']}%</span>", unsafe_allow_html=True); t4.markdown(f"**200 EMA**<br><span style='{prox_color(t_metrics['ema200_prox'])}'>{t_metrics['ema200_prox']}%</span>", unsafe_allow_html=True); t5.metric("Vol Spike", f"{t_metrics['vol_spike']}%" if t_metrics['vol_spike'] != "-" else "-")
        
        with st.container(border=True):
            st.markdown("**Interactive Chart**")
            render_tv_chart(sym_key)
    
    with tab_psych_exec:
        # Check if this is an unpromoted scanner row (-1)
        if sheet_row_id == -1:
            st.info("Scanner target staged for inspection. Promote this asset to your Watchlist to enable trade logging and position management.")
        else:
            st.markdown("#### Psychology & Trade Rationale")
            with st.container(border=True):
                curr_rationale = str(trade_data.get('Strategic Rationale (Why I took it)', ''))
                curr_emotions = str(trade_data.get('Emotions at Entry (FOMO, Calm, etc.)', ''))
                if curr_rationale.strip() and curr_rationale != 'nan': st.info(f"**Rationale:** {curr_rationale}")
                if curr_emotions.strip() and curr_emotions != 'nan': st.warning(f"**Emotions:** {curr_emotions}")
                
                with st.expander("📝 Update Psychology Notes"):
                    with st.form("psychology_update_form"):
                        new_rationale = st.text_area("Execution Rationale", value=curr_rationale if curr_rationale != 'nan' else '')
                        new_emotions = st.text_area("Psychological State", value=curr_emotions if curr_emotions != 'nan' else '')
                        if st.form_submit_button("Save Notes", type="primary"):
                            primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Strategic Rationale (Why I took it)") + 1, str(new_rationale))
                            primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Emotions at Entry (FOMO, Calm, etc.)") + 1, str(new_emotions))
                            st.rerun()
                            
            st.markdown("#### Execution & Asset Repair")
            with st.container(border=True):
                col1, col2, col3, col4, col5 = st.columns([1.5, 1.5, 1.5, 1.5, 4], gap="small")
                col1.metric("Status", trade_data.get('Status (Watch/Active/Closed)', 'N/A'))
                col2.metric("Entry Range", trade_data.get('Entry CMP / Range', 'N/A'))
                col3.metric("Live Price", trade_data.get('Live Price', '-'))
                col4.metric("Exit Price", trade_data.get('Exit Price', 'Pending'))
                with col5:
                    try:
                        entry_val = float(re.findall(r'[\d\.]+', str(trade_data['Entry CMP / Range']))[0])
                        exit_val = float(str(trade_data['Exit Price']))
                        pnl = exit_val - entry_val
                        if pnl > 0: st.success(f"Net Points Captured: +{round(pnl, 2)}")
                        else: st.error(f"Net Points Lost: {round(pnl, 2)}")
                    except: st.info("Awaiting execution parameters.")
                    
                with st.expander("🛠 Advanced Asset Repair Tool"):
                    fix_query = st.text_input("Search Official Master Database", value=str(trade_data.get('Symbol / Asset', '')).split()[0], key="fix_contract_query")
                    fix_results = api.search_instruments(fix_query)
                    if not fix_results.empty:
                        selected_fix = st.selectbox("Select Correct Contract:", fix_results['SEM_TRADING_SYMBOL'].tolist(), key="fix_contract_select")
                        if st.button("Save & Re-Link Asset", type="primary", use_container_width=True):
                            fix_row = fix_results[fix_results['SEM_TRADING_SYMBOL'] == selected_fix].iloc[0]
                            primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Symbol / Asset") + 1, str(fix_row['SEM_TRADING_SYMBOL']))
                            primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Security ID") + 1, str(fix_row['SEM_SMST_SECURITY_ID']))
                            primary_watchlist_ws.update_cell(sheet_row_id, sheet_headers.index("Exchange") + 1, "NSE_EQ" if str(fix_row['SEM_EXM_EXCH_ID']) == "NSE" and str(fix_row['SEM_SEGMENT']) == "E" else "NSE_FNO")
                            st.rerun()
