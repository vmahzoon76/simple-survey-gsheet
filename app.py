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


def _scroll_top():
    _html(
        """
        <script>
        (function(){
          function topNow(){
            try { window.scrollTo(0,0); } catch(e){}
            try { document.body.scrollTop = 0; } catch(e){}
          }
          topNow(); setTimeout(topNow,50); setTimeout(topNow,200);
        })();
        </script>
        """,
        height=0,
    )


def inject_highlight_listener():
    """Enable yellow highlight selection inside the discharge summary div."""
    _html(
        """
        <script>
        function enableHighlights(){
            const summaryDiv = document.getElementById('discharge-summary');
            if (!summaryDiv) return;
            summaryDiv.onmouseup = function() {
                const sel = window.getSelection();
                const text = sel.toString().trim();
                if (text.length > 0) {
                    const range = sel.getRangeAt(0);
                    const span = document.createElement("span");
                    span.style.backgroundColor = "yellow";
                    span.style.color = "black";
                    span.textContent = text;
                    range.deleteContents();
                    range.insertNode(span);

                    // send highlight back to Streamlit
                    const input = window.parent.document.querySelector('input[data-testid="stTextInput"]');
                    if (input) {
                        input.value = text;
                        const event = new Event('input', { bubbles: true });
                        input.dispatchEvent(event);
                    }
                }
                sel.removeAllRanges();
            };
        }
        window.addEventListener("load", enableHighlights);
        </script>
        """,
        height=0,
    )


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
    for i in range(6):
        try:
            return client.open_by_key(sheet_id)
        except APIError:
            time.sleep(1.5 * (i + 1))
    raise RuntimeError("Failed to open Google Sheet.")


def get_or_create_ws(sh, title, headers=None):
    try:
        ws = _retry_gs(sh.worksheet, title)
    except RuntimeError:
        ws = _retry_gs(sh.add_worksheet, title=title, rows=1000, cols=max(10, len(headers or [])))
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


@st.cache_data(ttl=60, show_spinner=False)
def _read_ws_df(sheet_id, ws_title):
    sh = _open_sheet_cached()
    ws = sh.worksheet(ws_title)
    recs = _retry_gs(ws.get_all_records)
    return pd.DataFrame(recs)


# ================== App state ==================
def init_state():
    defaults = dict(
        entered=False,
        reviewer_id="",
        case_idx=0,
        step=1,
        jump_to_top=True,
        highlights=[],
    )
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


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
    "q_aki", "q_highlight", "q_rationale", "q_confidence", "q_reasoning"
]

ws_adm = get_or_create_ws(sh, "admissions", adm_headers)
ws_labs = get_or_create_ws(sh, "labs", labs_headers)
ws_resp = get_or_create_ws(sh, "responses", resp_headers)

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
labs = _read_ws_df(st.secrets["gsheet_id"], "labs")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

if "resp_headers" not in st.session_state:
    st.session_state.resp_headers = _retry_gs(ws_resp.row_values, 1)

if admissions.empty:
    st.error("Admissions sheet is empty. Add rows to 'admissions'.")
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

# Restore previous highlights if present
prev_highlights = []
if not responses.empty:
    prev_highlights = responses.loc[
        (responses["case_id"].astype(str) == case_id)
        & (responses["reviewer_id"].astype(str) == st.session_state.reviewer_id)
        & (responses["q_highlight"].astype(str) != ""),
        "q_highlight",
    ].tolist()

# Apply yellow marks for previous highlights
if prev_highlights:
    for h in prev_highlights:
        if h.strip():
            summary = summary.replace(h, f"<mark>{h}</mark>")

# ================== Layout ==================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary**")

    # Render formatted text (Markdown + highlights)
    st.markdown(
        f'<div id="discharge-summary" style="white-space:pre-wrap; font-family:sans-serif; line-height:1.5;">'
        f'{summary.replace("\n", "  \n")}'
        f'</div>',
        unsafe_allow_html=True
    )

    inject_highlight_listener()

    selected_text = st.text_input("hidden_highlight_box", label_visibility="collapsed", key="hidden_highlight_box")

    if selected_text and selected_text not in st.session_state.highlights:
        st.session_state.highlights.append(selected_text)

with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only. Do not use structured data.")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        import altair as alt
        st.warning("Charts omitted for brevity in this version.")  # keep your charts here if needed

st.markdown("---")

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
                "q_highlight": "\n".join(st.session_state.get("highlights", [])),
                "q_rationale": q_rationale,
                "q_confidence": q_conf,
                "q_reasoning": "",
            }
            append_dict(ws_resp, row, headers=st.session_state.resp_headers)
            st.success("Saved Step 1 (highlights recorded).")
            st.session_state.highlights = []  # reset for next case
            st.session_state.step = 2
            st.session_state.jump_to_top = True
            _scroll_top()
            time.sleep(0.25)
            _rerun()
        finally:
            st.session_state.saving1 = False

else:
    st.subheader("Step 2 — Questions (Full Context)")
    with st.form("step2_form", clear_on_submit=False):
        q_aki2 = st.radio(
            "Given the info in the EHR record from this patient, do you believe this patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q2_aki"
        )
        q_reasoning = st.text_area(
            "Can you talk aloud about your reasoning process? Please mention everything you thought about.",
            height=180, key="q2_reasoning"
        )
        submitted2 = st.form_submit_button("Save Step 2 ✅ (Next case)", disabled=st.session_state.get("saving2", False))

    if submitted2:
        try:
            st.session_state.saving2 = True
            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 2,
                "q_aki": q_aki2,
                "q_highlight": "",
                "q_rationale": q_reasoning,
                "q_confidence": "",
                "q_reasoning": q_reasoning,
            }
            append_dict(ws_resp, row, headers=st.session_state.resp_headers)
            st.success("Saved Step 2.")
            st.session_state.step = 1
            st.session_state.case_idx += 1
            st.session_state.jump_to_top = True
            _scroll_top()
            time.sleep(0.25)
            _rerun()
        finally:
            st.session_state.saving2 = False


# Navigation
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("◀ Back"):
        if st.session_state.step == 2:
            st.session_state.step = 1
        elif st.session_state.case_idx > 0:
            st.session_state.case_idx -= 1
            st.session_state.step = 2
        st.session_state.jump_to_top = True
        _scroll_top()
        time.sleep(0.18)
        _rerun()
with c3:
    if st.button("Skip ▶"):
        st.session_state.step = 1
        st.session_state.case_idx += 1
        st.session_state.jump_to_top = True
        _scroll_top()
        time.sleep(0.18)
        _rerun()

