import os
import json
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as _html

# Optional Google Sheets support
USE_GSHEETS = True
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from gspread.exceptions import APIError, SpreadsheetNotFound
except Exception:
    USE_GSHEETS = False

# Optional Quill-based highlighter
HAS_QUILL = True
try:
    from streamlit_quill import st_quill  # pip install streamlit-quill
except Exception:
    HAS_QUILL = False

st.set_page_config(page_title="AKI Expert Review", layout="wide")
st.title("AKI Expert Review")
st.markdown('<div id="top" tabindex="-1"></div>', unsafe_allow_html=True)

# -------------------- Helpers --------------------
def _rerun():
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()

def _scroll_top():
    _html("""
        <script>
        (function(){
          function topNow(){
            window.scrollTo(0,0);
          }
          topNow();
          setTimeout(topNow, 50);
          setTimeout(topNow, 150);
        })();
        </script>
        """, height=0)

def _retry_gs(func, *args, tries=6, delay=1.0, backoff=1.6, **kwargs):
    last = None
    for _ in range(tries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            last = e
            time.sleep(delay)
            delay *= backoff
    raise RuntimeError(f"Google Sheets API error after retries: {last}")

# ================== Google Sheets helpers ==================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource(show_spinner=False)
def _get_client_cached():
    if not USE_GSHEETS:
        return None
    try:
        if "service_account" in st.secrets:
            data = st.secrets["service_account"]
            if isinstance(data, str):
                data = json.loads(data)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(data, SCOPE)
        else:
            if not os.path.exists("service_account.json"):
                return None
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", SCOPE)
        return gspread.authorize(creds)
    except Exception as e:
        print("Google auth error:", e)
        return None

@st.cache_resource(show_spinner=False)
def _open_sheet_cached():
    sheet_id = st.secrets.get("gsheet_id", "").strip()
    if not sheet_id:
        raise RuntimeError("Missing gsheet_id in Secrets.")
    client = _get_client_cached()
    if client is None:
        raise RuntimeError("Google Sheets client not available.")
    last_err = None
    for i in range(6):
        try:
            return client.open_by_key(sheet_id)
        except SpreadsheetNotFound:
            raise RuntimeError("Could not open the Google Sheet by ID.")
        except APIError as e:
            last_err = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"Google Sheets API error after retries: {last_err}")

def get_or_create_ws(sh, title, headers=None):
    try:
        ws = _retry_gs(sh.worksheet, title)
    except RuntimeError:
        ws = _retry_gs(sh.add_worksheet, title=title, rows=1000, cols=max(10, (len(headers) if headers else 10)))
        if headers:
            _retry_gs(ws.update, [headers])
    if headers:
        existing = _retry_gs(ws.row_values, 1)
        if not existing:
            _retry_gs(ws.update, [headers])
        elif existing != headers:
            merged = list(existing)
            for h in headers:
                if h not in merged:
                    merged.append(h)
            _retry_gs(ws.update, "A1", [merged])
    return ws

def append_dict(ws, d, headers=None):
    if headers is None:
        headers = _retry_gs(ws.row_values, 1)
    row = [d.get(h, "") for h in headers]
    _retry_gs(ws.append_row, row, value_input_option="USER_ENTERED")

# ================== App state ==================
def init_state():
    if "entered" not in st.session_state:
        st.session_state.entered = False
    if "reviewer_id" not in st.session_state:
        st.session_state.reviewer_id = ""
    if "case_idx" not in st.session_state:
        st.session_state.case_idx = 0
    if "step" not in st.session_state:
        st.session_state.step = 1

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
            _scroll_top()
            _rerun()

if not st.session_state.entered:
    st.info("Please sign in to begin.")
    st.stop()

# ================== Load data ==================
try:
    sh = _open_sheet_cached()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

adm_headers = ["case_id", "title", "discharge_summary", "weight_kg"]
labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = [
    "timestamp_utc", "reviewer_id", "case_id", "step",
    "q_aki", "q_highlight", "q_rationale", "q_confidence",
    "q_reasoning", "q_highlight_html"
]

ws_adm = get_or_create_ws(sh, "admissions", adm_headers)
ws_labs = get_or_create_ws(sh, "labs", labs_headers)
ws_resp = get_or_create_ws(sh, "responses", resp_headers)

admissions = pd.DataFrame(_retry_gs(ws_adm.get_all_records))
labs = pd.DataFrame(_retry_gs(ws_labs.get_all_records))
responses = pd.DataFrame(_retry_gs(ws_resp.get_all_records))

if admissions.empty:
    st.error("Admissions sheet is empty.")
    st.stop()

# ================== Current Case ==================
if st.session_state.case_idx >= len(admissions):
    st.success("All admissions completed. Thank you!")
    st.stop()

case = admissions.iloc[st.session_state.case_idx]
case_id = str(case.get("case_id", ""))
title = str(case.get("title", ""))
summary = str(case.get("discharge_summary", ""))
weight = case.get("weight_kg", "")

st.caption(
    f"Reviewer: **{st.session_state.reviewer_id}** • "
    f"Admission {st.session_state.case_idx + 1}/{len(admissions)} • "
    f"Step {st.session_state.step}/2"
)
st.markdown(f"### {case_id} — {title}")

# ================== Layout ==================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary**")

    # -------- ONE SINGLE TEXT BOX with Markdown formatting + Highlight --------
    import markdown
    def markdown_to_html(md_text: str) -> str:
        """Convert Markdown (**bold**, lists, etc.) to HTML."""
        return markdown.markdown(md_text, extensions=["nl2br", "sane_lists"], output_format="html5")

    if HAS_QUILL:
        st.markdown("""
        <style>
        .ql-toolbar.ql-snow {
            position: sticky;
            top: 0;
            background: #fff;
            z-index: 5;
        }
        </style>
        """, unsafe_allow_html=True)

        init_html = markdown_to_html(summary)
        st.markdown("**Highlight directly in the note (select text, then click the highlighter)**")

        quill_html = st_quill(
            value=init_html,
            html=True,
            placeholder="Select text and click the highlighter icon to mark it in yellow...",
            key="quill_step1",
            toolbar=[[{"background": []}], ["clean"]],
        )
    else:
        st.warning("Optional dependency 'streamlit-quill' not installed.")
        st.markdown(summary.replace("\n", "  \n"))
        quill_html = ""

# ================== Step 1 Form ==================
st.markdown("---")
st.subheader("Step 1 — Questions (Narrative Only)")

with st.form("step1_form", clear_on_submit=False):
    q_aki = st.radio(
        "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
        ["Yes", "No"], horizontal=True
    )
    q_rationale = st.text_area("Please provide a brief rationale for your assessment.", height=140)
    q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3)
    submitted1 = st.form_submit_button("Save Step 1 ✅")

if submitted1:
    try:
        row = {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "reviewer_id": st.session_state.reviewer_id,
            "case_id": case_id,
            "step": 1,
            "q_aki": q_aki,
            "q_highlight": "",
            "q_rationale": q_rationale,
            "q_confidence": q_conf,
            "q_reasoning": "",
            "q_highlight_html": quill_html or "",
        }
        append_dict(ws_resp, row, headers=resp_headers)
        st.success("Saved Step 1.")
        st.session_state.step = 2
        st.session_state.case_idx += 1
        _scroll_top()
        time.sleep(0.3)
        _rerun()
    except Exception as e:
        st.error(f"Error saving: {e}")

# ================== Navigation ==================
c1, c3 = st.columns(2)
with c1:
    if st.button("◀ Back"):
        if st.session_state.case_idx > 0:
            st.session_state.case_idx -= 1
            _scroll_top()
            _rerun()
with c3:
    if st.button("Skip ▶"):
        st.session_state.case_idx += 1
        _scroll_top()
        _rerun()
