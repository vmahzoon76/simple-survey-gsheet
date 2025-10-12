import os
import json
import time
from datetime import datetime
import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as _html
import markdown

# Optional Google Sheets support
USE_GSHEETS = True
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
except Exception:
    USE_GSHEETS = False

st.set_page_config(page_title="AKI Expert Review", layout="wide")
st.title("AKI Expert Review")
st.markdown('<div id="top" tabindex="-1"></div>', unsafe_allow_html=True)

# -------------------- Helpers --------------------
def _rerun():
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()

@st.cache_data(ttl=60, show_spinner=False)
def _read_ws_df(sheet_id, ws_title):
    sh = _open_sheet_cached()
    ws = sh.worksheet(ws_title)
    recs = _retry_gs(ws.get_all_records)
    return pd.DataFrame(recs)

def _scroll_top():
    _html("""
    <script>
    (function(){
      try { if ('scrollRestoration' in history) { history.scrollRestoration = 'manual'; } } catch(e) {}
      function topNow(){
        try { location.hash = '#top'; } catch(e){}
        try { window.scrollTo(0,0); } catch(e){}
      }
      topNow(); setTimeout(topNow, 300); setTimeout(topNow, 1000);
    })();
    </script>
    """, height=0)

def _retry_gs(func, *args, tries=8, delay=1.0, backoff=1.6, **kwargs):
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
    raise RuntimeError(f"Google Sheets API error: {last_err}")

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
    return ws

def append_dict(ws, d, headers=None):
    if headers is None:
        headers = _retry_gs(ws.row_values, 1)
    row = [d.get(h, "") for h in headers]
    _retry_gs(ws.append_row, row, value_input_option="USER_ENTERED")

# ================== Highlightable text component ==================
def render_highlightable_text(md_text, key):
    """
    Render markdown text as editable HTML, allow highlighting, and return highlighted HTML string.
    """
    html_text = markdown.markdown(md_text)  # convert **bold** etc. to HTML

    component_html = f"""
    <div id="editable_{key}" contenteditable="true"
         style="border:1px solid #ccc; padding:10px; border-radius:8px;
                height:400px; overflow:auto; font-family:Arial, sans-serif; font-size:15px;">
        {html_text}
    </div>
    <button onclick="highlightSelection_{key}()"
            style="margin-top:8px; padding:6px 12px; border-radius:6px; background-color:#f6c500;">
        Highlight Selection
    </button>
    <script>
    function highlightSelection_{key}() {{
        var sel = window.getSelection();
        if (!sel.rangeCount) return;
        var range = sel.getRangeAt(0);
        var newNode = document.createElement("mark");
        newNode.style.backgroundColor = "yellow";
        range.surroundContents(newNode);
    }}
    </script>
    """

    save_script = f"""
    <script>
    function saveHighlights_{key}() {{
        const content = document.getElementById('editable_{key}').innerHTML;
        window.parent.postMessage({{type: 'highlight_save_{key}', data: content}}, '*');
    }}
    </script>
    """

    _html(component_html + save_script, height=460)

    highlighted_html = st.text_area("Highlighted HTML (hidden for reviewers)", "", key=f"hidden_{key}", height=100, label_visibility="collapsed")

    sync_script = f"""
    <script>
    window.addEventListener('message', (event) => {{
        if (event.data.type === 'highlight_save_{key}') {{
            const textarea = window.parent.document.querySelector('textarea[data-testid="stTextArea"][aria-label="hidden_{key}"]');
            if (textarea) {{
                textarea.value = event.data.data;
                textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
            }}
        }}
    }});
    </script>
    """
    _html(sync_script, height=0)

    if st.button("💾 Save Highlights", key=f"save_{key}"):
        st.session_state[f"highlighted_{key}"] = st.session_state[f"hidden_{key}"]

    return st.session_state.get(f"highlighted_{key}", "")

# ================== App state ==================
def init_state():
    for k, v in {
        "entered": False, "reviewer_id": "", "case_idx": 0, "step": 1, "jump_to_top": True
    }.items():
        st.session_state.setdefault(k, v)

init_state()

if st.session_state.get("jump_to_top"):
    _scroll_top()
    st.session_state.jump_to_top = False

# ================== Sign-in ==================
with st.sidebar:
    st.subheader("Sign in")
    rid = st.text_input("Your name or ID", value=st.session_state.reviewer_id)
    if st.button("Enter"):
        if rid.strip():
            st.session_state.reviewer_id = rid.strip()
            st.session_state.entered = True
            st.session_state.step = 1
            st.session_state.jump_to_top = True
            _scroll_top()
            time.sleep(0.25)
            _rerun()

if not st.session_state.entered:
    st.info("Please sign in with your Reviewer ID to begin.")
    st.stop()

# ================== Load data from Google Sheets ==================
try:
    sh = _open_sheet_cached()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

adm_headers = ["case_id", "title", "discharge_summary", "weight_kg"]
labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = [
    "timestamp_utc", "reviewer_id", "case_id", "step",
    "q_aki", "q_highlight", "q_rationale", "q_confidence", "q_reasoning"
]

ws_adm = get_or_create_ws(sh, "admissions", adm_headers)
ws_labs = get_or_create_ws(sh, "labs", labs_headers)
ws_resp = get_or_create_ws(sh, "responses", resp_headers)

if "resp_headers" not in st.session_state:
    st.session_state.resp_headers = _retry_gs(ws_resp.row_values, 1)

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
labs = _read_ws_df(st.secrets["gsheet_id"], "labs")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

if admissions.empty:
    st.error("Admissions sheet is empty.")
    st.stop()

# ================== Current case ==================
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

# ========== Discharge Summary (highlightable) ==========
st.markdown("**Discharge Summary (Highlightable)**")
highlighted_summary = render_highlightable_text(summary, key=f"case_{case_id}")
if highlighted_summary:
    st.info("✅ Highlight captured and ready to save.")

# ================== Questions & Saving ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio(
            "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q1_aki"
        )
        q_rationale = st.text_area("Please provide a brief rationale for your assessment.", height=140, key="q1_rationale")
        q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3, key="q1_conf")

        submitted1 = st.form_submit_button("Save Step 1 ✅", disabled=st.session_state.get("saving1", False))

    if submitted1:
        try:
            st.session_state.saving1 = True
            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 1,
                "q_aki": q_aki,
                "q_highlight": highlighted_summary,
                "q_rationale": q_rationale,
                "q_confidence": q_conf,
                "q_reasoning": ""
            }
            append_dict(ws_resp, row, headers=st.session_state.resp_headers)
            st.success("Saved Step 1.")
            st.session_state.step = 2
            st.session_state.jump_to_top = True
            _scroll_top()
            time.sleep(0.25)
            _rerun()
        finally:
            st.session_state.saving1 = False
