/* Edit projects: a timeline of several clips. The list of projects, and the project editor (media, preview, timeline, inspector, render). */
"use strict";
const PJ_FITS = [["crop", "Fill the screen (crop)"], ["blur", "Whole picture on a blurred background"], ["whole", "Whole picture with black bars"], ["split", "Split screen: face camera on top (vertical only)"]];
const PJ_ASPECTS = [["9:16", "Vertical 9:16 (Shorts, TikTok, Reels)"], ["16:9", "Wide 16:9 (YouTube)"], ["4:5", "Portrait 4:5 (Instagram)"]];
const PJ_TRANS = [["none", "Cut (no transition)"], ["fade", "Fade"], ["dissolve", "Dissolve"], ["slideleft", "Slide"], ["wipeleft", "Wipe"], ["circleopen", "Circle open"]];
const PJ_LOOKS = [["none", "No colour change"], ["warm", "Warm"], ["cool", "Cool"], ["vivid", "Vivid"], ["bw", "Black and white"], ["vintage", "Vintage"], ["cinematic", "Cinematic"], ["bright", "Bright"]];
const PJ_CSSLOOK = {warm: "sepia(.25) saturate(1.2) hue-rotate(-8deg)", cool: "hue-rotate(14deg) saturate(1.1)", vivid: "saturate(1.5) contrast(1.08)", bw: "grayscale(1) contrast(1.1)", vintage: "sepia(.5) contrast(1.1)", cinematic: "contrast(1.2) saturate(.9)", bright: "brightness(1.06) contrast(1.05) saturate(1.1)"};
const pjFilter = l => l ? `${PJ_CSSLOOK[l.preset] || ""} brightness(${(1 + (l.brightness || 0)).toFixed(2)}) contrast(${l.contrast || 1}) saturate(${l.saturation === undefined ? 1 : l.saturation})`.trim() : "";
const PJ_TEMPLATES = {
  classic: ["Classic", {color: "#ffffff", bold: true, italic: false, upper: false, outline: "#000000", ow: 4, shadow: 1, bg: "", anim: "none", size: 64}],
  pop: ["Bold pop", {color: "#ffe600", bold: true, italic: false, upper: true, outline: "#000000", ow: 8, shadow: 2, bg: "", anim: "pop", size: 96}],
  boxed: ["Boxed", {color: "#ffffff", bold: true, italic: false, upper: false, outline: "#000000", ow: 0, shadow: 0, bg: "#000000", anim: "fade", size: 64}],
  neon: ["Neon", {color: "#00f0ff", bold: true, italic: false, upper: true, outline: "#0040ff", ow: 6, shadow: 0, bg: "", anim: "fade", size: 64}],
  title: ["Big title", {color: "#ffffff", bold: true, italic: false, upper: true, outline: "#000000", ow: 6, shadow: 2, bg: "", anim: "fade", size: 96, y: 0.5}],
  lower: ["Lower third", {color: "#ffffff", bold: true, italic: false, upper: false, outline: "#000000", ow: 0, shadow: 0, bg: "#e8590c", anim: "fade", size: 44, y: 0.88}],
};
const PJ_ANIMS = [["none", "No animation"], ["fade", "Fade in and out"], ["pop", "Pop in"]];
const PJ_SIZES = [["Small", 44], ["Medium", 64], ["Large", 96]];
const PJ_PLACES = [["Top", 0.15], ["Middle", 0.5], ["Bottom", 0.85]];
const pjFmt = (t, dec) => { t = Math.max(0, t || 0); const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${(dec ? s.toFixed(1) : String(Math.floor(s))).padStart(dec ? 4 : 2, "0")}`; };
const pjId = () => Math.random().toString(36).slice(2, 10);

async function projects() {
  const id = (location.hash.replace("#/", "").split("/")[1] || "");
  return id ? projectEditor(id) : projectList();
}

/* ------------------------------------------------------------ the list */
async function projectList() {
  $("#main").innerHTML = `<h1>Edit projects</h1>
    <div class="toolbar"><button class="pri" id="pjnew">New project</button><span class="muted" id="pjcount"></span></div><div id="pjgrid"></div>`;
  const load = guard(async () => {
    const d = await api("/api/editor/projects");
    $("#pjcount").textContent = `${d.projects.length} of ${d.max} projects`;
    $("#pjgrid").innerHTML = d.projects.length ? `<div class="pjcards">${d.projects.map(p => `<div class="card pjcard" data-id="${p.id}"><b>${esc(p.title)}</b>
        <div class="muted">${p.clips} clip${p.clips === 1 ? "" : "s"} · ${pjFmt(p.seconds)} · ${esc(p.aspect)}</div><div class="muted" style="font-size:12.5px">Changed ${when(p.updated_at)}</div>
        <div class="row" style="gap:8px;margin-top:10px"><a class="btn pri" href="#/projects/${p.id}">Open</a><button data-a="copy">Copy</button><button class="dng" data-a="del">Delete</button></div></div>`).join("")}</div>`
      : `<div class="card">${emptyState("film", "No projects yet", "Press New project to start your first timeline.")}</div>`;
    $("#pjgrid").querySelectorAll(".pjcard").forEach(card => card.querySelectorAll("button[data-a]").forEach(b => b.onclick = guard(async () => {
      const pid = card.dataset.id;
      if (b.dataset.a === "copy") { await api(`/api/editor/projects/${pid}/copy`, {method: "POST"}); toast("Copied"); }
      else { if (!confirm("Delete this project? The videos you added stay in your editor.")) return; await api(`/api/editor/projects/${pid}`, {method: "DELETE"}); toast("Deleted"); }
      load();
    })));
  });
  $("#pjnew").onclick = guard(async () => { const p = await api("/api/editor/projects", {method: "POST", body: {title: "My project"}}); location.hash = `#/projects/${p.id}`; });
  await load();
}

/* ------------------------------------------------------------ the editor */
async function projectEditor(pid) {
  let P;
  try { P = await api(`/api/editor/projects/${pid}`); } catch (e) { $("#main").innerHTML = `<div class="card">${emptyState("alert", "Project not found", "It may have been deleted. <a href='#/projects'>Back to your projects</a>")}</div>`; return; }
  let sel = null, playhead = 0, playing = false, pxs = 40, saveTimer = null, saving = false, dirty = false, conflict = false, stateMsg = "Saved";
  const undo = [], redo = [];
  const clips = () => P.data.clips;
  const spd = c => Math.max(0.25, c.speed || 1);
  const outLen = c => (c.end - c.start) / spd(c);
  const total = () => clips().reduce((a, c) => a + outLen(c), 0);
  const offsets = () => { let o = 0; return clips().map(c => { const s = o; o += outLen(c); return s; }); };
  const src = {}; let media = [], audioLib = {library: [], mine: []}, imgLib = {images: []};
  const music = () => (P.data.audio || {}).music || null;
  const info = c => src[c.source] || media.find(m => m.id === c.source) || {title: "Video", duration: c.end, width: 0, height: 0};
  const frameRatio = () => ({"9:16": "9/16", "16:9": "16/9", "4:5": "4/5"}[P.data.aspect] || "9/16");

  $("#main").innerHTML = `<div class="pj nopk">
    <div class="pjtop"><a class="btn" href="#/projects">← Projects</a><input id="pj_title" maxlength="100" value="${esc(P.title)}" aria-label="Project name">
      <span class="muted" id="pj_state"></span><span class="grow"></span><button id="pj_undo" title="Undo (Ctrl+Z)">Undo</button><button id="pj_redo" title="Redo (Ctrl+Y)">Redo</button>
      <select id="pj_aspect" title="Screen shape of the finished video">${PJ_ASPECTS.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}</select><button class="pri" id="pj_make">Make video</button></div>
    <div id="pj_conflict" class="authmsg bad" hidden>This project was changed somewhere else (another tab or device). <button id="pj_reload">Load the newest version</button></div>
    <div class="pjmain">
      <aside class="pjbin card"><h3>Your videos</h3><p class="muted" style="font-size:12.5px;margin:0 0 8px">Press Add to put a video on the timeline.</p><div id="pj_media" class="pjmedia"></div>
        <div class="row" style="gap:8px;margin-top:10px;flex-wrap:wrap"><label class="btn" for="pj_file" style="cursor:pointer">Upload a video</label><input type="file" id="pj_file" accept="video/*" hidden></div>
        <label style="margin-top:12px">Or use one of my finished videos</label><div class="row" style="gap:6px"><select id="pj_mine" class="grow"><option value="">Choose…</option></select><button id="pj_minego">Add</button></div></aside>
      <section class="pjprev card"><div class="pjstage"><div class="pjframe" id="pj_frame" style="aspect-ratio:${frameRatio()}"><video id="pj_v" playsinline preload="auto"></video><div id="pj_txt"></div><div class="pjempty" id="pj_empty">Add a video to start</div></div></div>
        <div class="pjtrans"><button id="pj_play" class="pri">Play</button><span class="muted" id="pj_time">0:00 / 0:00</span><span class="muted" style="font-size:12px">The preview is close to the result, not exact.</span></div></section>
      <aside class="pjins card" id="pj_ins"></aside></div>
    <div class="pjtl card"><div class="pjtlbar"><button id="pj_split" title="Cut the clip at the playhead">Split at playhead</button><button id="pj_dup">Duplicate</button><button id="pj_del" class="dng">Delete clip</button>
      <span class="grow"></span><label style="margin:0">Zoom</label><input type="range" id="pj_zoom" min="12" max="120" value="40" style="width:140px"></div>
      <div class="pjscroll"><div class="pjtrack" id="pj_track"></div></div></div>
    <div class="pjmu card" id="pj_music"></div><audio id="pj_a" preload="auto" hidden></audio>
    <div id="pj_render"></div></div>`;
  $("#pj_aspect").value = P.data.aspect;
  const v = $("#pj_v");

  /* ---- saving */
  const setState = m => { stateMsg = m; $("#pj_state").textContent = m; };
  const markDirty = () => { dirty = true; setState("Unsaved…"); clearTimeout(saveTimer); saveTimer = setTimeout(saveNow, 1200); };
  async function saveNow() {
    clearTimeout(saveTimer);
    if (saving || conflict || !dirty) return;
    saving = true; dirty = false; setState("Saving…");
    try {
      const r = await api(`/api/editor/projects/${pid}`, {method: "PUT", body: {version: P.version, title: P.title, data: P.data}});
      P.version = r.version; setState(dirty ? "Unsaved…" : "Saved");
    } catch (e) {
      if (/changed somewhere else/.test(e.message)) { conflict = true; $("#pj_conflict").hidden = false; setState("Not saved"); }
      else { dirty = true; setState("Not saved: " + e.message); }
    }
    saving = false;
    if (dirty && !conflict && !/Not saved/.test(stateMsg)) saveTimer = setTimeout(saveNow, 400);
  }
  $("#pj_reload").onclick = () => location.reload();
  const change = fn => { undo.push(JSON.stringify(P.data)); if (undo.length > 80) undo.shift(); redo.length = 0; fn(); markDirty(); drawAll(); };
  const doUndo = () => { if (!undo.length) return; redo.push(JSON.stringify(P.data)); P.data = JSON.parse(undo.pop()); if (!clips().some(c => c.id === sel)) sel = null; markDirty(); drawAll(); };
  const doRedo = () => { if (!redo.length) return; undo.push(JSON.stringify(P.data)); P.data = JSON.parse(redo.pop()); if (!clips().some(c => c.id === sel)) sel = null; markDirty(); drawAll(); };
  $("#pj_undo").onclick = doUndo; $("#pj_redo").onclick = doRedo;
  $("#pj_title").onchange = () => { P.title = $("#pj_title").value.trim() || "My project"; markDirty(); };
  $("#pj_aspect").onchange = () => change(() => { P.data.aspect = $("#pj_aspect").value; if (P.data.aspect !== "9:16") clips().forEach(c => { if (c.fit === "split") c.fit = "crop"; }); });
  const keys = e => {
    if (!$("#pj_v")) return removeEventListener("keydown", keys);
    if (/INPUT|TEXTAREA|SELECT/.test((e.target || {}).tagName || "")) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? doRedo() : doUndo(); }
    else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); doRedo(); }
    else if (e.key === " ") { e.preventDefault(); togglePlay(); }
    else if (e.key === "Delete" && sel) delClip();
  };
  addEventListener("keydown", keys);
  const leave = () => { if (location.hash.indexOf(`#/projects/${pid}`) !== 0) { removeEventListener("hashchange", leave); removeEventListener("keydown", keys); removeEventListener("beforeunload", warn); if (dirty && !conflict) saveNow(); v.pause && v.pause(); } };
  const warn = e => { if (dirty || saving) { e.preventDefault(); e.returnValue = ""; } };
  addEventListener("hashchange", leave); addEventListener("beforeunload", warn);

  /* ---- the media bin */
  const loadMedia = guard(async () => {
    const d = await api("/api/editor/sources"); media = d.sources; media.forEach(m => src[m.id] = m);
    $("#pj_media").innerHTML = media.length ? media.map(m => `<div class="pjm"><div class="grow" style="min-width:0"><b class="pjmt">${esc(m.title)}</b><span class="muted">${pjFmt(m.duration)} · ${m.width}×${m.height}</span></div><button data-add="${m.id}">Add</button></div>`).join("")
      : `<div class="muted">No videos yet. Upload one, or pick one of your finished videos below.</div>`;
    $("#pj_media").querySelectorAll("[data-add]").forEach(b => b.onclick = () => addClip(b.dataset.add));
  });
  const loadImages = guard(async () => { imgLib = await api("/api/editor/images"); drawInspector(); });
  const loadAudio = guard(async () => { audioLib = await api("/api/editor/audio"); drawMusic(); });
  const loadMine = guard(async () => {
    const list = (await api("/api/videos")).filter(x => !["failed", "discarded", "declined"].includes(x.status)).slice(0, 40);
    $("#pj_mine").innerHTML = `<option value="">Choose…</option>` + list.map(x => `<option value="${x.id}">${esc((x.title || "").slice(0, 60))}</option>`).join("");
  });
  const addClip = sid => {
    const m = src[sid]; if (!m) return;
    change(() => { const c = {id: pjId(), source: sid, start: 0, end: Math.round(m.duration * 100) / 100, fit: "crop", focus: m.face ? {x: m.face.x, y: m.face.y} : {x: 0.5, y: 0.5}, cam: null, captions: false, volume: 1, fade_in: 0, fade_out: 0, speed: 1, zoom: null, transition: {type: "none", duration: 0.6}, look: {preset: "none", brightness: 0, contrast: 1, saturation: 1}, pip: null, overlays: [], texts: []}; clips().push(c); sel = c.id; });
    if (clips().length === 1) seek(0);
  };
  $("#pj_file").onchange = guard(async () => {
    const f = $("#pj_file").files[0]; if (!f) return;
    toast("Uploading…"); const r = await api(`/api/editor/sources/upload?name=${encodeURIComponent(f.name)}`, {method: "POST", body: f, raw: true});
    src[r.source.id] = r.source; $("#pj_file").value = ""; await loadMedia(); addClip(r.source.id);
  });
  $("#pj_minego").onclick = guard(async () => {
    const vid = $("#pj_mine").value; if (!vid) return toast("Choose a video first", true);
    const r = await api("/api/editor/from-video", {method: "POST", body: {video_id: vid}}); src[r.source.id] = r.source; await loadMedia(); addClip(r.source.id);
  });

  /* ---- clip actions */
  const cur = () => clips().find(c => c.id === sel);
  const delClip = () => { if (!cur()) return toast("Click a clip first", true); change(() => { P.data.clips = clips().filter(c => c.id !== sel); sel = null; }); seek(Math.min(playhead, total())); };
  const dupClip = () => { const c = cur(); if (!c) return toast("Click a clip first", true); change(() => { const n = JSON.parse(JSON.stringify(c)); n.id = pjId(); clips().splice(clips().indexOf(c) + 1, 0, n); sel = n.id; }); };
  const splitClip = () => {
    const o = offsets(), i = clips().findIndex((c, k) => playhead > o[k] + 0.3 && playhead < o[k] + outLen(c) - 0.3);
    if (i < 0) return toast("Move the playhead into a clip (not at its very start or end) to split it.", true);
    change(() => {
      const c = clips()[i], at = Math.round((c.start + (playhead - o[i]) * spd(c)) * 100) / 100, a = JSON.parse(JSON.stringify(c)), b = JSON.parse(JSON.stringify(c));
      a.end = at; b.start = at; b.id = pjId();
      const rel = at - c.start; a.texts = c.texts.filter(t => t.t0 < rel).map(t => ({...t, t1: Math.min(t.t1, rel)}));
      b.texts = c.texts.filter(t => t.t1 > rel).map(t => ({...t, t0: Math.max(0, t.t0 - rel), t1: t.t1 - rel}));
      a.overlays = (c.overlays || []).filter(o => o.t0 < rel).map(o => ({...o, t1: Math.min(o.t1, rel)}));
      b.overlays = (c.overlays || []).filter(o => o.t1 > rel).map(o => ({...o, id: pjId(), t0: Math.max(0, o.t0 - rel), t1: o.t1 - rel}));
      clips().splice(i, 1, a, b); sel = b.id;
    });
  };
  $("#pj_split").onclick = splitClip; $("#pj_dup").onclick = dupClip; $("#pj_del").onclick = delClip;
  $("#pj_zoom").oninput = () => { pxs = +$("#pj_zoom").value; drawTimeline(); };

  /* ---- preview */
  const url = c => `/api/editor/sources/${c.source}/video`;
  const clipAt = t => { const o = offsets(); for (let i = clips().length - 1; i >= 0; i--) if (t >= o[i] - 1e-6) return i; return 0; };
  let loaded = null, curIdx = -1;
  const applyFit = c => {
    const f = c.fit === "crop" || c.fit === "split" ? "cover" : "contain";
    v.volume = Math.max(0, Math.min(1, c.volume === undefined ? 1 : c.volume)); v.playbackRate = spd(c); v.style.filter = pjFilter(c.look);
    v.style.objectFit = f; v.style.objectPosition = c.fit === "crop" ? `${(c.focus.x * 100).toFixed(0)}% ${(c.focus.y * 100).toFixed(0)}%` : "50% 50%";
  };
  const applyZoom = (c, prog) => {
    const z = c.zoom; if (!z) { v.style.transform = ""; return; }
    const p = Math.max(0, Math.min(1, prog)); v.style.transformOrigin = `${z.x * 100}% ${z.y * 100}%`; v.style.transform = `scale(${(z.from + (z.to - z.from) * p).toFixed(3)})`;
  };
  function showAt(i, within, autoplay) {
    const c = clips()[i]; if (!c) return;
    curIdx = i; applyFit(c); applyZoom(c, within * spd(c) / Math.max(0.1, c.end - c.start));
    const go = () => { v.currentTime = c.start + within * spd(c); if (autoplay) v.play().catch(() => {}); };
    if (loaded !== url(c)) { loaded = url(c); v.src = loaded; v.onloadedmetadata = () => { go(); v.onloadedmetadata = null; }; } else go();
  }
  function seek(t) {
    t = Math.max(0, Math.min(total(), t)); playhead = t;
    if (!clips().length) { v.removeAttribute("src"); loaded = null; drawTime(); drawTimeline(); return; }
    const i = clipAt(Math.min(t, total() - 0.01)); showAt(i, Math.max(0, t - offsets()[i]), playing); drawTime(); drawTimeline();
  }
  function tick() {
    if (!playing) return;
    const c = clips()[curIdx]; if (!c) return stop();
    if (v.currentTime >= c.end - 0.04 || v.ended) {
      if (curIdx + 1 < clips().length) { const n = clips()[curIdx + 1]; curIdx++; applyFit(n); if (loaded === url(n)) { v.currentTime = n.start; } else { loaded = url(n); v.src = loaded; v.onloadedmetadata = () => { v.currentTime = n.start; v.play().catch(() => {}); v.onloadedmetadata = null; }; } }
      else { stop(); playhead = total(); drawTime(); drawTimeline(); return; }
    }
    const k = clips()[curIdx]; playhead = offsets()[curIdx] + Math.max(0, v.currentTime - k.start) / spd(k); applyZoom(k, (v.currentTime - k.start) / Math.max(0.1, k.end - k.start)); drawTime(); drawPlayhead(); drawText(); requestAnimationFrame(tick);
  }
  const au = $("#pj_a"); let auRef = "";
  function musicPlay() {
    const m = music(); if (!m) return au.pause();
    if (auRef !== m.ref) { auRef = m.ref; au.src = `/api/editor/audio/file?ref=${encodeURIComponent(m.ref)}`; }
    au.volume = Math.max(0, Math.min(1, m.volume)); au.loop = !!m.loop;
    const go = () => { au.currentTime = m.start + playhead; au.play().catch(() => {}); };
    au.readyState >= 1 ? go() : au.addEventListener("loadedmetadata", go, {once: true});
  }
  function stop() { playing = false; v.pause(); au.pause(); $("#pj_play").textContent = "Play"; }
  function togglePlay() {
    if (!clips().length) return;
    if (playing) return stop();
    if (playhead >= total() - 0.05) playhead = 0;
    playing = true; $("#pj_play").textContent = "Pause"; const i = clipAt(playhead); showAt(i, playhead - offsets()[i], true); musicPlay(); requestAnimationFrame(tick);
  }
  $("#pj_play").onclick = togglePlay;
  const drawTime = () => { $("#pj_time").textContent = `${pjFmt(playhead, 1)} / ${pjFmt(total(), 1)}`; };
  function drawText() {
    const i = clipAt(playhead), c = clips()[i], box = $("#pj_txt"); box.innerHTML = "";
    if (!c) return;
    const rel = (playhead - offsets()[i]) * spd(c), fw = $("#pj_frame").clientWidth || 1, wide = P.data.aspect === "16:9";
    (c.overlays || []).filter(o => rel >= o.t0 && rel < o.t1).forEach(o => {
      const d = document.createElement("img"); d.className = "pjsticker"; d.alt = ""; d.src = `/api/editor/images/file?ref=${encodeURIComponent(o.ref)}`;
      d.style.width = `${o.scale * 100}%`; d.style.left = `${o.x * (100 - o.scale * 100)}%`; d.style.opacity = o.opacity;
      const place = () => { d.style.top = `${Math.max(0, (box.clientHeight - d.offsetHeight) * o.y)}px`; };
      d.onload = place; box.appendChild(d); if (d.complete) place();
    });
    const k = fw * (wide ? 1.6 / 1920 : 1 / 1080);
    c.texts.filter(t => rel >= t.t0 && rel < t.t1).forEach(t => {
      const d = document.createElement("div"); d.className = "pjtext"; d.textContent = t.upper ? t.text.toUpperCase() : t.text; d.style.left = `${t.x * 100}%`; d.style.top = `${t.y * 100}%`; d.style.color = t.color;
      d.style.fontSize = `${Math.max(9, t.size * k)}px`; d.style.fontWeight = t.bold === false ? 400 : 800; d.style.fontStyle = t.italic ? "italic" : "normal";
      if (t.bg) { d.style.background = t.bg; d.style.padding = "0.15em 0.5em"; d.style.borderRadius = "0.15em"; d.style.textShadow = "none"; }
      else { d.style.webkitTextStroke = `${(t.ow === undefined ? 4 : t.ow) * k * 1.6}px ${t.outline || "#000"}`; d.style.paintOrder = "stroke fill"; d.style.textShadow = t.shadow ? `${t.shadow * k}px ${t.shadow * k}px 0 rgba(0,0,0,.6)` : "none"; }
      box.appendChild(d);
    });
  }

  /* ---- timeline */
  function drawPlayhead() { const ph = $("#pj_ph"); if (ph) ph.style.left = `${playhead * pxs}px`; }
  function drawTimeline() {
    const tr = $("#pj_track"), o = offsets(), w = Math.max(total() * pxs + 80, 400);
    tr.style.width = `${w}px`; tr.style.height = music() ? "132px" : "104px";
    tr.innerHTML = `<div class="pjruler">${Array.from({length: Math.ceil(w / pxs / (pxs < 25 ? 10 : 5)) + 1}, (_, k) => { const s = k * (pxs < 25 ? 10 : 5); return `<span style="left:${s * pxs}px">${pjFmt(s)}</span>`; }).join("")}</div>
      ${music() ? `<div class="pjmbar" style="width:${Math.max(40, total() * pxs)}px" title="Music">♪ ${esc(musicName(music().ref))}</div>` : ""}
      <div class="pjclips">${clips().map((c, i) => { const inf = info(c), wpx = Math.max(34, outLen(c) * pxs); return `<div class="pjclip ${c.id === sel ? "on" : ""}" data-id="${c.id}" style="left:${o[i] * pxs}px;width:${wpx}px" title="${esc(inf.title)}">
        <i class="pjh l" data-h="l"></i><span class="pjct">${esc(inf.title)}</span><span class="pjcd">${pjFmt(outLen(c), 1)}${spd(c) !== 1 ? ` · ${+spd(c).toFixed(2)}x` : ""}${c.zoom ? " · Z" : ""}${i > 0 && c.transition && c.transition.type !== "none" ? " · ⇄" : ""}${c.texts.length ? " · T" : ""}${c.captions ? " · CC" : ""}</span><i class="pjh r" data-h="r"></i></div>`; }).join("")}</div><div class="pjph" id="pj_ph" style="left:${playhead * pxs}px"></div>`;
    tr.querySelectorAll(".pjclip").forEach(el => el.addEventListener("pointerdown", e => clipPointer(e, el)));
    tr.querySelector(".pjruler").addEventListener("pointerdown", e => scrub(e));
  }
  function scrub(e) {
    const tr = $("#pj_track"), at = ev => { const r = tr.getBoundingClientRect(); stop(); seek((ev.clientX - r.left) / pxs); };
    at(e); const mv = ev => at(ev), up = () => { removeEventListener("pointermove", mv); removeEventListener("pointerup", up); };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  }
  function clipPointer(e, el) {
    const c = clips().find(x => x.id === el.dataset.id); if (!c) return;
    const handle = e.target.dataset ? e.target.dataset.h : null, x0 = e.clientX, inf = info(c), snap0 = JSON.stringify(P.data);
    const o0 = {start: c.start, end: c.end}; let moved = false, dropAt = null;
    sel = c.id; drawInspector(); document.querySelectorAll(".pjclip").forEach(x => x.classList.toggle("on", x.dataset.id === sel));
    const mv = ev => {
      const dx = ev.clientX - x0; if (Math.abs(dx) > 3) moved = true; if (!moved) return;
      if (handle === "l") { c.start = Math.max(0, Math.min(o0.end - 0.3, o0.start + dx / pxs * spd(c))); drawTimeline(); }
      else if (handle === "r") { c.end = Math.max(o0.start + 0.3, Math.min(inf.duration || o0.end, o0.end + dx / pxs * spd(c))); drawTimeline(); }
      else { const tr = $("#pj_track").getBoundingClientRect(), t = (ev.clientX - tr.left) / pxs, o = offsets(); let to = 0; clips().forEach((k, i) => { if (k !== c && t > o[i] + outLen(k) / 2) to = clips().indexOf(k) + 1; }); dropAt = to; el.style.opacity = ".6"; el.style.transform = `translateX(${dx}px)`; }
    };
    const up = () => {
      removeEventListener("pointermove", mv); removeEventListener("pointerup", up);
      if (!moved) { seekToClip(c); return; }
      if (handle) { c.start = Math.round(c.start * 100) / 100; c.end = Math.round(c.end * 100) / 100; if (c.start !== o0.start || c.end !== o0.end) { undo.push(snap0); redo.length = 0; markDirty(); } seek(Math.min(playhead, total())); drawAll(); }
      else if (dropAt !== null) { const from = clips().indexOf(c); if (dropAt !== from && dropAt !== from + 1) { undo.push(snap0); redo.length = 0; clips().splice(from, 1); clips().splice(dropAt > from ? dropAt - 1 : dropAt, 0, c); markDirty(); } drawAll(); }
      else drawAll();
    };
    addEventListener("pointermove", mv); addEventListener("pointerup", up);
  }
  const seekToClip = c => { stop(); seek(offsets()[clips().indexOf(c)]); drawInspector(); };

  /* ---- inspector */
  const pjOpen = new Set(["Text on this clip"]);          // which settings sections are unfolded (kept while the member works)
function pjFold(box) {
  box.querySelectorAll('h3[style*="margin-top:14px"]').forEach(h => {
    const d = document.createElement("details"); d.className = "pjsec"; d.open = pjOpen.has(h.textContent.trim());
    const sm = document.createElement("summary"); sm.textContent = h.textContent.trim(); d.appendChild(sm);
    const rest = []; let n = h.nextSibling; while (n && !(n.nodeType === 1 && n.matches && n.matches('h3[style*="margin-top:14px"]'))) { rest.push(n); n = n.nextSibling; }
    h.replaceWith(d); rest.forEach(x => d.appendChild(x));
    d.addEventListener("toggle", () => { d.open ? pjOpen.add(sm.textContent) : pjOpen.delete(sm.textContent); });
  });
}
function drawInspector() {
    const box = $("#pj_ins"), c = cur();
    if (!c) { box.innerHTML = `<h3>Clip</h3><p class="muted">Click a clip on the timeline to change it: trim it, choose how it fills the screen, add captions or text.</p><p class="muted">Drag a clip to move it. Drag its edges to trim it. Click the ruler to move the playhead.</p>`; return; }
    const inf = info(c), split = P.data.aspect === "9:16", lk = c.look || {};
    const zk = !c.zoom ? "none" : (c.zoom.from <= 1.001 && c.zoom.to > 1) ? "in" : (c.zoom.from > 1 && c.zoom.to <= 1.001) ? "out" : "punch";
    box.innerHTML = `<h3>${esc(inf.title)}</h3><div class="muted" style="margin-bottom:8px">The whole video is ${pjFmt(inf.duration, 1)} long.</div>
      <div class="row" style="gap:8px"><div class="grow"><label>Start (seconds)</label><input type="number" id="ci_s" step="0.1" min="0" value="${c.start}"></div><div class="grow"><label>End (seconds)</label><input type="number" id="ci_e" step="0.1" min="0" value="${c.end}"></div></div>
      <label>How it fills the screen</label><select id="ci_fit">${PJ_FITS.filter(([k]) => k !== "split" || split).map(([k, t]) => `<option value="${k}" ${c.fit === k ? "selected" : ""}>${t}</option>`).join("")}</select>
      ${c.fit === "crop" ? `<div class="row" style="gap:8px"><div class="grow"><label>Keep this side in view (left to right)</label><input type="range" id="ci_fx" min="0" max="1" step="0.01" value="${c.focus.x}"></div><div class="grow"><label>(top to bottom)</label><input type="range" id="ci_fy" min="0" max="1" step="0.01" value="${c.focus.y}"></div></div>` : ""}
      <label style="display:flex;gap:8px;align-items:flex-start;margin-top:10px;white-space:normal;line-height:1.35"><input type="checkbox" id="ci_cc" style="width:auto;flex:none;margin-top:2px" ${c.captions ? "checked" : ""}><span>Captions from the speech (adds time when making the video)</span></label>
      <h3 style="margin-top:14px">Sound</h3><label style="margin-top:10px">Sound of this clip: <b id="ci_vl">${Math.round((c.volume === undefined ? 1 : c.volume) * 100)}%</b></label><input type="range" id="ci_vol" min="0" max="200" step="5" value="${Math.round((c.volume === undefined ? 1 : c.volume) * 100)}">
      <div class="row" style="gap:8px"><div class="grow"><label>Fade in (seconds)</label><input type="number" id="ci_fi" min="0" step="0.1" value="${c.fade_in || 0}"></div><div class="grow"><label>Fade out (seconds)</label><input type="number" id="ci_fo" min="0" step="0.1" value="${c.fade_out || 0}"></div></div>
      <h3 style="margin-top:14px">Speed</h3>
      <label>Speed: <b id="ci_spl">${spd(c).toFixed(2)}x</b> <span class="muted" id="ci_spn">(${pjFmt(outLen(c), 1)} in the video)</span></label><input type="range" id="ci_sp" min="25" max="400" step="5" value="${Math.round(spd(c) * 100)}">
      <div class="row" style="gap:6px;flex-wrap:wrap"><button data-sp="0.5">Slow 0.5x</button><button data-sp="1">Normal</button><button data-sp="2">Fast 2x</button></div>
      <h3 style="margin-top:14px">Zoom</h3>
      <select id="ci_zm"><option value="none" ${!c.zoom ? "selected" : ""}>No zoom</option><option value="in" ${zk === "in" ? "selected" : ""}>Slow zoom in</option><option value="out" ${zk === "out" ? "selected" : ""}>Slow zoom out</option><option value="punch" ${zk === "punch" ? "selected" : ""}>Punch in (stays zoomed)</option></select>
      ${c.zoom ? `<label>How much: <b id="ci_zal">${Math.round(Math.max(c.zoom.from, c.zoom.to) * 100)}%</b></label><input type="range" id="ci_za" min="110" max="300" step="5" value="${Math.round(Math.max(c.zoom.from, c.zoom.to) * 100)}">
        <div class="row" style="gap:8px"><div class="grow"><label>Aim (left to right)</label><input type="range" id="ci_zx" min="0" max="1" step="0.01" value="${c.zoom.x}"></div><div class="grow"><label>(top to bottom)</label><input type="range" id="ci_zy" min="0" max="1" step="0.01" value="${c.zoom.y}"></div></div>` : ""}
      ${clips().indexOf(c) > 0 ? `<h3 style="margin-top:14px">How this clip comes in</h3><select id="ci_tr">${PJ_TRANS.map(([k, t]) => `<option value="${k}" ${(c.transition || {}).type === k || (!c.transition && k === "none") ? "selected" : ""}>${t}</option>`).join("")}</select>
        ${c.transition && c.transition.type !== "none" ? `<label>Length: <b id="ci_tdl">${c.transition.duration}s</b></label><input type="range" id="ci_td" min="0.2" max="2" step="0.1" value="${c.transition.duration}"><div class="muted" style="font-size:12px">The clips overlap while they change, so the video gets a little shorter. The preview shows a plain cut.</div>` : ""}` : ""}
      <h3 style="margin-top:14px">Colour</h3>
      <select id="ci_lk">${PJ_LOOKS.map(([k, t]) => `<option value="${k}" ${(lk.preset || "none") === k ? "selected" : ""}>${t}</option>`).join("")}</select>
      <label>Brightness: <b id="ci_lbl">${Math.round((lk.brightness || 0) * 100)}</b></label><input type="range" id="ci_lb" min="-50" max="50" step="1" value="${Math.round((lk.brightness || 0) * 100)}">
      <label>Contrast: <b id="ci_lcl">${Math.round((lk.contrast || 1) * 100)}%</b></label><input type="range" id="ci_lc" min="50" max="200" step="5" value="${Math.round((lk.contrast || 1) * 100)}">
      <label>Colour strength: <b id="ci_lsl">${Math.round((lk.saturation === undefined ? 1 : lk.saturation) * 100)}%</b></label><input type="range" id="ci_ls" min="0" max="300" step="5" value="${Math.round((lk.saturation === undefined ? 1 : lk.saturation) * 100)}">
      <h3 style="margin-top:14px">Reaction in a corner</h3>
      <select id="ci_pip"><option value="">No reaction</option>${media.map(m => `<option value="${esc(m.id)}" ${c.pip && c.pip.source === m.id ? "selected" : ""}>${esc(m.title)} (${pjFmt(m.duration)})</option>`).join("")}</select>
      ${c.pip ? `<div class="muted" style="font-size:12px;margin:4px 0">Your reaction video plays in a small box over this clip. Its sound is not used. It shows in the finished video, not in the preview.</div>
        <label>Where</label><select id="ci_pc"><option value="1,0" ${c.pip.x === 1 && c.pip.y === 0 ? "selected" : ""}>Top right</option><option value="0,0" ${c.pip.x === 0 && c.pip.y === 0 ? "selected" : ""}>Top left</option><option value="1,1" ${c.pip.x === 1 && c.pip.y === 1 ? "selected" : ""}>Bottom right</option><option value="0,1" ${c.pip.x === 0 && c.pip.y === 1 ? "selected" : ""}>Bottom left</option></select>
        <label>Size: <b id="ci_psl">${Math.round(c.pip.scale * 100)}%</b></label><input type="range" id="ci_ps" min="10" max="60" step="1" value="${Math.round(c.pip.scale * 100)}">
        <div class="row" style="gap:6px;flex-wrap:wrap"><label style="margin:0">Shown from</label><input id="ci_p0" type="number" step="0.1" min="0" value="${c.pip.t0}" style="width:70px"><label style="margin:0">to</label><input id="ci_p1" type="number" step="0.1" min="0" value="${c.pip.t1}" style="width:70px"></div>
        <label>Start the reaction at (seconds into it)</label><input id="ci_pst" type="number" step="0.1" min="0" value="${c.pip.start}">
        <label class="pjchk" style="margin-top:8px"><input type="checkbox" id="ci_pb" ${c.pip.border ? "checked" : ""}><span>White border around it</span></label>` : ""}
      <h3 style="margin-top:14px">Stickers and logos</h3><div id="ci_ovs"></div>
      <div class="row" style="gap:8px;flex-wrap:wrap"><button id="ci_addov">Add a sticker</button><label class="btn" for="ci_img" style="cursor:pointer;margin:0">Upload a picture</label><input type="file" id="ci_img" accept="image/*" hidden></div>
      <div class="muted" style="font-size:12px;margin-top:4px">Your own pictures only (png, jpg, webp, gif up to ${imgLib.max_mb || 8} MB). Nobody else can use them.</div>
      <h3 style="margin-top:14px">Text on this clip</h3><div id="ci_texts"></div><div class="row" style="gap:8px;flex-wrap:wrap"><button id="ci_addtext">Add text</button><button id="ci_addcard" title="A short line at the start that tells viewers what they are seeing">Add context card</button><select id="ci_tmpl" style="max-width:170px" title="The look of the new text">${Object.entries(PJ_TEMPLATES).map(([k, [n]]) => `<option value="${k}">${n}</option>`).join("")}</select></div>`;
    pjFold(box);
    const texts = $("#ci_texts");
    texts.innerHTML = c.texts.map((t, i) => `<div class="pjtx" data-i="${i}"><input class="tt" value="${esc(t.text)}" maxlength="120" placeholder="Text">
      <div class="row" style="gap:6px;flex-wrap:wrap"><label style="margin:0">From</label><input class="t0" type="number" step="0.1" min="0" value="${t.t0}" style="width:70px"><label style="margin:0">to</label><input class="t1" type="number" step="0.1" min="0" value="${t.t1}" style="width:70px">
      <select class="ts">${PJ_SIZES.map(([n, s]) => `<option value="${s}" ${t.size === s ? "selected" : ""}>${n}</option>`).join("")}</select><select class="tp">${PJ_PLACES.map(([n, y]) => `<option value="${y}" ${Math.abs(t.y - y) < 0.01 ? "selected" : ""}>${n}</option>`).join("")}</select>
      <input class="tc" type="color" value="${t.color}" style="width:44px;height:34px;padding:2px;flex:none"><button class="dng td" title="Remove this text">✕</button></div>
      <div class="row" style="gap:6px;flex-wrap:wrap;margin-top:6px"><select class="tmpl"><option value="">Apply a style…</option>${Object.entries(PJ_TEMPLATES).map(([k, [n]]) => `<option value="${k}">${n}</option>`).join("")}</select>
        <select class="ta">${PJ_ANIMS.map(([k, n]) => `<option value="${k}" ${(t.anim || "none") === k ? "selected" : ""}>${n}</option>`).join("")}</select></div>
      <details style="margin-top:6px"><summary class="muted" style="cursor:pointer">More style</summary><div class="row" style="gap:10px;flex-wrap:wrap;margin-top:6px">
        <label class="pjchk"><input type="checkbox" class="tb" ${t.bold === false ? "" : "checked"}><span>Bold</span></label><label class="pjchk"><input type="checkbox" class="ti" ${t.italic ? "checked" : ""}><span>Italic</span></label><label class="pjchk"><input type="checkbox" class="tu" ${t.upper ? "checked" : ""}><span>CAPITALS</span></label>
        <label style="margin:0">Outline</label><input class="to" type="color" value="${t.outline || "#000000"}" style="width:40px;height:30px;padding:2px;flex:none"><input class="tw" type="number" min="0" max="16" step="1" value="${t.ow === undefined ? 4 : t.ow}" style="width:62px" title="Outline width">
        <label class="pjchk"><input type="checkbox" class="tgo" ${t.bg ? "checked" : ""}><span>Box behind</span></label><input class="tg" type="color" value="${t.bg || "#000000"}" style="width:40px;height:30px;padding:2px;flex:none"></div></details></div>`).join("");
    const upd = fn => change(() => fn(cur()));
    $("#ci_s").onchange = () => upd(k => { k.start = Math.max(0, Math.min(k.end - 0.3, +$("#ci_s").value || 0)); }); $("#ci_e").onchange = () => upd(k => { k.end = Math.max(k.start + 0.3, Math.min(inf.duration, +$("#ci_e").value || k.end)); });
    $("#ci_fit").onchange = () => upd(k => { k.fit = $("#ci_fit").value; });
    if ($("#ci_fx")) { $("#ci_fx").onchange = () => upd(k => { k.focus.x = +$("#ci_fx").value; }); $("#ci_fy").onchange = () => upd(k => { k.focus.y = +$("#ci_fy").value; }); }
    $("#ci_cc").onchange = () => upd(k => { k.captions = $("#ci_cc").checked; });
    $("#ci_vol").oninput = () => { $("#ci_vl").textContent = `${$("#ci_vol").value}%`; };
    $("#ci_vol").onchange = () => upd(k => { k.volume = +$("#ci_vol").value / 100; });
    $("#ci_fi").onchange = () => upd(k => { k.fade_in = Math.max(0, Math.min((k.end - k.start) / 2, +$("#ci_fi").value || 0)); });
    $("#ci_fo").onchange = () => upd(k => { k.fade_out = Math.max(0, Math.min((k.end - k.start) / 2, +$("#ci_fo").value || 0)); });
    $("#ci_sp").oninput = () => { const s = +$("#ci_sp").value / 100; $("#ci_spl").textContent = `${s.toFixed(2)}x`; $("#ci_spn").textContent = `(${pjFmt((c.end - c.start) / s, 1)} in the video)`; };
    $("#ci_sp").onchange = () => upd(k => { k.speed = Math.max(0.25, Math.min(4, +$("#ci_sp").value / 100)); });
    box.querySelectorAll("[data-sp]").forEach(b => b.onclick = () => upd(k => { k.speed = +b.dataset.sp; }));
    const zset = (kind, amt, x, y) => upd(k => { k.zoom = kind === "none" ? null : {from: kind === "in" ? 1 : amt, to: kind === "out" ? 1 : amt, x, y}; });
    $("#ci_zm").onchange = () => zset($("#ci_zm").value, c.zoom ? Math.max(c.zoom.from, c.zoom.to) : 1.5, c.zoom ? c.zoom.x : 0.5, c.zoom ? c.zoom.y : 0.5);
    if ($("#ci_za")) {
      $("#ci_za").oninput = () => { $("#ci_zal").textContent = `${$("#ci_za").value}%`; };
      const zr = () => zset(zk, +$("#ci_za").value / 100, +$("#ci_zx").value, +$("#ci_zy").value);
      $("#ci_za").onchange = zr; $("#ci_zx").onchange = zr; $("#ci_zy").onchange = zr;
    }
    if ($("#ci_tr")) {
      $("#ci_tr").onchange = () => upd(k => { k.transition = {type: $("#ci_tr").value, duration: (k.transition && k.transition.duration) || 0.6}; });
      if ($("#ci_td")) { $("#ci_td").oninput = () => { $("#ci_tdl").textContent = `${$("#ci_td").value}s`; }; $("#ci_td").onchange = () => upd(k => { k.transition.duration = +$("#ci_td").value; }); }
    }
    const setLook = () => upd(k => { k.look = {preset: $("#ci_lk").value, brightness: +$("#ci_lb").value / 100, contrast: +$("#ci_lc").value / 100, saturation: +$("#ci_ls").value / 100}; });
    $("#ci_lk").onchange = setLook;
    [["ci_lb", "ci_lbl", v => v], ["ci_lc", "ci_lcl", v => `${v}%`], ["ci_ls", "ci_lsl", v => `${v}%`]].forEach(([i, l, f]) => { $("#" + i).oninput = () => { $("#" + l).textContent = f($("#" + i).value); }; $("#" + i).onchange = setLook; });
    $("#ci_pip").onchange = () => upd(k => { const v = $("#ci_pip").value; k.pip = v ? {source: v, start: 0, x: 1, y: 0, scale: 0.3, t0: 0, t1: Math.round((k.end - k.start) * 100) / 100, border: true} : null; });
    if (c.pip) {
      $("#ci_pc").onchange = () => upd(k => { const [x, y] = $("#ci_pc").value.split(",").map(Number); k.pip.x = x; k.pip.y = y; });
      $("#ci_ps").oninput = () => { $("#ci_psl").textContent = `${$("#ci_ps").value}%`; }; $("#ci_ps").onchange = () => upd(k => { k.pip.scale = +$("#ci_ps").value / 100; });
      $("#ci_p0").onchange = () => upd(k => { k.pip.t0 = Math.max(0, Math.min(k.pip.t1 - 0.1, +$("#ci_p0").value || 0)); });
      $("#ci_p1").onchange = () => upd(k => { k.pip.t1 = Math.max(k.pip.t0 + 0.1, Math.min(k.end - k.start, +$("#ci_p1").value || 1)); });
      $("#ci_pst").onchange = () => upd(k => { k.pip.start = Math.max(0, +$("#ci_pst").value || 0); });
      $("#ci_pb").onchange = () => upd(k => { k.pip.border = $("#ci_pb").checked; });
    }
    const ovBox = $("#ci_ovs");
    const imgOpts = sel => imgLib.images.map(x => `<option value="${esc(x.ref)}" ${sel === x.ref ? "selected" : ""}>${esc(x.name)}</option>`).join("");
    ovBox.innerHTML = (c.overlays || []).map((o, i) => `<div class="pjov pjtx" data-i="${i}"><div class="row" style="gap:6px"><select class="op grow">${imgOpts(o.ref)}${imgLib.images.some(x => x.ref === o.ref) ? "" : `<option value="${esc(o.ref)}" selected>(picture missing)</option>`}</select><button class="dng od" title="Remove this sticker">✕</button></div>
      <div class="row" style="gap:8px"><div class="grow"><label>Left to right</label><input type="range" class="ox" min="0" max="1" step="0.01" value="${o.x}"></div><div class="grow"><label>Top to bottom</label><input type="range" class="oy" min="0" max="1" step="0.01" value="${o.y}"></div></div>
      <div class="row" style="gap:8px"><div class="grow"><label>Size</label><input type="range" class="os" min="3" max="100" step="1" value="${Math.round(o.scale * 100)}"></div><div class="grow"><label>Solid to see-through</label><input type="range" class="oa" min="10" max="100" step="5" value="${Math.round(o.opacity * 100)}"></div></div>
      <div class="row" style="gap:6px"><label style="margin:0">Shown from</label><input class="o0" type="number" step="0.1" min="0" value="${o.t0}" style="width:70px"><label style="margin:0">to</label><input class="o1" type="number" step="0.1" min="0" value="${o.t1}" style="width:70px"></div></div>`).join("");
    ovBox.querySelectorAll(".pjov").forEach(row => { const i = +row.dataset.i;
      row.querySelector(".op").onchange = e => upd(k => { k.overlays[i].ref = e.target.value; });
      row.querySelector(".ox").onchange = e => upd(k => { k.overlays[i].x = +e.target.value; }); row.querySelector(".oy").onchange = e => upd(k => { k.overlays[i].y = +e.target.value; });
      row.querySelector(".os").onchange = e => upd(k => { k.overlays[i].scale = +e.target.value / 100; }); row.querySelector(".oa").onchange = e => upd(k => { k.overlays[i].opacity = +e.target.value / 100; });
      row.querySelector(".o0").onchange = e => upd(k => { k.overlays[i].t0 = Math.max(0, Math.min(k.overlays[i].t1 - 0.1, +e.target.value || 0)); });
      row.querySelector(".o1").onchange = e => upd(k => { k.overlays[i].t1 = Math.max(k.overlays[i].t0 + 0.1, Math.min(k.end - k.start, +e.target.value || 1)); });
      row.querySelector(".od").onclick = () => upd(k => { k.overlays.splice(i, 1); }); });
    $("#ci_addov").onclick = () => {
      if (!imgLib.images.length) return toast("Upload a picture first (a logo or a sticker).", true);
      if ((c.overlays || []).length >= 8) return toast("Up to 8 stickers on a clip.", true);
      upd(k => { k.overlays = k.overlays || []; k.overlays.push({id: pjId(), ref: imgLib.images[0].ref, x: 0.9, y: 0.1, scale: 0.15, opacity: 1, t0: 0, t1: Math.round((k.end - k.start) * 100) / 100}); });
    };
    $("#ci_img").onchange = guard(async () => {
      const f = $("#ci_img").files[0]; if (!f) return;
      toast("Uploading…"); const r = await api(`/api/editor/images/upload?name=${encodeURIComponent(f.name)}`, {method: "POST", body: f, raw: true});
      $("#ci_img").value = ""; await loadImages(); toast("Picture added. Press Add a sticker.");
    });
    $("#ci_addcard").onclick = () => {
      if (c.texts.length >= 10) return toast("Up to 10 texts on a clip.", true);
      const who = (c.credit && c.credit.creator) || inf.title || "this clip";
      upd(k => { k.texts.push({text: `${who}: what you are seeing`.slice(0, 60), t0: 0.3, t1: Math.min(4, Math.round((k.end - k.start) * 100) / 100), x: 0.5, y: 0.12, size: 44, color: "#ffffff", bold: true, italic: false, upper: false, outline: "#000000", ow: 0, shadow: 0, bg: "#181818", anim: "fade"}); });
      toast("Context card added. Change its words to say who and what this is.");
    };
    $("#ci_addtext").onclick = () => {
      if (c.texts.length >= 10) return toast("Up to 10 texts on a clip.", true);
      const st = PJ_TEMPLATES[$("#ci_tmpl").value][1];
      upd(k => { k.texts.push({text: "Your text", t0: 0, t1: Math.round((k.end - k.start) * 100) / 100, x: 0.5, y: st.y || 0.85, ...st}); });
    };
    texts.querySelectorAll(".pjtx").forEach(row => { const i = +row.dataset.i;
      row.querySelector(".tt").onchange = e => upd(k => { k.texts[i].text = e.target.value.trim() || "Text"; });
      row.querySelector(".t0").onchange = e => upd(k => { k.texts[i].t0 = Math.max(0, Math.min(k.texts[i].t1 - 0.1, +e.target.value || 0)); });
      row.querySelector(".t1").onchange = e => upd(k => { k.texts[i].t1 = Math.max(k.texts[i].t0 + 0.1, Math.min(k.end - k.start, +e.target.value || 1)); });
      row.querySelector(".ts").onchange = e => upd(k => { k.texts[i].size = +e.target.value; }); row.querySelector(".tp").onchange = e => upd(k => { k.texts[i].y = +e.target.value; });
      row.querySelector(".tc").onchange = e => upd(k => { k.texts[i].color = e.target.value; }); row.querySelector(".td").onclick = () => upd(k => { k.texts.splice(i, 1); });
      row.querySelector(".tmpl").onchange = e => { const st = (PJ_TEMPLATES[e.target.value] || [])[1]; if (st) upd(k => { Object.assign(k.texts[i], st); }); };
      row.querySelector(".ta").onchange = e => upd(k => { k.texts[i].anim = e.target.value; });
      row.querySelector(".tb").onchange = e => upd(k => { k.texts[i].bold = e.target.checked; }); row.querySelector(".ti").onchange = e => upd(k => { k.texts[i].italic = e.target.checked; }); row.querySelector(".tu").onchange = e => upd(k => { k.texts[i].upper = e.target.checked; });
      row.querySelector(".to").onchange = e => upd(k => { k.texts[i].outline = e.target.value; }); row.querySelector(".tw").onchange = e => upd(k => { k.texts[i].ow = Math.max(0, Math.min(16, +e.target.value || 0)); });
      row.querySelector(".tgo").onchange = e => upd(k => { k.texts[i].bg = e.target.checked ? row.querySelector(".tg").value : ""; }); row.querySelector(".tg").onchange = e => upd(k => { if (k.texts[i].bg) k.texts[i].bg = e.target.value; }); });
  }

  /* ---- music: one track under the whole video */
  const musicName = ref => { const all = [...audioLib.library, ...audioLib.mine]; const t = all.find(x => x.ref === ref); return t ? t.name : "Music"; };
  function drawMusic() {
    const box = $("#pj_music"); if (!box) return;
    const m = music(), opt = (t, sel) => `<option value="${esc(t.ref)}" ${sel === t.ref ? "selected" : ""}>${esc(t.name)}</option>`;
    box.innerHTML = `<div class="row" style="gap:10px;align-items:center;flex-wrap:wrap"><h3 style="margin:0">Music</h3>
      <select id="mu_ref" style="max-width:320px"><option value="">No music</option>${audioLib.mine.length ? `<optgroup label="My own music">${audioLib.mine.map(t => opt(t, m && m.ref)).join("")}</optgroup>` : ""}${audioLib.library.length ? `<optgroup label="Studio music library">${audioLib.library.map(t => opt(t, m && m.ref)).join("")}</optgroup>` : ""}</select>
      <label class="btn" for="mu_file" style="cursor:pointer;margin:0">Upload my own</label><input type="file" id="mu_file" accept="audio/*" hidden>
      <span class="muted" style="font-size:12.5px">Up to ${audioLib.max_mb || 60} MB. Only you can use your own files.</span></div>
      ${m ? `<div class="pjmugrid"><div><label>Music volume: <b id="mu_vl">${Math.round(m.volume * 100)}%</b></label><input type="range" id="mu_vol" min="0" max="100" step="5" value="${Math.round(m.volume * 100)}"></div>
        <div><label>Fade in (seconds)</label><input type="number" id="mu_fi" min="0" max="10" step="0.5" value="${m.fade_in}"></div>
        <div><label>Fade out (seconds)</label><input type="number" id="mu_fo" min="0" max="10" step="0.5" value="${m.fade_out}"></div>
        <div><label>Start the track at (seconds)</label><input type="number" id="mu_st" min="0" step="1" value="${m.start}"></div>
        <label class="pjchk"><input type="checkbox" id="mu_loop" ${m.loop ? "checked" : ""}><span>Repeat the track if the video is longer</span></label>
        <label class="pjchk"><input type="checkbox" id="mu_duck" ${m.duck ? "checked" : ""}><span>Lower the music while there is speech or game sound</span></label></div>` : `<div class="muted" style="margin-top:6px">Pick a track to play under the whole video.</div>`}`;
    const set = fn => change(() => { P.data.audio = P.data.audio || {}; fn(); });
    $("#mu_ref").onchange = () => { const r = $("#mu_ref").value; set(() => { P.data.audio.music = r ? {ref: r, start: 0, volume: 0.3, fade_in: 1, fade_out: 2, loop: true, duck: true} : null; }); auRef = ""; if (playing) musicPlay(); };
    $("#mu_file").onchange = guard(async () => {
      const f = $("#mu_file").files[0]; if (!f) return;
      toast("Uploading…"); const r = await api(`/api/editor/audio/upload?name=${encodeURIComponent(f.name)}`, {method: "POST", body: f, raw: true});
      $("#mu_file").value = ""; await loadAudio(); set(() => { P.data.audio.music = {ref: `src:${r.source.id}`, start: 0, volume: 0.3, fade_in: 1, fade_out: 2, loop: true, duck: true}; }); auRef = "";
    });
    if (m) {
      $("#mu_vol").oninput = () => { $("#mu_vl").textContent = `${$("#mu_vol").value}%`; au.volume = +$("#mu_vol").value / 100; };
      $("#mu_vol").onchange = () => set(() => { P.data.audio.music.volume = +$("#mu_vol").value / 100; });
      $("#mu_fi").onchange = () => set(() => { P.data.audio.music.fade_in = Math.max(0, Math.min(10, +$("#mu_fi").value || 0)); });
      $("#mu_fo").onchange = () => set(() => { P.data.audio.music.fade_out = Math.max(0, Math.min(10, +$("#mu_fo").value || 0)); });
      $("#mu_st").onchange = () => set(() => { P.data.audio.music.start = Math.max(0, +$("#mu_st").value || 0); });
      $("#mu_loop").onchange = () => set(() => { P.data.audio.music.loop = $("#mu_loop").checked; });
      $("#mu_duck").onchange = () => set(() => { P.data.audio.music.duck = $("#mu_duck").checked; });
    }
  }

  /* ---- making the video (the queue is shared by every member) */
  let rpoll = null;
  const stopPoll = () => { if (rpoll) clearInterval(rpoll); rpoll = null; };
  function drawRender(r, dismissed) {
    const box = $("#pj_render"); if (!box) return stopPoll();
    if (!r || (dismissed && !["queued", "running"].includes(r.status))) { box.innerHTML = ""; return; }
    const act = ["queued", "running"].includes(r.status);
    box.innerHTML = `<div class="card pjrender"><div class="row" style="gap:12px;align-items:center;flex-wrap:wrap"><b>${r.status === "queued" ? "Waiting in line" : r.status === "running" ? "Making your video" : r.status === "done" ? "Your video is ready" : r.status === "cancelled" ? "Cancelled" : "It did not work"}</b>
      <span class="muted">${r.status === "queued" ? (r.ahead ? `${r.ahead} video${r.ahead === 1 ? "" : "s"} ahead of yours` : "You are next") : r.status === "cancelled" ? "" : esc(r.message || "")}</span><span class="grow"></span>
      ${act ? `<button id="pjr_cancel">Cancel</button>` : r.status === "done" ? `<a class="btn pri" href="#/videos">Open My videos</a>${r.result && r.result.kind === "short" ? `<a class="btn" href="#/social">Post on TikTok, Instagram, Facebook</a>` : ""}<button id="pjr_x">Dismiss</button>` : `<button id="pjr_x">Dismiss</button>`}</div>
      ${r.status === "done" && r.result ? `<div class="muted" style="margin-top:8px">${r.result.preset ? "Made for " + esc(r.result.preset.replace("yt_short", "YouTube Shorts").replace("tiktok", "TikTok").replace("reel", "Instagram Reels").replace("fb_", "Facebook ").replace("yt_video", "YouTube").replace("ig_feed", "Instagram feed")) + ". " : ""}It is in My videos, waiting for your check${r.result.kind === "short" ? ". To post it on TikTok, Instagram or Facebook, use the button above." : "."}</div>` : ""}
      ${r.status === "running" ? `<div class="pgx-bar" style="margin-top:10px"><i style="width:${r.pct}%"></i></div>` : ""}</div>`;
    if ($("#pjr_cancel")) $("#pjr_cancel").onclick = guard(async () => { await api(`/api/editor/renders/${r.id}/cancel`, {method: "POST"}); poll(r.id); });
    if ($("#pjr_x")) $("#pjr_x").onclick = () => drawRender(r, true);
  }
  async function poll(rid) {
    try { const r = await api(`/api/editor/renders/${rid}`); drawRender(r); if (!["queued", "running"].includes(r.status)) { stopPoll(); } } catch (e) { stopPoll(); }
  }
  const follow = rid => { stopPoll(); poll(rid); rpoll = setInterval(() => poll(rid), 2000); timer = rpoll; };
  let exportOpts = null;
  const fmtLen = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, "0")}`;
  const exportSet = () => { P.data.export = P.data.export || {preset: null, quality: "standard"}; return P.data.export; };
  async function showMakeForm() {
    const box = $("#pj_render"); if (!box) return;
    if (!exportOpts) exportOpts = await api("/api/editor/export-options");
    const ex = exportSet();
    box.innerHTML = `<div class="card pjmake"><h3 style="margin:0 0 10px">Make the video</h3>
      <div class="pjmakegrid"><div><label>Name</label><input id="mk_title" maxlength="100" value="${esc(P.title)}"></div>
        <div><label>Where is it going?</label><select id="mk_preset"><option value="">Anywhere (I choose the shape myself)</option>${exportOpts.presets.map(p => `<option value="${p.id}" ${ex.preset === p.id ? "selected" : ""}>${esc(p.name)} (${p.aspect}, up to ${fmtLen(p.max)})</option>`).join("")}</select></div>
        <div><label>Quality</label><select id="mk_q">${exportOpts.quality.map(q => `<option value="${q.id}" ${ex.quality === q.id ? "selected" : ""}>${esc(q.label)}</option>`).join("")}</select></div></div>
      <label>Description (optional)</label><textarea id="mk_desc" rows="2" maxlength="4000" placeholder="Shown with the video when you post it"></textarea>
      <div id="mk_info" class="muted" style="margin:8px 0"></div>
      <div class="row" style="gap:8px"><button class="pri" id="mk_go">Start making it</button><button id="mk_cancel">Cancel</button></div></div>`;
    const info = () => {
      const p = exportOpts.presets.find(x => x.id === exportSet().preset), len = total() - (P.data.clips.length > 1 && P.data.clips.some(c => c.transition && c.transition.type !== "none") ? 0.4 * (P.data.clips.length - 1) : 0);
      const tooLong = p && len > p.max + 0.5, wrong = p && P.data.aspect !== p.aspect;
      $("#mk_info").innerHTML = `Your video is about <b>${fmtLen(Math.max(0, len))}</b> long${p ? `. ${esc(p.name)} allows up to <b>${fmtLen(p.max)}</b>.` : "."}${tooLong ? ` <span style="color:var(--bad)">It is too long for this place. Shorten it or choose another.</span>` : ""}${wrong ? ` <span style="color:var(--bad)">The shape does not match.</span>` : ""}`;
      $("#mk_go").disabled = !!(tooLong || wrong);
    };
    $("#mk_preset").onchange = () => {
      const id = $("#mk_preset").value, p = exportOpts.presets.find(x => x.id === id);
      change(() => { exportSet().preset = id || null; if (p) { P.data.aspect = p.aspect; if (p.aspect !== "9:16") clips().forEach(c => { if (c.fit === "split") c.fit = "crop"; }); } });
      info();
    };
    $("#mk_q").onchange = () => { change(() => { exportSet().quality = $("#mk_q").value; }); };
    $("#mk_cancel").onclick = () => { box.innerHTML = ""; };
    $("#mk_go").onclick = guard(async () => {
      const title = $("#mk_title").value.trim() || P.title, description = $("#mk_desc").value.trim();
      stop(); dirty = true; await saveNow();
      if (conflict) return;
      const r = await api(`/api/editor/projects/${pid}/render`, {method: "POST", body: {title, description}});
      toast("Added to the line"); drawRender(r.render); follow(r.render.id);
    });
    info(); box.scrollIntoView({behavior: "smooth", block: "nearest"});
  }
  $("#pj_make").onclick = guard(async () => {
    if (!clips().length) return toast("Add a video to the timeline first.", true);
    stop(); await showMakeForm();
  });
  if (P.render) { drawRender(P.render, !["queued", "running"].includes(P.render.status)); if (["queued", "running"].includes(P.render.status)) follow(P.render.id); }

  function drawAll() { drawMusic(); $("#pj_empty").hidden = clips().length > 0; $("#pj_frame").style.aspectRatio = frameRatio(); $("#pj_aspect").value = P.data.aspect; drawTimeline(); drawInspector(); drawTime(); drawText(); $("#pj_undo").disabled = !undo.length; $("#pj_redo").disabled = !redo.length; if (!playing && clips().length) { const i = clipAt(Math.min(playhead, Math.max(0, total() - 0.01))), k = clips()[i]; applyFit(k); applyZoom(k, Math.max(0, playhead - offsets()[i]) * spd(k) / Math.max(0.1, k.end - k.start)); } }
  setState("Saved"); await Promise.all([loadMedia(), loadMine(), loadAudio(), loadImages()]);
  sel = clips()[0] ? clips()[0].id : null; drawAll(); if (clips().length) seek(0);
}
