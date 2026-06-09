import gspread
from google.oauth2.service_account import Credentials
import streamlit as st
import broker_api as api
from integrations.google_sheets import fetch_dataframe_safe, execute_with_quota_retry

@st.cache_resource
def init_db():
    scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
    credentials = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scopes)
    gc = gspread.authorize(credentials)
    
    sh = execute_with_quota_retry(gc.open, "Comprehensive Trading Tracker 2026")
    
    worksheet = sh.sheet1
    sheet_headers = execute_with_quota_retry(worksheet.row_values, 1)
    
    new_cols = ["Live Price", "Exit Price", "Notes", "Time Frame", "Setup Rating", "Raw Tip Text", "Price Chg %", "OI Chg %"]
    for col in new_cols:
        if col not in sheet_headers:
            execute_with_quota_retry(worksheet.update_cell, 1, len(sheet_headers) + 1, col)
            sheet_headers.append(col)
            
    worksheet_list = [ws.title for ws in sh.worksheets()]
    if "Scanners" in worksheet_list:
        scanner_sheet = execute_with_quota_retry(sh.worksheet, "Scanners")
    else:
        scanner_sheet = execute_with_quota_retry(sh.add_worksheet, title="Scanners", rows="1000", cols="10")
        execute_with_quota_retry(scanner_sheet.append_row, ["Date Added", "Scanner", "Symbol", "Trigger Price", "Trigger Time", "Status", "Notes / Analysis", "Live Price"])
        
    scanner_headers = execute_with_quota_retry(scanner_sheet.row_values, 1)
    if "Live Price" not in scanner_headers:
        execute_with_quota_retry(scanner_sheet.update_cell, 1, len(scanner_headers) + 1, "Live Price")
        scanner_headers.append("Live Price")
        
    if "Settings" in worksheet_list:
        settings_sheet = execute_with_quota_retry(sh.worksheet, "Settings")
        
        if settings_sheet.row_count < 15:
            execute_with_quota_retry(settings_sheet.resize, rows=15)
            
        val_a12 = execute_with_quota_retry(settings_sheet.acell, 'A12').value
        if not val_a12 or str(val_a12).strip() == "":
            execute_with_quota_retry(settings_sheet.update_acell, 'A12', "Sector Heatmap JSON")
            execute_with_quota_retry(settings_sheet.update_acell, 'B12', "-")
    else:
        settings_sheet = execute_with_quota_retry(sh.add_worksheet, title="Settings", rows="15", cols="2")
        execute_with_quota_retry(settings_sheet.update, [
            ["Key", "Value"], 
            ["Dhan Access Token", ""], 
            ["Last Synced (Old)", "-"], 
            ["Daemon Status", "-"],
            ["Nifty 50 (Old)", "-"],
            ["Bank Nifty", "-"],
            ["Sensex", "-"],
            ["Sync Interval", "60"],
            ["New Timestamp", "-"],
            ["New Nifty", "-"],
            ["---", "---"],
            ["Sector Heatmap JSON", "-"]
        ], "A1:B12")
        
    return worksheet, scanner_sheet, settings_sheet, sheet_headers, scanner_headers

def run_background_sync(df_filtered, state_key, worksheet, sheet_headers):
    if state_key in st.session_state and not df_filtered.empty:
        editor_state = st.session_state[state_key]
        edited_rows = editor_state.get("edited_rows", {})
        made_changes = False
        
        # 1. Handle UI Interactivity (Journaling)
        for idx, changes in list(edited_rows.items()):
            if "Journal" in changes and changes["Journal"] is True:
                sym = df_filtered.iloc[idx]['Symbol / Asset']
                row_id = df_filtered.iloc[idx]['_Sheet_Row']
                st.session_state.viewing_trade = sym
                st.session_state.viewing_trade_row = int(row_id)
                del changes["Journal"]
                if not changes: del editor_state["edited_rows"][idx]
        
        # 2. Handle Deletions Safely
        deleted_indices = editor_state.get("deleted_rows", [])
        if deleted_indices:
            rows_to_delete = df_filtered.iloc[deleted_indices]['_Sheet_Row'].tolist()
            rows_to_delete.sort(reverse=True)
            for r in rows_to_delete: 
                execute_with_quota_retry(worksheet.delete_rows, r)
            made_changes = True
            
        # 3. FIXED: THE BATCH UPDATE PROTOCOL
        if editor_state.get("edited_rows"):
            bulk_updates = []
            
            for idx, changes in editor_state["edited_rows"].items():
                sheet_row = df_filtered.iloc[idx]['_Sheet_Row']
                for col_name, new_val in changes.items():
                    if col_name in sheet_headers:
                        if col_name == "Symbol / Asset":
                            t_sym, t_sec, t_exch = api.resolve_instrument(str(new_val))
                            # Convert to A1 notation string for batch payload
                            sym_a1 = gspread.utils.rowcol_to_a1(sheet_row, sheet_headers.index("Symbol / Asset") + 1)
                            sec_a1 = gspread.utils.rowcol_to_a1(sheet_row, sheet_headers.index("Security ID") + 1)
                            exch_a1 = gspread.utils.rowcol_to_a1(sheet_row, sheet_headers.index("Exchange") + 1)
                            
                            bulk_updates.append({'range': sym_a1, 'values': [[t_sym]]})
                            bulk_updates.append({'range': sec_a1, 'values': [[t_sec]]})
                            bulk_updates.append({'range': exch_a1, 'values': [[t_exch]]})
                        else:
                            col_idx = sheet_headers.index(col_name) + 1
                            cell_a1 = gspread.utils.rowcol_to_a1(sheet_row, col_idx)
                            bulk_updates.append({'range': cell_a1, 'values': [[str(new_val)]]})
            
            # Fire exactly 1 API Request to update the whole UI block
            if bulk_updates:
                execute_with_quota_retry(worksheet.batch_update, bulk_updates)
                made_changes = True
            
        if made_changes:
            fetch_dataframe_safe.clear()

def run_scanner_sync(df_filtered, state_key, scanner_sheet, scanner_headers):
    if state_key in st.session_state and not df_filtered.empty:
        editor_state = st.session_state[state_key]
        deleted_indices = editor_state.get("deleted_rows", [])
        made_changes = False
        
        if deleted_indices:
            rows_to_delete = df_filtered.iloc[deleted_indices]['_Sheet_Row'].tolist()
            rows_to_delete.sort(reverse=True)
            for r in rows_to_delete: 
                execute_with_quota_retry(scanner_sheet.delete_rows, r)
            made_changes = True
            
        # 3. FIXED: THE BATCH UPDATE PROTOCOL FOR SCANNERS
        if editor_state.get("edited_rows"):
            bulk_updates = []
            
            for idx, changes in editor_state["edited_rows"].items():
                sheet_row = df_filtered.iloc[idx]['_Sheet_Row']
                for col_name, new_val in changes.items():
                    if col_name in scanner_headers:
                        col_idx = scanner_headers.index(col_name) + 1
                        cell_a1 = gspread.utils.rowcol_to_a1(sheet_row, col_idx)
                        bulk_updates.append({'range': cell_a1, 'values': [[str(new_val)]]})
                        
            if bulk_updates:
                execute_with_quota_retry(scanner_sheet.batch_update, bulk_updates)
                made_changes = True
            
        if made_changes:
            fetch_dataframe_safe.clear()
