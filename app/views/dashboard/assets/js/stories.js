/* Story videos: pick what is trending, get an idea (or write your own story), check the script, choose how the scenes move, and the studio makes the scenes and puts them in a project in the editor. */
"use strict";
async function stories() {
  const opt = await api("/api/stories/options");
  let genre = null, idea = null, script = null, scripts = [], part = 0, trendData = null, pollT = null;
  const CAMS = ["slow push in", "slow pull back", "pan left", "pan right", "static with gentle movement", "slow tilt up", "handheld", "push in left", "push in right"];
  $("#main").innerHTML = `<h1>Story videos</h1>
    <div class="card stp" id="st1"><h2><span class="no">1</span> What is trending</h2><p class="muted" style="margin:-4px 0 10px">The studio looks at the Shorts that grew fastest this week and ranks the kinds of stories. It only learns what works. Your story is always new.</p><div id="st_trend" class="muted">Loading…</div></div>
    <div class="card stp" id="st2"><h2><span class="no">2</span> Your story</h2>
      <div class="row" style="gap:8px;flex-wrap:wrap"><button id="st_ideas">Get story ideas</button><span class="muted" id="st_gname"></span></div><div id="st_ideaslist" class="stideas"></div>
      <label>Or write your own idea (a few words)</label><input id="st_prem" maxlength="500" placeholder="e.g. A night guard finds a door in the museum that was not there yesterday">
      <details style="margin-top:8px"><summary class="muted" style="cursor:pointer">I wrote the whole story myself</summary><textarea id="st_own" rows="6" maxlength="2500" placeholder="Paste your story. Your words are kept exactly; the AI only cuts them into scenes and describes the pictures."></textarea></details>
      <div class="stopts"><div><label>Look of the pictures</label><select id="st_style">${opt.styles.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join("")}</select></div>
        <div><label>About how long</label><select id="st_len"><option value="30">30 seconds</option><option value="40" selected>40 seconds</option><option value="55">55 seconds</option></select></div>
        <div><label>How many parts</label><select id="st_parts"><option value="1" selected>1 video (one part)</option><option value="2">2 parts (Part 1, Part 2)</option><option value="3">3 parts</option><option value="4">4 parts</option><option value="5">5 parts</option></select></div></div>
      <div class="row" style="gap:8px;margin-top:10px"><button class="pri" id="st_write">Write the script</button><span class="muted" id="st_wmsg"></span></div></div>
    <div class="card stp" id="st3" hidden><h2><span class="no">3</span> Check the script</h2><div id="st_script"></div></div>
    <div class="card stp" id="st4" hidden><h2><span class="no">4</span> Make the video</h2><div id="st_make"></div></div>
    <div id="st_run"></div><div id="st_hist"></div>`;
  const fmtLen = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  /* ---- 1: the trends */
  const loadTrend = guard(async () => {
    trendData = await api("/api/stories/trends"); const box = $("#st_trend"); if (!box) return;
    box.className = "";
    box.innerHTML = `<div class="stgenres">${trendData.genres.map((g, i) => `<button class="stg ${genre === g.id ? "on" : ""}" data-g="${g.id}"><b>${esc(g.name)}</b>${trendData.live ? `<span class="muted">${g.score ? g.score.toLocaleString() + " views an hour" : "no data"}</span>` : ""}<span class="muted">${esc(g.about)}</span>${i === 0 && trendData.live && g.score ? `<i class="badge uploaded">Trending most</i>` : ""}</button>`).join("")}</div>
      <div class="muted" style="margin-top:8px">${esc(trendData.message || "")}</div>`;
    if (!genre) genre = trendData.genres[0].id;
    box.querySelectorAll("[data-g]").forEach(b => b.onclick = () => { genre = b.dataset.g; idea = null; $("#st_ideaslist").innerHTML = ""; box.querySelectorAll("[data-g]").forEach(x => x.classList.toggle("on", x === b)); $("#st_gname").textContent = `Genre: ${trendData.genres.find(g => g.id === genre).name}`; });
    box.querySelectorAll("[data-g]").forEach(x => x.classList.toggle("on", x.dataset.g === genre));
    $("#st_gname").textContent = `Genre: ${trendData.genres.find(g => g.id === genre).name}`;
  });
  /* ---- 2: ideas and the script */
  $("#st_ideas").onclick = guard(async () => {
    $("#st_ideas").disabled = true; $("#st_ideas").textContent = "Thinking…";
    try { const r = await api("/api/stories/ideas", {method: "POST", body: {genre}});
      $("#st_ideaslist").innerHTML = r.ideas.map((x, i) => `<button class="stidea" data-i="${i}"><b>${esc(x.title)}</b><span>${esc(x.premise)}</span></button>`).join("");
      $("#st_ideaslist").querySelectorAll(".stidea").forEach(b => b.onclick = () => { idea = r.ideas[+b.dataset.i]; $("#st_prem").value = idea.premise; $("#st_ideaslist").querySelectorAll(".stidea").forEach(x => x.classList.toggle("on", x === b)); });
    } finally { $("#st_ideas").disabled = false; $("#st_ideas").textContent = "Get story ideas"; }
  });
  $("#st_write").onclick = guard(async () => {
    $("#st_write").disabled = true; $("#st_wmsg").textContent = "Writing the script… (about 20 seconds)";
    try {
      const r = await api("/api/stories/script", {method: "POST", body: {genre, premise: $("#st_prem").value, own_text: $("#st_own").value, seconds: +$("#st_len").value, style: $("#st_style").value, parts: $("#st_own").value.trim() ? 1 : +$("#st_parts").value}});
      scripts = r.scripts || [r.script]; part = 0; script = scripts[0]; drawScript(); toast(r.charged ? `Script written (${r.charged} token${r.charged === 1 ? "" : "s"})` : "Script written");
    } finally { $("#st_write").disabled = false; $("#st_wmsg").textContent = ""; }
  });
  /* ---- 3: the script, editable */
  function drawScript() {
    $("#st3").hidden = false;
    $("#st_script").innerHTML = `${scripts.length > 1 ? `<div class="stparts">${scripts.map((p, i) => `<button class="${i === part ? "pri" : ""}" data-part="${i}">Part ${i + 1}</button>`).join("")}<span class="muted">One story in ${scripts.length} parts. Each part is its own video and ends so that people want the next one.</span></div>` : ""}<label>Title</label><input id="sc_title" maxlength="90" value="${esc(script.title)}"><label>Description (for the video)</label><textarea id="sc_desc" rows="2" maxlength="600">${esc(script.description)}</textarea>
      ${script.characters.length ? `<h3 style="margin-top:12px">Characters (they look the same in every scene)</h3>${script.characters.map((c, i) => `<div class="row" style="gap:8px"><b style="min-width:90px">${esc(c.name)}</b><input data-ch="${i}" class="grow" maxlength="200" value="${esc(c.look)}"></div>`).join("")}` : ""}
      <h3 style="margin-top:12px">Scenes <span class="muted" id="sc_total"></span></h3>
      ${script.scenes.map((s, i) => `<div class="scene" data-i="${i}"><div class="row" style="gap:8px;align-items:center"><b>Scene ${s.n}</b><span class="grow"></span><select class="sc_cam">${CAMS.map(c => `<option ${c === s.camera ? "selected" : ""}>${c}</option>`).join("")}</select><label class="pjchk" style="margin:0" title="Only used when you choose AI video below"><input type="checkbox" class="sc_key" ${s.key ? "checked" : ""}><span>AI video here</span></label><button class="dng sc_del" title="Remove this scene">✕</button></div>
        <label>The narrator says</label><textarea class="sc_nar" rows="2" maxlength="240">${esc(s.narration)}</textarea><label>What we see (who is where and what they do)</label><textarea class="sc_vis" rows="2" maxlength="300">${esc(s.visual)}</textarea></div>`).join("")}
      <div class="stlabel" style="margin-top:10px">${script.realistic ? "This look is realistic. When you post it, YouTube's 'altered or synthetic content' box is ticked for you." : "Every story video is marked as AI-made in the editor."}</div>`;
    $("#st_script").querySelectorAll(".scene").forEach(el => {
      const i = +el.dataset.i;
      el.querySelector(".sc_nar").oninput = e => { script.scenes[i].narration = e.target.value; sync(); };
      el.querySelector(".sc_vis").oninput = e => { script.scenes[i].visual = e.target.value; };
      el.querySelector(".sc_key").onchange = e => { script.scenes[i].key = e.target.checked; estimate(); };
      el.querySelector(".sc_cam").onchange = e => { script.scenes[i].camera = e.target.value; };
      el.querySelector(".sc_del").onclick = () => { if (script.scenes.length <= 4) return toast("A story needs at least 4 scenes.", true); script.scenes.splice(i, 1); script.scenes.forEach((s, k) => s.n = k + 1); drawScript(); };
    });
    $("#st_script").querySelectorAll("[data-part]").forEach(b => b.onclick = () => { part = +b.dataset.part; script = scripts[part]; drawScript(); });
    $("#sc_title").oninput = e => { script.title = e.target.value; }; $("#sc_desc").oninput = e => { script.description = e.target.value; };
    $("#st_script").querySelectorAll("[data-ch]").forEach(inp => inp.oninput = e => { script.characters[+inp.dataset.ch].look = e.target.value; });
    sync(); drawMake();
  }
  const sync = () => { const sec = script.scenes.reduce((a, s) => a + Math.max(3, Math.min(8, Math.max(s.seconds || 0, s.narration.split(/\s+/).filter(Boolean).length / 2.6 + 0.4))), 0); if ($("#sc_total")) $("#sc_total").textContent = `· about ${fmtLen(sec)}`; };
  /* ---- 4: how to move, the price, go */
  let provider = "motion";
  async function drawMake() {
    $("#st4").hidden = false;
    $("#st_make").innerHTML = `<label>How should the scenes move?</label><div class="stprov">${opt.providers.map(p => `<label class="stp1 ${p.ok ? "" : "off"}"><input type="radio" name="st_prov" value="${p.id}" ${p.id === provider ? "checked" : ""} ${p.ok ? "" : "disabled"}><span><b>${esc(p.name)}</b><span class="muted">${esc(p.note)}</span></span></label>`).join("")}</div>
      <label class="pjchk" style="margin-top:10px"><input type="checkbox" id="st_cap" checked><span>Burn captions into the pictures</span></label>
      <label class="pjchk"><input type="checkbox" id="st_fin"><span>Make the finished video by itself at the end (otherwise you can change things in the editor first)</span></label>
      <div class="stest" id="st_est" style="margin:12px 0">Working out the price…</div><div class="row" style="gap:8px"><button class="pri" id="st_go">Make my story video</button><span class="muted">It runs in the background. You can leave this page.</span></div>`;
    $("#st_make").querySelectorAll("[name=st_prov]").forEach(r => r.onchange = () => { provider = r.value; estimate(); });
    ["#st_cap", "#st_fin"].forEach(q => { if ($(q)) $(q).onchange = () => estimate(); });
    $("#st_go").onclick = guard(async () => {
      $("#st_go").disabled = true;
      try { const r = await api("/api/stories", {method: "POST", body: {scripts, provider, finish: $("#st_fin").checked ? "render" : "open", captions: $("#st_cap").checked}}); toast(scripts.length > 1 ? `Your ${scripts.length} parts are in the line` : "Your story is in the line"); follow(r.id); }
      finally { $("#st_go").disabled = false; }
    });
    estimate();
  }
  const estimate = guard(async () => {
    const e = await api("/api/stories/estimate", {method: "POST", body: {scripts, provider, captions: $("#st_cap") ? $("#st_cap").checked : true, finish: $("#st_fin") && $("#st_fin").checked ? "render" : "open"}}); const box = $("#st_est"); if (!box) return;
    const pn = e.parts > 1 ? ` in ${e.parts} parts${e.discount ? ` (${e.discount}% off each part)` : ""}` : "";
    box.innerHTML = e.free ? `${e.scenes} scenes${pn}: free for the owner (the usage is still recorded).` : `${e.scenes} scenes${pn}: <b>about ${e.tokens} tokens</b> (${e.pictures} pictures${e.video_scenes ? `, ${e.video_scenes} AI video scene${e.video_scenes === 1 ? "" : "s"}` : ""}${e.motion_scenes ? `, ${e.motion_scenes} with camera movement` : ""}). The tokens are held now and what is not used comes back. A failed story costs nothing.`;
  });
  /* ---- progress */
  function drawRun(j) {
    const box = $("#st_run"); if (!box) return stopPoll();
    const act = ["queued", "running"].includes(j.status);
    box.innerHTML = `<div class="card"><div class="row" style="gap:12px;align-items:center;flex-wrap:wrap"><b>${j.status === "queued" ? "Waiting in line" : j.status === "running" ? "Making your story" : j.status === "done" ? "Your story is ready" : j.status === "cancelled" ? "Cancelled" : "It did not work"}: ${esc(j.title || "")}</b>
      <span class="muted">${j.status === "queued" ? (j.ahead ? `${j.ahead} ahead of yours` : "You are next") : esc(j.status === "error" ? j.error : j.step || "")}</span><span class="grow"></span>
      ${act ? `<button id="stj_cancel">Cancel</button>` : j.status === "done" ? `<a class="btn pri" href="#/projects/${j.result.project_id}">Open it in Edit projects</a>` : ""}</div>
      ${act ? `<div class="pgx-bar" style="margin-top:10px"><i style="width:${j.pct}%"></i></div>` : ""}
      <div class="stthumbs">${(j.scenes || []).map(s => `<div class="stth ${s.status}" title="${esc(s.note || "")}">${s.status === "done" || ["running"].includes(j.status) && s.status !== "waiting" ? `<img alt="" src="/api/stories/${j.id}/frame/${s.n}?t=${Date.now() % 100000}" onerror="this.style.display='none'">` : ""}<span>${s.n}</span>${s.kind ? `<i>${s.kind === "video" ? "AI video" : "camera"}</i>` : ""}${j.status === "done" && s.kind === "motion" ? `<button class="stredo" data-redo="${s.n}" title="Make this picture again (costs a few tokens)">↻</button>` : ""}</div>`).join("")}</div>
      ${receipt(j)}
      ${j.status === "done" ? `<p class="muted" style="margin:10px 0 0">${j.result.video_scenes} scene${j.result.video_scenes === 1 ? "" : "s"} with AI video, ${j.result.motion_scenes} with camera movement. You paid ${j.charged || 0} token${j.charged === 1 ? "" : "s"}. ${j.result.render_id ? "The video is being made now (see My videos)." : "Change anything you like in the editor, then press Make video."}${j.result.realistic ? " The look is realistic, so the upload will tick YouTube's AI label." : ""}</p>` : ""}</div>`;
    box.querySelectorAll("[data-redo]").forEach(b => b.onclick = guard(async () => {
      if (!confirm("Make this picture again? A new picture is drawn and the narration is recorded again. This costs tokens (see the price in your estimate); if it fails you pay nothing.")) return;
      b.disabled = true; b.textContent = "…";
      try { const r = await api(`/api/stories/${j.id}/scenes/${b.dataset.redo}/redo`, {method: "POST"}); toast("The picture was made again"); drawRun(r); } finally { b.disabled = false; }
    }));
    if ($("#stj_cancel")) $("#stj_cancel").onclick = guard(async () => { await api(`/api/stories/${j.id}/cancel`, {method: "POST"}); poll(j.id); });
  }
  function receipt(j) {
    const r = j.receipt; if (!r || !["done", "error", "cancelled"].includes(j.status)) return "";
    const n = x => (Math.round(x * 100) / 100).toString();
    return `<div class="strcpt"><b>Receipt</b>${r.free ? `<div class="muted">Free for the owner (the usage is still recorded).</div>` : ""}<table>${(r.lines || []).map(l => `<tr><td>${esc(l.label)}</td><td class="muted">${l.qty.toLocaleString()} ${esc(l.unit)}</td><td>${n(l.tokens)}</td></tr>`).join("")}
      ${r.discount ? `<tr><td colspan="2">Parts discount (${r.discount}%)</td><td>-${n(r.discount_tokens)}</td></tr>` : ""}
      <tr class="sep"><td colspan="2">Held when you started</td><td>${r.held}</td></tr>
      <tr><td colspan="2"><b>Used</b></td><td><b>${r.used}</b></td></tr>
      <tr><td colspan="2">Given back</td><td>${r.returned}</td></tr>${r.extra ? `<tr><td colspan="2">Taken in addition</td><td>${r.extra}</td></tr>` : ""}${r.later ? `<tr><td colspan="2">Scenes made again (paid when you pressed the button)</td><td>${n(r.later)}</td></tr>` : ""}</table>${j.status !== "done" ? `<div class="muted">Nothing was charged for this story.</div>` : ""}</div>`;
  }
  const stopPoll = () => { if (pollT) clearInterval(pollT); pollT = null; };
  async function poll(id) { try { const j = await api(`/api/stories/${id}`); drawRun(j); if (!["queued", "running"].includes(j.status)) { stopPoll(); drawHist(); const nx = (await api("/api/stories")).stories.filter(s => ["queued", "running"].includes(s.status) && s.series && j.series && s.series.title === j.series.title).pop(); if (nx) follow(nx.id); } } catch (e) { stopPoll(); } }
  const follow = id => { stopPoll(); poll(id); pollT = setInterval(() => poll(id), 3000); timer = pollT; };
  async function drawHist() {
    const r = await api("/api/stories"); const box = $("#st_hist"); if (!box) return;
    box.innerHTML = r.stories.length ? `<h2 style="margin-top:22px">Your story videos</h2><div class="card"><table><tr><th>Story</th><th>Status</th><th>Made</th><th></th></tr>${r.stories.map(s => `<tr><td>${esc(s.title || "")}</td><td>${esc(s.status)}</td><td class="muted">${when(s.created_at)}</td><td style="text-align:right">${s.status === "done" ? `<a href="#/projects/${s.result.project_id}">Open</a>` : ["queued", "running"].includes(s.status) ? `<a href="#" data-f="${s.id}">Watch</a>` : ""}</td></tr>`).join("")}</table></div>` : "";
    box.querySelectorAll("[data-f]").forEach(a => a.onclick = e => { e.preventDefault(); follow(a.dataset.f); });
  }
  const live = opt.mine.find(s => ["queued", "running"].includes(s.status));
  await loadTrend(); await drawHist(); if (live) follow(live.id);
}
