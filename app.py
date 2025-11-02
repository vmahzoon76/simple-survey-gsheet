import os
import json
import time
from datetime import datetime
import pytz
import numpy as np
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
if not st.session_state.get("entered", False):
    st.markdown(
        """
        ##  Instruction
        **Before starting: Please refer to the PowerPoint [slides here](https://tuprd-my.sharepoint.com/:p:/g/personal/tun53200_temple_edu/EQnr80BiXJ5HjRu58bAOCBkBTGRBPraOny7S16-gnnLyWQ?e=uBd3Nk) for the definitions of AKI**
        """
    )

# -------------------- Helpers --------------------
import re

def _boldify_simple(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.replace("\r\n", "\n")
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)

def _fmt_gender(g):
    g = str(g).strip().upper()
    return {"F": "Female", "M": "Male"}.get(g, "")

def _fmt_num(x):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    try:
        v = float(x)
        return str(int(v)) if v.is_integer() else f"{v:.1f}"
    except Exception:
        s = str(x).strip()
        return "" if s.lower() in {"", "nan", "none"} else s

def make_patient_blurb(age, gender, weight):
    age_s = _fmt_num(age)
    gender_s = _fmt_gender(gender)
    weight_s = _fmt_num(weight)
    parts = []
    if gender_s: parts.append(gender_s.lower())
    if age_s: parts.append(f"age {age_s}")
    if weight_s: parts.append(f"weight {weight_s} kg")
    if parts:
        core = ", ".join(parts)
        return f"This admission is related to a patient ({core})."
    else:
        return "This admission is related to a patient."

def _strip_strong_only(html: str) -> str:
    if not isinstance(html, str):
        return ""
    html = re.sub(r'<\s*/\s*(?:strong|b)\s*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<\s*(?:strong|b)(?:\s+[^>]*)?>', '', html, flags=re.IGNORECASE)
    return html

# -------------------- Highlight widget --------------------
import urllib.parse

def inline_highlighter(text: str, case_id: str, step_key: str, height: int = 560):
    qp_key = f"hl_{step_key}_{case_id}"
    code = f"""
    <div style="font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; line-height:1.55;">
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <button id="addBtn" type="button">Highlight</button>
        <button id="clearBtn" type="button">Clear</button>
      </div>
      <div id="text"
           style="border:1px solid #bbb;border-radius:10px;padding:14px;white-space:pre-wrap;overflow-y:auto;
                  max-height:{height}px; width:100%; box-sizing:border-box;"></div>
      <script>
        function escapeHtml(s) {{
          return s.replaceAll('&','&amp;').replaceAll('<','&lt;')
                  .replaceAll('>','&gt;').replaceAll('"','&quot;')
                  .replaceAll("'",'&#039;');
        }}
        function boldify(s) {{
          const esc = escapeHtml(s.replace(/\\r\\n?/g,'\\n').replace(/[\\u200B-\\u200D\\uFEFF]/g,''));
          return esc.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
        }}
        const qpKey = {json.dumps(qp_key)};
        const textEl = document.getElementById('text');
        textEl.innerHTML = boldify({json.dumps(text)});
        function syncToUrl() {{
          try {{
            const u = new URL(window.parent.location.href);
            u.searchParams.set(qpKey, encodeURIComponent(textEl.innerHTML));
            window.parent.history.replaceState(null, '', u.toString());
          }} catch(e) {{}}
        }}
        function mergeAdjacentMarks(root) {{
          const marks = root.querySelectorAll('mark');
          for (let i = 0; i < marks.length; i++) {{
            const m = marks[i];
            while (m.nextSibling && m.nextSibling.nodeType === 1 && m.nextSibling.tagName === 'MARK') {{
              const next = m.nextSibling;
              while (next.firstChild) m.appendChild(next.firstChild);
              next.remove();
            }}
            if (!m.textContent) {{
              const p = m.parentNode;
              p && p.removeChild(m);
            }}
          }}
        }}
        function clearMarks(root) {{
          const marks = root.querySelectorAll('mark');
          marks.forEach(m => {{
            const p = m.parentNode;
            if (!p) return;
            while (m.firstChild) p.insertBefore(m.firstChild, m);
            p.removeChild(m);
          }});
        }}
        document.getElementById('addBtn').onclick = () => {{
          const sel = window.getSelection();
          if (!sel || sel.rangeCount === 0) return;
          const rng = sel.getRangeAt(0);
          if (!textEl.contains(rng.startContainer) || !textEl.contains(rng.endContainer)) return;
          if (rng.collapsed) return;
          try {{
            const frag = rng.extractContents();
            const mark = document.createElement('mark');
            mark.appendChild(frag);
            rng.insertNode(mark);
            mergeAdjacentMarks(textEl);
            sel.removeAllRanges();
            syncToUrl();
          }} catch (e) {{
            console.warn('Highlight error:', e);
          }}
        }};
        document.getElementById('clearBtn').onclick = () => {{
          clearMarks(textEl);
          syncToUrl();
        }};
      </script>
    </div>
    """
    _html(code, height=height + 70)

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
            try { window.scrollTo(0,0); document.body.scrollTop=0; } catch(e){}
          }
          topNow();
          setTimeout(topNow, 200);
        })();
        </script>
        """,
        height=0,
    )

# ================== Google Sheets helpers ==================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

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
    return ws

def ws_to_df(ws):
    recs = _retry_gs(ws.get_all_records)
    return pd.DataFrame(recs)

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
    if "entered" not in st.session_state:
        st.session_state.entered = False
    if "reviewer_id" not in st.session_state:
        st.session_state.reviewer_id = ""
    if "case_idx" not in st.session_state:
        st.session_state.case_idx = 0

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

adm_headers = ["case_id", "title", "hadm_id", "DS", "weight", "age", "gender",
               "admittime", "dischtime"]
resp_headers = [
    "timestamp_et", "reviewer_id", "case_id", "step",
    "aki", "highlight_html", "rationale", "confidence"
]

ws_adm = get_or_create_ws(sh, "admissions", adm_headers)
ws_resp = get_or_create_ws(sh, "responses", resp_headers)

if "resp_headers" not in st.session_state:
    st.session_state.resp_headers = _retry_gs(ws_resp.row_values, 1)

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

for _c in ["admittime", "dischtime"]:
    if _c in admissions.columns:
        admissions[_c] = pd.to_datetime(admissions[_c], errors="coerce")

if admissions.empty:
    st.error("Admissions sheet is empty.")
    st.stop()

# ================== Current case ==================
if st.session_state.case_idx >= len(admissions):
    st.success("All admissions completed. Thank you!")
    st.stop()

case = admissions.iloc[st.session_state.case_idx]
case_id = str(case.get("case_id", ""))
title = str(case.get("title", ""))
summary = str(case.get("DS", ""))
weight = case.get("weight", "")
age = case.get("age", "")
gender = case.get("gender", "")

st.caption(
    f"Reviewer: **{st.session_state.reviewer_id}** • "
    f"Admission {st.session_state.case_idx + 1}/{len(admissions)}"
)
st.markdown(f"### {case_id} — {title}")

# ================== Step 1 only ==================
st.markdown("**Discharge Summary (highlight directly in the text below)**")
inline_highlighter(summary, case_id=case_id, step_key="step1", height=700)

st.markdown("---")
st.subheader("Assessment Questions")

with st.form("step1_form", clear_on_submit=False):
    q_aki = st.radio(
        "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
        ["Yes", "No"], horizontal=True, key="q1_aki"
    )

    q_rationale = st.text_area(
        "Please provide a brief rationale for your assessment. Please also highlight in the note any specific text that impacted your conclusion.",
        height=140, key="q1_rationale"
    )

    q_conf = st.radio(
        "Confidence (choose 1–5)",
        options=[1, 2, 3, 4, 5],
        index=2,
        horizontal=True,
        key="q1_conf",
    )

    submitted1 = st.form_submit_button("Save Step 1 ✅", disabled=st.session_state.get("saving1", False))

if submitted1:
    try:
        st.session_state.saving1 = True
        qp_key = f"hl_step1_{case_id}"
        qp = st.query_params
        hl_html = urllib.parse.unquote(qp.get(qp_key, "")) if qp_key in qp else ""
        hl_html = _strip_strong_only(hl_html)

        row = {
            "timestamp_et": datetime.now(pytz.timezone("US/Eastern")).isoformat(),
            "reviewer_id": st.session_state.reviewer_id,
            "case_id": case_id,
            "step": 1,
            "aki": q_aki,
            "highlight_html": hl_html,
            "rationale": q_rationale,
            "confidence": q_conf
        }
        append_dict(ws_resp, row, headers=st.session_state.resp_headers)

        try:
            st.query_params.pop(qp_key, None)
        except Exception:
            st.query_params.clear()

        st.success("Saved Step 1.")
        st.session_state.case_idx += 1
        st.session_state.jump_to_top = True
        _scroll_top(); time.sleep(0.25); _rerun()
    finally:
        st.session_state.saving1 = False

# ================== Navigation ==================
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("◀ Back"):
        if st.session_state.case_idx > 0:
            st.session_state.case_idx -= 1
        st.session_state.jump_to_top = True
        _scroll_top()
        time.sleep(0.18)
        _rerun()
with c3:
    if st.button("Skip ▶"):
        st.session_state.case_idx += 1
        st.session_state.jump_to_top = True
        _scroll_top()
        time.sleep(0.18)
        _rerun()
