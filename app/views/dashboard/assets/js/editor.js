/* The video editor. */
"use strict";
/* ------------------------------------------------------------ video editor */
const ED_ASPECT = {"9:16": [1080, 1920], "16:9": [1920, 1080], "4:5": [1080, 1350]};
const edFmt = (t, dec) => { t = Math.max(0, t || 0); const m = Math.floor(t / 60), s = t - m * 60; return `${m}:${(dec ? s.toFixed(1) : String(Math.floor(s))).padStart(dec ? 4 : 2, "0")}`; };
const edTime = v => { v = String(v || "").trim(); if (!v) return 0; const p = v.split(":").map(Number); if (p.some(isNaN)) return 0; return p.reduce((a, b) => a * 60 + b, 0); };
function edWatch(tid, onProgress) {
  return new Promise((resolve, reject) => {
    const poll = async () => {
      try {
        const t = await api(`/api/editor/tasks/${tid}`);
        if (onProgress) onProgress(t);
        if (t.status === "done") return resolve(t.result);
        if (t.status === "error") return reject(new Error(t.message));
        setTimeout(poll, 700);
      } catch (e) { reject(e); }
    };
    poll();
  });
}
const EDI = {
  twitch: '<path d="M4 3h17v11l-5 5h-4l-3 3v-3H4z"/><path d="M12 8v4M16 8v4"/>',
  kick: '<path d="M5 4h4v5l3-5h4l-4 6 4 6h-4l-3-5v5H5z"/>',
  youtube: '<rect x="2.5" y="5.5" width="19" height="13" rx="4"/><path d="M10 9.5v5l4.5-2.5z"/>',
  upload: '<path d="M12 16V5M7.5 9.5L12 5l4.5 4.5M5 19h14"/>',
  face: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><circle cx="12" cy="10" r="2.6"/><path d="M7.5 17c.8-2.2 2.5-3.2 4.5-3.2s3.7 1 4.5 3.2"/>',
  split: '<rect x="5" y="3.5" width="14" height="17" rx="2.5"/><path d="M5 10h14"/>',
  scissors: '<circle cx="6" cy="6.5" r="2.5"/><circle cx="6" cy="17.5" r="2.5"/><path d="M8 8l12 9M8 16l12-9"/>',
  wand: '<path d="M5 19L17 7M14 4l1 2.2L17.2 7 15 8l-1 2.2L13 8l-2.2-1L13 6zM19 12l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z"/>',
};
Object.assign(EDI, {
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 18.5h3"/>',
  film: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M7 5v14M17 5v14M3 9.5h4M3 14.5h4M17 9.5h4M17 14.5h4"/>',
  speaker: '<path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5zM15.5 9a4 4 0 0 1 0 6M18 6.5a8 8 0 0 1 0 11"/>',
  all: '<rect x="3.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.8"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.8"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.8"/>',
  both: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  live: '<circle cx="12" cy="12" r="2.2"/><path d="M7.5 7.5a6.4 6.4 0 0 0 0 9M16.5 7.5a6.4 6.4 0 0 1 0 9M4.6 4.6a10.5 10.5 0 0 0 0 14.8M19.4 4.6a10.5 10.5 0 0 1 0 14.8"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3"/>',
  bed: '<path d="M4 9v6M8 6v12M12 10v4M16 5v14M20 9v6"/>',
  wave: '<path d="M3 12h2.5l2-6 3 12 3-9 2 5 1.5-2H21"/>',
  bolt: '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
  hold: '<path d="M8.5 11V5.5a1.5 1.5 0 0 1 3 0V10M11.5 9.5V4.5a1.5 1.5 0 0 1 3 0V10M14.5 10V6.5a1.5 1.5 0 0 1 3 0V13a6 6 0 0 1-6 6h-1a6 6 0 0 1-5-2.7L4 13.5a1.6 1.6 0 0 1 2.7-1.6L8.5 14z"/>',
});
const edIcon = n => `<svg viewBox="0 0 24 24" aria-hidden="true">${EDI[n]}</svg>`;

async function editor() {
  $("#main").innerHTML = `<div class="edsrc"><div class="edsrc-l"><div class="eyebrow2">Pick a source</div><h1 style="margin:6px 0 10px">Search a streamer, paste a link, or upload.</h1>
      </div>
    <div class="card edsrc-r"><div class="edtiles" id="edtiles">
      <button class="edtile" data-k="twitch">${edIcon("twitch")}<b>Twitch</b><span>Past streams</span></button>
      <button class="edtile" data-k="kick">${edIcon("kick")}<b>Kick</b><span>Paste a link</span></button>
      <button class="edtile" data-k="youtube">${edIcon("youtube")}<b>YouTube</b><span>Paste a link</span></button>
      <button class="edtile" data-k="upload">${edIcon("upload")}<b>Upload</b><span>Your video file</span></button></div>
      <div id="edbody"></div></div></div>
    <section class="card fnd" id="fnd" style="margin-top:22px" hidden></section>
    <section class="card" style="margin-top:22px"><div class="sechead"><h2>Clip finder results</h2><span class="muted">Moments found earlier, kept for 3 days</span></div><div id="fndlist"></div></section>
    <section class="card" style="margin-top:22px"><div class="sechead"><h2>Open again</h2><span class="muted" id="edcount"></span></div><div id="edlist"></div></section>`;
  const body = $("#edbody");
  const openSrc = s => openEditor(s);
  /* ---- the clip finder: scan a source, show every moment found, process only the ones the member picks */
  let fndTimer = null;
  const stopFnd = () => { if (fndTimer) clearInterval(fndTimer); fndTimer = null; };
  const startScan = guard(async (url, start, end) => {
    const r = await api("/api/finder/scan", {method: "POST", body: {url, start, end}});
    showScan(r.scan);
  });
  const showScan = (sid, again) => {
    stopFnd();
    const box = $("#fnd"); box.hidden = false; box.innerHTML = `<div class="edbusy"><div class="spin"></div><div>Starting the scan…</div></div>`;
    if (!again) box.scrollIntoView({behavior: "smooth", block: "start"});
    const sel = new Set(); let last = "", busyPick = false;
    const reasonChips = c => c.reasons.map(r => `<span class="frs">${esc(r)}</span>`).join("");
    const card = (c, i) => `<div class="fcard ${sel.has(c.id) ? "on" : ""}" data-id="${c.id}"><div class="fv">${c.ready ? `<video preload="none" playsinline loop poster="${esc(c.thumb || "")}" src="${esc(c.video)}"></video><button class="fplay" type="button" title="Play">▶</button>` : `<div class="fwait"><div class="spin"></div><span>Cutting the preview…</span></div>`}
      <span class="frank">#${i + 1}</span><span class="fscore" title="How exciting this moment looks (0 to 100)">${c.score}</span><button class="fsel" type="button" title="${sel.has(c.id) ? "Chosen" : "Choose this moment"}">${sel.has(c.id) ? "✓" : ""}</button></div>
      <div class="fm"><b>${edFmt(c.start)} – ${edFmt(c.end)}</b><span>${c.length} s</span><div class="fr">${reasonChips(c)}</div></div></div>`;
    const bar = () => {
      const n = sel.size; const b = $("#f_bar"); if (!b) return;
      b.querySelector("#f_n").textContent = n ? `${n} chosen` : "Choose the moments you like";
      b.querySelectorAll("[data-act]").forEach(x => x.disabled = !n || busyPick);
    };
    const render = d => {
      const run = d.status === "running";
      $("#f_head").innerHTML = `<div class="fhead"><div><div class="eyebrow2">${d.live ? "● Live stream" : "Clip finder"} · ${esc(d.platform || "")}</div><h2 style="margin:2px 0 4px;font-size:21px">${esc(d.title || "Scanning…")}</h2>
          <div class="muted">${esc(d.creator || "")}${d.window ? ` · scanned ${edFmt(d.window[0])} – ${edFmt(d.window[1])}${d.duration && !d.live ? ` of ${edFmt(d.duration)}` : ""}` : ""}</div></div>
        <div class="row" style="gap:8px">${!run && d.more ? `<button id="f_more">Scan the next 45 minutes</button>` : ""}<button id="f_close">Close</button></div></div>
        ${run ? `<div class="pgx-bar"><i style="width:${Math.max(4, d.pct)}%"></i></div>` : ""}<div class="${d.status === "error" ? "authmsg bad" : "muted"}" style="margin-top:8px">${esc(d.message)}${d.note ? ` <span class="help">${esc(d.note)}</span>` : ""}${d.hidden ? ` <span class="help">${d.hidden} clip${d.hidden > 1 ? "s were" : " was"} hidden by the safety check.</span>` : ""}</div>`;
      if ($("#f_more")) $("#f_more").onclick = guard(async () => { await api(`/api/finder/scans/${d.id}/more`, {method: "POST", body: {}}); showScan(d.id, true); });
      $("#f_close").onclick = () => { stopFnd(); box.hidden = true; drawList(); };
      const sig = JSON.stringify(d.candidates.map(c => [c.id, c.ready]));
      if (sig !== last) {
        last = sig;
        $("#f_grid").innerHTML = d.candidates.length ? d.candidates.map(card).join("") : (run ? "" : `<div class="empty" style="grid-column:1/-1">${svg("film")}<b>No clear highlights here</b><div>Try another part or another stream.</div></div>`);
        bar();
      }
    };
    box.innerHTML = `<div id="f_head"></div><div class="fgrid" id="f_grid"></div>
      <div class="fbar" id="f_bar"><div class="fbl"><b id="f_n">Choose the moments you like</b><span class="muted">Press ▶ to watch. Tap the circle to choose.</span></div>
        <div class="fopts"><details class="more"><summary>How should the video be made?</summary><label>Sound</label><select id="f_audio"><option value="default">My default</option><option value="replace">AI commentary + music, original muted</option><option value="bed">Original under music</option><option value="original">Original only (high claim risk)</option></select>
          <label>Then</label><select id="f_after"><option value="">My setting</option><option value="auto">Upload by itself (Unlisted)</option><option value="hold">Wait for me</option></select></details></div>
        <div class="row" style="gap:8px"><button data-act="editor" id="f_ed">Open in the editor</button><button class="pri" data-act="short" id="f_sh" title="Commentary, captions, thumbnail and title, made for you (costs tokens)">Make videos with AI</button><button id="f_clear">Clear</button></div></div>`;
    const grid = $("#f_grid");
    grid.addEventListener("click", e => {
      const cardEl = e.target.closest(".fcard"); if (!cardEl) return; const id = cardEl.dataset.id;
      if (e.target.closest(".fplay") || e.target.tagName === "VIDEO") {
        const v = cardEl.querySelector("video"); grid.querySelectorAll("video").forEach(x => { if (x !== v) x.pause(); });
        if (v.paused) { v.play().catch(() => { v.muted = true; v.play().catch(() => {}); }); cardEl.classList.add("playing"); } else { v.pause(); cardEl.classList.remove("playing"); } return;
      }
      if (sel.has(id)) sel.delete(id); else sel.add(id);
      cardEl.classList.toggle("on", sel.has(id)); const b = cardEl.querySelector(".fsel"); if (b) b.textContent = sel.has(id) ? "✓" : ""; bar();
    });
    $("#f_clear").onclick = () => { sel.clear(); grid.querySelectorAll(".fcard").forEach(x => { x.classList.remove("on"); const b = x.querySelector(".fsel"); if (b) b.textContent = ""; }); bar(); };
    const pick = guard(async action => {
      if (!sel.size) return toast("Choose at least one moment");
      busyPick = true; bar(); const n = $("#f_n"); n.textContent = "Cutting your clips at full quality…";
      try {
        const body = {ids: [...sel], action}; if (action === "short") { body.audio_mode = $("#f_audio").value; body.after = $("#f_after").value; }
        const r = await api(`/api/finder/scans/${sid}/pick`, {method: "POST", body});
        const results = []; for (const t of r.tasks) { try { results.push(await edWatch(t, tk => { n.textContent = `${tk.message}${tk.pct ? " " + tk.pct + "%" : ""}`; })); } catch (e) { toast(e.message, true); } }
        if (action === "editor" && results[0]) { drawList(); openEditor(results[0].source); toast(results.length > 1 ? `${results.length} clips opened. The others are under "Open again".` : "Opened in the editor"); }
        else if (action === "short" && results.length) { toast(`${results.length} video${results.length > 1 ? "s" : ""} started`); refreshTokens(); openProgress(results[0].job_id); }
      } finally { busyPick = false; bar(); }
    });
    $("#f_ed").onclick = () => pick("editor"); $("#f_sh").onclick = () => pick("short");
    const tick = async () => {
      let d; try { d = await api(`/api/finder/scans/${sid}`); } catch (e) { stopFnd(); box.innerHTML = `<div class="authmsg bad">${esc(e.message)}</div>`; return; }
      if (!$("#f_head")) return stopFnd();
      render(d); if (d.status !== "running") stopFnd();
    };
    tick(); fndTimer = setInterval(tick, 1800);
  };

  const busy = (el, msg) => { el.innerHTML = `<div class="edbusy"><div class="spin"></div><div id="edbm">${esc(msg)}</div></div>`; return t => { const m = $("#edbm"); if (m) m.textContent = `${t.message}${t.pct ? " " + t.pct + "%" : ""}`; }; };
  const fromLink = guard(async (url, start, end) => {
    const prog = busy(body, "Opening the link…");
    try {
      const r = await api("/api/editor/from-link", {method: "POST", body: {url, start, end}});
      const res = await edWatch(r.task, prog); openSrc(res.source); drawList(); draw(cur.k);
    } catch (e) { draw(cur.k); toast(e.message, true); }
  });
  const linkForm = (k, label, hint) => {
    body.innerHTML = `<div class="edsearch"><span class="edsi">${edIcon(k)}</span><input id="e_url" placeholder="${esc(label)}" autocomplete="off"><button class="edgo" id="e_urlgo" title="Open">→</button></div>
      <div class="row" style="margin-top:12px"><label style="margin:0">Part to use (optional)</label><input id="e_s" placeholder="Start 0:00" style="max-width:130px"><input id="e_e" placeholder="End 20:00" style="max-width:130px"><span class="muted">up to 20 minutes</span></div>
      <div class="row" style="margin-top:14px"><button class="pri" id="e_find">Find the best clips</button><button id="e_open2">Open it to edit</button><span class="muted">a past stream, a video or a live stream</span></div>
      <p class="muted" style="margin:10px 0 0">${hint}</p>`;
    const go = () => fromLink($("#e_url").value.trim(), $("#e_s").value, $("#e_e").value);
    const findIt = () => { const u = $("#e_url").value.trim(); if (!u) return toast("Paste a link first", true); startScan(u, $("#e_s").value, $("#e_e").value); };
    $("#e_find").onclick = findIt; $("#e_open2").onclick = go;
    $("#e_urlgo").onclick = findIt; $("#e_url").onkeydown = e => { if (e.key === "Enter") go(); }; $("#e_url").focus();
  };
  const twitch = () => {
    body.innerHTML = `<div class="edsearch"><span class="edsi">${edIcon("twitch")}</span><input id="e_q" placeholder="Search a Twitch streamer…" autocomplete="off"><button class="edgo" id="e_qgo" title="Search">→</button></div><div id="e_res" style="margin-top:14px"></div>`;
    const res = $("#e_res");
    const videos = guard(async login => {
      res.innerHTML = `<div class="edbusy"><div class="spin"></div><div>Loading past streams…</div></div>`;
      const d = await api(`/api/editor/twitch/videos?login=${encodeURIComponent(login)}`);
      res.innerHTML = `<div class="muted" style="margin-bottom:8px"><a href="#" id="e_back">← All streamers</a> · <b>${esc(d.name)}</b> · past streams</div>${cur.live ? `<div class="edlive"><span class="ndot"></span><div style="flex:1"><b>${esc(d.name)} is live right now</b><div class="muted" style="font-size:12.5px">The stream is long, so the studio reads back what was already broadcast and finds the best moments in it.</div></div><button class="pri" id="e_findlive">Find clips in this live stream</button></div>` : ""}<div class="edvods">${d.videos.map((v, i) => `<div class="edvod" data-i="${i}"><img src="${esc(v.thumb)}" alt=""><b>${esc(v.title)}</b><span>${edFmt(v.seconds)} · ${esc((v.created_at || "").slice(0, 10))} · ${v.views} views</span></div>`).join("") || `<div class="empty">No past streams found.</div>`}</div>`;
      $("#e_back").onclick = e => { e.preventDefault(); $("#e_qgo").click(); };
      if ($("#e_findlive")) $("#e_findlive").onclick = () => startScan(`https://www.twitch.tv/${login}`);
      res.querySelectorAll(".edvod").forEach(el => el.onclick = () => scan(d.videos[+el.dataset.i]));
    });
    const scan = v => {
      const max = Math.min(v.seconds, 1200); let a = 0, b = max;
      res.innerHTML = `<div class="edscan"><img src="${esc(v.thumb)}" alt=""><div><b>${esc(v.title)}</b><div class="muted">Length ${edFmt(v.seconds)}</div></div></div>
        <label>Pick the part to open (up to 20 minutes)</label><div class="edrange"><input type="range" id="e_ra" min="0" max="${v.seconds}" value="0"><input type="range" id="e_rb" min="0" max="${v.seconds}" value="${b}"></div>
        <div class="row"><span class="chip acc" id="e_rt"></span><button class="pri" id="e_find2">Find the best clips in this part</button><button id="e_open">Open this part to edit</button><button id="e_cancel">Back</button></div>`;
      const upd = (who) => {
        a = +$("#e_ra").value; b = +$("#e_rb").value;
        if (who === "a" && b - a > 1200) b = a + 1200; if (who === "b" && b - a > 1200) a = b - 1200;
        if (b - a < 10) { if (who === "a") a = Math.max(0, b - 10); else b = Math.min(v.seconds, a + 10); }
        $("#e_ra").value = a; $("#e_rb").value = b; $("#e_rt").textContent = `${edFmt(a)} – ${edFmt(b)} · ${edFmt(b - a)} long`;
      };
      $("#e_ra").oninput = () => upd("a"); $("#e_rb").oninput = () => upd("b"); upd("b");
      $("#e_cancel").onclick = () => videos(v.login || cur.login);
      $("#e_open").onclick = () => fromLink(v.url, a, b); $("#e_find2").onclick = () => startScan(v.url, a, b);
    };
    const search = guard(async () => {
      const q = $("#e_q").value.trim(); if (q.length < 2) return;
      res.innerHTML = `<div class="edbusy"><div class="spin"></div><div>Searching…</div></div>`;
      const d = await api(`/api/editor/twitch/search?q=${encodeURIComponent(q)}`);
      res.innerHTML = d.channels.length ? `<div class="edchans">${d.channels.map(c => `<button class="edchan" data-l="${esc(c.login)}" data-live="${c.live ? 1 : 0}"><b>${esc(c.name)}</b><span>${c.live ? "● Live now" : "Past streams"}${c.game ? " · " + esc(c.game) : ""}</span></button>`).join("")}</div>` : `<div class="empty">No streamer found.</div>`;
      res.querySelectorAll(".edchan").forEach(b => b.onclick = () => { cur.login = b.dataset.l; cur.live = b.dataset.live === "1"; videos(b.dataset.l); });
    });
    $("#e_qgo").onclick = search; $("#e_q").onkeydown = e => { if (e.key === "Enter") search(); }; $("#e_q").focus();
  };
  const upload = () => {
    body.innerHTML = `<div class="eddrop" id="e_drop"><div class="edsi" style="width:46px;height:46px">${edIcon("upload")}</div><b>Drop a video here, or choose one</b><span class="muted">.mp4 .mov .mkv .webm · up to 2 GB</span><button class="pri" id="e_pick">Choose a video</button><input type="file" id="e_file" accept="video/*,.mkv" hidden></div>`;
    const send = file => {
      body.innerHTML = `<div class="edbusy"><div style="flex:1"><div id="e_um">Uploading ${esc(file.name)}…</div><div class="pgx-bar" style="margin:10px 0 0"><i id="e_ub" style="width:0%"></i></div></div></div>`;
      const x = new XMLHttpRequest(); x.open("POST", `/api/editor/sources/upload?name=${encodeURIComponent(file.name)}`); x.setRequestHeader("X-Requested-With", "studio");
      x.upload.onprogress = e => { if (e.lengthComputable && $("#e_ub")) { $("#e_ub").style.width = Math.round(100 * e.loaded / e.total) + "%"; } };
      x.onload = () => { let d = {}; try { d = JSON.parse(x.responseText); } catch (e) {} if (x.status === 200) { openSrc(d.source); drawList(); draw(cur.k); } else { draw(cur.k); toast(d.error || "Upload failed", true); } };
      x.onerror = () => { draw(cur.k); toast("Upload failed. Check your connection.", true); };
      x.send(file);
    };
    $("#e_pick").onclick = () => $("#e_file").click(); $("#e_file").onchange = e => { if (e.target.files[0]) send(e.target.files[0]); };
    const dz = $("#e_drop"); dz.ondragover = e => { e.preventDefault(); dz.classList.add("on"); }; dz.ondragleave = () => dz.classList.remove("on");
    dz.ondrop = e => { e.preventDefault(); dz.classList.remove("on"); if (e.dataTransfer.files[0]) send(e.dataTransfer.files[0]); };
  };
  const cur = {k: "twitch"};
  const draw = k => {
    cur.k = k; document.querySelectorAll("#edtiles .edtile").forEach(t => t.classList.toggle("on", t.dataset.k === k));
    if (k === "twitch") twitch();
    else if (k === "kick") linkForm("kick", "Paste a Kick video link…", "Paste the link of a Kick stream replay, clip or a channel that is live now. Then choose the part you want.");
    else if (k === "youtube") linkForm("youtube", "Paste a YouTube link…", "A normal video, a stream replay or a Short. For a long video choose the part you want (up to 20 minutes).");
    else upload();
  };
  let drawList = guard(async () => {
    const d = await api("/api/editor/sources");
    $("#edcount").textContent = d.sources.length ? `${d.sources.length} saved` : "";
    $("#edlist").innerHTML = d.sources.length ? `<div class="edlist">${d.sources.map(s => `<div class="edsrcard"><img src="/api/editor/sources/${s.id}/strip" alt="" loading="lazy"><div class="edsrcb"><b>${esc(s.title)}</b><span class="muted">${s.origin === "upload" ? "Upload" : s.origin === "link" ? "From a link" : "My video"} · ${edFmt(s.duration)} · ${s.width}×${s.height}</span>
      <div class="row" style="margin-top:8px"><button class="pri" data-o="${s.id}">Open</button><button data-d="${s.id}" title="Remove from the editor">Remove</button></div></div></div>`).join("")}</div>` : emptyState("film", "Nothing open yet", "Pick a source above. Your recent videos stay here so you can come back to them.");
    $("#edlist").querySelectorAll("[data-o]").forEach(b => b.onclick = () => openSrc(d.sources.find(s => s.id === b.dataset.o)));
    $("#edlist").querySelectorAll("[data-d]").forEach(b => b.onclick = guard(async () => { if (!confirm("Remove this from the editor? Videos you already saved are not affected.")) return; await api(`/api/editor/sources/${b.dataset.d}`, {method: "DELETE"}); drawList(); }));
  });
  const drawScans = guard(async () => {
    const d = await api("/api/finder/scans");
    $("#fndlist").innerHTML = d.scans.length ? `<div class="edlist">${d.scans.map(x => `<div class="edsrcard"><div class="edsrcb"><b>${esc(x.title || "Scan")}</b><span class="muted">${esc(x.creator || "")} · ${x.status === "running" ? "scanning…" : x.status === "error" ? "stopped" : x.count + " moments"} · ${ago(x.created_at)}</span>
      <div class="row" style="margin-top:8px"><button class="pri" data-s="${x.id}">Open</button><button data-sd="${x.id}">Remove</button></div></div></div>`).join("")}</div>` : `<div class="muted">Nothing yet. Press “Find the best clips” on any source above.</div>`;
    $("#fndlist").querySelectorAll("[data-s]").forEach(b => b.onclick = () => showScan(b.dataset.s));
    $("#fndlist").querySelectorAll("[data-sd]").forEach(b => b.onclick = guard(async () => { await api(`/api/finder/scans/${b.dataset.sd}`, {method: "DELETE"}); drawScans(); }));
  });
  const _dl = drawList; drawList = async () => { await _dl(); drawScans(); };
  document.querySelectorAll("#edtiles .edtile").forEach(t => t.onclick = () => draw(t.dataset.k));
  draw("twitch"); drawList();
}

async function openEditor(src) {
  const old = document.getElementById("edm"); if (old) old.remove();
  const dur = src.duration, SW = src.width, SH = src.height;
  const S = {segs: [[0, dur]], sel: 0, aspect: "9:16", fit: "crop", focus: {x: .5, y: .5}, cam: {x: 0, y: 0, w: .3, h: .3}, face: src.face || null, captions: false, texts: [], st: -1};
  if (S.face) S.focus = {x: S.face.x, y: S.face.y};
  const hist = [];
  const host = document.createElement("div"); host.id = "edm"; host.className = "edm";
  host.innerHTML = `<div class="edtop"><div class="edtitle"><span class="edsi">${edIcon("scissors")}</span><input id="e_title" value="${esc(src.title)}" maxlength="100" aria-label="Title"></div>
    <div class="row"><button id="e_undo" title="Undo (Ctrl+Z)">Undo</button><button id="e_close">Close</button></div></div>
    <div class="edcols">
    <div class="edcol edL"><div class="edlogo"><span class="edsi">${edIcon("wand")}</span><b>AI Edit</b></div>
      <button class="edbig" id="e_auto"><b>Auto edit</b><span>Cuts the dead air</span></button>
      <label class="edchk"><input type="checkbox" id="e_ums"> Also cut the “ums” (slower)</label>
      <div class="edor"><span>or</span></div>
      <label style="margin-top:0">Ask</label><div class="edask"><input id="e_ask" placeholder="Try “trim 3s off the end”"><button class="edgo" id="e_askgo" title="Do it">→</button></div>
      <div class="help">Say things like: cut 0:20 to 0:35 · keep 0:10 to 0:40 · trim 3s off the start · vertical · blur background · captions on</div>
      <div class="edtp"><button class="edt" id="e_face">${edIcon("face")}<b>Face detect</b></button><button class="edt" id="e_split">${edIcon("split")}<b>Split screen</b></button></div>
      <div class="help" id="e_msg" style="min-height:2.4em"></div></div>
    <div class="edcol edM"><div class="edmon"><div class="evw" id="evw" style="aspect-ratio:${SW}/${SH};width:min(100%,${Math.round(300 * SW / SH)}px)"><video id="ev" preload="auto" playsinline></video><div class="eguide" id="eg" hidden></div><div class="eface" id="ef" hidden><span>Face</span></div></div></div>
      <div class="edbar"><button class="edpp" id="e_pp" title="Play / pause (Space)">▶</button><span class="edtime" id="e_time"></span><span class="grow"></span>
        <button id="e_cut" title="Cut the video in two at the playhead (S)">${edIcon("scissors")}<span>Split here</span></button><button id="e_del" title="Remove the selected part (Delete)">Remove part</button><button id="e_reset">Reset</button></div>
      <div class="etl" id="etl"><div class="etlbg" style="background-image:url(/api/editor/sources/${src.id}/strip)"></div><div class="etlseg" id="etls"></div><div class="ehead" id="ehead"></div></div>
      <div class="help" id="e_sum" style="margin-top:6px"></div>
      <div class="edasp" id="e_asp"><button data-a="16:9"><i style="width:22px;height:13px"></i><b>16:9</b><span>Landscape</span></button><button data-a="9:16"><i style="width:13px;height:22px"></i><b>9:16</b><span>Vertical</span></button><button data-a="4:5"><i style="width:16px;height:20px"></i><b>4:5</b><span>Portrait</span></button></div></div>
    <div class="edcol edR"><div class="row"><button class="edic" id="e_cc" title="Captions: the words appear as they are spoken">CC</button><button class="edic" id="e_txt" title="Add text to the picture">T</button><button class="pri" id="e_export" style="margin-left:auto">Export</button></div>
      <div class="edprev"><canvas id="ec"></canvas></div>
      <div class="edfits" id="e_fits"><button data-f="crop"><b>Crop</b></button><button data-f="blur"><b>Blur fill</b></button><button data-f="whole"><b>Whole clip</b></button></div>
      <div id="e_tx"></div></div></div>
    <div class="edx" id="e_x" hidden></div>`;
  document.body.appendChild(host);
  const q = s => host.querySelector(s), qa = s => host.querySelectorAll(s);
  const vid = q("#ev"); vid.src = `/api/editor/sources/${src.id}/video`;
  const cv = q("#ec"), ctx = cv.getContext("2d");
  const msg = t => { q("#e_msg").textContent = t || ""; };
  const total = () => S.segs.reduce((a, [x, y]) => a + (y - x), 0);
  const push = () => { hist.push(JSON.stringify(S.segs)); if (hist.length > 50) hist.shift(); };
  const norm = () => { S.segs = S.segs.filter(([a, b]) => b - a >= .3).sort((x, y) => x[0] - y[0]); if (!S.segs.length) S.segs = [[0, dur]]; S.sel = Math.min(S.sel, S.segs.length - 1); };
  const srcAr = SW / SH;
  const outAr = () => ED_ASPECT[S.aspect][0] / ED_ASPECT[S.aspect][1];
  const topFrac = .38;
  const camH = () => Math.min(1, (S.cam.w * SW / (ED_ASPECT["9:16"][0] / (ED_ASPECT["9:16"][1] * topFrac))) / SH);
  const setCamFromFace = () => {
    const f = S.face; const w = f ? Math.min(1, Math.max(.2, f.w * 3.2)) : .3; S.cam.w = w; const h = camH();
    S.cam.x = f ? Math.min(1 - w, Math.max(0, f.x - w / 2)) : 0; S.cam.y = f ? Math.min(1 - h, Math.max(0, f.y - h / 2)) : 0;
  };
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  /* ---- the timeline */
  const tl = q("#etl");
  const pct = t => (100 * t / dur) + "%";
  const drawTl = () => {
    let h = "", prev = 0;
    S.segs.forEach(([a, b], i) => {
      if (a > prev) h += `<div class="etgap" style="left:${pct(prev)};width:${pct(a - prev)}"></div>`;
      h += `<div class="etseg${i === S.sel ? " on" : ""}" data-i="${i}" style="left:${pct(a)};width:${pct(b - a)}"><i class="hl" data-h="a"></i><i class="hr" data-h="b"></i></div>`; prev = b;
    });
    if (prev < dur) h += `<div class="etgap" style="left:${pct(prev)};width:${pct(dur - prev)}"></div>`;
    q("#etls").innerHTML = h;
    q("#e_sum").textContent = `Result: ${edFmt(total(), true)} from ${edFmt(dur)} · ${S.segs.length} part${S.segs.length > 1 ? "s" : ""}. Click a part to select it, drag its edges to trim.`;
  };
  const tAt = e => clamp((e.clientX - tl.getBoundingClientRect().left) / tl.getBoundingClientRect().width, 0, 1) * dur;
  tl.addEventListener("pointerdown", e => {
    const hnd = e.target.dataset && e.target.dataset.h, seg = e.target.closest(".etseg");
    if (hnd && seg) {
      const i = +seg.dataset.i; S.sel = i; push(); tl.setPointerCapture(e.pointerId);
      const mv = ev => { const t = tAt(ev), lo = i ? S.segs[i - 1][1] + .05 : 0, hi = i < S.segs.length - 1 ? S.segs[i + 1][0] - .05 : dur;
        if (hnd === "a") S.segs[i][0] = clamp(t, lo, S.segs[i][1] - .3); else S.segs[i][1] = clamp(t, S.segs[i][0] + .3, hi); vid.currentTime = S.segs[i][hnd === "a" ? 0 : 1] - (hnd === "b" ? .05 : 0); drawTl(); };
      const up = () => { tl.removeEventListener("pointermove", mv); tl.removeEventListener("pointerup", up); };
      tl.addEventListener("pointermove", mv); tl.addEventListener("pointerup", up); e.preventDefault(); return;
    }
    const t = tAt(e); const i = S.segs.findIndex(([a, b]) => t >= a && t <= b); if (i >= 0) S.sel = i; vid.currentTime = t; drawTl();
    tl.setPointerCapture(e.pointerId); const mv = ev => { vid.currentTime = tAt(ev); }, up = () => { tl.removeEventListener("pointermove", mv); tl.removeEventListener("pointerup", up); };
    tl.addEventListener("pointermove", mv); tl.addEventListener("pointerup", up);
  });
  q("#e_cut").onclick = () => { const t = vid.currentTime, i = S.segs.findIndex(([a, b]) => t > a + .3 && t < b - .3); if (i < 0) return msg("Move the playhead into a part (at least 0.3 s from its edges), then split."); push(); const [a, b] = S.segs[i]; S.segs.splice(i, 1, [a, t], [t, b]); S.sel = i + 1; drawTl(); msg("Split. Select a part and press Remove part to cut it out."); };
  q("#e_del").onclick = () => { if (S.segs.length < 2) return msg("Keep at least one part."); push(); S.segs.splice(S.sel, 1); norm(); drawTl(); };
  q("#e_reset").onclick = () => { push(); S.segs = [[0, dur]]; S.sel = 0; drawTl(); };
  q("#e_undo").onclick = () => { const h = hist.pop(); if (h) { S.segs = JSON.parse(h); norm(); drawTl(); } };
  /* ---- playing (skips the cut parts) */
  const playPause = () => { if (vid.paused) { const t = vid.currentTime; if (!S.segs.some(([a, b]) => t >= a && t < b - .05)) vid.currentTime = (S.segs.find(([a]) => a > t) || S.segs[0])[0]; vid.play(); } else vid.pause(); };
  q("#e_pp").onclick = playPause;
  const key = e => {
    if (!host.isConnected) return document.removeEventListener("keydown", key);
    if (e.target.matches("input,textarea,select")) return;
    if (e.key === " ") { e.preventDefault(); playPause(); } else if (e.key.toLowerCase() === "s") q("#e_cut").click(); else if (e.key === "Delete") q("#e_del").click(); else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); q("#e_undo").click(); }
  };
  document.addEventListener("keydown", key);
  /* ---- the picture the viewer will get (drawn from the video; the exported file is made by the server with the same rules) */
  const sizeCanvas = () => { const ar = outAr(), w = Math.round(Math.min(300, 400 * ar)), h = Math.round(w / ar); cv.style.width = w + "px"; cv.style.height = h + "px"; cv.width = w * 2; cv.height = h * 2; };
  const cover = (dx, dy, dw, dh, sx, sy, sw, sh) => { const k = Math.max(dw / sw, dh / sh), ww = dw / k, hh = dh / k; return [clamp(sx + sw / 2 - ww / 2, sx, sx + sw - ww), clamp(sy + sh / 2 - hh / 2, sy, sy + sh - hh), ww, hh]; };
  const drawOut = () => {
    const W = cv.width, H = cv.height, vw = vid.videoWidth || SW, vh = vid.videoHeight || SH; ctx.fillStyle = "#000"; ctx.fillRect(0, 0, W, H);
    if (vid.readyState < 2) return;
    if (S.fit === "crop") {
      const k = Math.max(W / vw, H / vh), ww = W / k, hh = H / k, sx = clamp(S.focus.x * vw - ww / 2, 0, vw - ww), sy = clamp(S.focus.y * vh - hh / 2, 0, vh - hh); ctx.drawImage(vid, sx, sy, ww, hh, 0, 0, W, H);
    } else if (S.fit === "blur") {
      const [sx, sy, sw, sh] = cover(0, 0, W, H, 0, 0, vw, vh); try { ctx.filter = "blur(14px)"; } catch (e) {} ctx.drawImage(vid, sx, sy, sw, sh, 0, 0, W, H); ctx.filter = "none";
      const k = Math.min(W / vw, H / vh); ctx.drawImage(vid, 0, 0, vw, vh, (W - vw * k) / 2, (H - vh * k) / 2, vw * k, vh * k);
    } else if (S.fit === "whole") {
      const k = Math.min(W / vw, H / vh); ctx.drawImage(vid, 0, 0, vw, vh, (W - vw * k) / 2, (H - vh * k) / 2, vw * k, vh * k);
    } else {
      const th = Math.round(H * topFrac), c = S.cam, ch = camH(); const [a, b, w, h] = cover(0, 0, W, th, c.x * vw, c.y * vh, c.w * vw, ch * vh); ctx.drawImage(vid, a, b, w, h, 0, 0, W, th);
      const [d, e, f, g] = cover(0, 0, W, H - th, 0, 0, vw, vh); ctx.drawImage(vid, d, e, f, g, 0, th, W, H - th);
    }
    const t = vid.currentTime, sc = outAr() >= 1 ? W / 1920 * 1.6 : W / 1080;
    S.texts.forEach((x, i) => { if (t >= x.t0 && t <= x.t1) { ctx.font = `900 ${Math.round(x.size * sc * (outAr() >= 1 ? 1 : 1))}px Segoe UI, Arial`; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.lineWidth = Math.max(2, x.size * sc / 9); ctx.strokeStyle = "#000"; ctx.lineJoin = "round"; ctx.strokeText(x.text, x.x * W, x.y * H); ctx.fillStyle = x.color; ctx.fillText(x.text, x.x * W, x.y * H); if (i === S.st) { ctx.strokeStyle = "#ffb15c"; ctx.setLineDash([6, 4]); ctx.lineWidth = 2; const m = ctx.measureText(x.text); ctx.strokeRect(x.x * W - m.width / 2 - 6, x.y * H - x.size * sc / 2 - 4, m.width + 12, x.size * sc + 8); ctx.setLineDash([]); } } });
    if (S.captions) { ctx.font = `900 ${Math.round(W / 14)}px Segoe UI, Arial`; ctx.textAlign = "center"; ctx.fillStyle = "#fff"; ctx.strokeStyle = "#000"; ctx.lineWidth = 5; ctx.strokeText("CAPTIONS", W / 2, H * (outAr() >= 1 ? .86 : .74)); ctx.fillText("CAPTIONS", W / 2, H * (outAr() >= 1 ? .86 : .74)); }
  };
  const guide = () => {
    const g = q("#eg"), f = q("#ef");
    if (S.face) { f.hidden = false; f.style.cssText = `left:${(S.face.x - S.face.w / 2) * 100}%;top:${(S.face.y - S.face.h / 2) * 100}%;width:${S.face.w * 100}%;height:${S.face.h * 100}%`; } else f.hidden = true;
    let w, h, x, y;
    if (S.fit === "split") { w = S.cam.w; h = camH(); x = S.cam.x; y = S.cam.y; }
    else if (S.fit === "crop") { const ar = outAr(); w = Math.min(1, ar / srcAr); h = Math.min(1, srcAr / ar); x = clamp(S.focus.x - w / 2, 0, 1 - w); y = clamp(S.focus.y - h / 2, 0, 1 - h); }
    if (w === undefined || (w >= .999 && h >= .999)) { g.hidden = true; return; }
    g.hidden = false; g.style.cssText = `left:${x * 100}%;top:${y * 100}%;width:${w * 100}%;height:${h * 100}%`; g.title = S.fit === "split" ? "Drag to choose the camera area" : "Drag to choose what stays in view";
  };
  const eg = q("#eg");
  eg.addEventListener("pointerdown", e => {
    const wr = q("#evw").getBoundingClientRect(); const sx = e.clientX, sy = e.clientY, f0 = {...S.focus}, c0 = {...S.cam}; eg.setPointerCapture(e.pointerId);
    const mv = ev => { const dx = (ev.clientX - sx) / wr.width, dy = (ev.clientY - sy) / wr.height;
      if (S.fit === "split") { S.cam.x = clamp(c0.x + dx, 0, 1 - S.cam.w); S.cam.y = clamp(c0.y + dy, 0, 1 - camH()); } else { S.focus.x = clamp(f0.x + dx, 0, 1); S.focus.y = clamp(f0.y + dy, 0, 1); } guide(); };
    const up = () => { eg.removeEventListener("pointermove", mv); eg.removeEventListener("pointerup", up); }; eg.addEventListener("pointermove", mv); eg.addEventListener("pointerup", up); e.preventDefault();
  });
  cv.addEventListener("pointerdown", e => { if (S.st < 0) return; const r = cv.getBoundingClientRect(); cv.setPointerCapture(e.pointerId);
    const mv = ev => { S.texts[S.st].x = clamp((ev.clientX - r.left) / r.width, 0, 1); S.texts[S.st].y = clamp((ev.clientY - r.top) / r.height, 0, 1); }; mv(e);
    const up = () => { cv.removeEventListener("pointermove", mv); cv.removeEventListener("pointerup", up); }; cv.addEventListener("pointermove", mv); cv.addEventListener("pointerup", up); });
  /* ---- controls */
  const refresh = () => {
    qa("#e_asp button").forEach(b => b.classList.toggle("on", b.dataset.a === S.aspect));
    const fits = [["crop", "Crop"], ["blur", "Blur fill"], ["whole", "Whole clip"]].concat(S.aspect === "9:16" ? [["split", "Split screen"]] : []);
    q("#e_fits").innerHTML = fits.map(([f, n]) => `<button data-f="${f}" class="${S.fit === f ? "on" : ""}"><b>${n}</b></button>`).join("");
    qa("#e_fits button").forEach(b => b.onclick = () => { S.fit = b.dataset.f; if (S.fit === "split") setCamFromFace(); refresh(); });
    q("#e_cc").classList.toggle("on", S.captions); q("#e_split").classList.toggle("on", S.fit === "split"); sizeCanvas(); guide(); drawTx();
  };
  qa("#e_asp button").forEach(b => b.onclick = () => { S.aspect = b.dataset.a; if (S.aspect !== "9:16" && S.fit === "split") S.fit = "blur"; refresh(); });
  q("#e_cc").onclick = () => { S.captions = !S.captions; q("#e_cc").classList.toggle("on", S.captions); msg(S.captions ? "Captions will be made from the speech when you export." : "Captions off."); };
  q("#e_split").onclick = () => { S.aspect = "9:16"; S.fit = S.fit === "split" ? "crop" : "split"; if (S.fit === "split") { setCamFromFace(); msg(S.face ? "The camera area is the face. Drag the box on the video to move it." : "Drag the box on the video onto the streamer's camera. (Face detect can find it for you.)"); } refresh(); };
  const drawTx = () => {
    q("#e_tx").innerHTML = S.texts.length ? S.texts.map((x, i) => `<div class="edtx${i === S.st ? " on" : ""}" data-i="${i}"><div class="row"><input data-k="text" value="${esc(x.text)}" maxlength="120" style="flex:1 1 120px"><input data-k="color" type="color" value="${x.color}" style="width:38px;padding:2px;flex:none"><button data-k="del" title="Remove this text">×</button></div>
      <div class="row" style="margin-top:6px"><label style="margin:0">Size</label><input data-k="size" type="range" min="30" max="160" value="${x.size}" style="flex:1"></div>
      <div class="row" style="margin-top:6px"><label style="margin:0">Shown from</label><input data-k="t0" value="${edFmt(x.t0, true)}" style="max-width:76px"><label style="margin:0">to</label><input data-k="t1" value="${edFmt(x.t1, true)}" style="max-width:76px"></div>
      <div class="help">Drag the text on the picture above to place it.</div></div>`).join("") : "";
    qa("#e_tx .edtx").forEach(box => { const i = +box.dataset.i;
      box.onpointerdown = () => { if (S.st !== i) { S.st = i; qa("#e_tx .edtx").forEach(b => b.classList.toggle("on", +b.dataset.i === i)); } };
      box.querySelectorAll("[data-k]").forEach(el => { const k = el.dataset.k;
        if (k === "del") el.onclick = () => { S.texts.splice(i, 1); S.st = -1; drawTx(); };
        else el.oninput = () => { if (k === "text") S.texts[i].text = el.value || " "; else if (k === "color") S.texts[i].color = el.value; else if (k === "size") S.texts[i].size = +el.value; else S.texts[i][k] = edTime(el.value); }; }); });
  };
  q("#e_txt").onclick = () => { if (S.texts.length >= 20) return; const t = vid.currentTime; S.texts.push({text: "Your text", t0: t, t1: Math.min(dur, t + 3), x: .5, y: .2, size: 80, color: "#ffffff"}); S.st = S.texts.length - 1; drawTx(); };
  const runTask = async (btn, label, start, done) => {
    const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<div class="spin"></div><b>${label}</b>`;
    try { const r = await start(); const res = await edWatch(r.task, t => { msg(t.message + (t.pct ? ` ${t.pct}%` : "")); }); done(res); }
    catch (e) { msg(e.message); toast(e.message, true); } finally { btn.disabled = false; btn.innerHTML = old; }
  };
  q("#e_auto").onclick = () => runTask(q("#e_auto"), "Working…", () => api(`/api/editor/sources/${src.id}/auto`, {method: "POST", body: {ums: q("#e_ums").checked}}),
    r => { push(); S.segs = r.segments; S.sel = 0; norm(); drawTl(); msg(`Auto edit removed ${r.removed} seconds${r.ums ? ` and ${r.ums} “um”${r.ums > 1 ? "s" : ""}` : ""}. Press Undo to go back.`); });
  q("#e_face").onclick = () => runTask(q("#e_face"), "Looking…", () => api(`/api/editor/sources/${src.id}/face`, {method: "POST", body: {}}),
    r => { if (!r.face) return msg("No face found. Drag the box on the video to choose what stays in view."); S.face = r.face; S.focus = {x: r.face.x, y: r.face.y}; if (S.fit === "whole" || S.fit === "blur") S.fit = "crop"; setCamFromFace(); refresh(); msg("Found the face. The crop now follows it. Drag the box to adjust."); });
  const ask = guard(async () => {
    const text = q("#e_ask").value.trim(); if (!text) return;
    const r = await api(`/api/editor/sources/${src.id}/ask`, {method: "POST", body: {text, state: {segments: S.segs, aspect: S.aspect, fit: S.fit, captions: S.captions}}});
    push(); const n = r.state; if (n.segments) { S.segs = n.segments; norm(); } if (n.aspect) S.aspect = n.aspect; if (n.fit) S.fit = n.fit; if (typeof n.captions === "boolean") S.captions = n.captions;
    if (S.fit === "split" && S.aspect !== "9:16") S.fit = "blur"; if (S.fit === "split") setCamFromFace(); q("#e_ask").value = ""; msg("Done: " + r.done.join(" · ")); drawTl(); refresh();
  });
  q("#e_askgo").onclick = ask; q("#e_ask").onkeydown = e => { if (e.key === "Enter") ask(); };
  /* ---- export */
  q("#e_export").onclick = () => {
    const box = q("#e_x"); box.hidden = false; const fitName = {crop: "Crop to fill", blur: "Blur fill", whole: "Whole clip", split: "Split screen"}[S.fit];
    box.innerHTML = `<div class="edxc card"><h2>Save as a video</h2><p class="muted" style="margin:0 0 6px">${edFmt(total(), true)} · ${S.aspect} · ${fitName}${S.captions ? " · captions" : ""}${S.texts.length ? ` · ${S.texts.length} text${S.texts.length > 1 ? "s" : ""}` : ""}</p>
      <label>Title</label><input id="x_title" value="${esc(q("#e_title").value)}" maxlength="100"><label>Description (optional)</label><textarea id="x_desc" style="min-height:70px" placeholder="${src.credit ? "Left empty, the original creator is credited for you." : "Optional"}"></textarea>
      <p class="help">It is saved in your Videos and waits for your check; it is never uploaded by itself. This costs no tokens.</p>
      <div id="x_st"></div><div class="row" style="margin-top:12px"><button class="pri" id="x_go">Make the video</button><button id="x_cancel">Back to editing</button></div></div>`;
    q("#x_cancel").onclick = () => { box.hidden = true; };
    q("#x_go").onclick = async () => {
      const go = q("#x_go"); go.disabled = true; const st = q("#x_st"); st.innerHTML = `<div class="pgx-bar"><i id="x_bar" style="width:3%"></i></div><div class="help" id="x_m">Starting…</div>`;
      try {
        const spec = {segments: S.segs, aspect: S.aspect, fit: S.fit, focus: S.focus, cam: S.fit === "split" ? {...S.cam, h: camH()} : null, captions: S.captions, texts: S.texts};
        const r = await api(`/api/editor/sources/${src.id}/render`, {method: "POST", body: {spec, title: q("#x_title").value, description: q("#x_desc").value}});
        const res = await edWatch(r.task, t => { q("#x_bar").style.width = Math.max(3, t.pct) + "%"; q("#x_m").textContent = t.message; });
        st.innerHTML = `<div class="authmsg ok">Saved to your Videos (${edFmt(res.seconds, true)}). It is waiting for your check.</div>`; q("#x_go").textContent = "Done"; q("#x_cancel").textContent = "Keep editing";
        const open = document.createElement("button"); open.className = "pri"; open.textContent = "Open Videos"; open.onclick = () => { close(); location.hash = "#/videos"; }; q("#x_go").replaceWith(open);
      } catch (e) { st.innerHTML = `<div class="authmsg bad">${esc(e.message)}</div>`; go.disabled = false; }
    };
  };
  const close = () => { vid.pause(); document.removeEventListener("keydown", key); host.remove(); };
  q("#e_close").onclick = () => { if (hist.length && !confirm("Close the editor? Your cuts will be lost (the video stays in your editor list).")) return; close(); };
  /* ---- the loop */
  const tick = () => {
    if (!host.isConnected) return;
    const t = vid.currentTime;
    if (!vid.paused) { if (!S.segs.some(([a, b]) => t >= a - .03 && t < b)) { const nx = S.segs.find(([a]) => a > t); if (nx) vid.currentTime = nx[0]; else { vid.pause(); vid.currentTime = S.segs[S.segs.length - 1][0]; } } }
    q("#e_pp").textContent = vid.paused ? "▶" : "❚❚"; q("#ehead").style.left = pct(t);
    let outT = 0; for (const [a, b] of S.segs) { if (t >= b) outT += b - a; else { outT += Math.max(0, t - a); break; } }
    q("#e_time").textContent = `${edFmt(t, true)} / ${edFmt(dur, true)}  ·  result ${edFmt(total(), true)}`;
    drawOut(); requestAnimationFrame(tick);
  };
  vid.addEventListener("loadeddata", () => { vid.currentTime = 0.01; });
  drawTl(); refresh(); requestAnimationFrame(tick);
  if (!S.face) api(`/api/editor/sources/${src.id}/face`, {method: "POST", body: {}}).then(r => edWatch(r.task)).then(r => { if (r.face && host.isConnected) { S.face = r.face; S.focus = {x: r.face.x, y: r.face.y}; setCamFromFace(); refresh(); msg("Found the face and centred the crop on it."); } }).catch(() => {});
}

