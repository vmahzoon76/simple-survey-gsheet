import os, json
from datetime import datetime
import pandas as pd
import streamlit as st

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
    if not USE_GSHEETS:
        return None
    scope = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/drive"]
    try:
        if "service_account" in st.secrets:  # Cloud
            data = st.secrets["service_account"]
            if isinstance(data, str):
                data = json.loads(data)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(data, scope)
        else:  # local dev
            if not os.path.exists("service_account.json"):
                return None
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", scope)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google auth error: {e}")
        return None

def open_sheet(client):
    name = st.secrets.get("sheet_name", "aki_responses")
    try:
        return client.open(name)
    except gspread.SpreadsheetNotFound:
        sh = client.create(name)
        return sh

def get_or_create_ws(sh, title, headers=None):
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=1000, cols=max(10, (len(headers) if headers else 10)))
        if headers:
            ws.update([headers])
    # Ensure headers exist
    if headers:
        existing = ws.row_values(1)
        if not existing:
            ws.update([headers])
        elif existing != headers:
            # Expand to include missing headers (non-destructive append)
            merged = list(existing)
            for h in headers:
                if h not in merged:
                    merged.append(h)
            ws.resize(rows=ws.row_count, cols=max(ws.col_count, len(merged)))
            ws.update_cell(1, 1, merged[0])
            if len(merged) > 1:
                ws.update(range_name=f"A1:{chr(64+len(merged))}1", values=[merged])
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

# Worksheets (create if missing)
adm_headers = ["case_id", "title", "discharge_summary", "weight_kg"]
labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = ["timestamp_utc","reviewer_id","case_id","step",
                "q_aki","q_highlight","q_rationale","q_confidence",
                "q_reasoning"]  # step2 uses q_aki + q_reasoning; others blank

ws_adm = get_or_create_ws(sh, "admissions", adm_headers)
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
case_id = str(case["case_id"])
title   = str(case["title"])
summary = str(case["discharge_summary"])
weight  = case.get("weight_kg", "")

st.caption(f"Reviewer: **{st.session_state.reviewer_id}** • "
           f"Admission {st.session_state.case_idx+1}/{len(admissions)} • "
           f"Step {st.session_state.step}/2")
st.markdown(f"### {case_id} — {title}")

# Filter labs for this case
case_labs = labs[labs["case_id"].astype(str) == case_id].copy()
if not case_labs.empty:
    case_labs["timestamp"] = pd.to_datetime(case_labs["timestamp"], errors="coerce")
scr = case_labs[case_labs["kind"].str.lower() == "scr"].sort_values("timestamp")
uo  = case_labs[case_labs["kind"].str.lower() == "uo"].sort_values("timestamp")

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
    q_aki = st.radio("Based on the discharge summary, do you think the note writers thought the patient had AKI?",
                     ["Yes","No"], horizontal=True)
    q_highlight = st.text_area("Please highlight (paste) any specific text in the note that impacted your conclusion.",
                               height=120)
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
        st.experimental_rerun()

else:
    st.subheader("Step 2 — Questions (Full Context)")
    q_aki2 = st.radio("Given the info in the EHR record from this patient, do you believe this patient had AKI?",
                      ["Yes","No"], horizontal=True)
    q_reasoning = st.text_area("Can you talk aloud about your reasoning process? Please mention everything you thought about.",
                               height=180)

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
        st.experimental_rerun()

# Navigation helpers
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("◀ Back"):
        if st.session_state.step == 2:
            st.session_state.step = 1
        elif st.session_state.case_idx > 0:
            st.session_state.case_idx -= 1
            st.session_state.step = 2
        st.experimental_rerun()
with c3:
    if st.button("Skip ▶"):
        st.session_state.step = 1
        st.session_state.case_idx += 1
        st.experimental_rerun()
