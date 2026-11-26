/* Helpers every page uses: $, esc, api(), toasts, the pickers. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const when = iso => iso ? new Date(iso).toLocaleString([], {dateStyle: "medium", timeStyle: "short"}) : "-";

async function api(path, opt = {}) {
  const o = {method: opt.method || "GET", headers: {"X-Requested-With": "studio"}};
  if (opt.body !== undefined) {
    if (opt.raw) { o.body = opt.body; } else { o.body = JSON.stringify(opt.body); o.headers["Content-Type"] = "application/json"; }
  }
  const r = await fetch(path, o);
  const data = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.startsWith("/api/auth/")) { showAuth(); throw new Error(data.error || "Please log in"); }
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}
function toast(msg, err) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : ""); t.textContent = msg; document.body.appendChild(t);
  setTimeout(() => t.remove(), err ? 6000 : 3000);
}
const guard = fn => async (...a) => { try { await fn(...a); } catch (e) { toast(e.message, true); } };
const badge = s => `<span class="badge ${esc(s)}">${esc(s)}</span>`;

let timer = null, activeJob = null;
function stopTimer() { if (timer) clearInterval(timer); timer = null; }

/* ------------------------------------------------------------ pickers: every short list becomes chips or tiles, every time list becomes pills
   The real <select> / <input> stays in the page (hidden), so each page's own code keeps reading and writing the same values. */
(function () {
  for (const proto of [HTMLSelectElement.prototype, HTMLInputElement.prototype]) {       // a value set by code (no event) still redraws the picker
    const d = Object.getOwnPropertyDescriptor(proto, "value");
    Object.defineProperty(proto, "value", {get() { return d.get.call(this); }, set(v) { d.set.call(this, v); this.dispatchEvent(new Event("pkrefresh")); }, configurable: true});
  }
  const OFF = ".edm, .tsm, .tsbox, [hidden], .nopk";
  const split = t => { const m = t.match(/^([^:(]{2,34}?)\s*[:(]\s*(.*?)\)?$/); return m ? [m[1].trim(), m[2].trim()] : [t.trim(), ""]; };
  const enhanceSelect = sel => {
    if (sel.dataset.pk || sel.multiple || sel.closest(OFF)) return;
    const n = sel.options.length; if (n < 2 || n > 7) return;
    sel.dataset.pk = "1";
    const longest = Math.max(...[...sel.options].map(o => o.textContent.trim().length));
    const tiles = longest > 30;
    const box = document.createElement("div"); box.className = tiles ? "pkgrid auto" : "pkbar"; box.setAttribute("role", "radiogroup");
    sel.style.display = "none"; sel.after(box);
    const render = () => {
      box.innerHTML = [...sel.options].map(o => {
        const on = o.value === sel.value, t = o.textContent.trim();
        if (!tiles) return `<button type="button" class="pkc ${on ? "on" : ""}" data-v="${esc(o.value)}" role="radio" aria-checked="${on}">${esc(t)}</button>`;
        const [a, b] = split(t);
        return `<button type="button" class="pk ${on ? "on" : ""}" data-v="${esc(o.value)}" role="radio" aria-checked="${on}"><b>${esc(a)}</b>${b ? `<span>${esc(b)}</span>` : ""}</button>`;
      }).join("");
    };
    box.addEventListener("click", e => { const b = e.target.closest("[data-v]"); if (!b) return; sel.value = b.dataset.v; sel.dispatchEvent(new Event("change", {bubbles: true})); });
    sel.addEventListener("change", render); sel.addEventListener("pkrefresh", render);
    new MutationObserver(render).observe(sel, {childList: true, subtree: true});
    render();
  };
  const enhanceTimes = inp => {
    if (inp.dataset.pk || inp.closest(OFF)) return;
    inp.dataset.pk = "1"; inp.style.display = "none";
    const box = document.createElement("div"); box.className = "pktimes"; inp.after(box);
    const list = () => [...new Set((inp.value.match(/\b\d{1,2}:\d{2}\b/g) || []).map(t => t.padStart(5, "0")))].sort();
    const render = () => {
      box.innerHTML = list().map(t => `<span class="pkt">${t}<b data-x="${t}" title="Remove">×</b></span>`).join("") +
        `<span class="pktadd"><input type="time" class="pkt-in" aria-label="Add a time"><button type="button" class="pkt-go">Add time</button></span>`;
    };
    box.addEventListener("click", e => {
      const x = e.target.closest("[data-x]");
      if (x) { inp.value = list().filter(t => t !== x.dataset.x).join(", "); return; }
      if (e.target.closest(".pkt-go")) { const v = box.querySelector(".pkt-in").value; if (v) inp.value = [...list(), v].join(", "); }
    });
    inp.addEventListener("pkrefresh", render); render();
  };
  const scan = () => {
    const main = document.getElementById("main"); if (!main) return;
    main.querySelectorAll("select:not([data-pk])").forEach(enhanceSelect);
    main.querySelectorAll("input[data-times]:not([data-pk])").forEach(enhanceTimes);
  };
  let queued = false;
  new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; scan(); }); } }).observe(document.getElementById("main"), {childList: true, subtree: true, attributes: true, attributeFilter: ["hidden"]});
})();

