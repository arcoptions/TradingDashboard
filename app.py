import streamlit as st
import database as db
import broker_api as api
import modals
import views

# --- PAGE CONFIG MUST BE FIRST ---
st.set_page_config(
    page_title="ARC Trading Terminal", 
    layout="wide",
    initial_sidebar_state="expanded" 
)

# --- CHAMPAGNE GOLD CSS FOR PREMIUM LIGHT THEME ---
st.markdown("""
    <style>
        #MainMenu {visibility: hidden;}
        [data-testid="stToolbar"] {display: none !important;} 
        footer {visibility: hidden;}
        .block-container {padding-top: 3rem; padding-bottom: 0rem;}
        
        :root {
            --arc-gold-light: #F9E7BE;
            --arc-gold-mid: #D1A553;
            --arc-gold-dark: #B88A3B;
            --arc-text-dark: #1A202C; 
        }
        
        div[data-testid="stSidebar"] .stButton > button,
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label,
        div[data-testid="stSidebar"] div[role="radiogroup"] label[data-testid="stRadioOption"] {
            width: 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
            height: 46px !important;
            min-height: 46px !important;
            max-height: 46px !important;
            box-sizing: border-box !important;
            margin: 6px 0px !important;
            padding: 10px 16px !important;
            border-radius: 6px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: flex-start !important;
            text-align: left !important;
            font-size: 15px !important;
            cursor: pointer !important;
            transition: all 0.15s ease-in-out !important;
        }

        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label > div:first-child {
            display: none !important;
        }

        div[data-testid="stSidebar"] .stButton > button div[data-testid="stMarkdownContainer"],
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label div[data-testid="stMarkdownContainer"] {
            width: 100% !important;
            display: flex !important;
            justify-content: flex-start !important;
            align-items: center !important;
        }

        div[data-testid="stSidebar"] .stButton > button p,
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label p {
            margin: 0 !important;
            padding: 0 !important;
            font-size: 15px !important;
            width: 100% !important;
            text-align: left !important;
        }

        div[data-testid="stSidebar"] .stButton > button[kind="primary"],
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, var(--arc-gold-light) 0%, var(--arc-gold-mid) 100%) !important; 
            color: var(--arc-text-dark) !important;
            border: 1px solid var(--arc-gold-dark) !important;
            font-weight: 700 !important;
        }
        div[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover,
        .stButton > button[kind="primary"]:hover {
            background: linear-gradient(135deg, #FFF0CA 0%, #E0B462 100%) !important;
            box-shadow: 0px 4px 12px rgba(209, 165, 83, 0.3) !important;
        }

        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-checked="true"] {
            background: linear-gradient(135deg, var(--arc-gold-light) 0%, var(--arc-gold-mid) 100%) !important; 
            border: 1px solid var(--arc-gold-dark) !important;
        }
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label[data-checked="true"] p {
            color: var(--arc-text-dark) !important;
            font-weight: 700 !important;
        }

        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] {
            background: linear-gradient(135deg, var(--arc-gold-light) 0%, var(--arc-gold-mid) 100%) !important;
            color: var(--arc-text-dark) !important;
            border: 1px solid var(--arc-gold-dark) !important;
        }
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] span {
            color: var(--arc-text-dark) !important;
            font-weight: 600 !important;
        }
        div[data-testid="stMultiSelect"] span[data-baseweb="tag"] svg {
            fill: var(--arc-text-dark) !important;
        }

        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label:not([data-checked="true"]) {
            background-color: transparent !important; 
            border: 1px solid #E2E8F0 !important;
        }
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label:not([data-checked="true"]):hover {
            background-color: #F8FAFC !important;
        }
        div[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] label:not([data-checked="true"]) p {
            color: #64748B !important;
            font-weight: 500 !important;
        }
        
        [data-testid="stSidebar"] div[data-testid="stExpander"] {
            border-color: #E2E8F0;
        }
        
        .sync-timestamp-text {
            font-size: 12px !important;
            color: #64748B !important;
            text-align: right !important;
            margin-top: -6px !important;
            padding-bottom: 14px !important;
            width: 100%;
        }
    </style>
""", unsafe_allow_html=True)

# --- SESSION STATE INITIALIZATION ---
if "viewing_trade" not in st.session_state: st.session_state.viewing_trade = None
if "viewing_trade_row" not in st.session_state: st.session_state.viewing_trade_row = None
if "qp_key" not in st.session_state: st.session_state.qp_key = 0

# --- DATABASE CONNECTION & GLOBAL AUTO-SCHEDULER ENGINE ---
try:
    worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers = db.init_db()
    api.start_cron_daemon_v5(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
except Exception as e:
    st.error(f"Database Connection Failed: {e}")
    st.stop()

# --- SIDEBAR NAV & SETTINGS ---
with st.sidebar:
    try: st.image("logo.png", use_container_width=True)
    except: st.markdown("## ARC Terminal")
    
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Log New Trade", type="primary", use_container_width=True): 
        modals.trade_entry_modal(worksheet, sheet_headers)
        
    st.markdown("<br>", unsafe_allow_html=True)
    current_page = st.radio("Navigation", ["Options Tracker", "Chartink Scanners"], label_visibility="collapsed")
    
    st.divider()
    with st.expander("Daily API Setup", expanded=False):
        st.caption("Paste today's generated Dhan Access Token here.")
        try: saved_token = settings_sheet.acell('B2').value or ""
        except: saved_token = ""
        new_token = st.text_input("Today's Token:", value=saved_token, type="password")
        if st.button("Save Key", use_container_width=True):
            settings_sheet.update_acell('B2', new_token)
            st.success("API Key Locked.")
            st.rerun()

# --- PAGE ROUTING ---
if current_page == "Options Tracker":
    views.render_options_tracker(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
elif current_page == "Chartink Scanners":
    views.render_chartink_scanners(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers)
