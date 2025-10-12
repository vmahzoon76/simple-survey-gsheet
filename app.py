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

# -------------------- CSS for Highlight UI --------------------
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
          function topNow(){
            try {
              location.hash = '#top';
              window.scrollTo(0,0);
              document.documentElement.scrollTop = 0;
              document.body.scrollTop = 0;
            }catch(e){}
          }
          topNow(); setTimeout(topNow,50); setTimeout(topNow,400);
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
            st.warning(f"Could not read header row for worksheet '{title}' right now.")
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
    for key, default in {
        "entered": False, "reviewer_id": "", "case_idx": 0,
        "step": 1, "jump_to_top": True
    }.items():
        if key not in st.session_state:
            st.session_state[key] = default

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

# Resume progress
if st.session_state.entered and not st.session_state.get("progress_initialized"):
    try:
        resp = responses.copy()
        rid = str(st.session_state.reviewer_id)
        if not resp.empty:
            resp = resp[resp["reviewer_id"].astype(str) == rid]
        else:
            resp = resp
        if not resp.empty and "step" in resp.columns:
            resp["step"] = pd.to_numeric(resp["step"], errors="coerce").fillna(0).astype(int)
        else:
            resp["step"] = []
        completed_ids = set(resp.loc[resp["step"] == 2, "case_id"].astype(str)) if not resp.empty else set()
        step1_only_ids = set(resp.loc[resp["step"] == 1, "case_id"].astype(str)) - completed_ids if not resp.empty else set()
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

# ================== HIGHLIGHT UTILITIES ==================
import html
from streamlit_js_eval import streamlit_js_eval  # ensure streamlit-js-eval is in requirements

def _merge_overlaps(spans):
    if not spans: return []
    spans = sorted(spans, key=lambda s: (s["start"], s["end"]))
    merged = [spans[0].copy()]
    for s in spans[1:]:
        last = merged[-1]
        if s["start"] <= last["end"]:
            last["end"] = max(last["end"], s["end"])
        else:
            merged.append(s.copy())
    return merged

def _render_with_highlights(raw_text, spans):
    if not spans:
        return f'<div id="sum" class="highlighter-wrap">{html.escape(raw_text)}</div>'
    spans = _merge_overlaps(spans)
    out, cursor = [], 0
    for s in spans:
        start, end = max(0, min(len(raw_text), s["start"])), max(0, min(len(raw_text), s["end"]))
        if start > cursor:
            out.append(html.escape(raw_text[cursor:start]))
        out.append(f'<mark class="hl">{html.escape(raw_text[start:end])}</mark>')
        cursor = end
    if cursor < len(raw_text):
        out.append(html.escape(raw_text[cursor:]))
    wrapped = "".join(out)
    return f'<div id="sum" class="highlighter-wrap">{wrapped}</div>'

# ================== Layout ==================
left, right = st.columns([2, 3], gap="large")

with left:
    st.markdown("**Discharge Summary**")
    hl_key = f"hl_{case_id}"
    if hl_key not in st.session_state:
        st.session_state[hl_key] = []

    # Render text with highlights
    summary_html = _render_with_highlights(summary, st.session_state[hl_key])
    st.markdown(summary_html, unsafe_allow_html=True)

    # 🔧 NEW: capture selection on mouseup inside #sum and cache it in window._hlSel
    _html("""
<script>
(function(){
  const box = document.getElementById('sum');
  if (!box) return;

  function getOffsets(rng) {
    const pre = document.createRange();
    pre.selectNodeContents(box);
    pre.setEnd(rng.startContainer, rng.startOffset);
    const start = pre.toString().length;
    const text  = rng.toString();
    return {text, start, end: start + text.length};
  }

  box.addEventListener('mouseup', function(){
    try{
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) { window._hlSel = null; return; }
      const rng = sel.getRangeAt(0);
      if (!box.contains(rng.commonAncestorContainer)) { window._hlSel = null; return; }
      const payload = getOffsets(rng);
      if (payload.text && payload.text.length > 0) {
        window._hlSel = payload;
      } else {
        window._hlSel = null;
      }
    }catch(e){ window._hlSel = null; }
  }, false);
})();
</script>
""", height=0)

    colA, colB = st.columns([1, 3])
    with colA:
        add_clicked = st.button("➕ Add selection", help="Select text inside the summary box, then click")

    if add_clicked:
        # Read cached selection (remains valid even if the button click clears the live selection)
        sel = streamlit_js_eval(js_expressions="window._hlSel || null", key=f"cached_sel_{case_id}")
        if sel and isinstance(sel, dict) and sel.get("text"):
            st.session_state[hl_key].append(sel)
            st.session_state[hl_key] = _merge_overlaps(st.session_state[hl_key])
            _rerun()
        else:
            st.warning("No selection detected. Select text in the summary (release mouse), then click Add selection.")

    # Manage highlights
    if st.session_state[hl_key]:
        st.caption(f"{len(st.session_state[hl_key])} highlight(s) ready to save to q_highlight.")
        for i, s in enumerate(st.session_state[hl_key]):
            label = s["text"].strip().replace("\n", " ")
            if len(label) > 40: label = label[:37] + "…"
            c1, c2 = st.columns([6,1])
            c1.markdown(f"<div class='hl-chip'>{html.escape(label)}</div>", unsafe_allow_html=True)
            if c2.button("✕", key=f"rm_{case_id}_{i}"):
                del st.session_state[hl_key][i]
                _rerun()
        if st.button("Clear all highlights 🗑️"):
            st.session_state[hl_key] = []
            _rerun()

with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only.")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        import altair as alt
        case_labs = labs[labs["case_id"].astype(str) == case_id].copy()
        case_labs["timestamp"] = pd.to_datetime(case_labs["timestamp"], errors="coerce")
        scr = case_labs[case_labs["kind"].str.lower() == "scr"].sort_values("timestamp")
        uo = case_labs[case_labs["kind"].str.lower() == "uo"].sort_values("timestamp")
        if not scr.empty:
            st.markdown("**Serum Creatinine (mg/dL)**")
            ch_scr = alt.Chart(scr.rename(columns={"timestamp": "time", "value": "scr"})).mark_line(point=True).encode(
                x=alt.X("time:T", title="Time"), y=alt.Y("scr:Q", title="mg/dL")
            )
            st.altair_chart(ch_scr, use_container_width=True)
        if not uo.empty:
            st.markdown("**Urine Output (mL/kg/h)**")
            ch_uo = alt.Chart(uo.rename(columns={"timestamp": "time", "value": "uo"})).mark_line(point=True).encode(
                x=alt.X("time:T", title="Time"), y=alt.Y("uo:Q", title="mL/kg/h")
            )
            st.altair_chart(ch_uo, use_container_width=True)

st.markdown("---")

# ================== Questions & Saving ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions (Narrative Only)")
    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio("Did the note writer think the patient had AKI?", ["Yes", "No"], horizontal=True)
        q_rationale = st.text_area("Please provide a brief rationale.", height=140)
        q_conf = st.slider("How confident are you? (1–5)", 1, 5, 3)
        submitted1 = st.form_submit_button("Save Step 1 ✅")

    if submitted1:
        try:
            row = {
                "timestamp_utc": datetime.utcnow().isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 1,
                "q_aki": q_aki,
                "q_highlight": json.dumps(st.session_state[hl_key], ensure_ascii=False),
                "q_rationale": q_rationale,
                "q_confidence": q_conf,
                "q_reasoning": ""
            }
            try:
                append_dict(ws_resp, row, headers=st.session_state.resp_headers)
            except Exception as e:
                st.error(f"Saving to Google Sheets failed: {e}")
                st.stop()

            st.success("Saved Step 1.")
            st.session_state.step = 2
            st.session_state.jump_to_top = True
            _scroll_top()
            time.sleep(0.25)
            _rerun()
        finally:
            pass
else:
    st.subheader("Step 2 — Questions (Full Context)")
    with st.form("step2_form", clear_on_submit=False):
        q_aki2 = st.radio("Given all info, did this patient have AKI?", ["Yes", "No"], horizontal=True)
        q_reasoning = st.text_area("Describe your reasoning process.", height=180)
        submitted2 = st.form_submit_button("Save Step 2 ✅ (Next case)")

    if submitted2:
        try:
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
            try:
                append_dict(ws_resp, row, headers=st.session_state.resp_headers)
            except Exception as e:
                st.error(f"Saving to Google Sheets failed: {e}")
                st.stop()

            st.success("Saved Step 2.")
            st.session_state.step = 1
            st.session_state.case_idx += 1
            st.session_state.jump_to_top = True
            _scroll_top()
            time.sleep(0.25)
            _rerun()
        finally:
            pass

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
