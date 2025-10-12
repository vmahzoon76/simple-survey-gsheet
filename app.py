import os
import json
import time
from datetime import datetime

import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as _html
from streamlit_js_eval import streamlit_js_eval  # NEW DEPENDENCY

# Optional Google Sheets support
USE_GSHEETS = True
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound
except Exception:
    USE_GSHEETS = False


# ================== PAGE CONFIG ==================
st.set_page_config(page_title="AKI Expert Review", layout="wide")
st.title("AKI Expert Review")
st.markdown('<div id="top" tabindex="-1"></div>', unsafe_allow_html=True)


# ================== STYLES ==================
st.markdown("""
<style>
.highlighter-wrap { 
  position: relative; 
  border: 1px solid #e6e6e6; 
  border-radius: 10px; 
  padding: 14px 16px; 
  background: #fff; 
  max-height: 420px; 
  overflow: auto; 
  line-height: 1.45;
}
.highlighter-wrap::-webkit-scrollbar { width: 10px; height: 10px; }
.highlighter-wrap::-webkit-scrollbar-thumb { background:#dcdcdc; border-radius: 8px; }
mark.hl {
  background: #fff3b0;
  padding: 0 0.06em;
  border-radius: 4px;
  box-shadow: 0 0 0 2px #ffeaa7 inset;
}
.hl-chip {
  display:inline-flex; align-items:center; gap:8px;
  background:#f6f6f6; border:1px solid #e6e6e6; border-radius:999px;
  padding:4px 10px; margin:4px 6px 0 0; font-size:12px;
}
.hl-chip button {
  border:none; background:transparent; cursor:pointer; color:#666; font-size:12px;
}
</style>
""", unsafe_allow_html=True)


# ================== HELPERS ==================
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
        try { window.scrollTo(0,0); document.body.scrollTop=0; } catch(e){}
      }
      topNow(); setTimeout(topNow,50); setTimeout(topNow,300);
    })();
    </script>
    """, height=0)


# ---------- Google Sheets ----------
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

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
        raise RuntimeError("Google Sheets client unavailable.")
    for i in range(6):
        try:
            return client.open_by_key(sheet_id)
        except SpreadsheetNotFound:
            raise RuntimeError("Sheet not found or not shared with service account.")
        except APIError:
            time.sleep(1.2 * (i + 1))
    raise RuntimeError("Google Sheets API failed repeatedly.")


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


def get_or_create_ws(sh, title, headers=None):
    try:
        ws = _retry_gs(sh.worksheet, title)
    except RuntimeError:
        ws = _retry_gs(sh.add_worksheet, title=title, rows=1000, cols=max(10, len(headers or [])))
        if headers:
            _retry_gs(ws.update, [headers])
    if headers:
        existing = _retry_gs(ws.row_values, 1)
        merged = list(existing)
        for h in headers:
            if h not in merged:
                merged.append(h)
        if ws.col_count < len(merged):
            _retry_gs(ws.resize, rows=ws.row_count, cols=len(merged))
        _retry_gs(ws.update, "A1", [merged])
    return ws


def append_dict(ws, d, headers=None):
    if headers is None:
        headers = _retry_gs(ws.row_values, 1)
    row = [d.get(h, "") for h in headers]
    _retry_gs(ws.append_row, row, value_input_option="USER_ENTERED")


@st.cache_data(ttl=60)
def _read_ws_df(sheet_id, ws_title):
    sh = _open_sheet_cached()
    ws = sh.worksheet(ws_title)
    recs = _retry_gs(ws.get_all_records)
    return pd.DataFrame(recs)


# ---------- Highlighting utilities ----------
import html
from dataclasses import dataclass

@dataclass
class Span:
    start: int
    end: int
    text: str

def _merge_overlaps(spans):
    if not spans:
        return []
    spans = sorted(spans, key=lambda s: (s["start"], s["end"]))
    merged = [spans[0].copy()]
    for s in spans[1:]:
        last = merged[-1]
        if s["start"] <= last["end"]:
            last["end"] = max(last["end"], s["end"])
            last["text"] = None
        else:
            merged.append(s.copy())
    return merged

def _render_with_highlights(raw_text, spans):
    if not spans:
        return f'<div id="sum" class="highlighter-wrap">{html.escape(raw_text)}</div>'
    spans = _merge_overlaps(spans)
    out, cursor = [], 0
    for s in spans:
        start = max(0, min(len(raw_text), s["start"]))
        end = max(0, min(len(raw_text), s["end"]))
        if start > cursor:
            out.append(html.escape(raw_text[cursor:start]))
        out.append(f'<mark class="hl">{html.escape(raw_text[start:end])}</mark>')
        cursor = end
    if cursor < len(raw_text):
        out.append(html.escape(raw_text[cursor:]))
    return f'<div id="sum" class="highlighter-wrap">{"".join(out)}</div>'


# ================== APP STATE ==================
def init_state():
    for k, v in [("entered", False), ("reviewer_id", ""), ("case_idx", 0), ("step", 1), ("jump_to_top", True)]:
        st.session_state.setdefault(k, v)

init_state()
if st.session_state.get("jump_to_top"):
    _scroll_top()
    st.session_state.jump_to_top = False


# ================== SIGN-IN ==================
with st.sidebar:
    st.subheader("Sign in")
    rid = st.text_input("Your name or ID", value=st.session_state.reviewer_id)
    if st.button("Enter"):
        if rid.strip():
            st.session_state.reviewer_id = rid.strip()
            st.session_state.entered = True
            st.session_state.step = 1
            st.session_state.jump_to_top = True
            _rerun()

if not st.session_state.entered:
    st.info("Please sign in with your Reviewer ID to begin.")
    st.stop()


# ================== LOAD SHEETS ==================
try:
    sh = _open_sheet_cached()
except RuntimeError as e:
    st.error(str(e))
    st.stop()

adm_headers = ["case_id", "title", "discharge_summary", "weight_kg"]
labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = ["timestamp_utc", "reviewer_id", "case_id", "step",
                "q_aki", "q_highlight", "q_rationale", "q_confidence", "q_reasoning"]

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


# ================== CURRENT CASE ==================
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


# ================== LAYOUT ==================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary**")

    # ---------- Highlighting feature (NEW) ----------
    hl_key = f"hl_{case_id}"
    if hl_key not in st.session_state:
        st.session_state[hl_key] = []

    summary_html = _render_with_highlights(summary, st.session_state[hl_key])
    st.markdown(summary_html, unsafe_allow_html=True)

    colA, _ = st.columns([1, 3])
    with colA:
        add_clicked = st.button("➕ Add selection", help="Select any text in the box, then click to highlight")

    if add_clicked:
        sel = streamlit_js_eval(js_expressions="""
(() => {
  const box = document.getElementById('sum');
  if (!box) return null;
  const sel = window.getSelection();
  if (!sel || sel.rangeCount === 0) return null;
  const rng = sel.getRangeAt(0);
  if (!box.contains(rng.commonAncestorContainer)) return null;
  const pre = document.createRange();
  pre.selectNodeContents(box);
  pre.setEnd(rng.startContainer, rng.startOffset);
  const start = pre.toString().length;
  const text = rng.toString();
  if (!text) return null;
  return {text, start, end: start + text.length};
})()
""", key=f"get_sel_{case_id}")
        if sel and isinstance(sel, dict) and sel.get("text"):
            st.session_state[hl_key].append(sel)
            st.session_state[hl_key] = _merge_overlaps(st.session_state[hl_key])
            _rerun()

    if st.session_state[hl_key]:
        st.caption("Your highlights:")
        for i, s in enumerate(st.session_state[hl_key]):
            snippet = s["text"].strip().replace("\n", " ")
            if len(snippet) > 45:
                snippet = snippet[:42] + "…"
            c1, c2 = st.columns([6, 1])
            c1.markdown(f"<div class='hl-chip'>{snippet}</div>", unsafe_allow_html=True)
            if c2.button("✕", key=f"rm_{case_id}_{i}"):
                del st.session_state[hl_key][i]
                _rerun()
        if st.button("Clear all highlights 🗑️"):
            st.session_state[hl_key] = []
            _rerun()

with right:
    st.info("Step 2 data will appear here once Step 1 is completed.")


# ================== QUESTIONS & SAVE ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio(
            "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q1_aki"
        )
        q_rationale = st.text_area("Please provide a brief rationale for your assessment.", height=140, key="q1_rationale")
        q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3, key="q1_conf")

        submitted1 = st.form_submit_button("Save Step 1 ✅")

    if submitted1:
        try:
            highlights_struct = st.session_state.get(hl_key, [])
            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 1,
                "q_aki": q_aki,
                "q_highlight": json.dumps(highlights_struct, ensure_ascii=False),
                "q_rationale": q_rationale,
                "q_confidence": q_conf,
                "q_reasoning": ""
            }
            append_dict(ws_resp, row, headers=st.session_state.resp_headers)
            st.success("Saved Step 1.")
            st.session_state.step = 2
            st.session_state.jump_to_top = True
            _rerun()
        finally:
            st.session_state.saving1 = False
