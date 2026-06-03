# --- PLOTLY SECTOR HEATMAP RENDERING ---
            with tab_heatmap:
                try: 
                    timestamp_val = settings_sheet.acell('B9').value or "Pending"
                except: 
                    timestamp_val = "Pending"
                
                st.markdown("#### Live NIFTY Sector Performance")
                st.caption(f"Visualizing official NSE sectoral index flows. Last updated: {timestamp_val}")
                
                if st.button("Sync Live Market Map", use_container_width=True, key="sync_heatmap"): 
                    api.fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)

                try:
                    raw_json = settings_sheet.acell('B12').value
                    # Defensive Check: Verify the cell contains real content before decoding
                    if raw_json and str(raw_json).strip() != "" and str(raw_json).strip() != "-":
                        data = json.loads(raw_json)
                        df_heat = pd.DataFrame(data)
                        
                        if not df_heat.empty:
                            fig = px.treemap(
                                df_heat, 
                                path=['sector'], 
                                values='weight', 
                                color='change',
                                color_continuous_scale=['#F23645', '#F8FAFC', '#089981'], 
                                color_continuous_midpoint=0
                            )
                            
                            fig.update_traces(
                                textinfo="label+text",
                                texttemplate="%{label}<br><b>%{customdata[0]:.2f}%</b>",
                                customdata=df_heat[['change']],
                                textfont=dict(size=16, color="white")
                            )
                            fig.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=500)
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.info("Dataframe parsed successfully but contains no rows.")
                    else:
                        st.info("Awaiting initial live JSON broadcast stream. Please click 'Sync Live Market Map' to initialize.")
                except json.JSONDecodeError:
                    st.warning("Data payload is preparing its structure. Click 'Sync Live Market Map' to force refresh.")
                except Exception as e:
                    st.error(f"Visualization Component Alert: {e}")
