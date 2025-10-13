def inline_highlighter(text: str, case_id: str, step_key: str, height: int = 560):
    """
    One-box highlighter rendered as the *actual* discharge summary text.
    Uses the original `text` (rawText) as canonical source so **bold** -> <strong>
    is reconstructed on every render. Restores saved <mark> highlights from the
    query param when present and preserves bold when re-rendering.
    """
    noscript_text = _py_html.escape(text)
    qp_key = f"hl_{step_key}_{case_id}"

    # Safely JSON-encode the two dynamic values we must inject into JS.
    raw_text_json = json.dumps(text)
    qp_key_json = json.dumps(qp_key)

    code = (
        """
    <div style="font-family: system-ui,-apple-system,Segoe UI,Roboto,Helvetica,Arial; line-height:1.55;">
      <div style="display:flex;gap:8px;margin-bottom:8px;">
        <button id="addBtn" type="button">Highlight</button>
        <button id="clearBtn" type="button">Clear</button>
      </div>

      <!-- The actual discharge summary text (one box only) -->
      <div id="text"
           style="border:1px solid #bbb;border-radius:10px;padding:14px;white-space:pre-wrap;overflow-y:auto;
                  max-height:""" + str(height) + """px; width:100%; box-sizing:border-box;">
        """ + noscript_text + """
      </div>

      <script>
        // canonical original text injected from Python (keeps ** markers intact)
        const rawText = """ + raw_text_json + """;

        const textEl = document.getElementById('text');
        const addBtn = document.getElementById('addBtn');
        const clearBtn = document.getElementById('clearBtn');
        const qpKey = """ + qp_key_json + """;
        let ranges = []; // array of {start, end} offsets relative to rawText

        function escapeHtml(s) {
          return s.replaceAll('&','&amp;').replaceAll('<','&lt;')
                  .replaceAll('>','&gt;').replaceAll('"','&quot;')
                  .replaceAll("'",'&#039;');
        }

        // Minimal markdown: **bold** -> <strong>bold</strong> (after escaping)
        function renderFragment(s) {
          const esc = escapeHtml(s);
          return esc.replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>');
        }

        // Merge overlapping/adjacent ranges
        function merge(rs) {
          if (!rs.length) return rs;
          rs.sort((a,b)=>a.start-b.start);
          const out=[{start: rs[0].start, end: rs[0].end}];
          for (let i=1;i<rs.length;i++) {
            const last=out[out.length-1], cur=rs[i];
            if (cur.start <= last.end) last.end=Math.max(last.end, cur.end);
            else out.push({start: cur.start, end: cur.end});
          }
          return out;
        }

        // Compute selection offsets relative to the canonical rawText.
        function selectionOffsets() {
          const sel = window.getSelection();
          if (!sel || sel.rangeCount===0) return null;
          const rng = sel.getRangeAt(0);
          if (!textEl.contains(rng.startContainer) || !textEl.contains(rng.endContainer)) return null;
          const pre = document.createRange();
          pre.setStart(textEl, 0);
          pre.setEnd(rng.startContainer, rng.startOffset);
          const start = pre.toString().length;
          const len = rng.toString().length;
          return len > 0 ? {start: start, end: start + len} : null;
        }

        // Convert saved HTML (with <mark>) into ranges relative to rawText
        function parseRangesFromSavedHTML(savedHTML) {
          try {
            const temp = document.createElement('div');
            temp.innerHTML = savedHTML;
            const out = [];
            let idx = 0;

            function walk(node) {
              if (node.nodeType === Node.TEXT_NODE) {
                idx += node.nodeValue.length;
              } else if (node.nodeType === Node.ELEMENT_NODE) {
                const tag = node.tagName ? node.tagName.toLowerCase() : '';
                if (tag === 'mark') {
                  const start = idx;
                  for (let i=0;i<node.childNodes.length;i++) walk(node.childNodes[i]);
                  const end = idx;
                  out.push({start: start, end: end});
                } else {
                  for (let i=0;i<node.childNodes.length;i++) walk(node.childNodes[i]);
                }
              }
            }

            walk(temp);
            return out;
          } catch (e) {
            return [];
          }
        }

        // Render function: ALWAYS uses rawText as source so markdown conversion is consistent
        function render() {
          const txt = rawText;

          if (!ranges.length) {
            textEl.innerHTML = renderFragment(txt);
          } else {
            const rs = ranges.slice().sort((a,b)=>a.start-b.start);
            let html = '', cur = 0;
            for (const r of rs) {
              const s = Math.max(0, Math.min(txt.length, r.start));
              const e = Math.max(0, Math.min(txt.length, r.end));
              html += renderFragment(txt.slice(cur, s));
              html += '<mark>' + renderFragment(txt.slice(s, e)) + '</mark>';
              cur = e;
            }
            html += renderFragment(txt.slice(cur));
            textEl.innerHTML = html;
          }
          syncToUrl();
        }

        // Save current innerHTML to parent's URL query param (encoded)
        function syncToUrl() {
          try {
            const html = textEl.innerHTML;
            const u = new URL(window.parent.location.href);
            u.searchParams.set(qpKey, encodeURIComponent(html));
            window.parent.history.replaceState(null, '', u.toString());
          } catch(e) { /* ignore */ }
        }

        // Hook save buttons in parent so we sync right before save clicks
        const hookSave = () => {
          try {
            const btns = window.parent.document.querySelectorAll('button');
            btns.forEach(b => {
              if (b.__hl_hooked__) return;
              const t = (b.textContent||'');
              if (t.includes('Save Step 1') || t.includes('Save Step 2')) {
                b.__hl_hooked__ = true;
                b.addEventListener('click', () => syncToUrl(), {capture:true});
              }
            });
          } catch(e) {}
        };

        try {
          const mo = new MutationObserver(hookSave);
          mo.observe(window.parent.document.body, {childList:true, subtree:true});
          hookSave();
        } catch(e) {}

        // Wire up add/clear
        addBtn.onclick = () => {
          const off = selectionOffsets();
          if (!off) return;
          ranges.push(off);
          ranges = merge(ranges);
          render();
        };
        clearBtn.onclick = () => {
          ranges = [];
          render();
        };

        // Initialization: if URL already contains saved HTML, try to restore ranges from it.
        (function init() {
          try {
            const u = new URL(window.parent.location.href);
            const saved = u.searchParams.get(qpKey);
            if (saved) {
              let decoded = saved;
              try { decoded = decodeURIComponent(saved); } catch (e) {}
              const parsed = parseRangesFromSavedHTML(decoded);
              if (parsed && parsed.length) {
                ranges = merge(parsed);
                render();
                return;
              } else {
                textEl.innerHTML = decoded;
                return;
              }
            }
          } catch (e) { /* ignore */ }

          // default: no saved highlights — render from canonical raw text
          render();
        })();
      </script>
    </div>
    """
    )

    _html(code, height=height + 70)
