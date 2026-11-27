/* Home (the overview) and the approvals list. */
"use strict";
/* ------------------------------------------------------------ overview */
async function overview() {
  const hr = new Date().getHours(), hello = hr < 5 ? "Working late" : hr < 12 ? "Good morning" : hr < 18 ? "Good afternoon" : "Good evening";
  $("#main").innerHTML = `<section class="hero2"><div><div class="eyebrow2">${hello}</div><h1>Hi ${esc((ME.name || "").split(" ")[0] || "there")}</h1>
      <div class="hero2act"><button class="pri" id="hero_create">Make a video</button></div></div></section><div id="getstarted"></div><div id="ytprompt"></div><div id="banner"></div><div class="kpis" id="kpis"></div>
    <div class="cols"><div><div id="approvals"></div>
      <section class="card"><div class="sechead"><h2>Latest videos</h2><a href="#/videos">View all</a></div><div id="latest"></div></section></div>
      <aside><section class="card nextup"><div class="sechead"><h2>Next up</h2><a href="#/schedule">Schedule</a></div><div id="nextup"></div></section>
        <section class="card"><div class="sechead"><h2>Setup</h2></div><div id="setup"></div></section></aside></div>`;
  $("#hero_create").onclick = () => { location.hash = "#/create"; };
  const load = async () => {
    const [h, s, v, jobs, sc, yt, storyList] = await Promise.all([api("/api/health"), api("/api/stats"), api("/api/videos"), api("/api/jobs"), api("/api/schedule/overview"), api("/api/youtube/status").catch(() => null), api("/api/stories").catch(() => ({stories: []}))]);
    if (false) {
      $("#ytprompt").innerHTML = `<section class="card" style="border-color:var(--warn);display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:16px">
        <div style="flex:1;min-width:240px"><h2 style="margin:0 0 4px">Connect your YouTube channel</h2>
        <div class="muted">${yt.configured ? "Connect once and the studio posts your videos to your channel automatically (Unlisted first, Public after you approve). Until then your videos are made but cannot be uploaded." : "The owner has not finished setting up YouTube sign-in yet. You can still create videos and post them to Twitch with the ready-made pack."}</div></div>
        ${yt.configured ? `<button class="pri" id="ytgo">Connect YouTube</button>` : ""}<a href="#/settings">Settings</a></section>`;
      if ($("#ytgo")) $("#ytgo").onclick = guard(async () => { const r = await api("/api/youtube/connect", {method: "POST"}); location.href = r.url; });
    } else $("#ytprompt").innerHTML = "";
    const vs = s.videos_by_status, tot = Object.values(vs).reduce((a, b) => a + b, 0);
    const steps = [["Connect your YouTube channel", yt && !yt.configured ? "The owner has not finished setting up YouTube yet. You can still make videos." : "So your videos can go to your channel by themselves.", !!(!yt || yt.connected || !yt.configured), "Connect", "yt"],
                   ["Choose your voice and look", "Your narrator, thumbnail style and logo.", !!((ME.prefs || {}).tts_voice), "Choose", "#/settings/prefs"],
                   ["Make your first video", "Pick a game and press Start. It takes a few minutes.", tot > 0, "Make a video", "#/create"],
                   ["Make a story video", "Pick a genre and the AI writes it scene by scene.", (storyList.stories || []).length > 0, "Story videos", "#/stories"],
                   ["Let it run by itself", "Choose times and the studio makes videos for you.", sc.upcoming.length > 0, "Set a schedule", "#/schedule"]];
    const gs = $("#getstarted");
    const tourPending = ME.role !== "owner" && !(ME.prefs || {}).tour;          // a new member is shown the tour first, then this checklist
    if (gs) gs.innerHTML = tourPending || steps.every(x => x[2]) ? "" : `<section class="gs"><h2>Get started in ${steps.length} steps</h2><p>Each step ticks by itself when it is done. You can skip any step and come back later.${ME.role !== "owner" ? ` <a href="#" id="gs_tour">Take the tour</a>` : ""}</p><ol class="gsl">${steps.map((x, i) => `<li class="${x[2] ? "done" : ""}"><span class="no">${x[2] ? "✓" : i + 1}</span><div class="tx"><b>${x[0]}</b><span>${x[1]}</span></div>${x[2] ? "" : x[4] === "yt" ? `<button class="pri" id="gs_yt">${x[3]}</button>` : `<a class="btn" href="${x[4]}">${x[3]}</a>`}</li>`).join("")}</ol></section>`;
    if ($("#gs_tour")) $("#gs_tour").onclick = e => { e.preventDefault(); startTour(true); };
    if ($("#gs_yt")) $("#gs_yt").onclick = guard(async () => { const r = await api("/api/youtube/connect", {method: "POST"}); location.href = r.url; });
    const waiting = v.filter(x => x.status === "uploaded" || x.status === "rendered").length;
    const kpi = (ic, tone, n, l, href) => `<${href ? `a href="${href}"` : "div"} class="card kpi"><span class="ic ${tone}">${svg(ic)}</span><div><div class="n">${n}</div><div class="l">${l}</div></div></${href ? "a" : "div"}>`;
    $("#kpis").innerHTML = kpi("inbox", waiting ? "warn" : "ok", waiting, "Waiting for your decision", "#/videos") + kpi("globeok", "ok", vs.public || 0, "Live on YouTube", "#/videos") +
      kpi("film", "info", tot, "Videos made", "#/videos") + kpi("alert", (s.jobs_by_status.failed || 0) ? "bad" : "ok", s.jobs_by_status.failed || 0, "Failed runs", "#/create");
    const run = jobs.find(j => j.status === "running");
    $("#banner").innerHTML = run ? `<div class="banner"><div class="spin"></div><div>Working now: <b>${esc(run.mode.replace("auto-", ""))}</b> ${sc.running && sc.running.game ? "· " + esc(sc.running.game) : ""}</div><a href="#" id="seeprog" style="margin-left:auto">See progress</a></div>` : "";
    if ($("#seeprog")) $("#seeprog").onclick = e => { e.preventDefault(); openProgress(run.id); };
    const now = new Date(sc.now).getTime(), tz = sc.timezone;
    $("#nextup").innerHTML = sc.upcoming.length ? sc.upcoming.slice(0, 4).map(u => `<div class="it"><span class="when">${new Date(u.at).toLocaleTimeString("en-GB", {timeZone: tz, hour: "2-digit", minute: "2-digit"})}</span>
      <div style="flex:1"><b>${esc(u.game || "-")}</b><div class="muted" style="font-size:12.5px">${kindLabel(u.kind === "shorts" ? "short" : u.kind)} · in ${relTime(new Date(u.at) - now)}</div></div></div>`).join("") : `<div class="muted">Nothing scheduled.</div>`;
    const checks = [["Database", h.mongo.ok, "MongoDB is not reachable", "#/settings"], ["Video engine (FFmpeg)", h.ffmpeg, "FFmpeg not found", "#/settings"],
      ["Gemini (commentary)", h.keys.gemini, "Add the Gemini key", "#/settings"], ["Twitch keys", h.keys.twitch, "Needed for Twitch clips & live chat", "#/settings"],
      ["Email alerts", h.email, "Set up SMTP to get approval emails", "#/settings"], ["YouTube downloads", !h.yt_blocked, "YouTube is refusing this server: check the proxy (Settings → YouTube access)", "#/settings"], ["Music tracks", h.music_tracks > 0, "Upload royalty-free music", "#/settings"]];
    const todo = ME.role === "owner" ? checks.filter(c => !c[1]) : [];
    $("#setup").innerHTML = todo.length ? `<div class="checklist">${todo.map(c => `<div class="it"><span class="dot warn"></span><div class="t"><b>${c[0]}</b><span>${c[2]}</span></div><a href="${c[3]}">Fix</a></div>`).join("")}</div>`
      : `<div class="allclear"><span class="ic">${svg("check")}</span><div><b style="color:var(--text)">All set</b><div>Everything needed is connected.</div></div></div>`;
    $("#latest").innerHTML = v.length ? `<div class="vgrid">${v.slice(0, 6).map(vcard).join("")}</div>` : emptyState("film", "No videos yet", "Start your first one on the Create page.");
    bindVcards($("#latest"));
    renderApprovals(v.filter(x => x.status === "uploaded" || x.status === "rendered"));
  };
  await load();
  timer = setInterval(() => load().catch(() => {}), 5000);
}

function renderApprovals(list) {
  const box = $("#approvals"); if (!box || box.dataset.busy) return;
  const sig = list.map(x => x.id).join(",");
  if (box.dataset.sig === sig) return;
  box.dataset.sig = sig;
  box.innerHTML = list.length ? `<section class="card" style="border-color:var(--warn)"><div class="sechead"><h2>Waiting for your decision (${list.length})</h2></div>
    <p class="muted" style="margin:-4px 0 6px">Approve puts the video on YouTube as <b>Public</b> right away (a video that is only rendered is uploaded first). Decline discards it.</p>
    ${list.map(v => `<div class="approve"><img data-open="${v.id}" src="/media/${v.id}/thumb" alt="">
      <div style="min-width:0"><b>${esc(v.title)}</b><div class="muted">${esc(v.game_name || "")} · ${kindLabel(v.kind)} · ${v.youtube_id ? "on YouTube as Unlisted" : "not on YouTube yet"}</div>
        <div style="margin-top:6px">${v.youtube_url ? `<a href="${esc(v.youtube_url)}" target="_blank" rel="noopener">Watch on YouTube</a> · ` : ""}<a href="#" data-open="${v.id}">Preview &amp; details</a></div></div>
      <div class="acts"><button class="pri" data-ap="${v.id}">${v.youtube_id ? "Approve &amp; publish" : "Approve &amp; upload"}</button><button class="dng" data-dc="${v.id}">Decline</button></div></div>`).join("")}</section>`
    : `<section class="card"><div class="allclear"><span class="ic">${svg("check")}</span><div><b style="color:var(--text)">You're all caught up</b><div>New videos appear here the moment they are ready for your decision.</div></div></div></section>`;
  const act = (attr, path, ask, doing) => box.querySelectorAll(`[${attr}]`).forEach(b => b.onclick = async () => {
    if (!confirm(typeof ask === "function" ? ask(b.getAttribute(attr)) : ask)) return;
    box.dataset.busy = "1"; b.disabled = true; b.textContent = doing;
    try { const r = await api(`/api/videos/${b.getAttribute(attr)}/${path}`, {method: "POST"}); toast(r.message); }
    catch (e) { toast(e.message, true); }
    delete box.dataset.busy; box.dataset.sig = ""; nav();
  });
  act("data-ap", "publish", id => riskAsk(list.find(x => x.id === id), "Put this video on YouTube as PUBLIC now? (A rendered video is uploaded first and that can take a few minutes.)"), "Working…");
  act("data-dc", "decline", "Decline this video? It will never be published.", "Declining…");
  box.querySelectorAll("[data-open]").forEach(a => a.onclick = e => { e.preventDefault(); openVideo(a.dataset.open); });
}

