/* Tokens and usage. */
"use strict";
/* ------------------------------------------------------------ my usage (every account) */
/* The owner has two views of the same numbers: what they used themselves, and what the whole studio used. One page, two tabs. */
function usageTabs(active) {
  if (!ME || ME.role !== "owner") return "";
  return `<div class="seg" style="margin:6px 0 14px"><a class="btn ${active === "usage" ? "on" : ""}" href="#/usage">My usage</a><a class="btn ${active === "reports" ? "on" : ""}" href="#/reports">Whole studio (reports)</a><a class="btn ${active === "stories" ? "on" : ""}" href="#/reports/stories">Story videos (studio)</a></div>`;
}

async function usage() {
  let days = 30;
  $("#main").innerHTML = `<h1>Tokens and usage</h1>${usageTabs("usage")}<div class="toolbar"><label style="margin:0">Period</label>
      <select id="mdays">${[[1, "Last 24 hours"], [7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]].map(([v, l]) => `<option value="${v}" ${v === days ? "selected" : ""}>${l}</option>`).join("")}</select>
      <span class="grow"></span><a class="btn" id="mcsv" href="#">Download CSV</a></div>
    <div class="kpis" id="mkpi"></div>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>Tokens spent per day</h2><span class="muted">UTC days.</span></div><div id="mdaily"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>What you used</h2><span class="muted">You pay only for what each video really used. A failed step or video costs nothing.</span></div><div id="mserv"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>Your videos</h2><span class="muted">The last 40. Open one to see its itemised receipt.</span></div><div id="mrec"></div></section>
    <section class="card"><div class="sechead"><h2>Token history</h2></div><div id="mled"></div></section>`;
  const num = n => Number(n).toLocaleString();
  const load = guard(async () => {
    days = +$("#mdays").value;
    const r = await api(`/api/me/report?days=${days}`), t = r.totals;
    $("#mcsv").href = `/api/me/report.csv?days=${days}`;
    const k = (ic, tone, n, l, sub) => `<div class="card kpi"><span class="ic ${tone}">${svg(ic)}</span><div><div class="n">${n}</div><div class="l">${l}${sub ? `<br><span class="muted">${sub}</span>` : ""}</div></div></div>`;
    $("#mkpi").innerHTML = (r.owner ? k("check", "ok", "Free", "Your account", "the owner is never charged") : k("check", r.balance > 0 ? "ok" : "bad", num(r.balance), "Tokens left", r.balance > 0 ? "ask the owner for more any time" : "ask the owner for more tokens")) +
      k("alert", "warn", num(r.owner ? t.would_cost : t.tokens_spent), r.owner ? "Tokens it would have cost" : "Tokens spent", "in this period") +
      k("film", "info", num(t.videos), "Videos made", t.failed ? `${t.failed} failed (not charged)` : "") +
      k("globeok", "info", t.daily_uploads === null ? `${t.uploads_today}` : `${t.uploads_today} / ${t.daily_uploads}`, "Uploads today", t.daily_uploads === null ? "no limit" : "your daily upload limit") +
      k("inbox", "info", num(t.refunded_tokens), "Tokens refunded", "failed videos and uploads");
    const mx = Math.max(1, ...r.daily.map(d => d.tokens));
    $("#mdaily").innerHTML = r.daily.some(d => d.tokens || d.videos)
      ? `<div style="display:flex;gap:${r.daily.length > 40 ? 2 : 6}px;align-items:flex-end;height:130px;overflow-x:auto;padding-top:6px">${r.daily.map(d => `
          <div title="${d.d}: ${d.videos} video(s), ${d.tokens} tokens" style="flex:1;min-width:${r.daily.length > 40 ? 6 : 22}px;display:flex;flex-direction:column;align-items:center;gap:4px">
            <div style="display:flex;align-items:flex-end;height:100px;width:100%"><div style="width:100%;background:var(--accent2);border-radius:3px 3px 0 0;height:${Math.max(2, 100 * d.tokens / mx)}px"></div></div>
            <span class="muted" style="font-size:10px">${d.d.slice(5)}</span></div>`).join("")}</div>`
      : `<p class="muted">Nothing used in this period yet.</p>`;
    $("#mserv").innerHTML = r.services.length ? `<table><tr><th>What</th><th>Used</th><th>Tokens</th></tr>${r.services.map(x => `
      <tr><td><b>${esc(x.label)}</b></td><td>${x.units != null ? `${num(x.units)} <span class="muted">${esc(x.unit)}</span>` : ""}</td><td>${x.tokens}</td></tr>`).join("")}</table>` : `<p class="muted">No usage yet. Make a video and it appears here.</p>`;
    $("#mrec").innerHTML = r.recent.length ? `<table><tr><th>Finished (UTC)</th><th>Video</th><th>Type</th><th>Status</th><th>Tokens for the video</th><th>Tokens for the upload</th><th></th></tr>${r.recent.map(v => `
      <tr><td class="muted">${when(v.when)}</td><td>${esc(v.title || "-")}</td><td>${v.kind}</td><td>${v.status === "done" ? '<span class="badge uploaded">made</span>' : '<span class="badge declined">failed</span>'}</td>
        <td>${v.status === "failed" ? '<span class="muted">not charged</span>' : (r.owner ? `<span class="muted">free (${v.would_cost})</span>` : v.tokens)}</td><td>${v.upload_tokens || '<span class="muted">-</span>'}</td>
        <td>${v.video_id ? `<a href="#" data-mv="${v.video_id}">Receipt</a>` : ""}</td></tr>`).join("")}</table>` : `<p class="muted">No videos finished in this period.</p>`;
    document.querySelectorAll("[data-mv]").forEach(a => a.onclick = e => { e.preventDefault(); openVideo(a.dataset.mv); });
    $("#mled").innerHTML = r.ledger.length ? `<table><tr><th>When</th><th>What</th><th style="text-align:right">Tokens</th><th style="text-align:right">Balance</th></tr>${r.ledger.map(l => `
      <tr><td class="muted">${when(l.t)}</td><td>${esc(l.reason)}</td><td style="text-align:right;color:var(--${l.delta >= 0 ? "ok" : "bad"})">${l.delta > 0 ? "+" : ""}${l.delta}</td><td style="text-align:right">${l.balance}</td></tr>`).join("")}</table>`
      : `<p class="muted">No token changes yet.</p>`;
  });
  $("#mdays").onchange = load;
  await load();
}


