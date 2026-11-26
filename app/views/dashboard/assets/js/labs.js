/* Reaction Lab and Learning Lab (beta). */
"use strict";
/* ------------------------------------------------------------ Reaction Lab (beta): find the moments people react to, judge them, and let the studio learn your taste */
Object.assign(ICON, {reactions: '<circle cx="12" cy="12" r="9"/><path d="M8 14c1 1.6 2.4 2.4 4 2.4s3-.8 4-2.4"/><path d="M9 9.5h.01M15 9.5h.01"/>'});
/* ------------------------------------------------------------ Learning Lab (beta): your examples, and what the studio learned from your results */
Object.assign(ICON, {lab: '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 1.8 3h10.4A2 2 0 0 0 19 18l-5-9V3"/><path d="M8.5 14h7"/>'});
async function lab() {
  const PART = {
    titles: {name: "Titles", up: "more views per day", down: "fewer views per day",
      what: "The AI that writes your titles is shown the titles you like, and the choice between its candidate titles gets a small nudge from what worked on your own videos."},
    descriptions: {name: "Descriptions",
      what: "The AI that writes your descriptions hears how yours sound: the examples you add here, and the descriptions you rewrite by hand in the Videos page."},
    clipping: {name: "Clipping", up: "published more often", down: "published less often",
      what: "The score of a moment gets a small nudge (at most 10 points out of 100) toward the kinds of clips you publish, and away from the kinds you decline."},
  };
  const S = {part: "titles"};
  $("#main").innerHTML = `<h1>Learning Lab <span class="betatag big">BETA</span></h1>
    <div class="rxnote"><b>Experimental, and off by default.</b> Nothing changes in your videos until you switch a part on. It only affects videos made for the owner account, never a member's. It learns from your own examples and results, and it only ever nudges: the normal scoring stays in charge. It is not a trained language model: that needs far more data than a channel has.</div>
    <div class="seg" id="lab_tabs" style="margin:16px 0">${Object.keys(PART).map(k => `<button data-p="${k}">${PART[k].name}</button>`).join("")}</div>
    <div id="lab_body"><div class="card muted">Loading…</div></div>`;
  const when = at => { try { return new Date(at).toLocaleString(); } catch (e) { return ""; } };
  const draw = d => {
    const p = PART[d.part], o = d.overview, min = (S.min || {});
    const stat = d.part === "titles" ? `${o.examples} examples you like · ${o.logged} titles written so far · ${o.with_views} videos with view counts (${min.titles || 12} are needed to learn)`
      : d.part === "descriptions" ? `${o.examples} examples · ${o.logged} descriptions written so far`
      : `${o.published} published · ${o.declined} declined (it needs ${min.clipping || 20} decisions in total and ${min.per_class || 6} of each kind)`;
    const learned = (d.learned || []).length
      ? d.learned.map(r => `<div class="row" style="gap:10px;margin:6px 0"><span class="st ${r.direction > 0 ? "ok" : "warn"}">${r.direction > 0 ? "▲" : "▼"}</span><span>${esc(r.label)}</span><span class="muted">${r.strength} · ${r.direction > 0 ? p.up : p.down}</span></div>`).join("")
      : `<div class="muted">${esc(d.note || "It has not learned anything yet.")}</div>`;
    const examples = d.part === "clipping" ? "" : `
      <section class="card" style="margin-top:14px"><h2 style="margin-top:0">${d.part === "titles" ? "Titles you like" : "Descriptions you like"}</h2>
        <div class="help" style="margin-bottom:8px">${d.part === "titles" ? "Add titles you wish every video had (from any channel). The AI copies their feel, never their words." : "Add the first lines of descriptions you like. The AI copies their voice, never their words."} A title or description you rewrite in the Videos page is added here by itself.</div>
        <textarea id="lab_ex" rows="2" style="width:100%" placeholder="${d.part === "titles" ? "He Grabbed the Wrong Car and the Whole Street Turned on Him" : "He grabs the wrong car and the whole street turns on him. One guy screams about cargo while another dares him to fight."}"></textarea>
        <div class="row" style="margin-top:8px"><button class="pri" id="lab_add">Add example</button></div>
        <div id="lab_exlist" style="margin-top:12px">${(d.examples || []).length ? d.examples.map(e => `<div class="row" style="gap:10px;margin:6px 0;align-items:flex-start"><span class="st ${e.source === "edit" ? "" : "ok"}">${e.source === "edit" ? "your edit" : "added by you"}</span><span class="grow" style="min-width:0;overflow-wrap:anywhere">${esc(e.text)}</span><button data-del="${e.id}">Remove</button></div>`).join("") : `<div class="muted">No examples yet.</div>`}</div>
      </section>`;
    const results = d.part === "descriptions" ? "" : `
      <section class="card" style="margin-top:14px"><h2 style="margin-top:0">What it learned</h2>
        <div class="help" style="margin-bottom:10px">${d.part === "titles" ? "It compares your videos' views per day with how their titles are built. With few videos it stays close to 'no effect'." : "It compares the clips you published with the ones you declined."}</div>
        ${learned}
        <div class="row" style="margin-top:14px;gap:10px;flex-wrap:wrap">${d.part === "titles" ? `<button id="lab_sync">Update view counts</button>` : ""}<button class="pri" id="lab_train">Learn from my videos</button><button id="lab_reset">Start over</button><span class="muted" id="lab_msg"></span></div>
        ${d.part === "titles" && !S.key ? `<div class="help" style="margin-top:8px">To read your view counts add a YouTube Data API key in Settings → Accounts &amp; keys.</div>` : ""}
      </section>`;
    const recent = d.part === "clipping" ? "" : `
      <section class="card" style="margin-top:14px"><h2 style="margin-top:0">Written recently</h2>${(d.recent || []).length ? d.recent.map(r => d.part === "titles"
        ? `<div style="margin:10px 0"><b>${esc((r.data || {}).picked || "")}</b> <span class="muted">${when(r.at)}</span><div class="help">${((r.data || {}).rows || []).slice(0, 5).map(x => `${esc(x.title)} (${x.total}${x.lab ? ", lab " + (x.lab > 0 ? "+" : "") + x.lab : ""})`).join("<br>")}</div></div>`
        : `<div style="margin:10px 0"><b>${esc((r.data || {}).hook || "")}</b> <span class="muted">${when(r.at)}</span><div class="help">${esc((r.data || {}).about || "")}<br>${esc((r.data || {}).question || "")}</div></div>`).join("") : `<div class="muted">Nothing yet. It fills as the studio makes videos for you.</div>`}</section>`;
    $("#lab_body").innerHTML = `
      <section class="card"><div class="row" style="gap:12px;align-items:center;flex-wrap:wrap"><h2 style="margin:0">${p.name}</h2><span class="st ${d.on ? "ok" : ""}">${d.on ? "On" : "Off"}</span><span class="grow"></span><button class="${d.on ? "" : "pri"}" id="lab_on">${d.on ? "Switch off" : "Switch on"}</button></div>
        <div class="help" style="margin-top:8px"><b>When it is on:</b> ${p.what}</div>
        <div class="help" style="margin-top:6px">${esc(stat)}</div></section>${examples}${results}${recent}`;
    const msg = t => { const m = $("#lab_msg"); if (m) m.textContent = t; };
    $("#lab_on").onclick = guard(async () => { draw(await api(`/api/lab/${d.part}`, {method: "PUT", body: {on: !d.on}})); toast(d.on ? "Switched off" : "Switched on"); });
    if ($("#lab_add")) $("#lab_add").onclick = guard(async () => { const t = $("#lab_ex").value.trim(); if (!t) throw new Error("Type or paste an example first"); draw(await api("/api/lab/examples", {method: "POST", body: {kind: d.part === "titles" ? "title" : "description", text: t}})); toast("Added"); });
    document.querySelectorAll("#lab_exlist [data-del]").forEach(b => b.onclick = guard(async () => { await api(`/api/lab/examples/${b.dataset.del}`, {method: "DELETE"}); load(d.part); }));
    if ($("#lab_train")) $("#lab_train").onclick = guard(async () => { msg("Learning…"); const r = await api("/api/lab/train", {method: "POST", body: {part: d.part}}); draw(r.detail); const m = $("#lab_msg"); if (m) m.textContent = r.message; });
    if ($("#lab_reset")) $("#lab_reset").onclick = guard(async () => { if (!confirm("Forget what it learned? Your examples and videos are kept.")) return; draw(await api("/api/lab/reset", {method: "POST", body: {part: d.part}})); toast("Started over"); });
    if ($("#lab_sync")) $("#lab_sync").onclick = guard(async () => { msg("Reading the view counts…"); const r = await api("/api/lab/sync", {method: "POST", body: {}}); load(d.part, r.message); });
  };
  const load = guard(async (part, note) => {
    S.part = part || S.part;
    document.querySelectorAll("#lab_tabs button").forEach(b => b.classList.toggle("on", b.dataset.p === S.part));
    const ov = await api("/api/lab"); S.min = ov.min; S.key = ov.has_api_key;
    draw(await api(`/api/lab/${S.part}`));
    if (note) { const m = $("#lab_msg"); if (m) m.textContent = note; }
  });
  document.querySelectorAll("#lab_tabs button").forEach(b => b.onclick = () => load(b.dataset.p));
  load("titles");
}
async function reactions() {
  let opt;
  try { opt = await api("/api/reactions/options"); } catch (e) { $("#main").innerHTML = `<h1>Reaction Lab</h1><div class="card"><div class="authmsg bad" style="margin:0">${esc(e.message)}</div></div>`; return; }
  const CAT = {any: "Any kind", funny: "😂 Funny", rage: "🤬 Rage", fail: "💥 Fail", scary: "😱 Scary", shock: "😮 Shock", epic: "🏆 Epic"};
  const S = {cat: "any", moments: 12, faces: true, words: false, scan: null, model: opt.model};
  const tm = s => { s = Math.round(s); const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
  $("#main").innerHTML = `<h1>Reaction Lab <span class="betatag big">BETA</span></h1>
    <div class="rxnote"><b>Experimental.</b> This lab runs on its own: it never edits, uploads, schedules or spends AI tokens, and nothing in your videos changes because of it. It finds the moments people react to, you judge them, and it learns what a good reaction means for your channel.</div>
    <section class="card rx-ask"><div class="crt-h"><span class="crt-n">1</span><div><h2>Find the reactions</h2><p>Paste a YouTube or Twitch video or a stream replay. It listens, reads the chat when the platform allows, and checks the picture.</p></div></div>
      <label class="crt-l">Link</label><input id="rx_url" placeholder="https://www.youtube.com/watch?v=…" autocomplete="off" maxlength="300">
      <label class="crt-l">What kind of reaction are you after?</label><div class="pkbar" id="rx_cats">${opt.categories.map(c => `<button type="button" class="pkc" data-c="${c}">${CAT[c] || c}</button>`).join("")}</div>
      <div class="help" style="margin-top:4px">Each kind learns its own taste once you have judged enough of it.</div>
      <label class="crt-l">How many moments to look at closely</label><div class="pkbar" id="rx_n">${opt.moments.map(n => `<button type="button" class="pkc" data-n="${n}">${n} moments</button>`).join("")}</div>
      <div class="rxopts"><label><input type="checkbox" id="rx_faces" checked> Look at the face camera for smiles and jolts</label><label><input type="checkbox" id="rx_words"> Listen to the words said (slower, uses your computer)</label></div>
      <details class="more"><summary>Only part of the video</summary><div class="row" style="gap:10px;margin-top:8px"><input id="rx_a" placeholder="Start, e.g. 1:20:00" style="max-width:200px"><input id="rx_b" placeholder="End, e.g. 1:50:00" style="max-width:200px"></div><div class="help">Without this it looks at the first 30 minutes.</div></details>
      <div class="row" style="margin-top:18px"><button class="pri" id="rx_go">Find the reactions</button><span class="muted" id="rx_hint"></span></div></section>
    <section class="card" id="rx_run" style="margin-top:18px" hidden></section>
    <section id="rx_res" style="margin-top:18px" hidden></section>
    <section class="card" id="rx_learn" style="margin-top:18px"></section>
    <section class="card" style="margin-top:18px"><div class="sechead"><h2>Earlier scans</h2><span class="muted">Your judgments are kept even when a scan is deleted</span></div><div id="rx_hist"></div></section>
    <p class="help" style="margin-top:14px">Beta: the signals are rough measures (for example "laughing sounds" is a guess from the audio). They are a starting point; your judgments are what make the ranking yours. Chat can be read only for videos whose platform keeps the chat replay.</p>`;
  const sync = () => {
    document.querySelectorAll("#rx_cats .pkc").forEach(b => b.classList.toggle("on", b.dataset.c === S.cat));
    document.querySelectorAll("#rx_n .pkc").forEach(b => b.classList.toggle("on", +b.dataset.n === S.moments));
    $("#rx_hint").textContent = `Takes about ${S.moments <= 8 ? 3 : S.moments <= 12 ? 5 : 8} to ${S.words ? 15 : 10} minutes.`;
  };
  $("#rx_cats").onclick = e => { const b = e.target.closest(".pkc"); if (b) { S.cat = b.dataset.c; sync(); } };
  $("#rx_n").onclick = e => { const b = e.target.closest(".pkc"); if (b) { S.moments = +b.dataset.n; sync(); } };
  $("#rx_faces").onchange = e => S.faces = e.target.checked; $("#rx_words").onchange = e => { S.words = e.target.checked; sync(); };
  /* ---- what it has learned */
  const drawLearn = () => {
    const m = S.model, g = m.models[0], ph = g.phase, need = ph.next, pct = need ? Math.min(100, Math.round(100 * m.labels / need)) : 100;
    const w = [...g.weights].sort((a, b) => b.now - a.now);
    $("#rx_learn").innerHTML = `<div class="sechead"><h2>What the lab has learned</h2><span class="rxphase">${esc(ph.name)}</span></div>
      <div class="rxlearn"><div><p style="margin:0 0 10px">${esc(ph.text)}</p>
        <div class="rxprog"><i style="width:${pct}%"></i></div><div class="muted" style="margin:6px 0 14px">${m.labels} moment${m.labels === 1 ? "" : "s"} judged · ${m.good} good · ${m.bad} not good${need ? ` · next step at ${need}` : ""}</div>
        ${g.trained ? (g.acc != null ? `<div class="rxacc"><b>${Math.round(100 * g.acc)}%</b><span>of moments it had not seen were called right (always guessing the common answer would be ${Math.round(100 * g.base)}%)</span></div>` : `<div class="help">Its accuracy is measured after about 15 judgments.</div>`) : `<div class="help">It starts learning after at least ${m.min_each} good and ${m.min_each} not-good judgments.</div>`}
        ${m.models.length > 1 ? `<div class="rxcats">${m.models.slice(1).map(x => `<span class="chip">${esc(CAT[x.category] || x.category)} model · ${x.n} judged</span>`).join("")}</div>` : ""}
        <div class="row" style="margin-top:14px"><button type="button" class="dng" id="rx_reset" ${g.trained ? "" : "disabled"}>Reset learning</button><span class="muted">Keeps your judgments, starts the weights over.</span></div></div>
        <div><h3 class="insh" style="margin-top:0">What it looks for, right now</h3>${w.map(x => `<div class="rxw" title="${esc(opt.signals.find(s => s.id === x.signal).help)}"><span>${esc(x.label)}</span><i><u style="width:${x.share}%"></u></i>${Math.abs(x.change) >= .15 ? `<em class="${x.change > 0 ? "up" : "down"}">${x.change > 0 ? "▲" : "▼"} ${Math.abs(x.change).toFixed(1)}</em>` : `<em></em>`}</div>`).join("")}
          <div class="help" style="margin-top:8px">The bars are how much each thing counts. ▲ ▼ show what changed from the starting weights because of your judgments.</div></div></div>`;
    const rb = $("#rx_reset"); if (rb) rb.onclick = guard(async () => { if (!confirm("Start the weights over? Your judgments are kept.")) return; const r = await api("/api/reactions/model", {method: "DELETE"}); S.model = r.model; drawLearn(); toast("Learning reset"); });
  };
  /* ---- one scan's results */
  const mapSvg = v => {
    const tl = v.timeline, n = tl.length, w0 = v.window[0], w1 = v.window[1];
    if (n < 2) return "";
    const pts = tl.map((y, i) => `${(i / (n - 1) * 1000).toFixed(1)},${(112 - y * 1.0).toFixed(1)}`);
    const marks = v.candidates.map((c, i) => { const x = Math.max(12, Math.min(988, (c.peak - w0) / (w1 - w0) * 1000)); return `<g class="rxmk" data-c="${c.id}"><line x1="${x}" x2="${x}" y1="14" y2="112"/><circle cx="${x}" cy="14" r="11"/><text x="${x}" y="18.5">${i + 1}</text></g>`; }).join("");
    return `<svg viewBox="0 0 1000 124" preserveAspectRatio="none" class="rxmap"><defs><linearGradient id="rxg" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".55"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs>
      <polygon points="0,112 ${pts.join(" ")} 1000,112" fill="url(#rxg)"/><polyline points="${pts.join(" ")}" fill="none" stroke="var(--accent)" stroke-width="2" vector-effect="non-scaling-stroke"/>${marks}</svg>
      <div class="rxaxis"><span>${tm(w0)}</span><span>${tm((w0 + w1) / 2)}</span><span>${tm(w1)}</span></div>`;
  };
  const cardHtml = (c, i, v) => {
    const have = c.signals.filter(s => s.value != null).sort((a, b) => b.value - a.value), miss = c.signals.filter(s => s.value == null);
    return `<div class="rxc ${c.label === 1 ? "good" : c.label === 0 ? "bad" : ""}" id="rxc_${c.id}" data-id="${c.id}">
      <div class="rxv">${c.ready ? `<video controls preload="none" playsinline ${c.thumb ? `poster="${c.thumb}"` : ""} src="${c.video}"></video>` : `<div class="rxnov">No preview could be cut for this moment</div>`}<span class="rxrank">${i + 1}</span></div>
      <div class="rxb"><div class="rxtop"><div class="rxring" style="--p:${c.score}" title="How likely this is a strong reaction, by the model"><b>${c.score}</b></div>
        <div class="rxwho"><b>${tm(c.start)} – ${tm(c.end)}</b><span class="muted">${c.length} s · peak at ${tm(c.peak)}</span><div class="rlr">${(c.reasons || []).map(r => `<span class="frs">${esc(r)}</span>`).join("") || `<span class="muted">No strong signal</span>`}</div></div></div>
        ${c.said ? `<div class="rxsaid">“${esc(c.said)}”</div>` : ""}
        <div class="rxsigs">${have.map(s => `<div class="rxs" title="${esc(s.help)}"><span>${esc(s.label)}</span><i><u style="width:${s.value}%"></u></i><em>${s.value}</em></div>`).join("")}</div>
        ${miss.length ? `<details class="more"><summary>Not measured (${miss.length})</summary><div class="help">${miss.map(s => esc(s.label)).join(" · ")}. These need a face camera, chat replay, the words option or a YouTube replay curve.</div></details>` : ""}
        <div class="rxj"><div class="pkbar"><button type="button" class="pkc ${c.label === 1 ? "on" : ""}" data-y="1">👍 Good reaction</button><button type="button" class="pkc ${c.label === 0 ? "on" : ""}" data-y="0">👎 Not a reaction</button></div>
          <select data-cat title="What kind of reaction is this?">${opt.categories.map(k => `<option value="${k}" ${k === (c.category || v.category) ? "selected" : ""}>${esc(CAT[k] || k)}</option>`).join("")}</select></div></div></div>`;
  };
  const drawScan = v => {
    const box = $("#rx_res"); box.hidden = false;
    const judged = v.candidates.filter(c => c.label != null).length;
    box.innerHTML = `<div class="rxhead card"><div class="rphead" style="margin:0 0 6px"><span class="rpico">🎭</span><div class="rptitle"><h2>${esc(v.title || "Scan")}</h2><div class="rpmeta"><span class="chip">${esc(v.creator || "")}</span><span class="chip">${esc(CAT[v.category] || v.category)}</span><span class="chip">scored with ${esc(v.model)}</span>
          ${v.available.chat ? `<span class="chip ok">chat read</span>` : `<span class="chip">no chat</span>`}${v.available.faces ? `<span class="chip ok">face camera seen</span>` : v.available.faces_asked ? `<span class="chip">no face camera</span>` : ""}${v.available.words ? `<span class="chip ok">words heard</span>` : ""}${v.available.heat ? `<span class="chip ok">replay curve</span>` : ""}</div></div>
        <span class="rpbadge ${judged ? "ok" : "idle"}">${judged} of ${v.candidates.length} judged</span></div>
      <div class="rxmapw">${mapSvg(v)}</div>
      <div class="row" style="gap:10px;margin-top:10px"><button type="button" id="rx_rescore" title="Score these moments again with what the lab has learned since">Re-rank with what it has learned</button><button type="button" class="dng" id="rx_del">Delete this scan</button><span class="muted">Judge each moment: it is how the lab learns.</span></div></div>
      <div class="rxgrid">${v.candidates.map((c, i) => cardHtml(c, i, v)).join("")}</div>`;
    box.querySelectorAll(".rxmk").forEach(g => g.onclick = () => { const el = $("#rxc_" + g.dataset.c); if (el) { el.scrollIntoView({behavior: "smooth", block: "center"}); el.classList.add("flash"); setTimeout(() => el.classList.remove("flash"), 1400); } });
    box.querySelectorAll(".rxc").forEach(card => {
      const cid = card.dataset.id, c = v.candidates.find(x => x.id === cid);
      card.querySelectorAll("[data-y]").forEach(b => b.onclick = guard(async () => {
        const y = +b.dataset.y, same = c.label === y;
        const r = await api(`/api/reactions/scans/${v.id}/c/${cid}/label`, {method: "POST", body: {y: same ? null : y, category: card.querySelector("[data-cat]").value}});
        c.label = same ? null : y; S.model = r.model;
        card.classList.toggle("good", c.label === 1); card.classList.toggle("bad", c.label === 0);
        card.querySelectorAll("[data-y]").forEach(x => x.classList.toggle("on", c.label === +x.dataset.y));
        box.querySelector(".rpbadge").textContent = `${v.candidates.filter(x => x.label != null).length} of ${v.candidates.length} judged`;
        drawLearn(); drawHist();
      }));
    });
    $("#rx_rescore").onclick = guard(async () => { const r = await api(`/api/reactions/scans/${v.id}/rescore`, {method: "POST", body: {}}); drawScan(r); toast("Re-ranked"); });
    $("#rx_del").onclick = guard(async () => { if (!confirm("Delete this scan and its previews? Your judgments are kept.")) return; await api(`/api/reactions/scans/${v.id}`, {method: "DELETE"}); S.scan = null; box.hidden = true; drawHist(); });
  };
  /* ---- running a scan */
  let poll = null;
  const stopPoll = () => { if (poll) clearInterval(poll); poll = null; };
  const show = id => {
    stopPoll(); S.scan = id; const run = $("#rx_run"); const t0 = Date.now();
    const tick = async () => {
      let v; try { v = await api(`/api/reactions/scans/${id}`); } catch (e) { stopPoll(); run.hidden = true; return; }
      if (v.status === "running") {
        run.hidden = false; $("#rx_res").hidden = true;
        run.innerHTML = `<div class="rpx run"><div class="rphead"><span class="rpico pulse">🎭</span><div class="rptitle"><h2>${esc(v.title || "Scanning…")}</h2><div class="muted">${esc(v.message)}</div></div><span class="rpbadge idle">${Math.round((Date.now() - t0) / 1000)} s</span></div>
          <div class="pgx-bar"><i style="width:${Math.max(4, v.pct)}%"></i></div><div class="help" style="margin-top:8px">You can leave this page; the scan keeps running and is here when you come back.</div></div>`;
        return;
      }
      stopPoll(); run.hidden = true;
      if (v.status === "error") { run.hidden = false; run.innerHTML = `<div class="rpx err"><div class="rphead"><span class="rpico">⚠️</span><div class="rptitle"><h2>${esc(v.title && v.title !== "Scanning…" ? v.title : "Scan failed")}</h2></div><span class="rpbadge bad">Failed</span></div><div class="authmsg bad" style="margin:0">${esc(v.message)}</div></div>`; }
      else drawScan(v);
      drawHist();
    };
    tick(); poll = setInterval(tick, 3000);
  };
  const drawHist = guard(async () => {
    const d = await api("/api/reactions/scans");
    $("#rx_hist").innerHTML = d.scans.length ? `<div class="rhgrid">${d.scans.map(s => `<div class="rh ${esc(s.status)}"><div class="rhtop"><span class="rhico">🎭</span><div class="rhname"><b>${esc(s.title)}</b><div class="muted">${ago(s.created_at)} · ${esc(CAT[s.category] || s.category)}</div></div><span class="rhst ${esc(s.status)}">${{done: "Done", error: "Failed", running: "Running"}[s.status] || s.status}</span></div>
      <div class="muted">${s.count} moments · ${s.judged} judged</div><div class="row rhact"><button data-o="${s.id}">Open</button></div></div>`).join("")}</div>` : `<div class="muted">No scans yet. Paste a link above.</div>`;
    $("#rx_hist").querySelectorAll("[data-o]").forEach(b => b.onclick = () => { show(b.dataset.o); window.scrollTo({top: 0, behavior: "smooth"}); });
  });
  $("#rx_go").onclick = guard(async () => {
    const r = await api("/api/reactions/scan", {method: "POST", body: {url: $("#rx_url").value, category: S.cat, moments: S.moments, faces: S.faces, words: S.words, start: $("#rx_a").value, end: $("#rx_b").value}});
    show(r.scan);
  });
  sync(); drawLearn(); drawHist();
  try { const l = await api("/api/reactions/scans"); if (l.scans.length) show(l.scans[0].id); } catch (e) {}
}

