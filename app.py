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

@st.cache_data(ttl=60, show_spinner=False)
def _read_ws_df(sheet_id, ws_title):
    sh = _open_sheet_cached()
    ws = sh.worksheet(ws_title)
    recs = _retry_gs(ws.get_all_records)
    return pd.DataFrame(recs)

def _scroll_top():
    _html(
        """
        <script>
        (function(){
          try { if ('scrollRestoration' in history) { history.scrollRestoration = 'manual'; } } catch(e) {}
          function topNow(){
            try {
              location.hash = '#top';
              window.scrollTo(0,0);
              document.documentElement.scrollTop = 0;
              document.body.scrollTop = 0;
              if (window.parent && window.parent !== window) {
                window.parent.scrollTo(0,0);
              }
              const el = document.getElementById('top');
              if (el && el.focus) el.focus();
            } catch(e){}
          }
          topNow(); setTimeout(topNow, 50); setTimeout(topNow,150);
        })();
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
        try:
            existing = _retry_gs(ws.row_values, 1)
        except RuntimeError:
            return ws
        if not existing:
            _retry_gs(ws.update, [headers])
        elif existing != headers:
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

# ============ Highlighter Widget ============
import html as _py_html
def highlight_widget(text: str, key: str = "hl_1", height: int = 420):
    safe_text = _py_html.escape(text)
    code = f"""
    <div style="font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;">
      <div style="margin-bottom:8px;">
        <button id="addBtn">Add highlight</button>
        <button id="clearBtn" style="margin-left:6px;">Clear all</button>
      </div>
      <div id="box"
           style="border:1px solid #ddd;border-radius:8px;padding:12px;white-space:pre-wrap;line-height:1.5;max-height:200px;overflow:auto;">
        {safe_text}
      </div>
      <div style="margin-top:10px;font-size:12px;color:#666;">
        Select text above, then click <b>Add highlight</b>.
      </div>
      <div style="margin-top:12px;">
        <div style="font-weight:600;margin-bottom:6px;">Preview</div>
        <div id="preview" style="border:1px dashed #ccc;border-radius:8px;padding:10px;white-space:pre-wrap;max-height:140px;overflow:auto;"></div>
      </div>
      <script>
        const original = `{safe_text}`;
        const box = document.getElementById('box');
        const addBtn = document.getElementById('addBtn');
        const clearBtn = document.getElementById('clearBtn');
        const preview = document.getElementById('preview');
        let highlights = [];

        function currentSelectionOffsets() {{
          const sel = window.getSelection();
          if (!sel || sel.rangeCount === 0) return null;
          const range = sel.getRangeAt(0);
          if (!box.contains(range.startContainer) || !box.contains(range.endContainer)) return null;
          const preRange = document.createRange();
          preRange.setStart(box, 0);
          preRange.setEnd(range.startContainer, range.startOffset);
          const start = preRange.toString().length;
          const len = range.toString().length;
          return len > 0 ? {{start: start, end: start + len}} : null;
        }}

        function rebuildPreview() {{
          if (highlights.length === 0) {{ preview.textContent = original; return; }}
          const sorted = [...highlights].sort((a,b)=>a.start-b.start);
          let html = "", cursor = 0;
          for (const h of sorted) {{
            const pre = original.slice(cursor, h.start);
            const mid = original.slice(h.start, h.end);
            html += escapeHtml(pre) + "<mark>" + escapeHtml(mid) + "</mark>";
            cursor = h.end;
          }}
          html += escapeHtml(original.slice(cursor));
          preview.innerHTML = html;
        }}

        function escapeHtml(s) {{
          return s.replaceAll("&","&amp;").replaceAll("<","&lt;")
                  .replaceAll(">","&gt;").replaceAll('"',"&quot;")
                  .replaceAll("'","&#039;");
        }}

        function mergeRanges(ranges) {{
          if (ranges.length===0) return [];
          const s = ranges.sort((a,b)=>a.start-b.start);
          const out = [s[0]];
          for (let i=1;i<s.length;i++) {{
            const last = out[out.length-1];
            const cur = s[i];
            if (cur.start <= last.end) last.end = Math.max(last.end, cur.end);
            else out.push(cur);
          }}
          return out;
        }}

        function post() {{
          const payload = {{
            highlights: highlights.map(h => ({{...h, text: original.slice(h.start,h.end)}})),
            html: preview.innerHTML
          }};
          if (window.Streamlit && window.Streamlit.setComponentValue)
            window.Streamlit.setComponentValue(payload);
        }}

        addBtn.onclick = () => {{
          const off = currentSelectionOffsets();
          if (!off) return;
          highlights.push(off);
          highlights = mergeRanges(highlights);
          rebuildPreview();
          post();
        }};
        clearBtn.onclick = () => {{
          highlights = [];
          rebuildPreview();
          post();
        }};
        rebuildPreview();
        if (window.Streamlit && window.Streamlit.setFrameHeight)
          window.Streamlit.setFrameHeight({height});
      </script>
    </div>
    """
    return _html(code, height=height + 40, scrolling=True, key=key)

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
    if "jump_to_top" not in st.session_state:
        st.session_state.jump_to_top = True

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

if "resp_headers" not in st.session_state:
    st.session_state.resp_headers = _retry_gs(ws_resp.row_values, 1)

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
labs = _read_ws_df(st.secrets["gsheet_id"], "labs")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

if admissions.empty:
    st.error("Admissions sheet is empty.")
    st.stop()

# ========== Progress resume ==========
if st.session_state.entered and not st.session_state.get("progress_initialized"):
    try:
        resp = responses.copy()
        rid = str(st.session_state.reviewer_id)
        if not resp.empty:
            resp = resp[resp["reviewer_id"].astype(str) == rid]
        if not resp.empty and "step" in resp.columns:
            resp["step"] = pd.to_numeric(resp["step"], errors="coerce").fillna(0).astype(int)
        completed_ids = set(resp.loc[resp["step"] == 2, "case_id"].astype(str)) if not resp.empty else set()
        step1_only_ids = set(resp.loc[resp["step"] == 1, "case_id"].astype(str)) - completed_ids if not resp.empty else set()
        target_idx, target_step = None, 1
        for idx, row in admissions.reset_index(drop=True).iterrows():
            cid = str(row.get("case_id", ""))
            if cid in completed_ids:
                continue
            target_idx = idx
            target_step = 2 if cid in step1_only_ids else 1
            break
        if target_idx is not None:
            st.session_state.case_idx = int(target_idx)
            st.session_state.step = int(target_step)
        else:
            st.session_state.case_idx = len(admissions)
            st.session_state.step = 1
    except Exception as e:
        st.warning(f"Could not auto-resume: {e}")
    st.session_state.progress_initialized = True
    st.session_state.jump_to_top = True
    _scroll_top()
    time.sleep(0.15)
    _rerun()

# ================== Current case ==================
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

# ================== Step 1 ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio(
            "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q1_aki"
        )
        st.markdown("**Highlight the exact text that influenced your conclusion**")
        hl_val = highlight_widget(summary, key=f"hl_{case_id}", height=420)
        if isinstance(hl_val, dict) and hl_val.get("highlights"):
            with st.expander("Your selected highlights (preview)"):
                st.markdown(hl_val["html"], unsafe_allow_html=True)

        q_rationale = st.text_area("Please provide a brief rationale for your assessment.", height=140, key="q1_rationale")
        q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3, key="q1_conf")

        submitted1 = st.form_submit_button("Save Step 1 ✅", disabled=st.session_state.get("saving1", False))

    if submitted1:
        try:
            st.session_state.saving1 = True
            hl_json = json.dumps(hl_val["highlights"]) if isinstance(hl_val, dict) else "[]"
            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 1,
                "q_aki": q_aki,
                "q_highlight": hl_json,
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

# ================== Step 2 ==================
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
                "q_reasoning": q_reasoning
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

# ========== Navigation ==========
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
