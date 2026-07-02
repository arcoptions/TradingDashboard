import requests
import pandas as pd
import gspread
import base64
from google.oauth2.service_account import Credentials
import streamlit as st
import threading
import time
import json
import datetime
import re
from datetime import timezone, timedelta
from streamlit.runtime.scriptrunner import add_script_run_ctx
from integrations.google_sheets import fetch_dataframe_safe, fetch_settings_dict

SECTOR_SYMBOLS = {
    "Financial Services": {"symbol": "NIFTY FIN SERVICE", "weight": 35.0},
    "IT": {"symbol": "NIFTY IT", "weight": 14.5}, 
    "Oil & Gas / Energy": {"symbol": "NIFTY ENERGY", "weight": 12.0},
    "FMCG": {"symbol": "NIFTY FMCG", "weight": 9.0},
    "Auto": {"symbol": "NIFTY AUTO", "weight": 7.0},
    "Pharma": {"symbol": "NIFTY PHARMA", "weight": 5.0},
    "Metal": {"symbol": "NIFTY METAL", "weight": 4.0},
    "Realty": {"symbol": "NIFTY REALTY", "weight": 1.0},
    "Media": {"symbol": "NIFTY MEDIA", "weight": 0.5}
}

def robust_api_call(func, *args, **kwargs):
    delay = 1.5
    for attempt in range(4):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if ("429" in str(e) or "Quota" in str(e)) and attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise e

def _download_dhan_scrip_master():
    url = "https://images.dhan.co/api-data/api-scrip-master.csv"
    df = pd.read_csv(url, low_memory=False)
    if df.empty:
        return df
    return df[df['SEM_EXM_EXCH_ID'].isin(['NSE', 'IDX'])]


@st.cache_data(ttl=1800)
def get_dhan_scrip_master():
    try:
        return _download_dhan_scrip_master()
    except: return pd.DataFrame()


def get_dhan_scrip_master_fresh():
    try:
        return _download_dhan_scrip_master()
    except:
        return pd.DataFrame()


def _search_in_scrip_df(scrip_df, cleaned_query):
    if scrip_df.empty:
        return pd.DataFrame()

    exact_match = scrip_df[scrip_df['SEM_TRADING_SYMBOL'] == cleaned_query]
    if not exact_match.empty:
        return exact_match.head(10)

    terms = cleaned_query.split()
    working_df = scrip_df.copy()
    if 'SEARCH_STRING' not in working_df.columns:
        normalized_trading_sym = working_df['SEM_TRADING_SYMBOL'].fillna('').str.replace('-', ' ', regex=False).str.replace('_', ' ', regex=False)
        normalized_custom_sym = working_df['SEM_CUSTOM_SYMBOL'].fillna('').str.replace('-', ' ', regex=False).str.replace('_', ' ', regex=False)
        working_df['SEARCH_STRING'] = normalized_trading_sym.str.upper() + " " + normalized_custom_sym.str.upper()

    mask = pd.Series([True] * len(working_df))
    for term in terms:
        mask = mask & working_df['SEARCH_STRING'].str.contains(term, regex=False)
    results = working_df[mask].copy()

    if not results.empty and 'SEM_EXPIRY_DATE' in results.columns:
        results['segment_order'] = results['SEM_SEGMENT'].apply(lambda x: 0 if x == 'D' else 1)
        results['Parsed_Expiry'] = pd.to_datetime(results['SEM_EXPIRY_DATE'], errors='coerce')
        results = results.sort_values(by=['segment_order', 'Parsed_Expiry', 'SEM_TRADING_SYMBOL'], ascending=[True, True, True])
        results = results.drop(columns=['segment_order', 'Parsed_Expiry'])

    return results.head(200)

def search_instruments(query):
    scrip_df = get_dhan_scrip_master()
    if not query or scrip_df.empty: return pd.DataFrame()
    cleaned_query = str(query).replace('-', ' ').replace('_', ' ').upper().strip()

    results = _search_in_scrip_df(scrip_df, cleaned_query)
    # If option-like query is missing in cached snapshot, retry once with fresh CSV.
    is_option_like = any(t in cleaned_query for t in [" CE", " PE", " CALL", " PUT"]) or any(ch.isdigit() for ch in cleaned_query)
    if results.empty and is_option_like:
        fresh_df = get_dhan_scrip_master_fresh()
        if not fresh_df.empty:
            results = _search_in_scrip_df(fresh_df, cleaned_query)

    return results

def resolve_instrument(parsed_sym):
    scrip_df = get_dhan_scrip_master()
    parsed_sym = str(parsed_sym).strip().upper()
    if not parsed_sym or scrip_df.empty: return parsed_sym, "", "NSE_EQ"
    
    eq_match = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == parsed_sym) & (scrip_df['SEM_SEGMENT'] == 'E')]
    if not eq_match.empty:
        return str(eq_match.iloc[0]['SEM_TRADING_SYMBOL']), str(eq_match.iloc[0]['SEM_SMST_SECURITY_ID']), "NSE_EQ"
        
    results = search_instruments(parsed_sym)
    if not results.empty:
        row = results.iloc[0]
        exch, seg = str(row['SEM_EXM_EXCH_ID']), str(row['SEM_SEGMENT'])
        ret_exch = "NSE_EQ" if exch == "NSE" and seg == "E" else "NSE_FNO"
        return str(row['SEM_TRADING_SYMBOL']), str(row['SEM_SMST_SECURITY_ID']), ret_exch
    return parsed_sym, "", "NSE_EQ"

def _normalize_dhan_token(raw_token):
    token = str(raw_token or "").strip()
    token = token.strip("'\"")
    token = re.sub(r"^(access[-_ ]?token|token)\s*[:=]\s*", "", token, flags=re.IGNORECASE)
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    token = " ".join(token.split())
    return token


def _decode_dhan_token_payload(raw_token):
    token = _normalize_dhan_token(raw_token)
    parts = token.split(".")
    if len(parts) < 2:
        return {}

    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded_payload = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
    except Exception:
        return {}
    return decoded_payload if isinstance(decoded_payload, dict) else {}


def _get_dhan_token_expiry(raw_token):
    payload = _decode_dhan_token_payload(raw_token)
    exp_value = payload.get("exp")
    if not exp_value:
        return None
    try:
        return datetime.datetime.fromtimestamp(int(exp_value), tz=timezone.utc)
    except Exception:
        return None


def _is_dhan_token_expired(raw_token):
    expiry = _get_dhan_token_expiry(raw_token)
    return bool(expiry and expiry <= datetime.datetime.now(timezone.utc))


def _extract_dhan_client_id(raw_token):
    payload = _decode_dhan_token_payload(raw_token)
    return str(payload.get("dhanClientId") or "").strip()


def _resolve_dhan_client_id(raw_token=None, fallback_client_id=None):
    token_client_id = _extract_dhan_client_id(raw_token)
    if token_client_id:
        return token_client_id
    return str(fallback_client_id or st.secrets["dhan"].get("dhan_client_id", "")).strip()


def _format_dhan_api_error(response, fallback_prefix="Dhan API request failed"):
    try:
        payload = response.json()
    except ValueError:
        payload = None

    details = ""
    if isinstance(payload, dict):
        data_node = payload.get("data")
        if isinstance(data_node, dict):
            if data_node.get("806") == "Data APIs not Subscribed":
                details = "Data APIs not subscribed for this Dhan account"
            elif data_node:
                details = "; ".join([f"{k}: {v}" for k, v in data_node.items()])

        for key in ("message", "remarks", "error", "errors", "status"):
            value = payload.get(key)
            if value:
                if not details or str(value).strip().lower() not in {"failed", "error"}:
                    details = str(value)
                break

    if not details:
        details = (response.text or "").strip()

    details = details[:200] if details else ""
    if details:
        return f"{fallback_prefix} ({response.status_code}): {details}"
    return f"{fallback_prefix} ({response.status_code})"


def _build_dhan_headers(daily_token=None, fallback_client_id=None):
    token_to_use = _normalize_dhan_token(daily_token or st.secrets["dhan"].get("access_token", ""))
    client_id_to_use = _resolve_dhan_client_id(token_to_use, fallback_client_id=fallback_client_id)
    return {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'access-token': token_to_use,
        'client-id': client_id_to_use,
    }


def _parse_option_chain_symbol(asset_symbol):
    import derivatives_engine as de

    contract_meta = de.parse_option_contract(asset_symbol)
    if contract_meta:
        return contract_meta

    clean_symbol = re.sub(r'\(.*?\)', '', str(asset_symbol or '').upper()).strip()
    compact_match = re.search(r'([A-Z&]+)\s+(\d{2,6})\s+(CE|PE|CALL|PUT)', clean_symbol)
    if not compact_match:
        return None

    option_type = compact_match.group(3)
    if option_type == 'CALL':
        option_type = 'CE'
    if option_type == 'PUT':
        option_type = 'PE'

    return {
        "underlying": compact_match.group(1).strip(),
        "strike": float(compact_match.group(2)),
        "type": option_type,
        "expiry_date": "",
    }


def _fetch_option_chain_payload(asset_symbol, daily_token=None):
    contract_meta = _parse_option_chain_symbol(asset_symbol)
    if not contract_meta:
        return None, None

    underlying = contract_meta["underlying"]
    fallback_expiry = contract_meta.get("expiry_date", "")
    scrip_df = get_dhan_scrip_master()
    if scrip_df.empty:
        return contract_meta, None

    underlying_upper = str(underlying).strip().upper()
    candidate_symbols = [underlying_upper]
    if underlying_upper == "SENSEX":
        candidate_symbols = ["SENSEX", "SENSEX1", "BSESENSEX"]

    candidate_rows = scrip_df[scrip_df['SEM_TRADING_SYMBOL'].astype(str).str.upper().isin(candidate_symbols)].copy()
    if candidate_rows.empty:
        candidate_rows = scrip_df[scrip_df['SEM_TRADING_SYMBOL'].astype(str).str.upper().str.contains(underlying_upper, regex=False, na=False)].copy()

    if candidate_rows.empty:
        return contract_meta, None

    headers = _build_dhan_headers(daily_token=daily_token)
    seen_combinations = set()

    for _, row in candidate_rows.iterrows():
        underlying_id = int(row['SEM_SMST_SECURITY_ID'])
        exch = str(row['SEM_EXM_EXCH_ID']).strip().upper()
        seg = str(row['SEM_SEGMENT']).strip().upper()
        if seg == 'I':
            seg_candidates = ["IDX_I", "BSE_I", "NSE_I"]
        elif exch == 'BSE':
            seg_candidates = ["BSE_I", "IDX_I", "BSE_EQ"]
        else:
            seg_candidates = ["IDX_I", "NSE_EQ", "BSE_I"]

        for underlying_seg in seg_candidates:
            combo_key = (underlying_id, underlying_seg)
            if combo_key in seen_combinations:
                continue
            seen_combinations.add(combo_key)

            valid_expiry = fallback_expiry
            try:
                exp_res = requests.post(
                    "https://api.dhan.co/v2/optionchain/expirylist",
                    headers=headers,
                    json={"UnderlyingScrip": underlying_id, "UnderlyingSeg": underlying_seg},
                    timeout=5,
                )
                if exp_res.status_code == 200 and exp_res.json().get("data"):
                    exp_list = exp_res.json()["data"]
                    if fallback_expiry:
                        parsed_dt = datetime.datetime.strptime(fallback_expiry, "%Y-%m-%d")
                        matching_expiries = [
                            e for e in exp_list
                            if datetime.datetime.strptime(e, "%Y-%m-%d").year == parsed_dt.year
                            and datetime.datetime.strptime(e, "%Y-%m-%d").month == parsed_dt.month
                        ]
                        if matching_expiries:
                            valid_expiry = max(matching_expiries)
                    if not valid_expiry and exp_list:
                        valid_expiry = exp_list[0]
            except Exception:
                continue

            if not valid_expiry:
                continue

            try:
                res = requests.post(
                    "https://api.dhan.co/v2/optionchain",
                    headers=headers,
                    json={"UnderlyingScrip": underlying_id, "UnderlyingSeg": underlying_seg, "Expiry": valid_expiry},
                    timeout=10,
                )
                if res.status_code == 200 and res.json().get("data"):
                    contract_meta["expiry_date"] = valid_expiry
                    return contract_meta, res.json()["data"]
            except Exception:
                continue

    return contract_meta, None


def get_index_option_chain_snapshot(index_symbol, daily_token=None):
    underlying_upper = str(index_symbol or "").strip().upper()
    if not underlying_upper:
        return pd.DataFrame(), {}

    scrip_df = get_dhan_scrip_master()
    if scrip_df.empty:
        return pd.DataFrame(), {}

    exact_priority = {
        "NIFTY": ["NIFTY"],
        "SENSEX": ["SENSEX", "SENSEX1", "BSESENSEX"],
    }
    candidate_symbols = exact_priority.get(underlying_upper, [underlying_upper])

    candidate_rows = scrip_df[scrip_df['SEM_TRADING_SYMBOL'].astype(str).str.upper().isin(candidate_symbols)].copy()
    if candidate_rows.empty:
        candidate_rows = scrip_df[scrip_df['SEM_TRADING_SYMBOL'].astype(str).str.upper().str.contains(underlying_upper, regex=False, na=False)].copy()
    if candidate_rows.empty:
        return pd.DataFrame(), {}

    if underlying_upper == "SENSEX":
        candidate_rows = candidate_rows.assign(
            _priority=candidate_rows['SEM_TRADING_SYMBOL'].astype(str).str.upper().map(
                lambda symbol: 0 if symbol == 'SENSEX' else 1 if symbol == 'SENSEX1' else 2
            )
        ).sort_values(by=["_priority", "SEM_TRADING_SYMBOL"]).drop(columns=["_priority"])

    headers = _build_dhan_headers(daily_token=daily_token)
    seen_combinations = set()

    for _, row in candidate_rows.iterrows():
        underlying_id = int(row['SEM_SMST_SECURITY_ID'])
        exch = str(row['SEM_EXM_EXCH_ID']).strip().upper()
        seg = str(row['SEM_SEGMENT']).strip().upper()
        if seg == 'I':
            seg_candidates = ["NSE_I", "BSE_I", "IDX_I"] if underlying_upper == "NIFTY" else ["BSE_I", "IDX_I", "NSE_I"]
        elif exch == 'BSE':
            seg_candidates = ["BSE_I", "IDX_I", "BSE_EQ"]
        else:
            seg_candidates = ["IDX_I", "NSE_EQ", "NSE_I"]

        for underlying_seg in seg_candidates:
            combo_key = (underlying_id, underlying_seg)
            if combo_key in seen_combinations:
                continue
            seen_combinations.add(combo_key)

            try:
                exp_res = requests.post(
                    "https://api.dhan.co/v2/optionchain/expirylist",
                    headers=headers,
                    json={"UnderlyingScrip": underlying_id, "UnderlyingSeg": underlying_seg},
                    timeout=5,
                )
                if exp_res.status_code != 200 or not exp_res.json().get("data"):
                    continue
                exp_list = exp_res.json()["data"]
                if not exp_list:
                    continue
                valid_expiry = exp_list[0]

                res = requests.post(
                    "https://api.dhan.co/v2/optionchain",
                    headers=headers,
                    json={"UnderlyingScrip": underlying_id, "UnderlyingSeg": underlying_seg, "Expiry": valid_expiry},
                    timeout=10,
                )
                if res.status_code == 200 and res.json().get("data"):
                    data_obj = res.json()["data"]
                    rows = []
                    for strike_str, strike_data in data_obj.get("oc", {}).items():
                        ce_node = strike_data.get("ce", {}) or {}
                        pe_node = strike_data.get("pe", {}) or {}
                        rows.append({
                            "strike": float(strike_str),
                            "call_oi": float(ce_node.get("oi", 0) or 0),
                            "put_oi": float(pe_node.get("oi", 0) or 0),
                            "call_oi_change": float(ce_node.get("oi_change", ce_node.get("change_in_oi", ce_node.get("previous_oi", 0))) or 0),
                            "put_oi_change": float(pe_node.get("oi_change", pe_node.get("change_in_oi", pe_node.get("previous_oi", 0))) or 0),
                        })

                    df_chain = pd.DataFrame(rows)
                    if df_chain.empty:
                        return df_chain, {}

                    df_chain = df_chain.sort_values(by="strike").reset_index(drop=True)
                    meta = {
                        "underlying": underlying_upper,
                        "expiry": valid_expiry,
                        "spot_price": float(data_obj.get("last_price", 0) or 0),
                        "target_strike": 0.0,
                        "max_call_oi_strike": float(df_chain.loc[df_chain["call_oi"].idxmax(), "strike"]),
                        "max_put_oi_strike": float(df_chain.loc[df_chain["put_oi"].idxmax(), "strike"]),
                    }
                    return df_chain, meta
            except Exception:
                continue

    return pd.DataFrame(), {}


def get_option_chain_metrics(asset_symbol, daily_token=None):
    contract_meta, data_obj = _fetch_option_chain_payload(asset_symbol, daily_token=daily_token)
    if not contract_meta or not data_obj:
        return {}

    strike = float(contract_meta["strike"])
    opt_type = contract_meta["type"].lower()
    oc_dict = data_obj.get("oc", {})
    total_call_oi, total_put_oi = 0.0, 0.0
    metrics_map = {"implied_volatility": 0.0, "delta": 0.0, "theta": 0.0, "strike_pcr": 0.0, "overall_pcr": 1.0, "best_ce": "-", "best_pe": "-"}
    ce_pool, pe_pool = [], []

    for strike_str, strike_data in oc_dict.items():
        node_strike = float(strike_str)
        ce_node, pe_node = strike_data.get("ce", {}), strike_data.get("pe", {})
        c_oi = float(ce_node.get("oi", 0) if ce_node else 0)
        p_oi = float(pe_node.get("oi", 0) if pe_node else 0)
        total_call_oi += c_oi
        total_put_oi += p_oi

        if c_oi > 0:
            ce_pool.append({"strike": node_strike, "oi": c_oi})
        if p_oi > 0:
            pe_pool.append({"strike": node_strike, "oi": p_oi})

        if abs(node_strike - strike) < 0.1:
            target_node = strike_data.get(opt_type)
            if target_node:
                metrics_map.update({
                    "implied_volatility": float(target_node.get("implied_volatility", 0.0)),
                    "delta": float(target_node.get("greeks", {}).get("delta", 0)),
                    "theta": float(target_node.get("greeks", {}).get("theta", 0)),
                    "strike_pcr": round(p_oi / c_oi, 2) if c_oi > 0 else 0.0
                })
    metrics_map["overall_pcr"] = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 0.0
    if ce_pool:
        metrics_map["best_ce"] = sorted(ce_pool, key=lambda x: x["oi"], reverse=True)[0]["strike"]
    if pe_pool:
        metrics_map["best_pe"] = sorted(pe_pool, key=lambda x: x["oi"], reverse=True)[0]["strike"]
    return metrics_map


def get_option_chain_snapshot(asset_symbol, daily_token=None):
    contract_meta, data_obj = _fetch_option_chain_payload(asset_symbol, daily_token=daily_token)
    if not contract_meta or not data_obj:
        return pd.DataFrame(), {}

    rows = []
    oc_dict = data_obj.get("oc", {})
    for strike_str, strike_data in oc_dict.items():
        ce_node = strike_data.get("ce", {}) or {}
        pe_node = strike_data.get("pe", {}) or {}
        rows.append({
            "strike": float(strike_str),
            "call_oi": float(ce_node.get("oi", 0) or 0),
            "put_oi": float(pe_node.get("oi", 0) or 0),
            "call_oi_change": float(ce_node.get("oi_change", ce_node.get("change_in_oi", ce_node.get("previous_oi", 0))) or 0),
            "put_oi_change": float(pe_node.get("oi_change", pe_node.get("change_in_oi", pe_node.get("previous_oi", 0))) or 0),
        })

    df_chain = pd.DataFrame(rows)
    if df_chain.empty:
        return df_chain, {}

    df_chain = df_chain.sort_values(by="strike").reset_index(drop=True)
    spot_price = float(data_obj.get("last_price", 0) or 0)
    target_strike = float(contract_meta.get("strike", 0) or 0)
    if target_strike > 0:
        df_chain["distance"] = (df_chain["strike"] - target_strike).abs()
        df_chain = df_chain.sort_values(by=["distance", "strike"]).head(11).sort_values(by="strike").reset_index(drop=True)
        df_chain = df_chain.drop(columns=["distance"])

    meta = {
        "underlying": contract_meta.get("underlying", ""),
        "expiry": contract_meta.get("expiry_date", ""),
        "spot_price": spot_price,
        "target_strike": target_strike,
        "max_call_oi_strike": float(df_chain.loc[df_chain["call_oi"].idxmax(), "strike"]) if not df_chain.empty else 0.0,
        "max_put_oi_strike": float(df_chain.loc[df_chain["put_oi"].idxmax(), "strike"]) if not df_chain.empty else 0.0,
    }
    return df_chain, meta


def fetch_dhan_orders(daily_token=None):
    try:
        settings = fetch_settings_dict()
        token_to_use = _normalize_dhan_token(daily_token or settings.get("Dhan Access Token", ""))
        if not token_to_use:
            return pd.DataFrame(), "Missing Dhan access token"
        headers = _build_dhan_headers(token_to_use)
        if not headers.get("client-id"):
            return pd.DataFrame(), "Missing Dhan client ID"
        response = requests.get("https://api.dhan.co/v2/orders", headers=headers, timeout=15)
        if response.status_code != 200:
            return pd.DataFrame(), f"Dhan orders API returned {response.status_code}: {response.text[:200]}"

        payload = response.json()
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                orders = payload.get("data", [])
            else:
                orders = [payload]
        elif isinstance(payload, list):
            orders = payload
        else:
            orders = []

        if not orders:
            return pd.DataFrame(), ""

        df_orders = pd.DataFrame(orders)
        if "updateTime" in df_orders.columns:
            df_orders["Parsed Update Time"] = pd.to_datetime(df_orders["updateTime"], errors="coerce")
            df_orders = df_orders.sort_values(by="Parsed Update Time", ascending=False)
        return df_orders, ""
    except Exception as e:
        return pd.DataFrame(), f"Unable to fetch Dhan orders: {e}"


def fetch_dhan_positions(daily_token=None):
    try:
        settings = fetch_settings_dict()
        token_to_use = _normalize_dhan_token(daily_token or settings.get("Dhan Access Token", ""))
        if not token_to_use:
            return pd.DataFrame(), "Missing Dhan access token"
        headers = _build_dhan_headers(token_to_use)
        if not headers.get("client-id"):
            return pd.DataFrame(), "Missing Dhan client ID"
        response = requests.get("https://api.dhan.co/v2/positions", headers=headers, timeout=15)
        if response.status_code != 200:
            return pd.DataFrame(), f"Dhan positions API returned {response.status_code}: {response.text[:200]}"

        payload = response.json()
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), list):
                positions = payload.get("data", [])
            else:
                positions = [payload]
        elif isinstance(payload, list):
            positions = payload
        else:
            positions = []

        if not positions:
            return pd.DataFrame(), ""

        df_positions = pd.DataFrame(positions)
        if "netQty" in df_positions.columns:
            df_positions["netQty"] = pd.to_numeric(df_positions["netQty"], errors="coerce")
        if "unrealizedProfit" in df_positions.columns:
            df_positions["unrealizedProfit"] = pd.to_numeric(df_positions["unrealizedProfit"], errors="coerce")
        if "positionType" in df_positions.columns:
            df_positions = df_positions.sort_values(by=["positionType"], ascending=True)
        return df_positions, ""
    except Exception as e:
        return pd.DataFrame(), f"Unable to fetch Dhan positions: {e}"

# --- FIXED: Stopped individual B2 Acell scraping ---
def execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers, background_client_id=None, daily_token=None):
    try:
        if not daily_token:
            vals = robust_api_call(settings_sheet.get_all_values)
            s_dict = {str(r[0]).strip(): str(r[1]).strip() for r in vals if len(r)>=2}
            daily_token = s_dict.get("Dhan Access Token", "")
        daily_token = _normalize_dhan_token(daily_token)
        if not daily_token: return "Missing dynamic authorization token"
    except Exception as e: return f"Database connection error: {e}"
    
    scrip_df = get_dhan_scrip_master()
    payload = {"NSE_EQ": [], "NSE_FNO": [], "IDX_I": [13]}
    row_map = []
    sheet1_heal_updates = []
    
    try:
        opt_data = robust_api_call(worksheet.get_all_records)
        if opt_data:
            df_opt = pd.DataFrame(opt_data)
            if not df_opt.empty:
                df_opt['_Sheet_Row'] = range(2, len(df_opt) + 2)
                
                active_rows = df_opt[df_opt["Status (Watch/Active/Closed)"].isin(["Active", "Watchlist"])]
                
                exch_idx = sheet_headers.index("Exchange") + 1
                sec_idx = sheet_headers.index("Security ID") + 1
                type_idx = sheet_headers.index("Trade Type (Eq/Option)") + 1
                
                for _, row in active_rows.iterrows():
                    symbol = str(row.get("Symbol / Asset", "")).strip()
                    exch = str(row.get("Exchange", "")).strip()
                    sec_id = str(row.get("Security ID", "")).strip()
                    
                    if not exch or not sec_id or sec_id in ["", "-", "None"]:
                        t_sym, t_sec, t_exch = resolve_instrument(symbol)
                        if t_sec:
                            exch, sec_id = t_exch, t_sec
                            auto_type = "Equity" if "EQ" in t_exch else "Option"
                            sheet1_heal_updates.append({'range': gspread.utils.rowcol_to_a1(row['_Sheet_Row'], exch_idx), 'values': [[t_exch]]})
                            sheet1_heal_updates.append({'range': gspread.utils.rowcol_to_a1(row['_Sheet_Row'], sec_idx), 'values': [[t_sec]]})
                            sheet1_heal_updates.append({'range': gspread.utils.rowcol_to_a1(row['_Sheet_Row'], type_idx), 'values': [[auto_type]]})
                            
                    if exch in payload and str(sec_id).isdigit():
                        payload[exch].append(int(sec_id))
                        row_map.append({"type": "opt", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": str(sec_id)})

        if scanner_sheet:
            scan_data = robust_api_call(scanner_sheet.get_all_records)
            if scan_data:
                df_scan = pd.DataFrame(scan_data)
                if not df_scan.empty:
                    df_scan['_Sheet_Row'] = range(2, len(df_scan) + 2)
                    for _, row in df_scan[df_scan["Status"].isin(["Monitoring", "Moved to Watchlist"])].iterrows():
                        symbol = str(row.get("Symbol", "")).strip()
                        if symbol:
                            _, sec_id, exch = resolve_instrument(symbol)
                            if exch in payload and str(sec_id).isdigit():
                                payload[exch].append(int(sec_id))
                                row_map.append({"type": "scan", "sheet_row": row['_Sheet_Row'], "exch": exch, "sec_id": str(sec_id)})
    except Exception as e: return f"Staging exception: {e}"

    if sheet1_heal_updates:
        try: robust_api_call(worksheet.batch_update, sheet1_heal_updates)
        except: pass

    payload = {k: list(set(v)) for k, v in payload.items() if v}
    if not payload or (len(payload) == 1 and not payload.get("IDX_I")): return "No active sync rows mapped"
        
    headers = _build_dhan_headers(daily_token, fallback_client_id=background_client_id)
    
    try: response = requests.post("https://api.dhan.co/v2/marketfeed/quote", headers=headers, json=payload, timeout=15)
    except Exception as e: return f"HTTP Timeout: {e}"
    
    if response.status_code == 200:
        data = response.json().get("data", {})
        opt_updates, scan_updates, settings_updates = [], [], []
        opt_col_idx = sheet_headers.index("Live Price") + 1
        
        scan_col_idx = scanner_headers.index("Live Price") + 1 if scanner_headers and "Live Price" in scanner_headers else None
        price_chg_col_idx = sheet_headers.index("Price Chg %") + 1 if "Price Chg %" in sheet_headers else None
        oi_chg_col_idx = sheet_headers.index("OI Chg %") + 1 if "OI Chg %" in sheet_headers else None
        
        for item in row_map:
            exch, sec_id = item["exch"], item["sec_id"]
            if exch in data and sec_id in data[exch]:
                sec_data = data[exch][sec_id]
                last_price = sec_data.get("last_price", "")
                lp = float(last_price) if last_price else 0.0
                pc = float(sec_data.get("previous_close") or sec_data.get("ohlc", {}).get("close") or lp)
                price_chg = round(((lp - pc) / pc * 100), 2) if pc > 0 else 0.0
                oi = float(sec_data.get("open_interest", 0))
                prev_oi = float(sec_data.get("previous_open_interest") or oi)
                oi_chg = round(((oi - prev_oi) / prev_oi * 100), 2) if prev_oi > 0 else 0.0
                
                if item["type"] == "opt": 
                    opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], opt_col_idx), 'values': [[str(last_price)]]})
                    if price_chg_col_idx and oi_chg_col_idx:
                        opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], price_chg_col_idx), 'values': [[str(price_chg)]]})
                        opt_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], oi_chg_col_idx), 'values': [[str(oi_chg)]]})
                elif item["type"] == "scan" and scan_col_idx: 
                    scan_updates.append({'range': gspread.utils.rowcol_to_a1(item["sheet_row"], scan_col_idx), 'values': [[str(last_price)]]})
        try:
            # Batch updates in chunks of 100 to avoid hitting quota limits
            max_batch_size = 100
            if opt_updates:
                for i in range(0, len(opt_updates), max_batch_size):
                    batch_chunk = opt_updates[i:i + max_batch_size]
                    robust_api_call(worksheet.batch_update, batch_chunk)
                    time.sleep(0.5)  # Small delay between batches
            
            if scan_updates and scanner_sheet:
                for i in range(0, len(scan_updates), max_batch_size):
                    batch_chunk = scan_updates[i:i + max_batch_size]
                    robust_api_call(scanner_sheet.batch_update, batch_chunk)
                    time.sleep(0.5)  # Small delay between batches
            
            idx_item = data.get("IDX_I", {}).get("13", {})
            lp_n50 = float(idx_item.get("last_price", 0.0))
            if lp_n50 > 0:
                ohlc_close = float(idx_item.get("ohlc", {}).get("close", lp_n50))
                diff_n50 = lp_n50 - ohlc_close
                pct_n50 = (diff_n50 / ohlc_close) * 100 if ohlc_close > 0 else 0.0
                settings_updates.append({'range': 'B10', 'values': [[f"{lp_n50:.2f},{diff_n50:.2f},{pct_n50:.2f}"]]})
                
            heatmap_arr = []
            idx_master = data.get("IDX_I", {})
            for name, info in SECTOR_SYMBOLS.items():
                match_rows = scrip_df[(scrip_df['SEM_TRADING_SYMBOL'] == info["symbol"]) & (scrip_df['SEM_EXM_EXCH_ID'] == 'IDX')]
                if not match_rows.empty:
                    s_id = str(match_rows.iloc[0]['SEM_SMST_SECURITY_ID'])
                    if s_id in idx_master:
                        node = idx_master[s_id]
                        n_lp = float(node.get("last_price", 0.0))
                        n_pc = float(node.get("ohlc", {}).get("close", n_lp))
                        n_pct = round(((n_lp - n_pc) / n_pc * 100), 2) if n_pc > 0 else 0.0
                        heatmap_arr.append({"sector": name, "change": n_pct, "weight": info["weight"]})
            
            if heatmap_arr: 
                settings_updates.append({'range': 'B12', 'values': [[json.dumps(heatmap_arr)]]})
            
            ist_time = (datetime.datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).strftime("%d-%b %I:%M %p")
            settings_updates.append({'range': 'B9', 'values': [[ist_time]]})
            
            if settings_updates:
                robust_api_call(settings_sheet.batch_update, settings_updates)

            # CLEAR CACHE SO UI UPDATES IMMEDIATELY WITH NEW PRICES
            fetch_dataframe_safe.clear()
            fetch_settings_dict.clear()

        except Exception as e: return f"Sheets transmission exception: {e}"
        return "Success"
    if response.status_code == 401:
        return _format_dhan_api_error(response, "Dhan authorization failed. Save a fresh access token in API & Sync Setup")
    return _format_dhan_api_error(response, "Dhan marketfeed request failed")

# --- FIXED: Only opens Google Connection once at start, reducing Read Quota completely! ---
def background_sync_loop(gcp_creds_dict, dhan_client_id):
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    try:
        credentials = Credentials.from_service_account_info(gcp_creds_dict, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open("Comprehensive Trading Tracker 2026")
    except Exception as e:
        sh = None

    sheet1_headers_cache = []
    scanner_headers_cache = []
    last_headers_refresh = 0
    cached_sync_interval = 60
    last_interval_check = 0
    quota_backoff = 0  # Exponential backoff for quota errors
    last_sync_time = 0
        
    while True:
        sleep_timer = cached_sync_interval
        now = datetime.datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        
        # Only sync during market hours: Mon-Fri, 9:00-15:30 IST
        is_market_hours = now.weekday() < 5 and (9, 0) <= (now.hour, now.minute) <= (15, 30)
        
        # Check if enough time has passed since last sync (respects user's interval + quota backoff)
        time_since_sync = time.time() - last_sync_time
        should_sync = is_market_hours and time_since_sync >= (cached_sync_interval + quota_backoff)
        
        if not is_market_hours and last_sync_time == 0:
            # First iteration - log that we're waiting for market hours
            print(f"🔄 Auto-sync daemon active but waiting for market hours (9:00-15:30 IST, Mon-Fri). Current time: {now.strftime('%A %H:%M IST')}")
        
        if should_sync:
            try:
                # Re-auth safely if disconnected
                if sh is None:
                    credentials = Credentials.from_service_account_info(gcp_creds_dict, scopes=scopes)
                    gc = gspread.authorize(credentials)
                    sh = gc.open("Comprehensive Trading Tracker 2026")
                    
                settings_ws = sh.worksheet("Settings")
                
                # Refresh sync interval setting at most once per 5 minutes
                if time.time() - last_interval_check > 300:
                    try:
                        # Read only specific cells instead of all values to reduce API calls
                        sync_interval_cell = robust_api_call(settings_ws.acell, "B8").value
                        token_cell = robust_api_call(settings_ws.acell, "B2").value
                        
                        if sync_interval_cell and str(sync_interval_cell).isdigit():
                            cached_sync_interval = int(sync_interval_cell)
                            sleep_timer = cached_sync_interval
                        daily_token = str(token_cell) if token_cell else ""
                        last_interval_check = time.time()
                    except Exception as e:
                        print(f"Settings refresh failed: {e}, using cached interval: {cached_sync_interval}")
                        # Fall back to cached value on error
                        pass
                else:
                    # Use cached interval between refreshes
                    sleep_timer = cached_sync_interval
                    try:
                        daily_token = robust_api_call(settings_ws.acell, "B2").value or ""
                    except:
                        daily_token = ""
                
                try: scanner_ws = sh.worksheet("Scanners")
                except: scanner_ws = None

                # Refresh headers at most once in 15 minutes unless cache is empty.
                if (not sheet1_headers_cache) or (time.time() - last_headers_refresh > 900):
                    try:
                        sheet1_headers_cache = sh.sheet1.row_values(1)
                    except:
                        sheet1_headers_cache = []

                    try:
                        scanner_headers_cache = scanner_ws.row_values(1) if scanner_ws else []
                    except:
                        scanner_headers_cache = []

                    last_headers_refresh = time.time()

                res = execute_core_sync(
                    sh.sheet1,
                    scanner_ws,
                    settings_ws,
                    sheet1_headers_cache,
                    scanner_headers_cache,
                    background_client_id=dhan_client_id,
                    daily_token=daily_token
                )
                
                # Reset quota backoff on success
                if "Success" in str(res):
                    quota_backoff = 0
                    last_sync_time = time.time()
                    print(f"Background Sync Success")
                elif "429" in str(res) or "Quota" in str(res) or "rate" in str(res).lower():
                    # Exponential backoff for quota errors (max 5 minutes)
                    quota_backoff = min(quota_backoff * 2 + 30, 300)
                    print(f"Quota limit hit, backing off {quota_backoff}s: {res}")
                else:
                    print(f"Background Sync Output: {res}")
                    
            except Exception as loop_err: 
                print(f"Daemon Background Sync Aborted Safely: {loop_err}")
                sh = None  # Force reconnection next loop
                quota_backoff = min(quota_backoff * 2 + 10, 120)  # Shorter backoff for connection errors
        
        time.sleep(min(sleep_timer, 10))  # Sleep in smaller chunks to check market hours frequently

@st.cache_resource
def start_cron_daemon_v12(_worksheet, _scanner_sheet, _settings_sheet, _sheet_headers, _scanner_headers):
    gcp_creds = dict(st.secrets["gcp_service_account"])
    dhan_id = st.secrets["dhan"]["dhan_client_id"]
    cron_worker = threading.Thread(target=background_sync_loop, args=(gcp_creds, dhan_id), daemon=True)
    
    try:
        add_script_run_ctx(cron_worker)
    except Exception as ctx_err:
        print(f"⚠️ Could not add Streamlit context to daemon: {ctx_err}. Daemon will still run.")
    
    cron_worker.start()
    print("✅ Background sync daemon started successfully")
    return True

def fetch_live_prices(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers):
    with st.spinner("Refreshed price feeds synchronizing from Dhan..."):
        settings = fetch_settings_dict()
        daily_token = settings.get("Dhan Access Token", "")
        result = execute_core_sync(worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers, daily_token=daily_token)
        return result
