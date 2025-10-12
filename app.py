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
# anchor element so hash/focus-based scrolling has a reliable target
st.markdown('<div id="top" tabindex="-1"></div>', unsafe_allow_html=True)

# -------------------- Helpers --------------------
def _rerun():
    """Streamlit rerun helper that works across versions."""
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
    """
    Aggressive scroll-to-top:
     - sets location.hash to '#top' (requires the #top element to exist)
     - scrolls window and parent (if in iframe)
     - focuses the top anchor (helps some browsers)
     - repeats attempts at multiple delays to survive Streamlit reflows/async loads
    """
    _html(
        """
        <script>
        (function(){
          try { if ('scrollRestoration' in history) { history.scrollRestoration = 'manual'; } } catch(e) {}

          function topNow(){
            try {
              // anchor jump
              try { location.hash = '#top'; } catch(e){}

              // scroll window/document
              try { window.scrollTo(0,0); } catch(e){}
              try { document.documentElement && (document.documentElement.scrollTop = 0); } catch(e){}
              try { document.body && (document.body.scrollTop = 0); } catch(e){}

              // parent frame if embedded
              try {
                if (window.parent && window.parent !== window) {
                  try { window.parent.scrollTo(0,0); } catch(e){}
                  try {
                    var pdoc = window.parent.document;
                    if (pdoc) {
                      pdoc.documentElement && (pdoc.documentElement.scrollTop = 0);
                      pdoc.body && (pdoc.body.scrollTop = 0);
                    }
                  } catch(e){}
                }
              } catch(e){}

              // focus anchor
              try {
                var el = document.getElementById('top');
                if (el && typeof el.focus === 'function') { el.focus(); }
              } catch(e){}
            } catch(e){}
          }

          topNow();
          setTimeout(topNow, 50);
          setTimeout(topNow, 150);
          setTimeout(topNow, 400);
          setTimeout(topNow, 900);
          setTimeout(topNow, 1500);
          setTimeout(topNow, 3000);
        })();
        </script>
        """,
        height=0,
    )

def _retry_gs(func, *args, tries=8, delay=1.0, backoff=1.6, **kwargs):
    """
    Retry wrapper for Google Sheets calls to tolerate transient API errors (rate limit / 5xx).
    Raises RuntimeError after repeated failures so UI shows a clear message.
    """
    last = None
    for _ in range(tries):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            last = e
            time.sleep(delay)
            delay *= backoff
    raise RuntimeError(f"Google Sheets API error after retries: {last}")

# ---------- NEW: In-place highlighter (yellow) with **bold** markdown support ----------
def highlight_editor(summary_md: str, key: str = "hl_editor", height: int = 600):
    """
    Renders a contenteditable highlighter:
      - Converts minimal markdown (**bold**) to HTML client-side
      - Lets users highlight selections with <mark> (yellow)
      - Returns the current HTML back to Streamlit when 'Save to app' is clicked
    Returns:
        saved_html (str | None)
    """
    html = f"""
    <div style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; line-height:1.5;">
      <style>
        .toolbar {{
          position: sticky; top: 0; z-index: 10;
          display: flex; gap: 8px; padding: 8px; margin-bottom: 8px;
          background: #f7f7f9; border: 1px solid #e6e6ef; border-radius: 8px;
        }}
        .toolbar button {{
          border: 1px solid #d0d0da; border-radius: 8px; padding: 6px 10px; cursor: pointer;
          background: white;
        }}
        .toolbar button:hover {{ background: #f0f0ff; }}
        #editor {{
          border: 1px solid #e6e6ef; border-radius: 10px; padding: 12px; 
          min-height: {height - 88}px;
          max-height: {height - 24}px;
          overflow: auto; background: #fff;
          outline: none; white-space: pre-wrap;
        }}
        mark {{ background: yellow; padding: 0 .1em; border-radius: .2em; }}
        .muted {{ color: #666; font-size: 12px; margin-top: 6px; }}
      </style>

      <div class="toolbar">
        <button onclick="applyMark()">Highlight</button>
        <button onclick="removeMark()">Remove highlight</button>
        <button onclick="resetFromSource()">Reset</button>
        <div style="margin-left:auto;"></div>
        <button onclick="saveToApp()" style="background:#2e6bff;color:white;border-color:#2e6bff;">Save to app</button>
      </div>

      <div id="editor" contenteditable="true" spellcheck="false"></div>
      <div class="muted">Tip: select text, click <b>Highlight</b>. Bold markdown (**like this**) is supported.</div>

      <script>
        // Minimal markdown-to-HTML: **bold** + line breaks
        function mdToHtml(md) {{
          const esc = (s) => s.replace(/[&<>]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]));
          let t = esc(md).replace(/\\*\\*(.+?)\\*\\*/g, '<strong>$1</strong>');
          t = t.replace(/\\r?\\n/g, '<br>');
          return t;
        }}

        const sourceMd = {json.dumps(summary_md)};
        const looksHtml = typeof sourceMd === 'string' && /<\\w+[^>]*>/.test(sourceMd);
        const sourceHtml = looksHtml ? sourceMd : mdToHtml(sourceMd);
        const editor = document.getElementById('editor');
        editor.innerHTML = sourceHtml;

        function getSelectionRangeWithin(el) {{
          const sel = window.getSelection();
          if (!sel || sel.rangeCount === 0) return null;
          const range = sel.getRangeAt(0);
          if (!el.contains(range.commonAncestorContainer)) return null;
          return range;
        }}

        function wrapRangeWith(range, tagName) {{
          const wrapper = document.createElement(tagName);
          try {{
            range.surroundContents(wrapper);
          }} catch (e) {{
            const docFrag = range.extractContents();
            wrapper.appendChild(docFrag);
            range.insertNode(wrapper);
          }}
          return wrapper;
        }}

        function applyMark() {{
          const r = getSelectionRangeWithin(editor);
          if (!r || r.collapsed) return;
          wrapRangeWith(r, 'mark');
        }}

        function removeMark() {{
          const r = getSelectionRangeWithin(editor);
          if (!r || r.collapsed) return;
          const container = r.commonAncestorContainer.nodeType === 1 ? r.commonAncestorContainer : r.commonAncestorContainer.parentNode;
          const mark = container.closest ? container.closest('mark') : null;
          if (mark && editor.contains(mark)) {{
            const parent = mark.parentNode;
            while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
            parent.removeChild(mark);
          }}
        }}

        function resetFromSource() {{
          editor.innerHTML = sourceHtml;
        }}

        function saveToApp() {{
          const payload = editor.innerHTML;
          window.parent.postMessage({{
            isStreamlitMessage: true,
            type: 'streamlit:setComponentValue',
            value: payload
          }}, '*');
        }}
      </script>
    </div>
    """
    return _html(html, height=height, scrolling=True, key=key)

# ================== Google Sheets helpers ==================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

@st.cache_resource(show_spinner=False)
def _get_client_cached():
    """Create and cache a gspread client (no args so Streamlit can hash)."""
    if not USE_GSHEETS:
        return None
    try:
        if "service_account" in st.secrets:
            data = st.secrets["service_account"]
            if isinstance(data, str):
                data = json.loads(data)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(data, SCOPE)
        else:
            # local fallback file
            if not os.path.exists("service_account.json"):
                return None
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", SCOPE)
        return gspread.authorize(creds)
    except Exception as e:
        print("Google auth error:", e)
        return None

@st.cache_resource(show_spinner=False)
def _open_sheet_cached():
    """Open spreadsheet by ID (stored in st.secrets['gsheet_id']) with retries."""
    sheet_id = st.secrets.get("gsheet_id", "").strip()
    if not sheet_id:
        raise RuntimeError("Missing gsheet_id in Secrets. Add the Google Sheet ID between /d/ and /edit.")

    client = _get_client_cached()
    if client is None:
        raise RuntimeError("Google Sheets client not available. Ensure Secrets/service_account or service_account.json is present.")

    last_err = None
    for i in range(6):
        try:
            return client.open_by_key(sheet_id)
        except SpreadsheetNotFound:
            raise RuntimeError(
                "Could not open the Google Sheet by ID. Double-check gsheet_id and share the sheet with the service-account email as Editor."
            )
        except APIError as e:
            last_err = e
            time.sleep(1.2 * (i + 1))
    raise RuntimeError(f"Google Sheets API error after retries: {last_err}")

def get_or_create_ws(sh, title, headers=None):
    """
    Get a worksheet by title; create with headers if missing.
    Uses _retry_gs around worksheet and worksheet operations to reduce transient failures.
    """
    try:
        ws = _retry_gs(sh.worksheet, title)
    except RuntimeError:
        # probably not found -> create
        ws = _retry_gs(sh.add_worksheet, title=title, rows=1000, cols=max(10, (len(headers) if headers else 10)))
        if headers:
            _retry_gs(ws.update, [headers])

    # Ensure header row exists and merge non-destructively
    if headers:
        try:
            existing = _retry_gs(ws.row_values, 1)
        except RuntimeError as e:
            st.warning(f"Could not read header row for worksheet '{title}' right now; continuing. ({e})")
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

def ws_to_df(ws):
    recs = _retry_gs(ws.get_all_records)
    return pd.DataFrame(recs)

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
    if "jump_to_top" not in st.session_state:
        st.session_state.jump_to_top = True
    if "resp_headers" not in st.session_state:
        st.session_state.resp_headers = None

init_state()

# perform top scroll early on each render if requested
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

# Debug info (optional)
try:
    st.caption(f"Connected to Google Sheet: **{sh.title}**")
    st.caption("Tabs: " + ", ".join([ws.title for ws in sh.worksheets()]))
except Exception:
    pass

# ================== Worksheets (create if missing) ==================
adm_headers = ["case_id", "title", "discharge_summary", "weight_kg"]
labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = [
    "timestamp_utc", "reviewer_id", "case_id", "step",
    "q_aki", "q_highlight", "q_rationale", "q_confidence", "q_reasoning"
]

ws_adm = get_or_create_ws(sh, "admissions", adm_headers)
ws_labs = get_or_create_ws(sh, "labs", labs_headers)
ws_resp = get_or_create_ws(sh, "responses", resp_headers)

# Cache the response headers once so we don’t re-read them on every save
if st.session_state.resp_headers is None:
    st.session_state.resp_headers = _retry_gs(ws_resp.row_values, 1)

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
labs = _read_ws_df(st.secrets["gsheet_id"], "labs")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

if admissions.empty:
    st.error("Admissions sheet is empty. Add rows to 'admissions' with: case_id,title,discharge_summary,weight_kg")
    st.stop()

# ===== Resume progress for this reviewer (run once per sign-in) =====
if st.session_state.entered and not st.session_state.get("progress_initialized"):
    try:
        resp = responses.copy()
        rid = str(st.session_state.reviewer_id)

        # Filter for this reviewer only
        if not resp.empty:
            resp = resp[resp["reviewer_id"].astype(str) == rid]
        else:
            resp = resp  # leave empty

        # Normalize types
        if not resp.empty and "step" in resp.columns:
            resp["step"] = pd.to_numeric(resp["step"], errors="coerce").fillna(0).astype(int)
        else:
            resp["step"] = []

        # Sets of finished/started cases
        completed_ids = set(resp.loc[resp["step"] == 2, "case_id"].astype(str)) if not resp.empty else set()
        step1_only_ids = set(resp.loc[resp["step"] == 1, "case_id"].astype(str)) - completed_ids if not resp.empty else set()

        # Find first admission not fully completed
        target_idx = None
        target_step = 1
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
        st.warning(f"Could not auto-resume progress: {e}")

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

# Filter labs for this case
case_labs = labs[labs["case_id"].astype(str) == case_id].copy()
if not case_labs.empty:
    case_labs["timestamp"] = pd.to_datetime(case_labs["timestamp"], errors="coerce")
scr = case_labs[case_labs["kind"].astype(str).str.lower() == "scr"].sort_values("timestamp")
uo = case_labs[case_labs["kind"].astype(str).str.lower() == "uo"].sort_values("timestamp")

# ================== Layout ==================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary**")
    # ---------- NEW: High, scrollable, in-place highlight editor ----------
    saved_highlight_html = highlight_editor(summary_md=summary, key=f"hl_{case_id}", height=600)
    if saved_highlight_html:
        # Store captured HTML in session for save handlers
        st.session_state[f"highlight_html_{case_id}"] = saved_highlight_html
        st.success("Highlights captured. Don’t forget to save this step.")

with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only. Do not use structured data.")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        import altair as alt

        if not scr.empty:
            st.markdown("**Serum Creatinine (mg/dL)**")
            ch_scr = alt.Chart(scr.rename(columns={"timestamp": "time", "value": "scr"})).mark_line(point=True).encode(
                x=alt.X("time:T", title="Time"),
                y=alt.Y("scr:Q", title="mg/dL")
            )
            st.altair_chart(ch_scr, use_container_width=True)
            st.caption("Table — SCr:")
            st.dataframe(scr[["timestamp", "value", "unit"]].rename(columns={"value": "scr"}), use_container_width=True)
        else:
            st.warning("No SCr values for this case.")

        if not uo.empty:
            st.markdown("**Urine Output (mL/kg/h)**" + (f" — weight: {weight} kg" if weight else ""))
            ch_uo = alt.Chart(uo.rename(columns={"timestamp": "time", "value": "uo"})).mark_line(point=True).encode(
                x=alt.X("time:T", title="Time"),
                y=alt.Y("uo:Q", title="mL/kg/h")
            )
            ref = pd.DataFrame({"time": [uo["timestamp"].min(), uo["timestamp"].max()], "ref": [0.5, 0.5]})
            ch_ref = alt.Chart(ref).mark_rule(strokeDash=[6, 6]).encode(x="time:T", y="ref:Q")
            st.altair_chart(ch_uo + ch_ref, use_container_width=True)
            st.caption("Table — UO:")
            st.dataframe(uo[["timestamp", "value", "unit"]].rename(columns={"value": "uo"}), use_container_width=True)
        else:
            st.warning("No UO values for this case.")

st.markdown("---")

# ================== Questions & Saving ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio(
            "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q1_aki"
        )
        # REMOVED the old free-text highlight box; we capture HTML from the editor instead
        q_rationale = st.text_area("Please provide a brief rationale for your assessment.", height=140, key="q1_rationale")
        q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3, key="q1_conf")

        submitted1 = st.form_submit_button("Save Step 1 ✅", disabled=st.session_state.get("saving1", False))

    if submitted1:
        try:
            st.session_state.saving1 = True
            # Pull last captured highlight HTML (if reviewer clicked 'Save to app')
            highlight_html = st.session_state.get(f"highlight_html_{case_id}", "")
            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 1,
                "q_aki": q_aki,
                "q_highlight": highlight_html,   # store HTML with <mark> and <strong>
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
                "q_highlight": "",          # optional: could also persist highlight_html if desired
                "q_rationale": q_reasoning, # keeping same mapping as your schema
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

# Navigation helpers
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
