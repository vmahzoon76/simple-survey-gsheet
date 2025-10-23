
import os
import json
import time
from datetime import datetime
import pytz
from datetime import datetime
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
# anchor element so hash/focus-based scrolling has a reliable target
st.markdown('<div id="top" tabindex="-1"></div>', unsafe_allow_html=True)
if not st.session_state.get("entered", False):
    st.markdown(
        """
        ##  Instruction
        **Before starting: Please review the [slides here](https://tuprd-my.sharepoint.com/:p:/g/personal/tun53200_temple_edu/ETBC7JRhTf5LpN3JaySbyzEBEwHTP3ihMnpl4fYDM740HQ?e=NC7uxc) to get familiar with the protocols for this study.**
        """
    )

# -------------------- Helpers --------------------
import re

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
    age_s     = _fmt_num(age)
    gender_s  = _fmt_gender(gender)
    weight_s  = _fmt_num(weight)

    parts = []
    if gender_s: parts.append(gender_s.lower())     # “female” / “male”
    if age_s:    parts.append(f"age {age_s}")
    if weight_s: parts.append(f"weight {weight_s} kg")

    if parts:
        core = ", ".join(parts)
        return f"This admission is related to a patient ({core})."
    else:
        return "This admission is related to a patient."


def _build_intervals_hours(admit_ts, disch_ts, edreg_ts, edout_ts, icu_in_ts, icu_out_ts):
    """
    Return (intervals_df, horizon_hours) where intervals_df has columns:
      label ('ED'/'ICU'), start (hours), end (hours)
    All intervals are clipped to [0, horizon].
    If admit/discharge missing/invalid, returns (empty_df, None).
    """
    if pd.isna(admit_ts) or pd.isna(disch_ts) or (disch_ts < admit_ts):
        return pd.DataFrame(columns=["label" ,"start" ,"end"]), None

    horizon_hours = (disch_ts - admit_ts).total_seconds() / 3600.0

    def _to_hours(ts):
        if pd.isna(ts):
            return None
        return (ts - admit_ts).total_seconds() / 3600.0

    raw = []
    # ED band
    s, e = _to_hours(edreg_ts), _to_hours(edout_ts)
    if s is not None:
        e = horizon_hours if e is None else e
        if e is not None:
            if e < s: s, e = e, s
            raw.append(("ED", s, e))
    # ICU band
    s, e = _to_hours(icu_in_ts), _to_hours(icu_out_ts)
    if s is not None:
        e = horizon_hours if e is None else e
        if e is not None:
            if e < s: s, e = e, s
            raw.append(("ICU", s, e))

    # Clip to [0, horizon]
    clipped = []
    for lbl, s, e in raw:
        s2 = max(0.0, s)
        e2 = min(horizon_hours, e)
        if e2 > s2:  # keep only positive-length ranges
            clipped.append((lbl, s2, e2))

    return pd.DataFrame(clipped, columns=["label" ,"start" ,"end"]), horizon_hours


def _strip_strong_only(html: str) -> str:
    """Remove <strong> (and <b>) tags but keep everything else, esp. <mark>."""
    if not isinstance(html, str):
        return ""
    # remove closing first, then opening; allow spaces/attrs just in case
    html = re.sub(r'<\s*/\s*(?:strong|b)\s*>', '', html, flags=re.IGNORECASE)
    html = re.sub(r'<\s*(?:strong|b)(?:\s+[^>]*)?>', '', html, flags=re.IGNORECASE)
    return html

def _hours_to_int(col: pd.Series) -> pd.Series:
    # Round to nearest hour and keep NA friendly
    s = pd.to_numeric(col, errors="coerce")
    return s.round().astype("Int64")  # Pandas nullable int so NaN stays blank


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
        // Render once with **bold** -> <strong>
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

        // Merge adjacent <mark> siblings for clean HTML
        function mergeAdjacentMarks(root) {{
          const marks = root.querySelectorAll('mark');
          for (let i = 0; i < marks.length; i++) {{
            const m = marks[i];
            // Merge next sibling if it's also a mark
            while (m.nextSibling && m.nextSibling.nodeType === 1 && m.nextSibling.tagName === 'MARK') {{
              const next = m.nextSibling;
              // move all children of next into m
              while (next.firstChild) m.appendChild(next.firstChild);
              next.remove();
            }}
            // If mark wrapped empty, unwrap
            if (!m.textContent) {{
              const p = m.parentNode;
              p && p.removeChild(m);
            }}
          }}
        }}

        // Clear: unwrap all <mark> nodes
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

          // Only work if selection is inside our box
          if (!textEl.contains(rng.startContainer) || !textEl.contains(rng.endContainer)) return;
          if (rng.collapsed) return; // nothing selected

          try {{
            // Clone the exact selection contents
            const frag = rng.extractContents(); // removes selection from DOM and collapses range
            // Wrap it with <mark> and insert back at the original position
            const mark = document.createElement('mark');
            mark.appendChild(frag);
            rng.insertNode(mark);

            // Normalize: join adjacent marks produced by consecutive selections
            mergeAdjacentMarks(textEl);

            // Optional: clear selection to avoid accidental re-wrapping
            sel.removeAllRanges();

            syncToUrl();
          }} catch (e) {{
            // If selection crosses disallowed boundaries, fall back: do nothing silently
            // (extractContents can throw for malformed ranges)
            console.warn('Highlight error:', e);
          }}
        }};

        document.getElementById('clearBtn').onclick = () => {{
          clearMarks(textEl);
          syncToUrl();
        }};

        // Final sync before save buttons
        const hookSave = () => {{
          try {{
            const btns = window.parent.document.querySelectorAll('button');
            btns.forEach(b => {{
              if (b.__hl_hooked__) return;
              const t = (b.textContent||'');
              if (t.includes('Save Step 1') || t.includes('Save Step 2')) {{
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
    _html(code, height=height + 70)






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
        raise RuntimeError \
            ("Google Sheets client not available. Ensure Secrets/service_account or service_account.json is present.")

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

        # --- Forgot ID: show known reviewers from 'responses' sheet ---
    st.divider()
    if st.button("Forgot your ID?"):
        try:
            sh = _open_sheet_cached()  # uses st.secrets['gsheet_id']
            try:
                ws = _retry_gs(sh.worksheet, "responses")
            except RuntimeError:
                st.warning("No 'responses' sheet found yet.")
            else:
                recs = _retry_gs(ws.get_all_records)
                df = pd.DataFrame(recs)

                if df.empty or "reviewer_id" not in df.columns:
                    st.info("No reviewers have submitted responses yet.")
                else:
                    # Clean and summarize
                    df["timestamp_et"] = pd.to_datetime(df.get("timestamp_et"), errors="coerce")
                    df["reviewer_id"] = df["reviewer_id"].astype(str).str.strip()

                    grp = (
                        df.loc[df["reviewer_id"] != ""]
                        .groupby("reviewer_id", as_index=False)
                        .agg(submissions=("reviewer_id", "size"),
                             last_seen=("timestamp_et", "max"))
                    )
                    grp = grp.sort_values(["submissions", "last_seen"], ascending=[False, False])

                    st.caption("Known reviewers (from Responses):")
                    st.dataframe(grp, use_container_width=True, hide_index=True)
        except Exception as e:
            st.error(f"Could not load reviewers: {e}")


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
adm_headers = [
    "case_id", "title", "hadm_id", "PT", "DS", "weight",
    "age", "gender",   # <-- add these two
    "admittime", "dischtime", "edregtime", "edouttime", "intime", "outtime"
]

labs_headers = ["case_id", "timestamp", "kind", "value", "unit"]
resp_headers = [
    "timestamp_et", "reviewer_id", "case_id", "step",
    "aki",                     # "Yes"/"No"
    "highlight_html",          # <mark>...</mark> from this step
    "rationale",               # free-text rationale (Step 1) or empty on Step 2
    "confidence",              # 1–5 for both steps
    "reasoning",               # think-aloud (Step 2) or empty on Step 1
    "aki_etiology",            # Step 2 only when aki == "Yes"
    "aki_stage",               # Step 2 only when aki == "Yes"
    "aki_onset_explanation"    # Step 2 only when aki == "Yes"
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

admissions = _read_ws_df(st.secrets["gsheet_id"], "admissions")
labs = _read_ws_df(st.secrets["gsheet_id"], "labs")
responses = _read_ws_df(st.secrets["gsheet_id"], "responses")

# Parse all relevant times
for _c in ["admittime", "dischtime", "edregtime", "edouttime", "intime", "outtime"]:
    if _c in admissions.columns:
        admissions[_c] = pd.to_datetime(admissions[_c], errors="coerce")

labs["timestamp"] = pd.to_datetime(labs["timestamp"], errors="coerce")




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
        step1_only_ids = set \
            (resp.loc[resp["step"] == 1, "case_id"].astype(str)) - completed_ids if not resp.empty else set()

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
case_id   = str(case.get("case_id", ""))
title     = str(case.get("title", ""))
summary  = str(case.get("DS", ""))   # Step 1 text
PT  = str(case.get("PT", ""))   # Step 2 text
weight    = case.get("weight", "")
admit_ts  = case.get("admittime")           # pandas.Timestamp or NaT
# Additional timestamps for shading/axis
disch_ts  = case.get("dischtime")
edreg_ts  = case.get("edregtime")
edout_ts  = case.get("edouttime")
icu_in_ts = case.get("intime")
icu_out_ts= case.get("outtime")
age       = case.get("age", "")             # <-- new
gender    = case.get("gender", "")          # <-- new



st.caption(
    f"Reviewer: **{st.session_state.reviewer_id}** • "
    f"Admission {st.session_state.case_idx + 1}/{len(admissions)} • "
    f"Step {st.session_state.step}/2"
)
st.markdown(f"### {case_id} — {title}")

# Filter labs for this case
case_labs = labs[labs["case_id"].astype(str) == case_id].copy()

# timestamp should already be datetime, but this is harmless if it is
case_labs["timestamp"] = pd.to_datetime(case_labs["timestamp"], errors="coerce")

# Compute hours since admission (will be NaN if admittime is missing)
if pd.notna(admit_ts):
    case_labs["hours"] = (case_labs["timestamp"] - admit_ts).dt.total_seconds() / 3600.0
else:
    case_labs["hours"] = pd.NA

# Normalize kind for filtering, retain original for display
case_labs["_kind_lower"] = case_labs["kind"].astype(str).str.lower()

scr = case_labs[case_labs["_kind_lower"] == "scr"].sort_values("timestamp").copy()
uo  = case_labs[case_labs["_kind_lower"] != "scr"].sort_values("timestamp").copy()



# ================== Layout ==================
left, right = st.columns([5, 4], gap="large")

with left:
    st.markdown("**Discharge Summary (highlight directly in the text below)**")
    if st.session_state.step == 1:
        inline_highlighter(summary, case_id=case_id, step_key="step1", height=700)
    else:
        inline_highlighter(summary, case_id=case_id, step_key="step2", height=700)




with right:
    if st.session_state.step == 1:
        st.info("Step 1: Narrative only. Do not use structured data.")
    else:
        st.info("Step 2: Summary + Figures + Tables")
        import altair as alt
        blurb = make_patient_blurb(age, gender, weight)
        st.markdown(f"> {blurb} Click on a tab below to explore each visualization.")

        # --- Tabs for four visualizations ---
        tabs = st.tabs([
            "Serum Creatinine (SCr)",
            # "Urine Output (UO)",
            # "Intake / Output",
            "Procedures"
        ])

        # -------- Tab 1: Serum Creatinine --------
        with tabs[0]:
            st.markdown("**Serum Creatinine (mg/dL)**")
            if not scr.empty:
                src = scr.rename(columns={"value": "scr_value"}).copy()
                intervals_df, horizon_hours = _build_intervals_hours(
                    admit_ts, disch_ts, edreg_ts, edout_ts, icu_in_ts, icu_out_ts
                )
                if (horizon_hours is not None) and (src["hours"].notna().any()):
                    max_tick = int(np.ceil(horizon_hours / 24.0) * 24)
                    tick_vals = list(np.arange(0, max_tick + 1, 24))
                    line = alt.Chart(src).mark_line(point=True).encode(
                        x=alt.X("hours:Q",
                                title="Hours since admission",
                                scale=alt.Scale(domain=[0, horizon_hours]),
                                axis=alt.Axis(values=tick_vals)),
                        y=alt.Y("scr_value:Q", title="Serum Creatinine (mg/dL)"),
                        tooltip=["timestamp:T", "hours:Q", "scr_value:Q", "unit:N", "kind:N"]
                    )
                    if not intervals_df.empty:
                        shade = alt.Chart(intervals_df).mark_rect(opacity=0.25).encode(
                            x="start:Q", x2="end:Q",
                            color=alt.Color("label:N", legend=alt.Legend(title="Care setting"),
                                            scale=alt.Scale(domain=["ED", "ICU"], range=["#fde68a", "#bfdbfe"]))
                        )
                        st.altair_chart(alt.layer(line, shade).resolve_scale(color='independent'), use_container_width=True)
                    else:
                        st.altair_chart(line, use_container_width=True)
                else:
                    st.altair_chart(
                        alt.Chart(src).mark_line(point=True).encode(
                            x="timestamp:T", y="scr_value:Q", tooltip=["timestamp:T", "scr_value:Q"]
                        ),
                        use_container_width=True,
                    )
            else:
                st.warning("No SCr values for this case.")

        # # -------- Tab 2: Urine Output --------
        # with tabs[1]:
        #     st.markdown("**Urine Output (mL)** — available during ICU only")
        #     if not uo.empty:
        #         uox = uo.rename(columns={"value": "uo_value"})
        #         if pd.notna(admit_ts) and uox["hours"].notna().any():
        #             ch_uo = alt.Chart(uox).mark_line(point=True).encode(
        #                 x="hours:Q", y="uo_value:Q", tooltip=["timestamp:T", "hours:Q", "uo_value:Q"]
        #             )
        #         else:
        #             ch_uo = alt.Chart(uox).mark_line(point=True).encode(
        #                 x="timestamp:T", y="uo_value:Q", tooltip=["timestamp:T", "uo_value:Q"]
        #             )
        #         st.altair_chart(ch_uo, use_container_width=True)
        #     else:
        #         st.warning("No UO values for this case.")

        # -------- Tab 3: Intake / Output --------
        # with tabs[1]:
        #     st.markdown("**Intake and Output Balance (per time interval)**")
        #     try:
        #         inout = _read_ws_df(st.secrets["gsheet_id"], "inout")
        #         if not inout.empty:
        #             inout_case = inout[inout["case_id"].astype(str) == case_id].copy()
        #             if not inout_case.empty:
        #                 inout_case["day_start"] = pd.to_datetime(inout_case["day_start"], errors="coerce")
        #                 inout_case["day_end"]   = pd.to_datetime(inout_case["day_end"], errors="coerce")
        #                 if pd.notna(admit_ts):
        #                     inout_case["start_hr"] = ((inout_case["day_start"] - admit_ts).dt.total_seconds()/3600).round().astype("Int64")
        #                     inout_case["end_hr"]   = ((inout_case["day_end"] - admit_ts).dt.total_seconds()/3600).round().astype("Int64")
        #                 inout_case["intake_ml"] = inout_case["intake_ml"].astype(float).abs()
        #                 inout_case["output_ml"] = -inout_case["output_ml"].astype(float).abs()
        #                 inout_case["interval"] = inout_case["start_hr"].astype(str) + "–" + inout_case["end_hr"].astype(str)
        #                 df_plot = inout_case.melt(
        #                     id_vars=["interval"], value_vars=["intake_ml", "output_ml"],
        #                     var_name="Type", value_name="mL"
        #                 ).replace({"Type": {"intake_ml": "Intake (mL)", "output_ml": "Output (mL)"}})
        #                 ch_inout = (
        #                     alt.Chart(df_plot).mark_bar().encode(
        #                         x=alt.X("interval:N", title="Interval (hours since admission)", axis=alt.Axis(labelAngle=45)),
        #                         y=alt.Y("mL:Q", title="mL per interval", stack=None),
        #                         color=alt.Color("Type:N", scale=alt.Scale(domain=["Intake (mL)", "Output (mL)"],
        #                                                                  range=["#3b82f6", "#f97316"])),
        #                         tooltip=["interval", "Type", "mL"]
        #                     ).properties(height=320)
        #                 )
        #                 st.altair_chart(ch_inout, use_container_width=True)
        #             else:
        #                 st.info("No intake/output records for this case.")
        #         else:
        #             st.warning("Sheet 'inout' is empty.")
        #     except Exception as e:
        #         st.error(f"Could not load intake/output data: {e}")

        # -------- Tab 4: Procedures --------
        with tabs[1]:
            st.markdown("**Procedures (ICD-coded)**")
            try:
                proc = _read_ws_df(st.secrets["gsheet_id"], "proc")
                if not proc.empty:
                    proc_case = proc[proc["case_id"].astype(str) == case_id].copy()
                    if not proc_case.empty:
                        proc_case["chartdate"] = pd.to_datetime(proc_case["chartdate"], errors="coerce")
                        if pd.notna(admit_ts):
                            proc_case["days_since_admit"] = np.clip(
                                np.floor((proc_case["chartdate"] - admit_ts).dt.total_seconds()/(24*3600)), 0, None
                            ).astype("Int64")
                        proc_case = proc_case[["chartdate", "days_since_admit", "icd_code", "long_title"]].rename(
                            columns={
                                "chartdate": "Date",
                                "days_since_admit": "Days After Admission",
                                "icd_code": "ICD Code",
                                "long_title": "Procedure Description",
                            }
                        )
                        st.dataframe(proc_case.sort_values("Date"), use_container_width=True, hide_index=True)
                    else:
                        st.info("No procedures recorded for this case.")
                else:
                    st.warning("Procedure sheet ('proc') is empty.")
            except Exception as e:
                st.error(f"Could not load procedures: {e}")


        




st.markdown("---")

# ================== Questions & Saving ==================
if st.session_state.step == 1:
    st.subheader("Step 1 — Questions")

    with st.form("step1_form", clear_on_submit=False):
        q_aki = st.radio(
            "Based on the discharge summary, do you think the note writers thought the patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q1_aki"
        )

        # Bring back rationale
        q_rationale = st.text_area(
            "Please provide a brief rationale for your assessment. Please also highlight in the note any specific text that impacted your conclusion.",
            height=140, key="q1_rationale"
        )

        q_conf = st.radio(
            "Confidence (choose 1–5)",
            options=[1, 2, 3, 4, 5],
            index=2,  # default = 3
            horizontal=True,
            key="q1_conf",
        )



        submitted1 = st.form_submit_button("Save Step 1 ✅", disabled=st.session_state.get("saving1", False))

    if submitted1:
        try:
            st.session_state.saving1 = True

            # Read Step-1 highlights
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
                "confidence": q_conf,
                "reasoning": "",
                "aki_etiology": "",
                "aki_stage": "",
                "aki_onset_explanation": ""
            }
            append_dict(ws_resp, row, headers=st.session_state.resp_headers)

            # Clear Step-1 param so it won’t bleed anywhere
            try:
                st.query_params.pop(qp_key, None)
            except Exception:
                st.query_params.clear()

            st.success("Saved Step 1.")
            st.session_state.step = 2
            st.session_state.jump_to_top = True
            _scroll_top(); time.sleep(0.25); _rerun()
        finally:
            st.session_state.saving1 = False








else:
    st.subheader("Step 2 — Questions (Full Context)")

    # Proactively clear any leftover Step-1 highlight (safety)
    try:
        st.query_params.pop(f"hl_step1_{case_id}", None)
    except Exception:
        pass
    st.markdown(
        """
        **Before you begin:**  
        Please refer to the PowerPoint [slides here](https://tuprd-my.sharepoint.com/:p:/g/personal/tun53200_temple_edu/EQnr80BiXJ5HjRu58bAOCBkBTGRBPraOny7S16-gnnLyWQ?e=uBd3Nk) for the definitions of AKI.  Use that shared definition when answering the following questions.
        """
    )
    with st.form("step2_form", clear_on_submit=False):
        
        q_aki2 = st.radio(
            "Given the info in the EHR record from this patient, do you believe this patient had AKI?",
            ["Yes", "No"], horizontal=True, key="q2_aki"
        )

        # Confidence for Step 2 as well
        q_conf2 = st.radio(
            "Confidence (choose 1–5)",
            options=[1, 2, 3, 4, 5],
            index=2,  # default = 3
            horizontal=True,
            key="q2_conf",
        )



        # Think-aloud reasoning (keep)
        q_reasoning = st.text_area(
            "Please explain the reason for your decision. Please also highlight in the note any specific text that impacted your conclusion.",
            height=180, key="q2_reasoning"
        )

        # Conditional fields if AKI == Yes
        # Conditional fields if AKI == Yes
        # Conditional fields if AKI == Yes
        # Conditional fields if AKI == Yes
        q_etiology_choice = ""
        q_etiology_expl = ""
        q_stage_choice = ""
        q_stage_expl = ""
        q_onset_exp = ""

        if q_aki2 == "Yes":
            st.markdown("**If you believe this patient had AKI, please answer the following questions:**")

            # --- Etiology: radio then explain ---
            etiology_options = ["Pre-renal", "Intrinsic (ATN)", "Intrinsic (Other)", "Post-renal(Obstruction)", "Multi-factorial"]
            q_etiology_choice = st.radio(
                "AKI etiology — What was the reason behind AKI?",
                options=etiology_options,
                horizontal=True,
                key="q2_etiology_choice",
            )
            q_etiology_expl = st.text_area(
                "Please explain how you concluded the etiology:",
                key="q2_etiology_expl",
                height=120
            )

            # --- Stage: radio then explain ---
            stage_options = ["Mild", "Moderate", "Severe"]
            q_stage_choice = st.radio(
                "AKI Severity - How severe do you think the AKI episode was?",
                options=stage_options,
                horizontal=True,
                key="q2_stage_choice",
            )
            q_stage_expl = st.text_area(
                "Please explain how you concluded the severity:",
                key="q2_stage_expl",
                height=120
            )

            # --- Onset explanation (free text) ---
            q_onset_exp = st.text_area(
                "AKI onset — When did it start, and how did you conclude it?",
                key="q2_onset_explanation",
                height=160
            )




        submitted2 = st.form_submit_button("Save Step 2 ✅ (Next case)", disabled=st.session_state.get("saving2", False))

    if submitted2:
        try:
            st.session_state.saving2 = True

            # Read Step-2 highlights
            qp_key2 = f"hl_step2_{case_id}"
            qp = st.query_params
            hl_html2 = urllib.parse.unquote(qp.get(qp_key2, "")) if qp_key2 in qp else ""
            hl_html2 = _strip_strong_only(hl_html2)

            row = {
                "timestamp_et": datetime.now(pytz.timezone("US/Eastern")).isoformat(),
                "reviewer_id": st.session_state.reviewer_id,
                "case_id": case_id,
                "step": 2,
                "aki": q_aki2,
                "highlight_html": hl_html2,
                "rationale": "",
                "confidence": q_conf2,
                "reasoning": q_reasoning,
                "aki_etiology": (f"{q_etiology_choice} — {q_etiology_expl.strip()}" if q_aki2 == "Yes" else ""),
                "aki_stage": (f"{q_stage_choice} — {q_stage_expl.strip()}" if q_aki2 == "Yes" else ""),
                "aki_onset_explanation": (q_onset_exp if q_aki2 == "Yes" else "")
            }


            append_dict(ws_resp, row, headers=st.session_state.resp_headers)

            # Clear Step-2 highlight param and advance
            try:
                st.query_params.pop(qp_key2, None)
            except Exception:
                st.query_params.clear()

            st.success("Saved Step 2.")
            st.session_state.step = 1
            st.session_state.case_idx += 1
            st.session_state.jump_to_top = True
            _scroll_top(); time.sleep(0.25); _rerun()
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
