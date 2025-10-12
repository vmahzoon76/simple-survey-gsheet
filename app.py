import os
import json
import time
from datetime import datetime
import urllib.parse
import pandas as pd
import streamlit as st
from streamlit.components.v1 import html as _html

# ================================================================
# Google Sheets setup (same as your version)
# ================================================================
USE_GSHEETS = True
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    from gspread.exceptions import APIError, SpreadsheetNotFound
except Exception:
    USE_GSHEETS = False

st.set_page_config(page_title="AKI Expert Review", layout="wide")
st.title("AKI Expert Review")
st.markdown('<div id="top" tabindex="-1"></div>', unsafe_allow_html=True)

# ================================================================
# Inline Highlighter (directly inside the discharge text)
# ================================================================
import html as _py_html

def inline_highlighter(text: str, case_id: str, height: int = 400):
    """Render discharge summary with live inline highlighting."""
    safe_text = _py_html.escape(text)
    qp_key = f"hl_{case_id}"

    code = f"""
    <div style="font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; line-height:1.5;">
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <button id="addBtn" type="button">Highlight</button>
        <button id="clearBtn" type="button">Clear</button>
      </div>

      <!-- The *actual discharge summary text* -->
      <div id="text"
           style="border:1px solid #ccc;border-radius:8px;padding:12px;white-space:pre-wrap;
                  overflow-y:auto;max-height:{height}px;">
        {safe_text}
      </div>

      <script>
        const textEl = document.getElementById('text');
        const addBtn = document.getElementById('addBtn');
        const clearBtn = document.getElementById('clearBtn');
        const qpKey = {json.dumps(qp_key)};
        let ranges = [];

        function escapeHtml(s) {{
          return s.replaceAll('&','&amp;').replaceAll('<','&lt;')
                  .replaceAll('>','&gt;').replaceAll('"','&quot;')
                  .replaceAll("'",'&#039;');
        }}

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

        function getSelectionOffsets() {{
          const sel = window.getSelection();
          if (!sel || sel.rangeCount===0) return null;
          const range = sel.getRangeAt(0);
          if (!textEl.contains(range.startContainer) || !textEl.contains(range.endContainer)) return null;
          const pre = document.createRange();
          pre.setStart(textEl,0);
          pre.setEnd(range.startContainer, range.startOffset);
          const start = pre.toString().length;
          const len = range.toString().length;
          return len>0 ? {{start, end:start+len}} : null;
        }}

        function render() {{
          const txt = textEl.textContent;
          if (!ranges.length) {{
            textEl.innerHTML = escapeHtml(txt);
          }} else {{
            const rs = ranges.slice().sort((a,b)=>a.start-b.start);
            let html='', cur=0;
            for (const r of rs) {{
              html += escapeHtml(txt.slice(cur, r.start));
              html += '<mark>' + escapeHtml(txt.slice(r.start, r.end)) + '</mark>';
              cur = r.end;
            }}
            html += escapeHtml(txt.slice(cur));
            textEl.innerHTML = html;
          }}
          syncToUrl();
        }}

        function syncToUrl() {{
          try {{
            const html = textEl.innerHTML;
            const u = new URL(window.parent.location.href);
            u.searchParams.set(qpKey, encodeURIComponent(html));
            window.parent.history.replaceState(null, '', u.toString());
          }} catch(e) {{}}
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

        // Hook to auto-sync before Save Step 1
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
        const mo = new MutationObserver(hookSave);
        try {{
          mo.observe(window.parent.document.body, {{childList:true, subtree:true}});
          hookSave();
        }} catch(e) {{}}
      </script>
    </div>
    """
    _html(code, height=height + 60)

# ================================================================
# Utility helpers
# ================================================================
def _rerun():
    try: st.rerun()
    except AttributeError: st.experimental_rerun()

def _retry_gs(func, *args, tries=5, delay=1.0, backoff=1.5, **kwargs):
    for _ in range(tries):
        try:
            return func(*args, **kwargs)
        except APIError:
            time.sleep(delay)
            delay *= backoff
    raise

SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]

@st.cache_resource(show_spinner=False)
def _get_client_cached():
    if not USE_GSHEETS:
        return None
    try:
        if "service_account" in st.secrets:
            data = st.secrets["service_account"]
            if isinstance(data, str): data = json.loads(data)
            creds = ServiceAccountCredentials.from_json_keyfile_dict(data, SCOPE)
        else:
            creds = ServiceAccountCredentials.from_json_keyfile_name("service_account.json", SCOPE)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"Google auth error: {e}")
        return None

@st.cache_resource(show_spinner=False)
def _open_sheet_cached():
    sheet_id = st.secrets.get("gsheet_id", "").strip()
    if not sheet_id: raise RuntimeError("Missing gsheet_id in Secrets.")
    client = _get_client_cached()
    return client.open_by_key(sheet_id)

def get_or_create_ws(sh, title, headers):
    try:
        ws = sh.worksheet(title)
    except:
        ws = sh.add_worksheet(title=title, rows=1000, cols=len(headers))
        ws.update("A1", [headers])
    return ws

@st.cache_data(ttl=120, show_spinner=False)
def _read_ws_df(sheet_id, ws_title):
    sh = _open_sheet_cached()
    ws = sh.worksheet(ws_title)
    recs = ws.get_all_records()
    return pd.DataFrame(recs)

def append_dict(ws, d, headers):
    row = [d.get(h, "") for h in headers]
    ws.append_row(row, value_input_option="USER_ENTERED")

# ================================================================
# Session & state initialization
# ================================================================
def init_state():
    for k,v in {
        "entered": False, "reviewer_id": "", "case_idx": 0,
        "step": 1, "jump_to_top": True
    }.items():
        if k not in st.session_state: st.session_state[k] = v

init_state()

# ================================================================
# Sign-in
# ================================================================
with st.sidebar:
    st.subheader("Sign in")
    rid = st.text_input("Your name or ID", value=st.session_state.reviewer_id)
    if st.button("Enter"):
        if rid.strip():
            st.session_state.reviewer_id = rid.strip()
            st.session_state.entered = True
            _rerun()

if not st.session_state.entered:
    st.info("Please sign in with your Reviewer ID to begin.")
    st.stop()

# ================================================================
# Load Sheets
# ================================================================
sh = _open_sheet_cached()
ws_adm = get_or_create_ws(sh, "admissions", ["case_id", "title", "discharge_summary", "weight_kg"])
ws_labs = get_or_create_ws(sh, "labs", ["case_id", "timestamp", "kind", "value", "unit"])
ws_resp = get_or_create_ws(sh, "responses", [
    "timestamp_utc","reviewer_id","case_id","step",
    "q_aki","q_highlight","q_rationale","q_confidence","q_reasoning"
])

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
labs = _read_ws_df(st.secrets["gsheet_id"], "labs")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

if admissions.empty:
    st.error("Admissions sheet is empty.")
    st.stop()

# ================================================================
# Current Case
# ================================================================
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

# ================================================================
# Layout
# ================================================================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary (Highlight directly in text below)**")
    inline_highlighter(summary, case_id=case_id, height=420)

with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only (no structured data).")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        import altair as alt
        case_labs = labs[labs["case_id"].astype(str) == case_id]
        if not case_labs.empty:
            case_labs["timestamp"] = pd.to_datetime(case_labs["timestamp"], errors="coerce")
            scr = case_labs[case_labs["kind"].str.lower() == "scr"]
            uo = case_labs[case_labs["kind"].str.lower() == "uo"]
        else:
            scr = uo = pd.DataFrame()

        if not scr.empty:
            st.markdown("**Serum Creatinine (mg/dL)**")
            ch = alt.Chart(scr.rename(columns={"timestamp":"time","value":"scr"})) \
                .mark_line(point=True).encode(x="time:T", y="scr:Q")
            st.altair_chart(ch, use_container_width=True)
        else:
            st.warning("No SCr values for this case.")
        if not uo.empty:
            st.markdown("**Urine Output (mL/kg/h)**")
            ch = alt.Chart(uo.rename(columns={"timestamp":"time","value":"uo"})) \
                .mark_line(point=True).encode(x="time:T", y="uo:Q")
            st.altair_chart(ch, use_container_width=True)
        else:
            st.warning("No UO values for this case.")

st.markdown("---")

# ================================================================
# Step 1 / Step 2 Forms
# ================================================================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio(
            "Based on the discharge summary, did the note writers think the patient had AKI?",
            ["Yes","No"], horizontal=True, key="q1_aki"
        )
        q_rationale = st.text_area("Rationale for your assessment:", height=140)
        q_conf = st.slider("Confidence (1–5)", 1, 5, 3)
        submitted1 = st.form_submit_button("Save Step 1 ✅")
    if submitted1:
        qp_key = f"hl_{case_id}"
        qp = st.query_params
        hl_html = urllib.parse.unquote(qp.get(qp_key, "")) if qp_key in qp else ""
        append_dict(ws_resp, {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "reviewer_id": st.session_state.reviewer_id,
            "case_id": case_id,
            "step": 1,
            "q_aki": q_aki,
            "q_highlight": hl_html,
            "q_rationale": q_rationale,
            "q_confidence": q_conf,
            "q_reasoning": ""
        }, headers=ws_resp.row_values(1))
        st.query_params.clear()
        st.success("Saved Step 1.")
        st.session_state.step = 2
        _rerun()

else:
    st.subheader("Step 2 — Questions (Full Context)")
    with st.form("step2_form", clear_on_submit=False):
        q_aki2 = st.radio("Given all EHR info, did the patient have AKI?",
                          ["Yes","No"], horizontal=True)
        q_reasoning = st.text_area("Describe your reasoning process:", height=180)
        submitted2 = st.form_submit_button("Save Step 2 ✅ (Next Case)")
    if submitted2:
        append_dict(ws_resp, {
            "timestamp_utc": datetime.utcnow().isoformat(),
            "reviewer_id": st.session_state.reviewer_id,
            "case_id": case_id,
            "step": 2,
            "q_aki": q_aki2,
            "q_highlight": "",
            "q_rationale": q_reasoning,
            "q_confidence": "",
            "q_reasoning": q_reasoning
        }, headers=ws_resp.row_values(1))
        st.success("Saved Step 2.")
        st.session_state.step = 1
        st.session_state.case_idx += 1
        _rerun()

# ================================================================
# Navigation buttons
# ================================================================
col1, _, col3 = st.columns(3)
with col1:
    if st.button("◀ Back"):
        if st.session_state.step == 2:
            st.session_state.step = 1
        elif st.session_state.case_idx > 0:
            st.session_state.case_idx -= 1
            st.session_state.step = 2
        _rerun()
with col3:
    if st.button("Skip ▶"):
        st.session_state.step = 1
        st.session_state.case_idx += 1
        _rerun()
