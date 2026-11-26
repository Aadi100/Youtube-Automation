/* Reports (owner). */
"use strict";
/* ------------------------------------------------------------ reports (owner) */
async function reports() {
  let days = 7;
  $("#main").innerHTML = `<h1>Reports</h1><div class="toolbar"><label style="margin:0">Period</label>
      <select id="rdays">${[[1, "Last 24 hours"], [7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"]].map(([v, l]) => `<option value="${v}" ${v === days ? "selected" : ""}>${l}</option>`).join("")}</select>
      <span class="grow"></span><a class="btn" id="rcsv" href="#">Download CSV</a></div>
    <div class="kpis" id="rkpi"></div>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>AI tokens saved</h2><span class="muted">The AI saver: pictures read cheaply, answers reused, nothing wasted.</span></div><div id="rsave"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>Per day</h2><span class="muted">UTC days. Green = billed to members (in dollars), grey = your real spend.</span></div><div id="rdaily"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>By service</h2><span class="muted">What each part used, what it really cost you, and what it earned.</span></div><div id="rserv"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>By member</h2></div><div id="rmem"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>What one finished video really used</h2><span class="muted">Average over the period.</span></div><div id="ravg"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>Recent videos</h2><span class="muted">The last 40 finished or failed. Failed videos are never billed.</span></div><div id="rrec"></div></section>
    <section class="card"><div class="sechead"><h2>Your real costs and the value of a token</h2><span class="muted">Type what the services charge you. Used only for these reports; members never see it.</span></div><div id="rrates"></div></section>`;
  const usd = n => (n < 0 ? "-$" : "$") + Math.abs(n).toFixed(n !== 0 && Math.abs(n) < 1 ? 3 : 2);
  const num = n => Number(n).toLocaleString();
  const loadSave = guard(async () => {
    const d = await api(`/api/admin/ai-savings?days=${days}`);
    $("#rsave").innerHTML = (d.saved || d.spent) ? `<div class="kpis" style="margin:0 0 12px"><div class="card kpi"><div><div class="n">${num(d.saved)}</div><div class="l">tokens not spent</div></div></div><div class="card kpi"><div><div class="n">${num(d.spent)}</div><div class="l">tokens spent</div></div></div><div class="card kpi"><div><div class="n">${d.percent}%</div><div class="l">of all AI tokens saved</div></div></div></div><table><tr><th>How it was saved</th><th>Tokens</th></tr>${d.by_kind.map(k => `<tr><td>${esc(k.label)}</td><td>${num(k.tokens)}</td></tr>`).join("") || `<tr><td colspan="2" class="muted">Nothing saved yet in this period.</td></tr>`}</table>` : `<div class="muted">No AI use in this period yet.</div>`;
  });
  const load = guard(async () => {
    days = +$("#rdays").value;
    loadSave();
    const r = await api(`/api/admin/report?days=${days}`), t = r.totals;
    $("#rcsv").href = `/api/admin/report.csv?days=${days}`;
    const k = (ic, tone, n, l, sub) => `<div class="card kpi"><span class="ic ${tone}">${svg(ic)}</span><div><div class="n">${n}</div><div class="l">${l}${sub ? `<br><span class="muted">${sub}</span>` : ""}</div></div></div>`;
    $("#rkpi").innerHTML = k("check", "ok", usd(t.revenue_usd), "Billed to members", `${num(t.billed_tokens)} tokens at $${r.token_usd} each`) +
      k("alert", "warn", usd(t.real_usd), "Your real spend", "AI and images, from the rates below") +
      k("globeok", t.net_usd >= 0 ? "ok" : "bad", usd(t.net_usd), "Left over", "billed minus your real spend") +
      k("film", "info", num(t.videos), "Videos made", `${num(t.uploads)} uploaded to YouTube`) +
      k("inbox", t.failed ? "warn" : "ok", num(t.failed), "Videos that failed", `${usd(t.wasted_usd)} spent on them, nobody billed`) +
      k("inbox", "info", num(t.refunded_tokens), "Tokens refunded", "failed videos and uploads");
    // per-day bars: billed (green) next to real spend (grey)
    const mx = Math.max(0.0001, ...r.daily.map(d => Math.max(d.revenue_usd, d.real_usd)));
    $("#rdaily").innerHTML = r.daily.some(d => d.revenue_usd || d.real_usd || d.videos)
      ? `<div style="display:flex;gap:${r.daily.length > 40 ? 2 : 6}px;align-items:flex-end;height:150px;overflow-x:auto;padding-top:6px">${r.daily.map(d => `
          <div title="${d.d}: ${d.videos} video(s), billed ${usd(d.revenue_usd)}, spent ${usd(d.real_usd)}" style="flex:1;min-width:${r.daily.length > 40 ? 6 : 22}px;display:flex;flex-direction:column;align-items:center;gap:4px">
            <div style="display:flex;align-items:flex-end;gap:2px;height:120px;width:100%"><div style="flex:1;background:var(--ok);border-radius:3px 3px 0 0;height:${Math.max(2, 120 * d.revenue_usd / mx)}px"></div>
              <div style="flex:1;background:var(--muted);opacity:.55;border-radius:3px 3px 0 0;height:${Math.max(2, 120 * d.real_usd / mx)}px"></div></div>
            <span class="muted" style="font-size:10px">${d.d.slice(5)}</span></div>`).join("")}</div>`
      : `<p class="muted">Nothing used in this period yet.</p>`;
    $("#rserv").innerHTML = r.services.length ? `<table><tr><th>Service</th><th>Used</th><th>Your real cost</th><th>At your token prices</th><th>Billed to members</th><th>Earned</th></tr>${r.services.map(s => `
      <tr><td><b>${esc(s.label)}</b></td><td>${num(s.units)} <span class="muted">${esc(s.unit)}</span></td><td>${usd(s.real_usd)}</td><td>${s.cost_tokens} tokens</td><td>${s.billed_tokens} tokens</td><td>${usd(s.revenue_usd)}</td></tr>`).join("")}</table>` : `<p class="muted">No usage recorded yet.</p>`;
    $("#rmem").innerHTML = r.members.length ? `<table><tr><th>Member</th><th>Videos</th><th>Failed</th><th>Uploads</th><th>Gemini tokens</th><th>DeepSeek tokens</th><th>Images</th><th>Billed</th><th>Your real cost</th><th>Left over</th></tr>${r.members.map(m => `
      <tr><td><b>${esc(m.name)}</b> <span class="muted">${m.role === "owner" ? "owner · not billed" : esc(m.email)}</span></td><td>${m.videos}</td><td>${m.failed}</td><td>${m.uploads}</td><td>${num(m.gemini_tokens)}</td><td>${num(m.deepseek_tokens)}</td><td>${m.images}</td>
        <td>${m.billed_tokens} <span class="muted">(${usd(m.revenue_usd)})</span></td><td>${usd(m.real_usd)}</td><td>${m.role === "owner" ? '<span class="muted">-</span>' : usd(m.net_usd)}</td></tr>`).join("")}</table>` : `<p class="muted">No members have used anything yet.</p>`;
    const AV = Object.values(r.average);
    $("#ravg").innerHTML = AV.length ? `<table><tr><th>Video</th><th>Measured</th><th>Gemini tokens</th><th>DeepSeek tokens</th><th>Images</th><th>At your token prices</th><th>Your real cost</th></tr>${AV.map(a => `
      <tr><td><b>${a.label}</b></td><td>${a.videos}</td><td>${num(a.gemini_tokens)}</td><td>${num(a.deepseek_tokens)}</td><td>${a.images}</td><td>${a.cost_tokens} tokens (${usd(a.cost_tokens * r.token_usd)})</td><td>${usd(a.real_usd)}</td></tr>`).join("")}</table>`
      : `<p class="muted">No finished video in this period has been measured yet.</p>`;
    $("#rrec").innerHTML = r.recent.length ? `<table><tr><th>Finished (UTC)</th><th>Member</th><th>Type</th><th>Status</th><th>Gemini</th><th>DeepSeek</th><th>Images</th><th>Billed</th><th>Your real cost</th><th></th></tr>${r.recent.map(v => `
      <tr><td class="muted">${when(v.when)}</td><td>${esc(v.name)}</td><td>${v.kind}</td><td>${v.status === "done" ? '<span class="badge uploaded">made</span>' : '<span class="badge declined">failed</span>'}</td>
        <td>${num(v.gemini_tokens)}</td><td>${num(v.deepseek_tokens)}</td><td>${v.images}</td><td>${v.role === "owner" ? '<span class="muted">owner</span>' : v.charged_tokens + " tokens"}</td><td>${usd(v.real_usd)}</td>
        <td>${v.video_id ? `<a href="#" data-rv="${v.video_id}">Open</a>` : ""}</td></tr>`).join("")}</table>` : `<p class="muted">No videos finished in this period.</p>`;
    document.querySelectorAll("[data-rv]").forEach(a => a.onclick = e => { e.preventDefault(); openVideo(a.dataset.rv); });
    const rt = r.rates;
    $("#rrates").innerHTML = `<div class="fields">${[["token_usd", "One token is worth, $"], ["gemini_in_per_1m", "Gemini input, $ per 1M tokens"], ["gemini_out_per_1m", "Gemini output, $ per 1M tokens"], ["claude_search_usd", "Claude web search, $ per search"], ["claude_in_per_1m", "Claude input, $ per 1M tokens"], ["claude_out_per_1m", "Claude output, $ per 1M tokens"], ["deepseek_in_per_1m", "DeepSeek input, $ per 1M tokens"],
        ["deepseek_out_per_1m", "DeepSeek output, $ per 1M tokens"], ["image_gemini_usd", "Gemini image, $ each"], ["image_flux_usd", "Best thumbnail (FLUX), $ each"], ["image_free_usd", "Free image, $ each"]].map(([k, l]) =>
        `<div><label>${l}</label><input type="number" min="0" step="0.0001" data-rc="${k}" value="${rt[k]}"></div>`).join("")}</div>
      <div class="row" style="margin-top:12px"><button class="pri" id="rc_save">Save</button><span class="muted">Free-tier keys cost $0. Change the token prices on the Users page.</span></div>`;
    $("#rc_save").onclick = guard(async () => { const body = {}; document.querySelectorAll("[data-rc]").forEach(i => body[i.dataset.rc] = i.value); await api("/api/admin/costs", {method: "PUT", body}); toast("Saved"); load(); });
  });
  $("#rdays").onchange = load;
  await load();
}

