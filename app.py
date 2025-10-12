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

from streamlit.components.v1 import html as _html
import html as _py_html

# ======== REPLACE your existing highlight_widget with this version ========
import html as _py_html
from streamlit.components.v1 import html as _html

import html as _py_html
from streamlit.components.v1 import html as _html
import json

# --- Highlighter widget with legacy postMessage fallback ---
import html as _py_html
from streamlit.components.v1 import html as _html
import json as _json

# ======== REPLACE your existing highlight_widget with this version ========
import html as _py_html
from streamlit.components.v1 import html as _html

import html as _py_html
from streamlit.components.v1 import html as _html
import json
import urllib.parse


import html as _py_html
from streamlit.components.v1 import html as _html
import json
import urllib.parse

import html as _py_html
from streamlit.components.v1 import html as _html
import json

def highlight_widget_inside_form(text: str, case_id: str, height: int = 280):
    """
    One-box highlighter for *inside* a Streamlit form.
    - Buttons at the top.
    - Selection and preview are the same box.
    - Auto-syncs to URL query param ?hl_<case_id>=<urlencoded html> after every change.
    """
    safe_text = _py_html.escape(text)
    safe_text_json = json.dumps(safe_text)
    qp_key = f"hl_{case_id}"

    code = f"""
    <div style="font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial;">
      <!-- Buttons at top -->
      <div style="display:flex; gap:8px; margin-bottom:8px;">
        <button id="addBtn" type="button">Add selection</button>
        <button id="clearBtn" type="button">Clear</button>
      </div>

      <!-- Single viewer: selection + live highlights -->
      <div id="viewer"
           style="border:1px solid #ddd;border-radius:8px;padding:12px;white-space:pre-wrap;line-height:1.5;max-height:{height}px;overflow:auto;"></div>

      <script>
        const original = {safe_text_json};
        const qpKey = {json.dumps(qp_key)};
        const viewer = document.getElementById('viewer');
        const addBtn = document.getElementById('addBtn');
        const clearBtn = document.getElementById('clearBtn');

        // Maintain highlight ranges as offsets over the *plain* original text.
        let ranges = [];

        function escapeHtml(s) {{
          return s.replaceAll('&','&amp;').replaceAll('<','&lt;')
                  .replaceAll('>','&gt;').replaceAll('"','&quot;')
                  .replaceAll("'",'&#039;');
        }}

        function render() {{
          if (!ranges.length) {{
            viewer.innerHTML = escapeHtml(original);
          }} else {{
            const rs = ranges.slice().sort((a,b)=>a.start-b.start);
            let html='', cur=0;
            for (const r of rs) {{
              html += escapeHtml(original.slice(cur, r.start));
              html += '<mark>' + escapeHtml(original.slice(r.start, r.end)) + '</mark>';
              cur = r.end;
            }}
            html += escapeHtml(original.slice(cur));
            viewer.innerHTML = html;
          }}
          syncToUrl();  // auto-sync after every render
        }}

        function syncToUrl() {{
          try {{
            const html = viewer.innerHTML;
            const u = new URL(window.parent.location.href);
            u.searchParams.set(qpKey, encodeURIComponent(html));
            window.parent.history.replaceState(null, '', u.toString());
          }} catch(e) {{ /* ignore */ }}
        }}

        // Merge overlapping/adjacent
        function merge(rs) {{
          if (!rs.length) return rs;
          rs.sort((a,b)=>a.start-b.start);
          const out=[rs[0]];
          for (let i=1;i<rs.length;i++) {{
            const last=out[out.length-1], cur=rs[i];
            if (cur.start <= last.end) last.end=Math.max(last.end, cur.end);
            else out.push(cur);
          }}
          return out;
        }}

        // Compute selection offsets relative to the *displayed* text (marks ignored via toString)
        function getSelectionOffsets() {{
          const sel = window.getSelection();
          if (!sel || sel.rangeCount===0) return null;
          const rng = sel.getRangeAt(0);
          if (!viewer.contains(rng.startContainer) || !viewer.contains(rng.endContainer)) return null;

          const pre = document.createRange();
          pre.setStart(viewer, 0);
          pre.setEnd(rng.startContainer, rng.startOffset);
          const start = pre.toString().length;
          const len = rng.toString().length;
          return len>0 ? {{start, end:start+len}} : null;
        }}

        addBtn.onclick = () => {{
          const off = getSelectionOffsets();
          if (!off) return;
          ranges.push(off);
          ranges = merge(ranges);
          render();
        }};

        clearBtn.onclick = () => {{
          ranges = [];
          render();
        }};

        // Initial paint
        render();

        // Ensure a final sync right before parent "Save Step 1" is clicked
        const hookSave = () => {{
          try {{
            const btns = window.parent.document.querySelectorAll('button');
            btns.forEach(b => {{
              if (b.__hl_hooked__) return;
              if ((b.textContent||'').includes('Save Step 1')) {{
                b.__hl_hooked__ = true;
                b.addEventListener('click', () => syncToUrl(), {{capture:true}});
              }}
            }});
          }} catch(e) {{}}
        }};
        try {{
          const mo = new MutationObserver(hookSave);
          mo.observe(window.parent.document.body, {{childList:true, subtree:true}});
          hookSave();
        }} catch(e) {{}}
      </script>
    </div>
    """
    return _html(code, height=height + 80)







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

              // focus anchor (preventScroll true not supported everywhere, but trying helps)
              try {
                var el = document.getElementById('top');
                if (el && typeof el.focus === 'function') { el.focus(); }
              } catch(e){}
            } catch(e){}
          }

          // call several times to survive Streamlit's DOM changes / async loads
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
            # Non-fatal: warn and continue. App can still append rows with headers in unknown order.
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
        # start at top on first load
        st.session_state.jump_to_top = True

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
    # non-fatal debug failure
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
if "resp_headers" not in st.session_state:
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
            # All admissions completed by this reviewer
            st.session_state.case_idx = len(admissions)
            st.session_state.step = 1

    except Exception as e:
        st.warning(f"Could not auto-resume progress: {e}")

    # Mark done and refresh to land on the right case/step
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
    st.write(summary)

with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only. Do not use structured data.")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        import altair as alt

        # ensure we nudge to top when entering step 2 (defensive)
        # (we set jump_to_top before rerun on transitions; leave this commented unless needed)
        # st.session_state.jump_to_top = True
        # _scroll_top()

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

        st.markdown("**Highlight the exact text that influenced your conclusion**")
        highlight_widget_inside_form(summary, case_id=case_id, height=260)

        q_rationale = st.text_area("Please provide a brief rationale for your assessment.",
                                   height=140, key="q1_rationale")
        q_conf = st.slider("How confident are you in your assessment? (1–5)", 1, 5, 3, key="q1_conf")

        submitted1 = st.form_submit_button("Save Step 1 ✅", disabled=st.session_state.get("saving1", False))

    if submitted1:
        try:
            st.session_state.saving1 = True

            # Read the synced highlights from the URL query params at submit time
            qp_key = f"hl_{case_id}"
            qp = st.query_params
            hl_html = urllib.parse.unquote(qp.get(qp_key, "")) if qp_key in qp else ""

            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 1,
                "q_aki": q_aki,
                "q_highlight": hl_html,     # HTML with <mark>...</mark>
                "q_rationale": q_rationale,
                "q_confidence": q_conf,
                "q_reasoning": ""
            }
            append_dict(ws_resp, row, headers=st.session_state.resp_headers)

            # clear param so it doesn't leak into the next case
            st.query_params.clear()

            st.success("Saved Step 1.")
            st.session_state.step = 2
            st.session_state.jump_to_top = True
            _scroll_top(); time.sleep(0.25)
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
                "q_rationale": q_reasoning,  # keep if you want both; otherwise drop this field from headers later
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

