import os, json
from datetime import datetime
import pandas as pd
import streamlit as st

def _rerun():
    """Streamlit rerun helper for both old and new versions."""
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()

# Optional Google Sheets support
USE_GSHEETS = True
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
except Exception:
    USE_GSHEETS = False

st.set_page_config(page_title="AKI Expert Review — Sheets (no HTML)", layout="wide")
st.title("AKI Expert Review — Sheets-backed (no HTML files)")

# ================== Google Sheets helpers ==================
def get_gs_client():
    """Authorize using service account from Streamlit secrets (or local file as fallback)."""
    if not USE_GSHEETS:
        return None
    # Classic oauth2client scopes (you need Drive to open/create by ID)
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        # Cloud: st.secrets["service_account"] (can be dict or JSON string)
        if "service_account" in st.secrets:
            data = st.secrets["service_account"]
            if isinstance(data, str):
                data = json.loads(data)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(data, scope)
        else:
            # Local dev fallback
            if not os.path.exists("service_account.json"):
                return None
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google auth error: {e}")
        return None

def open_sheet(client):
    """Open the Google Sheet by ID from secrets; fail clearly if not found."""
    sheet_id = st.secrets.get("gsheet_id", "").strip()
    if not sheet_id:
        st.error("Missing gsheet_id in Secrets. Add the Google Sheet ID between /d/ and /edit.")
        st.stop()
    try:
        return client.open_by_key(sheet_id)
    except gspread.SpreadsheetNotFound:
        st.error(
            "Could not open the Google Sheet by ID. "
            "Double-check gsheet_id in Secrets and share the sheet with the service-account email as Editor."
        )
        st.stop()

def get_or_create_ws(sh, title, headers=None):
    """Get a worksheet by title; create with headers if missing. Non-destructive header merge."""
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(10, (len(headers) if headers else 10)))
        if headers:
            ws.update([headers])

    # Ensure header row exists and contains required headers (non-destructive)
    if headers:
        existing = ws.row_values(1)
        if not existing:
            ws.update([headers])
        elif existing != headers:
            merged = list(existing)
            for h in headers:
                if h not in merged:
                    merged.append(h)
            # Resize columns if needed; then write merged header row
            if ws.col_count < len(merged):
                ws.resize(rows=ws.row_count, cols=len(merged))
            # Write the merged header row in one update
            range_end_col = len(merged)
            start_col = 1
            # Build a 2D list for update
            ws.update(f"A1:{gspread.utils.rowcol_to_a1(1, range_end_col)[0]}1", [merged])

    return ws

def ws_to_df(ws):
    recs = ws.get_all_records()
    return pd.DataFrame(recs)

def append_dict(ws, d):
    headers = ws.row_values(1)
    row = [d.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")

# ================== App state ==================
def init_state():
    if "entered" not in st.session_state:
        st.session_state.entered = False
    if "reviewer_id" not in st.session_state:
        st.session_state.reviewer_id = ""
    if "case_idx" not in st.session_state:
        st.session_state.case_idx = 0
    if "step" not in st.session_state:
        st.session_state.step = 1  # 1 or 2

init_state()

# ================== Sign-in ==================
with st.sidebar:
    st.subheader("Sign in")
    rid = st.text_input("Your name or ID", value=st.session_state.reviewer_id)
    if st.button("Enter"):
        if rid.strip():
            st.session_state.reviewer_id = rid.strip()
            st.session_state.entered = True
            st.session_state.step = 1

if not st.session_state.entered:
    st.info("Please sign in with your Reviewer ID to begin.")
    st.stop()

# ================== Load data from Google Sheets ==================
gc = get_gs_client()
if gc is None:
    st.error("Google Sheets client not available. Ensure API enabled and secrets or service_account.json present.")
    st.stop()

sh = open_sheet(gc)

# Debug: confirm which spreadsheet and tabs we have (helps diagnose mismatches)
try:
    st.caption(f"Connected to Google Sheet: **{sh.title}**")
    st.caption("Tabs: " + ", ".join([ws.title for ws in sh.worksheets()]))
except Exception as e:
    st.error(f"Could not list worksheets: {e}")

# Worksheets (create if missing)
adm_headers = ["case_id", "title", "discharge_summary", "weight_kg"]
labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = [
    "timestamp_utc","reviewer_id","case_id","step",
    "q_aki","q_highlight","q_rationale","q_confidence","q_reasoning"
]

ws_adm  = get_or_create_ws(sh, "admissions", adm_headers)
ws_labs = get_or_create_ws(sh, "labs", labs_headers)
ws_resp = get_or_create_ws(sh, "responses", resp_headers)

admissions = ws_to_df(ws_adm)
labs = ws_to_df(ws_labs)

if admissions.empty:
    st.error("Admissions sheet is empty. Add rows to 'admissions' with: case_id,title,discharge_summary,weight_kg")
    st.stop()

# ================== Current case ==================
if st.session_state.case_idx >= len(admissions):
    st.success("All admissions completed. Thank you!")
    st.stop()

case = admissions.iloc[st.session_state.case_idx]
case_id = str(case.get("case_id", ""))
title   = str(case.get("title", ""))
summary = str(case.get("discharge_summary", ""))
weight  = case.get("weight_kg", "")

st.caption(
    f"Reviewer: **{st.session_state.reviewer_id}** • "
    f"Admission {st.session_state.case_idx+1}/{len(admissions)} • "
    f"Step {st.session_state.step}/2"
)
st.markdown(f"### {case_id} — {title}")

# Filter labs for this case
case_labs = labs[labs["case_id"].astype(str) == case_id].copy()
if not case_labs.empty:
    case_labs["timestamp"] = pd.to_datetime(case_labs["timestamp"], errors="coerce")
scr = case_labs[case_labs["kind"].astype(str).str.lower() == "scr"].sort_values("timestamp")
uo  = case_labs[case_labs["kind"].astype(str).str.lower() == "uo"].sort_values("timestamp")

# ================== Layout ==================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary**")
    st.write(summary)

with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only. Do not use structured data.")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        # Figures
        import altair as alt
        if not scr.empty:
            st.markdown("**Serum Creatinine (mg/dL)**")
            ch_scr = alt.Chart(scr.rename(columns={"timestamp":"time","value":"scr"})).mark_line(point=True).encode(
                x=alt.X("time:T", title="Time"),
                y=alt.Y("scr:Q", title="mg/dL")
            )
            st.altair_chart(ch_scr, use_container_width=True)
            st.caption("Table — SCr:")
            st.dataframe(scr[["timestamp","value","unit"]].rename(columns={"value":"scr"}), use_container_width=True)
        else:
            st.warning("No SCr values for this case.")

        if not uo.empty:
            st.markdown("**Urine Output (mL/kg/h)**" + (f" — weight: {weight} kg" if weight else ""))
            ch_uo = alt.Chart(uo.rename(columns={"timestamp":"time","value":"uo"})).mark_line(point=True).encode(
                x=alt.X("time:T", title="Time"),
                y=alt.Y("uo:Q", title="mL/kg/h")
            )
            # reference rule at 0.5
            import numpy as np
            ref = pd.DataFrame({"time":[uo["timestamp"].min(), uo["timestamp"].max()], "ref":[0.5, 0.5]})
            ch_ref = alt.Chart(ref).mark_rule(strokeDash=[6,6]).encode(x="time:T", y="ref:Q")
            st.altair_chart(ch_uo + ch_ref, use_container_width=True)
            st.caption("Table — UO:")
            st.dataframe(uo[["timestamp","value","unit"]].rename(columns={"value":"uo"}), use_container_width=True)
        else:
            st.warning("No UO values for this case.")

st.markdown("---")

# ================== Questions & Saving ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    q_aki = st.radio(
        "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
        ["Yes","No"], horizontal=True
    )
    q_highlight = st.text_area(
        "Please highlight (paste) any specific text in the note that impacted your conclusion.",
        height=120
    )
    q_rationale = st.text_area("Please provide a brief rationale for your assessment.", height=140)
    q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3)

    if st.button("Save Step 1 ✅"):
        row = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "reviewer_id": st.session_state.reviewer_id,
            "case_id": case_id,
            "step": 1,
            "q_aki": q_aki,
            "q_highlight": q_highlight,
            "q_rationale": q_rationale,
            "q_confidence": q_conf,
            "q_reasoning": ""  # not used in step 1
        }
        append_dict(ws_resp, row)
        st.success("Saved Step 1.")
        st.session_state.step = 2
        _rerun()

else:
    st.subheader("Step 2 — Questions (Full Context)")
    q_aki2 = st.radio(
        "Given the info in the EHR record from this patient, do you believe this patient had AKI?",
        ["Yes","No"], horizontal=True
    )
    q_reasoning = st.text_area(
        "Can you talk aloud about your reasoning process? Please mention everything you thought about.",
        height=180
    )

    if st.button("Save Step 2 ✅ (Next case)"):
        row = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "reviewer_id": st.session_state.reviewer_id,
            "case_id": case_id,
            "step": 2,
            "q_aki": q_aki2,
            "q_highlight": "",          # optional in step 2 — leaving blank
            "q_rationale": q_reasoning, # store reasoning here
            "q_confidence": "",         # not asked in step 2
            "q_reasoning": q_reasoning  # duplicate if you prefer a dedicated column
        }
        append_dict(ws_resp, row)
        st.success("Saved Step 2.")
        # advance
        st.session_state.step = 1
        st.session_state.case_idx += 1
        _rerun()

# Navigation helpers
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("◀ Back"):
        if st.session_state.step == 2:
            st.session_state.step = 1
        elif st.session_state.case_idx > 0:
            st.session_state.case_idx -= 1
            st.session_state.step = 2
        _rerun()
with c3:
    if st.button("Skip ▶"):
        st.session_state.step = 1
        st.session_state.case_idx += 1
        _rerun()
