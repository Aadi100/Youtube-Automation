/* Find ideas (research). */
"use strict";
/* ------------------------------------------------------------ clipping research (Claude + web search) */
Object.assign(ICON, {research: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5M8.5 11h5M11 8.5v5"/>'});
async function research() {
  let opt;
  try { opt = await api("/api/research/options"); } catch (e) { $("#main").innerHTML = `<h1>Research</h1><div class="card"><div class="authmsg bad" style="margin:0">${esc(e.message)}</div></div>`; return; }
  const SC = {world: "🌍", game: "🎮", creator: "🎙", marketplace: "🏷"};
  const S = {scope: "world", platforms: new Set(), depth: "normal", filter: "all", q: "", run: null, prov: (opt.providers || []).find(p => p.id === opt.provider && p.ready) ? opt.provider : ((opt.providers || []).find(p => p.ready) || {}).id || opt.provider || "claude"};
  $("#main").innerHTML = `<h1>Research</h1>
    <section class="card rs-ask"><div class="crt-h"><span class="crt-n">1</span><div><h2>What should the AI find?</h2><p>It searches the web and reports who allows clipping, with proof.</p></div></div>
      ${opt.ready ? "" : `<div class="authmsg bad" style="margin:0 0 14px">Research needs an AI key. Add a Claude key (or a Gemini key) in <a href="#/settings">Settings → Accounts &amp; keys</a>. For Claude, make sure web search is switched on for your Anthropic account.</div>`}
      <div class="pkgrid auto" id="rs_scope">${opt.scopes.map(x => `<button type="button" class="pk" data-v="${x.id}"><span class="pki" style="font-size:20px">${SC[x.id] || ""}</span><b>${esc(x.name)}</b><span>${esc(x.desc)}</span></button>`).join("")}</div>
      <div id="rs_qbox" hidden><label class="crt-l">Name</label><input id="rs_q" maxlength="120" placeholder="" autocomplete="off"></div>
      <label class="crt-l">Look on</label><div class="pkbar" id="rs_plats">${opt.platforms.map(p => `<button type="button" class="pkc" data-p="${p}">${p === "other" ? "Anywhere else" : p[0].toUpperCase() + p.slice(1)}</button>`).join("")}</div>
      <div class="help" style="margin-top:4px">Choose none to look everywhere.</div>
      <label class="crt-l">How deep</label><div class="pkbar" id="rs_depth">${opt.depth.map(d => `<button type="button" class="pkc" data-d="${d.id}">${d.id[0].toUpperCase() + d.id.slice(1)} · ${d.searches} searches</button>`).join("")}</div>
      ${(opt.providers || []).length ? `<label class="crt-l">Which AI does the research</label><div class="pkbar" id="rs_prov">${opt.providers.map(p => `<button type="button" class="pkc" data-pv="${p.id}" ${p.ready ? "" : "disabled"} title="${esc(p.ready ? p.how : p.why)}">${esc(p.name)}${p.ready ? "" : " · not set up"}</button>`).join("")}</div>
        <div class="help" id="rs_provhelp" style="margin-top:4px"></div>
        <label class="crt-l">Model</label><select id="rs_model" style="max-width:420px"></select><div class="help" style="margin-top:4px">A larger model reads and judges better but costs more. The AI and model are saved with the research.</div>` : ""}
      <div class="row" style="margin-top:18px"><button class="pri" id="rs_go" ${opt.ready ? "" : "disabled"}>Start research</button><span class="muted" id="rs_est"></span></div></section>
    <section class="card" id="rs_run" hidden></section>
    <section class="card" id="rs_ins" style="margin-top:18px" hidden></section>
    <section class="card" id="rs_res" style="margin-top:18px" hidden></section>
    <section class="card" style="margin-top:18px"><div class="sechead"><h2>Earlier research</h2><span class="muted">Every research is kept with its proof. Open it, download it, or run it again.</span></div><div id="rs_hist"></div></section>
    <p class="help" style="margin-top:14px">These are research notes, not legal advice. A creator's or programme's own rules page is what counts, so confirm with them before you clip. Permission to clip is not permission to earn: YouTube's rules for reused content still apply.</p>`;
  const sync = () => {
    document.querySelectorAll("#rs_scope .pk").forEach(b => b.classList.toggle("on", b.dataset.v === S.scope));
    document.querySelectorAll("#rs_plats .pkc").forEach(b => b.classList.toggle("on", S.platforms.has(b.dataset.p)));
    document.querySelectorAll("#rs_depth .pkc").forEach(b => b.classList.toggle("on", b.dataset.d === S.depth));
    $("#rs_qbox").hidden = !["game", "creator"].includes(S.scope); $("#rs_q").placeholder = S.scope === "game" ? "e.g. Valorant, Minecraft, Roblox" : "e.g. a streamer's name";
    const pv = (opt.providers || []).find(p => p.id === S.prov);
    document.querySelectorAll("#rs_prov .pkc").forEach(b => b.classList.toggle("on", b.dataset.pv === S.prov));
    if (pv && $("#rs_model") && $("#rs_model").dataset.for !== S.prov) {
      $("#rs_model").dataset.for = S.prov;
      $("#rs_model").innerHTML = pv.models.map(m => `<option value="${esc(m)}" ${m === pv.model ? "selected" : ""}>${esc(m)}</option>`).join("");
      $("#rs_provhelp").textContent = pv.how;
    }
    const e = (opt.depth.find(d => d.id === S.depth) || {}).estimate || {}, nm = pv ? pv.name : "Claude";
    $("#rs_est").textContent = e.searches ? `About ${e.searches} searches and ${Math.round(e.tokens / 1000)}k ${nm} tokens${S.prov !== "claude" ? " (your " + nm + " plan or bill applies)" : e.rates_entered ? ` · about $${e.usd}` : " (enter Claude's rates under Reports to see dollars)"}. Takes a few minutes.` : "";
  };
  $("#rs_scope").onclick = e => { const b = e.target.closest(".pk"); if (b) { S.scope = b.dataset.v; sync(); if (!$("#rs_qbox").hidden) $("#rs_q").focus(); } };
  $("#rs_plats").onclick = e => { const b = e.target.closest(".pkc"); if (!b) return; S.platforms.has(b.dataset.p) ? S.platforms.delete(b.dataset.p) : S.platforms.add(b.dataset.p); sync(); };
  if ($("#rs_prov")) $("#rs_prov").onclick = e => { const b = e.target.closest(".pkc"); if (b && !b.disabled) { S.prov = b.dataset.pv; sync(); } };
  $("#rs_depth").onclick = e => { const b = e.target.closest(".pkc"); if (b) { S.depth = b.dataset.d; sync(); } };
  /* ---- the leads */
  const ALLOW = {yes: ["Allowed", "ok"], conditional: ["Allowed with conditions", "warn"], unknown: ["Not proven", "idle"], no: ["Not allowed", "bad"]};
  const MON = {yes: "Can earn on your channel", conditional: "Earning depends on conditions", unknown: "Earning not stated", no: "No earning"};
  const PLAT = {youtube_shorts: "YouTube Shorts", youtube_long: "YouTube long", tiktok: "TikTok", instagram: "Instagram"};
  const leadCard = l => `<div class="rl ${esc(l.allows)}" data-id="${l.id}"><div class="rlh"><div><b class="rln">${esc(l.name)}</b><div class="rlm"><span class="chip">${esc(l.type)}</span><span class="chip">${esc(l.platform)}</span>${(l.games || []).map(g => `<span class="chip">${esc(g)}</span>`).join("")}</div></div>
      <div class="rlb"><span class="rlbadge ${ALLOW[l.allows][1]}">${ALLOW[l.allows][0]}</span><span class="muted" title="How well the sources support this">Confidence: ${esc(l.confidence)}</span></div></div>
    ${l.permission_text ? `<p class="rlp">${esc(l.permission_text)}</p>` : ""}${l.note ? `<p class="help">${esc(l.note)}</p>` : ""}
    ${l.programme ? `<div class="rlprog"><b>Clipping programme${l.programme.name ? ": " + esc(l.programme.name) : ""}</b>${l.programme.where ? `<div>Where: ${esc(l.programme.where)}</div>` : ""}${l.programme.pay ? `<div>Pay: ${esc(l.programme.pay)}</div>` : ""}${l.programme.how_to_join ? `<div>How to join: ${esc(l.programme.how_to_join)}</div>` : ""}</div>` : ""}
    ${(l.content_wanted || []).length ? `<div class="rlr"><span class="muted">Wants:</span> ${l.content_wanted.map(x => `<span class="frs">${esc(x)}</span>`).join("")}</div>` : ""}
    ${(l.platforms_allowed || []).length ? `<div class="rlr"><span class="muted">Allowed on:</span> ${l.platforms_allowed.map(x => `<span class="frs">${esc(PLAT[x] || x)}</span>`).join("")}</div>` : ""}
    ${(l.requirements || []).length ? `<ul class="rlreq">${l.requirements.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <div class="rlmon ${esc(l.monetization.verdict)}"><b>${MON[l.monetization.verdict]}</b>${l.monetization.why ? `<span>${esc(l.monetization.why)}</span>` : ""}</div>
    <details class="more"><summary>Proof (${(l.evidence || []).length} source${(l.evidence || []).length === 1 ? "" : "s"})</summary>${(l.evidence || []).length ? l.evidence.map(e => `<div class="rev"><a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">${esc(e.url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 70))}</a>${e.date ? ` <span class="muted">· ${esc(e.date)}</span>` : ""}<q>${esc(e.quote)}</q></div>`).join("") : `<div class="muted">No page was proven for this.</div>`}</details>
    <div class="row rla"><div class="pkbar">${opt.statuses.map(st => `<button type="button" class="pkc ${l.status === st ? "on" : ""}" data-st="${st}">${st}</button>`).join("")}</div>
      <input class="rlnotes" placeholder="Notes (who you messaged, what they said)" value="${esc(l.notes || "")}" maxlength="1000"></div>
    <div class="row rla">${l.url ? `<a class="btn" href="${esc(l.url)}" target="_blank" rel="noopener noreferrer">Open their page</a>` : ""}${["yes", "conditional"].includes(l.allows) ? `<button type="button" data-act="creator" title="Save this creator so you can take clips only from them on the Create page">Use in Create</button>` : ""}<button type="button" class="dng" data-act="del">Remove</button></div></div>`;
  const drawLeads = async () => {
    const box = $("#rs_res"); box.hidden = false;
    const qs = new URLSearchParams(); if (S.filter === "saved") qs.set("status", "saved"); else if (["yes", "conditional", "unknown", "no"].includes(S.filter)) qs.set("allows", S.filter); if (S.q) qs.set("q", S.q);
    if (S.run && S.filter === "run") qs.set("run", S.run);
    const d = await api(`/api/research/leads?${qs}`);
    const f = [["all", "All"], ...(S.run ? [["run", "This research"]] : []), ["yes", "Allowed"], ["conditional", "With conditions"], ["unknown", "Not proven"], ["no", "Not allowed"], ["saved", "Saved"]];
    box.innerHTML = `<div class="sechead"><h2>Leads <span class="muted" style="font-weight:400">${d.leads.length}</span></h2><input id="rs_search" type="search" placeholder="Search name, game or text" value="${esc(S.q)}" style="max-width:260px"></div>
      <div class="pkbar" id="rs_f" style="margin-bottom:14px">${f.map(([k, n]) => `<button type="button" class="pkc ${S.filter === k ? "on" : ""}" data-f="${k}">${n}</button>`).join("")}</div>
      ${d.leads.length ? `<div class="rlgrid">${d.leads.map(leadCard).join("")}</div>` : emptyState("research", "Nothing here yet", "Start a research above, or change the filter.")}`;
    $("#rs_f").onclick = e => { const b = e.target.closest("[data-f]"); if (b) { S.filter = b.dataset.f; drawLeads(); } };
    $("#rs_search").onkeydown = e => { if (e.key === "Enter") { S.q = e.target.value.trim(); drawLeads(); } };
    box.querySelectorAll(".rl").forEach(card => {
      const id = card.dataset.id;
      card.querySelectorAll("[data-st]").forEach(b => b.onclick = guard(async () => { await api(`/api/research/leads/${id}`, {method: "PATCH", body: {status: b.dataset.st}}); card.querySelectorAll("[data-st]").forEach(x => x.classList.toggle("on", x === b)); }));
      card.querySelector(".rlnotes").onchange = guard(async e => { await api(`/api/research/leads/${id}`, {method: "PATCH", body: {notes: e.target.value}}); toast("Notes saved"); });
      card.querySelectorAll("[data-act]").forEach(b => b.onclick = guard(async () => {
        if (b.dataset.act === "del") { if (!confirm("Remove this lead?")) return; await api(`/api/research/leads/${id}`, {method: "DELETE"}); drawLeads(); drawIns(); }
        else { const r = await api(`/api/research/leads/${id}/creator`, {method: "POST", body: {}}); toast(`${r.creator.label} saved. Pick it on the Create page under "One creator".`); }
      }));
    });
  };
  /* ---- what the research says: everything added up, to decide what to make next */
  const drawIns = async () => {
    const box = $("#rs_ins"), d = await api("/api/research/insights");
    if (!d.total) { box.hidden = true; return; }
    box.hidden = false;
    const kpi = (n, l, tone) => `<div class="insk ${tone || ""}"><b>${n}</b><span>${l}</span></div>`;
    const max = a => Math.max(1, ...a.map(x => x.n));
    const bars = (a, key) => a.length ? a.map(x => `<button type="button" class="insbar" data-q="${esc(x.name)}" title="Show the leads for ${esc(x.name)}"><span>${esc(PLAT[x.name] || x.name)}</span><i style="width:${Math.round(100 * x.n / max(a))}%"></i><em>${x.n}</em></button>`).join("") : `<div class="muted">Nothing yet.</div>`;
    box.innerHTML = `<div class="sechead"><h2>What your research says</h2><span class="muted">Added up from every lead you kept. Click anything to see the creators behind it.</span></div>
      <div class="inskpis">${kpi(d.total, "leads kept")}${kpi(d.allowed, "clipping allowed", "ok")}${kpi(d.conditional, "with conditions", "warn")}${kpi(d.unknown, "not proven", "idle")}${kpi(d.no, "not allowed", "bad")}${kpi(d.programmes, "clipping programmes")}${kpi(d.earn_yes, "support earning")}</div>
      ${d.best.length ? `<h3 class="insh">Best opportunities</h3><div class="insbest">${d.best.map((b, i) => `<div class="insrow"><span class="insn">${i + 1}</span><div class="insmain"><b>${esc(b.name)}</b> <span class="chip">${esc(b.platform)}</span> <span class="rlbadge ${b.allows === "yes" ? "ok" : "warn"}">${b.allows === "yes" ? "Allowed" : "With conditions"}</span>
          <div class="muted">${esc(b.why.join(" · "))}</div>
          <div class="rlr">${b.games.map(g => `<span class="frs">${esc(g)}</span>`).join("")}${b.content_wanted.map(g => `<span class="frs">${esc(g)}</span>`).join("")}</div>${b.pay ? `<div class="help">Pays: ${esc(b.pay)}</div>` : ""}</div>
          <div class="insscore" title="Higher is better: proof, permission, earning, programme"><i style="width:${Math.min(100, Math.round(b.score * 100 / 9))}%"></i><b>${b.score}</b></div><button type="button" data-q="${esc(b.name)}">Open</button></div>`).join("")}</div>` : ""}
      ${d.plan.length ? `<h3 class="insh">What to make</h3><div class="insplan">${d.plan.map(p => `<div class="insp"><b>${esc(p.kind)}</b><div class="muted">${p.creators} creator${p.creators === 1 ? "" : "s"} want this${p.games.length ? " · " + p.games.map(esc).join(", ") : ""}</div>
          ${p.platforms.length ? `<div class="rlr"><span class="muted">Post on:</span> ${p.platforms.map(x => `<span class="frs">${esc(PLAT[x] || x)}</span>`).join("")}</div>` : ""}<div class="help">From: ${p.who.map(esc).join(", ")}</div></div>`).join("")}</div>` : ""}
      <div class="insgrid"><div><h3 class="insh">Kinds of clips wanted</h3>${bars(d.kinds)}</div><div><h3 class="insh">Games and categories in demand</h3>${bars(d.games)}</div><div><h3 class="insh">Where clips may be posted</h3>${bars(d.platforms)}</div></div>
      ${d.programme_list.length ? `<h3 class="insh">Clipping programmes</h3><table><tr><th>Programme</th><th>Run by</th><th>Where</th><th>Pay</th><th>How to join</th></tr>${d.programme_list.map(p => `<tr><td><b>${esc(p.programme.name || "-")}</b></td><td>${esc(p.name)}</td><td>${esc(p.programme.where || "-")}</td><td>${esc(p.programme.pay || "not stated")}</td><td>${esc(p.programme.how_to_join || "-")}</td></tr>`).join("")}</table>` : ""}
      ${d.avoid.length ? `<h3 class="insh">Do not clip</h3><div class="muted">${d.avoid.map(a => `<b>${esc(a.name)}</b>${a.text ? ": " + esc(a.text) : ""}`).join(" · ")}</div>` : ""}
      <div class="row" style="margin-top:16px"><button type="button" id="rs_csv">Download all leads (spreadsheet)</button><span class="muted">The score is only a guide: it adds up proven permission, earning, a programme and the sources.</span></div>`;
    box.querySelectorAll("[data-q]").forEach(b => b.onclick = () => { S.q = b.dataset.q; S.filter = "all"; drawLeads(); $("#rs_res").scrollIntoView({behavior: "smooth"}); });
    $("#rs_csv").onclick = guard(async () => {
      const all = (await api("/api/research/leads")).leads, q = v => `"${String(v == null ? "" : v).replace(/"/g, '""')}"`;
      const head = ["Name", "Type", "Platform", "Clipping", "Earning", "Programme", "Pay", "Games", "Wants", "Allowed on", "Rules", "Confidence", "Status", "Notes", "Page", "Proof"];
      const rows = all.map(l => [l.name, l.type, l.platform, l.allows, l.monetization.verdict, (l.programme || {}).name, (l.programme || {}).pay, (l.games || []).join("; "), (l.content_wanted || []).join("; "), (l.platforms_allowed || []).join("; "), (l.requirements || []).join("; "), l.confidence, l.status, l.notes, l.url, (l.evidence || []).map(e => e.url).join(" ")]);
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob(["﻿" + [head, ...rows].map(r => r.map(q).join(",")).join("\r\n")], {type: "text/csv"}));
      a.download = "clipping-research.csv"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    });
  };
  /* ---- a run: the report, and the history of every research */
  let poll = null;
  const stopPoll = () => { if (poll) clearInterval(poll); poll = null; };
  const SCN = id => (opt.scopes.find(x => x.id === id) || {}).name || "Research";
  const AI = {claude: "Claude", gemini: "Gemini", deepseek: "DeepSeek"};
  const ZERO = {yes: 0, conditional: 0, unknown: 0, no: 0};
  const sentences = t => String(t || "").split(/(?<=[.!?])\s+(?=[A-Z0-9])/).map(x => x.trim()).filter(Boolean);
  const runTitle = r => `${esc(SCN(r.scope))}${r.query ? ": " + esc(r.query) : ""}`;
  const aiName = r => `${esc(AI[r.provider] || r.provider || "Claude")}${r.model ? " · " + esc(r.model) : ""}`;
  const download = guard(async id => {
    const rec = await api(`/api/research/runs/${id}/export`);
    const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([JSON.stringify(rec, null, 2)], {type: "application/json"}));
    a.download = `research-${(rec.run.query || rec.run.scope || "record").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-${id.slice(-6)}.json`; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  });
  const rerun = guard(async (r, depth) => {
    const x = await api("/api/research/run", {method: "POST", body: {scope: r.scope, query: r.query || "", platforms: r.platforms || [], depth: depth || r.depth || "normal", model: r.model || "", provider: r.provider || "", language: r.language || ""}});
    S.run = x.run; showRun(x.run); $("#rs_run").scrollIntoView({behavior: "smooth"});
  });
  const report = (r, leads) => {
    const c = {...ZERO}; leads.forEach(l => { if (c[l.allows] != null) c[l.allows]++; });
    const n = leads.length, finds = sentences(r.summary);
    const tile = (v, l, tone) => `<div class="rpt ${tone}"><b>${v}</b><span>${l}</span></div>`;
    return `<div class="rpx"><div class="rphead"><span class="rpico">${SC[r.scope] || "🔎"}</span><div class="rptitle"><h2>${runTitle(r)}</h2>
        <div class="rpmeta"><span class="chip">${aiName(r)}</span><span class="chip">${esc(r.depth || "normal")} depth</span>${(r.platforms || []).map(p => `<span class="chip">${esc(p)}</span>`).join("")}<span class="muted">${ago(r.created_at)}</span></div></div>
        <span class="rpbadge ${n ? "ok" : "idle"}">${n} lead${n === 1 ? "" : "s"}</span></div>
      <div class="rptiles">${tile(c.yes, "allow clipping", "ok")}${tile(c.conditional, "with conditions", "warn")}${tile(c.unknown, "not proven", "idle")}${tile(c.no, "do not allow", "bad")}${tile(r.searches == null ? "-" : r.searches, "searches")}${tile(Math.round(r.tokens / 1000) + "k", "tokens used")}</div>
      ${/too long/.test(r.message) ? `<div class="help" style="margin:0 0 12px">The answer was too long, so only the finished leads were kept. Run it again on one platform to see more.</div>` : ""}
      <div class="rpcols"><div class="rpbox"><h3><span>✨</span> What was found</h3>${finds.length ? `<ul class="rpfind">${finds.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<div class="muted">No summary was written.</div>`}</div>
        <div class="rpbox gap"><h3><span>❓</span> Still unknown</h3>${(r.gaps || []).length ? `<ul class="rpgap">${r.gaps.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : `<div class="muted">Nothing was left open.</div>`}<div class="help">Run it again with Deep depth, or on one platform, to dig into these.</div></div></div>
      <div class="row rpact">${n ? `<button class="pri" data-go="leads">See these ${n} lead${n === 1 ? "" : "s"}</button>` : ""}<button data-go="dl">Download this record</button><button data-go="again">Run again, deeper</button></div></div>`;
  };
  const showRun = id => {
    stopPoll(); const box = $("#rs_run"); box.hidden = false; const t0 = Date.now();
    const tick = async () => {
      let d; try { d = await api(`/api/research/runs/${id}`); } catch (e) { stopPoll(); return; }
      const r = d.run, running = r.status === "running";
      if (running) {
        box.innerHTML = `<div class="rpx run"><div class="rphead"><span class="rpico pulse">${SC[r.scope] || "🔎"}</span><div class="rptitle"><h2>${runTitle(r)}</h2><div class="rpmeta"><span class="chip">${aiName(r)}</span><span class="chip">${esc(r.depth || "normal")} depth</span></div></div><span class="rpbadge idle">${Math.round((Date.now() - t0) / 1000)} s</span></div>
          <div class="scanbar"><i></i></div><div class="muted">${esc(r.message || "Searching the web…")}</div><div class="help" style="margin-top:6px">This usually takes 1 to 4 minutes. You can leave this page; the result is kept and appears under Earlier research.</div></div>`;
        return;
      }
      stopPoll();
      if (r.status === "error") {
        box.innerHTML = `<div class="rpx err"><div class="rphead"><span class="rpico">⚠️</span><div class="rptitle"><h2>${runTitle(r)}</h2><div class="rpmeta"><span class="chip">${aiName(r)}</span><span class="muted">${ago(r.created_at)}</span></div></div><span class="rpbadge bad">Failed</span></div>
          <div class="authmsg bad" style="margin:0 0 12px">${esc(r.message)}</div><div class="row rpact"><button class="pri" data-go="again">Try again</button><button data-go="dl">Download this record</button></div></div>`;
      } else box.innerHTML = report(r, d.leads);
      box.querySelectorAll("[data-go]").forEach(b => b.onclick = () => {
        if (b.dataset.go === "leads") { S.run = r.id; S.filter = "run"; drawLeads(); $("#rs_res").scrollIntoView({behavior: "smooth"}); }
        else if (b.dataset.go === "dl") download(r.id); else rerun(r, r.status === "error" ? r.depth : "deep");
      });
      S.run = r.id; S.filter = "all"; drawLeads(); drawHist(); drawIns();
    };
    tick(); poll = setInterval(tick, 3000);
  };
  const drawHist = guard(async () => {
    const d = await api("/api/research/runs"), st = d.stats, runs = d.runs;
    const sk = (v, l) => `<div class="rhs"><b>${v}</b><span>${l}</span></div>`, top = Math.max(1, ...st.trend.map(t => t.leads));
    $("#rs_hist").innerHTML = !runs.length ? `<div class="muted">Nothing yet. Start your first research above.</div>` : `
      <div class="rhstats">${sk(st.runs, "researches")}${sk(st.leads, "leads kept")}${sk(st.allowed, "allow clipping")}${sk(st.searches, "searches made")}${sk(Math.round(st.tokens / 1000) + "k", "tokens used")}
        <div class="rhs wide"><span>Leads per research (latest ${st.trend.length})</span><div class="rhspark">${st.trend.map(t => `<i class="${t.status === "error" ? "bad" : ""}" style="height:${Math.max(8, Math.round(100 * t.leads / top))}%" title="${t.status === "error" ? "failed" : t.leads + " leads"}"></i>`).join("")}</div>
          <div class="rhai">${Object.entries(st.by_ai).map(([k, n]) => `<span class="chip">${esc(AI[k] || k)} · ${n}</span>`).join("")}${st.failed ? `<span class="chip bad">${st.failed} failed</span>` : ""}</div></div></div>
      <div class="rhgrid">${runs.map(r => {
        const c = r.counts || ZERO, tot = c.yes + c.conditional + c.unknown + c.no, lab = {done: "Done", error: "Failed", running: "Running"}[r.status] || r.status;
        return `<div class="rh ${esc(r.status)}"><div class="rhtop"><span class="rhico">${SC[r.scope] || "🔎"}</span><div class="rhname"><b>${runTitle(r)}</b><div class="muted">${ago(r.created_at)} · ${aiName(r)}</div></div><span class="rhst ${esc(r.status)}">${lab}</span></div>
          ${r.status === "done" ? (tot ? `<div class="rhmix">${[["yes", "ok"], ["conditional", "warn"], ["unknown", "idle"], ["no", "bad"]].filter(([k]) => c[k]).map(([k, t]) => `<i class="${t}" style="flex:${c[k]}"></i>`).join("")}</div>
            <div class="rhnums"><span class="ok">${c.yes} allowed</span><span class="warn">${c.conditional} conditions</span><span>${c.unknown} unproven</span><span class="bad">${c.no} no</span></div>` : `<div class="muted">${esc(r.message)}</div>`)
            : r.status === "error" ? `<div class="help rhmsg">${esc(r.message)}</div>` : `<div class="muted">Still running…</div>`}
          <div class="muted rhfoot">${r.searches != null ? r.searches + " searches · " : ""}${Math.round(r.tokens / 1000)}k tokens</div>
          <div class="row rhact"><button data-r="${r.id}">Open</button><button data-x="${r.id}" title="Download the whole record: question, model, cost, every lead with its proof, and the AI's answer">Download</button><button data-a="${r.id}" title="Ask the same question again">Run again</button></div></div>`;
      }).join("")}</div>`;
    const by = Object.fromEntries(runs.map(r => [r.id, r]));
    $("#rs_hist").querySelectorAll("[data-r]").forEach(b => b.onclick = () => { showRun(b.dataset.r); $("#rs_run").scrollIntoView({behavior: "smooth"}); });
    $("#rs_hist").querySelectorAll("[data-x]").forEach(b => b.onclick = () => download(b.dataset.x));
    $("#rs_hist").querySelectorAll("[data-a]").forEach(b => b.onclick = () => rerun(by[b.dataset.a]));
  });
  $("#rs_go").onclick = guard(async () => {
    const r = await api("/api/research/run", {method: "POST", body: {scope: S.scope, query: $("#rs_q").value, platforms: [...S.platforms], depth: S.depth, model: $("#rs_model") ? $("#rs_model").value : "", provider: $("#rs_prov") ? S.prov : ""}});
    S.run = r.run; showRun(r.run); $("#rs_run").scrollIntoView({behavior: "smooth"});
  });
  sync(); drawLeads(); drawHist(); drawIns();
}

