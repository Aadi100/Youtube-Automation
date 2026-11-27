/* Shared page helpers: icons, video cards, status labels. */
"use strict";
/* ------------------------------------------------------------ shared page helpers */
Object.assign(ICON, {
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  alert: '<path d="M12 8v5M12 17h.01"/><path d="M10.3 3.9L2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
  globeok: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16 9.5"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  inbox: '<path d="M3 13l3-8h12l3 8v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M3 13h5l1 3h6l1-3h5"/>',
});
const AUDIO_LABEL = {replace: "AI commentary + music (original muted)", bed: "Original audio under music", original: "Original audio, untouched"};
const kindLabel = k => k === "compilation" ? "Compilation" : "Short";
const STATUS_LABEL = {rendered: "Rendered", uploaded: "Unlisted", public: "Public", declined: "Declined", failed: "Failed", discarded: "Discarded"};
const sbadge = s => `<span class="badge ${esc(s)}">${esc(STATUS_LABEL[s] || s)}</span>`;
const emptyState = (icon, title, text) => `<div class="empty"><span class="ic">${svg(icon)}</span><b>${title}</b><div>${text || ""}</div></div>`;
const relTime = ms => { const m = Math.max(0, Math.round(ms / 60000)); return m < 60 ? `${m} min` : m < 1440 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 1440)} d`; };

const UPLOAD_NOTE = {hold: "Waiting for you: check it, choose the audio, then upload it", queued: "Waiting for an upload slot", uploading: "Uploading to YouTube…", needs_youtube: "Connect YouTube in Settings to upload", error: "Upload failed: open it for details"};
const RISK_LABEL = {low: "Low risk", medium: "Medium risk", high: "High risk"};
const riskChip = r => r && r.level !== "low" ? `<span class="rchip ${r.level}" title="How likely YouTube is to treat this as reused content">${RISK_LABEL[r.level]}</span>` : "";
const riskAsk = (v, q) => v && v.risk && v.risk.level === "high" ? `Careful: this video looks like reused content (risk ${v.risk.score} of 100).\n\n${(v.risk.reasons[0] || {}).text || ""}\n${(v.risk.reasons[0] || {}).fix ? "Tip: " + v.risk.reasons[0].fix + "\n" : ""}\n${q}` : q;
const pct = x => x === null || x === undefined ? "-" : `${Math.round(x * (x <= 1 ? 100 : 1))}%`;
const secs = x => x === null || x === undefined ? "-" : `${Math.round(x)} s`;
function resultsBox(v) {
  const r = v.results; if (!r) return "";
  return `<div class="dsec"><h3>Results from YouTube</h3><div class="resgrid">
    <div><b>${(r.views || 0).toLocaleString()}</b><span>views</span></div><div><b>${r.avp === null || r.avp === undefined ? "-" : Math.round(r.avp) + "%"}</b><span>of the video watched on average</span></div>
    <div><b>${r.stayed === null || r.stayed === undefined ? "-" : Math.round(r.stayed * 100) + "%"}</b><span>stayed to watch</span></div><div><b>${secs(r.avd)}</b><span>average watch time</span></div>
    <div><b>${r.likes || 0}</b><span>likes</span></div><div><b>${r.shares || 0}</b><span>shares</span></div></div>
    <p class="muted" style="margin:8px 0 0">"Stayed to watch" is the share of views that went past the first moments. The studio learns from these numbers (Learning Lab).</p></div>`;
}
function riskBox(v) {
  const r = v.risk; if (!r) return "";
  return `<div class="dsec"><h3>Reused-content risk <span class="rchip ${r.level}">${RISK_LABEL[r.level]} · ${r.score}/100</span></h3>
    <p class="muted" style="margin:2px 0 6px">YouTube can refuse to pay for, or remove, videos made mostly from other people's footage. This is advice from simple rules, not YouTube's decision.</p>
    ${r.reasons.length ? `<ul class="rlist">${r.reasons.map(x => `<li>${esc(x.text)}<div class="rfix">What to do: ${esc(x.fix)}</div></li>`).join("")}</ul>` : ""}
    ${r.good.length ? `<ul class="rlist">${r.good.map(x => `<li style="color:var(--ok)">✓ ${esc(x)}</li>`).join("")}</ul>` : ""}
    <p class="muted" style="margin:8px 0 0">Got a creator's permission? <a href="#/permissions">Write it down</a> and the score goes down.${v.risk_held ? " This video was held back from automatic upload because of its risk." : ""}</p></div>`;
}
function vcard(v) {
  const wide = v.kind === "compilation";
  return `<article class="vc" data-v="${v.id}" tabindex="0"><div class="vc-img ${wide ? "wide" : ""}"><img loading="lazy" src="/media/${v.id}/thumb" alt="">${sbadge(v.status)}</div>
    <div class="vc-body"><div class="vc-title">${esc(v.title)}</div><div class="muted vc-meta">${esc(v.game_name || "")} · ${kindLabel(v.kind)} · ${when(v.created_at)} ${riskChip(v.risk)}</div>
    ${v.status === "rendered" && (UPLOAD_NOTE[v.upload_status] || v.upload_wait) ? `<div class="upnote ${v.upload_status}">${esc(v.upload_status === "queued" && v.upload_wait ? v.upload_wait : UPLOAD_NOTE[v.upload_status])}</div>` : ""}</div></article>`;
}
function bindVcards(root) {
  root.querySelectorAll(".vc[data-v]").forEach(el => { el.onclick = () => openVideo(el.dataset.v); el.onkeydown = e => { if (e.key === "Enter") openVideo(el.dataset.v); }; });
}

