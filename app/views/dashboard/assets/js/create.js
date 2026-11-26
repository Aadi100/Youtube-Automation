/* Make a video. */
"use strict";
/* ------------------------------------------------------------ create */
async function create() {
  $("#main").innerHTML = `<h1>Make a video</h1>
  <div class="crt">
   <div class="crt-main">
    <section class="card crt-sec"><div class="crt-h"><span class="crt-n">1</span><div><h2>What are you making?</h2><p>Pick the kind of video.</p></div></div>
      <div class="choices crt-kind" id="kind"><button class="choice on" data-v="auto-short"><span class="kart">${edIcon("phone")}</span><b>Short</b><span class="kd">Under 60 seconds, vertical 9:16. Fast and easy to make.</span></button>
        <button class="choice" data-v="auto-compilation"><span class="kart">${edIcon("film")}</span><b>Compilation</b><span class="kd">An 8–10 minute video joined from about 14 clips.</span></button></div></section>
    <section class="card crt-sec"><div class="crt-h"><span class="crt-n">2</span><div><h2>Where should the clips come from?</h2><p>Search by game, or take clips from one creator.</p></div>
        <div class="seg crt-seg" id="srcmode" style="margin-left:auto"><button class="on" data-m="game" type="button">By game</button><button data-m="creator" type="button">One creator</button></div></div>
      <div id="pn_game"><label class="crt-l">Game</label><div class="pkchips" id="pk_game"></div>
        <label class="crt-l" id="l_source">Look for clips on</label><div class="pkgrid" id="pk_source"></div>
        <div id="trend_box" hidden><label class="crt-l">Trending mode</label>
          <label class="row" style="gap:12px;align-items:center;cursor:pointer"><span class="switch"><input type="checkbox" id="d_trend"><span></span></span><b>Look at what is trending for this game first</b><span class="muted" id="trend_price"></span></label>
          <div class="help" style="margin-top:6px">The studio looks back two days, ranks Twitch and YouTube clips and videos by how fast they are growing (views per hour) and takes the best live stream too, then clips from the fastest risers. An AI can also read what is hot for the game. The fee is charged only when the video is made.</div></div></div>
      <div id="pn_creator" hidden><div id="creatorbox"><label class="crt-l" style="margin-top:0">Creator</label>
        <div class="edsearch"><div class="pkmini" id="cr_tiles"></div><input id="cr_name" class="grow" autocomplete="off" placeholder="Name, or a link to their channel"><button id="cr_check" type="button" class="edgo" title="Check who this is">→</button></div>
        <div class="row" style="margin-top:10px"><button id="cr_save" type="button">Save to my list</button><span class="muted" id="cr_info" style="flex:1;min-width:200px">Only this creator's own recent clips or videos are used. The creator is credited, the clip is yours alone, and it still goes through the safety check.</span></div>
        <div class="pkchips" id="cr_saved" style="margin:10px 0 0"></div>
        <div class="help" style="margin-top:12px">The game you pick under “By game” is used for the title and thumbnail. With Auto and a Twitch creator, it is taken from the clip itself.</div></div></div>
    </section>
    <section class="card crt-sec"><div class="crt-h"><span class="crt-n">3</span><div><h2>What kind of moment?</h2><p>Say exactly what you want this time, or leave it on any moment.</p></div></div>
      <div class="pkchips" id="pk_want"></div>
      <div class="help" id="want_desc" style="margin-top:8px"></div>
      <label class="crt-l">Or say it in your own words (optional)</label>
      <input id="want_text" maxlength="200" autocomplete="off" placeholder="e.g. a street fight where the police arrive, or someone reacting to a trailer">
      <div id="want_strict_box" hidden><label class="crt-l">How strict</label>
        <div class="seg crt-seg" id="want_strict"><button class="on" data-s="1" type="button">Only this</button><button data-s="0" type="button">Prefer this</button></div>
        <div class="help" id="want_help" style="margin-top:8px"></div></div>
    </section>
    <section class="card crt-sec"><div class="crt-h"><span class="crt-n">4</span><div><h2>Voice and sound</h2><p>Who talks, and what happens to the creator's own audio.</p></div></div>
      <label class="crt-l" style="margin-top:0">Narrator</label><div class="row"><div style="flex:1;min-width:220px"><select id="voice"><option value="default">Use my default (Settings)</option><option value="random">Random for this video</option></select></div><button type="button" id="v_listen">${edIcon("speaker")}<span>Listen</span></button></div>
      <label class="crt-l">Original audio</label><div class="pkgrid" id="pk_audio"></div></section>
    <section class="card crt-sec"><div class="crt-h"><span class="crt-n">5</span><div><h2>After it is made</h2><p>Upload it by itself, or check it first.</p></div></div><div class="pkgrid" id="pk_after"></div></section>
    <section class="card crt-sec"><div class="crt-h"><span class="crt-n">6</span><div><h2>More control</h2><p>Do parts yourself to save tokens, or fine-tune the run.</p></div></div><details class="more" id="diybox" hidden><summary>Do it yourself · save tokens</summary>
        <p class="muted" style="margin:6px 0 4px">Whatever the AI does not do is not charged. The content-safety check always runs and cannot be skipped.</p>
        <div id="diy_ai"><label>Which AI writes the text</label><select id="ai_text"><option value="">Balanced (default)</option><option value="budget">${ME.role === "owner" ? "Budget: DeepSeek first (cheapest)" : "Budget (cheapest)"}</option><option value="quality">${ME.role === "owner" ? "Quality: Gemini first" : "Quality (best writing)"}</option><option value="off">No AI text: I write everything</option></select></div>
        <div id="diy_meta"><label>Title and description</label><select id="d_title"><option value="ai">AI writes them</option><option value="mine">I write them</option></select>
          <div id="d_title_box" hidden><input id="own_title" maxlength="90" placeholder="Your title"><textarea id="own_desc" maxlength="1500" style="min-height:70px" placeholder="Your description (the creator credits and hashtags are added for you)"></textarea><input id="own_tags" placeholder="Tags, separated by commas (optional)"></div></div>
        <div id="diy_thumb"><label>Thumbnail</label><select id="d_thumb"><option value="ai">AI image</option><option value="frame">A frame from the video (no AI). You can upload your own later, inside the video.</option></select>
          <label style="margin-top:12px">Thumbnail level</label><select id="d_tier"><option value="">My setting</option></select><div class="help" id="d_tier_help"></div>
          <select id="d_pics" style="margin-top:8px"><option value="">AI pictures: use my setting</option><option value="1">1 AI picture</option><option value="3">3 AI pictures to choose from (3 times the picture cost; pick in the Thumbnail studio)</option></select></div>
        <div id="diy_comm"><label>Commentary</label><select id="d_comm"><option value="ai">AI writes it</option><option value="mine">I write it (the voice is free)</option></select>
          <textarea id="own_comm" maxlength="1200" hidden style="min-height:70px" placeholder="Your commentary: about 2 words per second of the clip. Needs the audio mode 'Replace'."></textarea></div>
        <div id="diy_src"><label>The clip</label><select id="d_src"><option value="auto">Find it for me</option><option value="mine">I pick a YouTube clip</option></select>
          <div id="d_src_box" hidden><input id="own_url" placeholder="https://www.youtube.com/watch?v=..."><div class="row"><input id="own_start" type="number" min="0" placeholder="Start (seconds)"><input id="own_end" type="number" min="0" placeholder="End (seconds)"></div>
            <p class="muted" style="margin:4px 0 0">15 to 58 seconds. The creator is credited, the clip must be unique to you, and it still goes through the safety check.</p></div></div></details><details class="more"><summary>More options</summary>
        <div><label>Look back (hours)</label><input id="hours" type="number" min="1" max="168" value="24"></div>
        <div id="shortOpts"><label>Layout</label><select id="layout"><option value="blur">Blurred background</option><option value="split">Facecam on top + gameplay</option></select></div>
        <div id="compOpts" hidden><label>Clips to download</label><input id="count" type="number" min="1" max="40" value="14">
          <label>Target length (minutes)</label><input id="target" type="number" min="1" max="30" step="0.5" value="8">
          <label>Title (optional)</label><input id="title" placeholder="blank = '&lt;game&gt; Best Streamer Moments'"></div></details></section>
    <div hidden id="pkdata"><select id="game"><option value="auto">Auto: take turns across all enabled games</option></select><select id="source"><option value="all">Everything (clips + live streams)</option><option value="both">Twitch + YouTube clips and videos</option><option value="live">Live streams only</option><option value="twitch">Twitch clips only</option><option value="youtube">YouTube only</option></select><select id="audio"><option value="default">Use my default (Settings)</option><option value="replace">Replace: AI commentary + music, original muted (safest)</option><option value="bed">Bed: original ducked under music</option><option value="original">Original: untouched (high claim risk)</option></select><select id="after"><option value="">Use my setting (Settings)</option><option value="auto">Upload it automatically as Unlisted</option><option value="hold">Wait for me: I check it and choose the audio before it goes to YouTube</option></select><select id="cr_plat"><option value="twitch">Twitch</option><option value="youtube">YouTube</option></select></div>
   </div>
   <aside class="crt-side">
    <div class="card crt-sum"><h2>Your video</h2><div class="sumrows" id="sumrows"></div>
      <div class="crt-cost" id="costhint">Loading the price…</div>
      <button class="pri crt-go" id="go">Start making it</button><div class="muted" id="hint" style="text-align:center;margin-top:6px"></div></div>
    <div class="card"><h2>Progress</h2><div id="jobHead" class="muted">Start a video or pick one below to follow its progress.</div>
      <div class="row" style="margin-top:12px"><button id="cancel" class="dng" hidden>Cancel</button><a id="vlink" href="#" hidden>Open video</a></div></div>
   </aside>
  </div>
  <section class="card" style="margin-top:20px"><div class="sechead"><h2>Recent runs</h2></div><div id="jobs"></div></section>`;
  // ---- the picker layer: tiles that drive the (hidden) selects, so every rule below keeps working
  const tiles = (boxId, selId, items) => {
    const box = $("#" + boxId), sel = $("#" + selId);
    const draw = () => { box.innerHTML = items.map(([v, t, d, ic]) => `<button type="button" class="pk ${sel.value === v ? "on" : ""}" data-v="${esc(v)}">${ic ? `<span class="pki">${edIcon(ic)}</span>` : ""}<b>${t}</b><span>${d}</span></button>`).join(""); };
    box.onclick = e => { const b = e.target.closest(".pk"); if (!b) return; sel.value = b.dataset.v; sel.dispatchEvent(new Event("change")); };
    sel.addEventListener("change", draw); draw(); return draw;
  };
  let SRC = ["twitch", "youtube"]; try { SRC = (await api("/api/sources")).mine; } catch (e) {}        // where this account looks for clips (Settings -> Clip sources)
  tiles("pk_source", "source", [["all", "Everything", "Clips and live streams", "all"], ["both", "Twitch + YouTube", "Clips and videos", "both"], ["live", "Live now", "Streams happening now", "live"], ["twitch", "Twitch", "Clips only", "twitch"], ["youtube", "YouTube", "Videos only", "youtube"]].filter(t => t[0] === "twitch" ? SRC.includes("twitch") : t[0] === "youtube" ? SRC.includes("youtube") : t[0] === "both" ? SRC.length > 1 : true));
  tiles("pk_audio", "audio", [["default", "My default", "From Settings", "bolt"], ["replace", "AI commentary", "Music + voice, original muted. Safest.", "mic"], ["bed", "Original under music", "Original sound turned down", "bed"], ["original", "Original only", "Untouched. High claim risk.", "wave"]]);
  tiles("pk_after", "after", [["", "My setting", "From Settings", "bolt"], ["auto", "Upload by itself", "Goes to YouTube as Unlisted", "upload"], ["hold", "Wait for me", "I check it and choose the audio first", "hold"]]);
  const drawPlat = tiles("cr_tiles", "cr_plat", [["twitch", "Twitch", "", "twitch"], ["youtube", "YouTube", "", "youtube"]]);
  $("#cr_tiles").classList.add("pkmini");
  const drawGames = () => { const sel = $("#game"); $("#pk_game").innerHTML = [...sel.options].map(o => `<button type="button" class="pkchip ${sel.value === o.value ? "on" : ""}" data-v="${esc(o.value)}"><i>${o.value === "auto" ? "★" : esc(o.textContent.trim().slice(0, 1).toUpperCase())}</i>${o.value === "auto" ? "Auto: take turns" : esc(o.textContent)}</button>`).join(""); };
  $("#pk_game").onclick = e => { const b = e.target.closest(".pkchip"); if (!b) return; $("#game").value = b.dataset.v; $("#game").dispatchEvent(new Event("change")); };
  $("#game").addEventListener("change", drawGames);
  let crMode = "game";
  document.querySelectorAll("#srcmode button").forEach(b => b.onclick = () => { crMode = b.dataset.m; document.querySelectorAll("#srcmode button").forEach(x => x.classList.toggle("on", x === b)); $("#pn_creator").hidden = crMode !== "creator"; $("#l_source").hidden = $("#pk_source").hidden = crMode === "creator"; sum(); showCost(); });
  window.__crMode = () => crMode;
  // ---- what kind of moment: chips + the member's own words -> one request for this video
  const WANT_ICON = {reaction: "😮", fight: "🥊", funny: "😂", fail: "💥", clutch: "🎯", chaos: "🚔", scary: "😱", rage: "🤬", epic: "🏆", story: "🎬", glitch: "🐛"};
  let want = {kinds: [], text: "", strict: true}, wantKinds = [];
  const wantBody = () => { const t = $("#want_text").value.trim(); return want.kinds.length || t ? {kinds: want.kinds, text: t, strict: want.strict} : null; };
  const wantName = () => { const w = wantBody(); if (!w) return "Any moment"; return [...w.kinds.map(k => (wantKinds.find(x => x.id === k) || {}).name || k), ...(w.text ? [`“${w.text.slice(0, 28)}${w.text.length > 28 ? "…" : ""}”`] : [])].join(", "); };
  const drawWant = () => {
    $("#pk_want").innerHTML = `<button type="button" class="pkchip ${want.kinds.length ? "" : "on"}" data-k=""><i>✨</i>Any moment</button>` + wantKinds.map(k => `<button type="button" class="pkchip ${want.kinds.includes(k.id) ? "on" : ""}" data-k="${k.id}" title="${esc(k.desc)}"><i>${WANT_ICON[k.id] || "•"}</i>${esc(k.name)}</button>`).join("");
    const w = wantBody();
    $("#want_strict_box").hidden = !w;
    $("#want_desc").textContent = want.kinds.length ? want.kinds.map(k => { const x = wantKinds.find(y => y.id === k); return x ? `${x.name}: ${x.desc}.` : ""; }).join(" ") : "";
    document.querySelectorAll("#want_strict button").forEach(b => b.classList.toggle("on", (b.dataset.s === "1") === want.strict));
    $("#want_help").textContent = want.strict ? "Only moments like this are used. If none can be found the video can fail: choose “Prefer this” to let other good moments fill in." : "Moments like this are ranked first, but other good moments can still be used.";
  };
  $("#pk_want").onclick = e => {
    const b = e.target.closest(".pkchip"); if (!b) return; const k = b.dataset.k;
    if (!k) want.kinds = []; else if (want.kinds.includes(k)) want.kinds = want.kinds.filter(x => x !== k); else if (want.kinds.length < 3) want.kinds.push(k); else toast("Pick up to three kinds, or describe it in your own words");
    drawWant(); sum();
  };
  $("#want_strict").onclick = e => { const b = e.target.closest("button"); if (b) { want.strict = b.dataset.s === "1"; drawWant(); } };
  $("#want_text").addEventListener("input", () => { drawWant(); sum(); });
  $("#v_listen").onclick = () => { const v = $("#voice").value; if (!v || v === "default" || v === "random") return toast("Pick one voice to listen to it"); new Audio("/api/voices/preview?voice=" + encodeURIComponent(v)).play().catch(() => toast("Could not play the sample", true)); };
  const optText = id => { const o = $("#" + id).selectedOptions[0]; return o ? o.textContent.replace(/^(Use my default|Use my setting).*/, "My default").split(":")[0].split(" (")[0] : ""; };
  const sum = () => {
    const kindName = document.querySelector("#kind .choice.on").dataset.v === "auto-short" ? "Short · vertical" : "Compilation · 8–10 min";
    const srcName = crMode === "creator" ? `${$("#cr_plat").value === "twitch" ? "Twitch" : "YouTube"} · ${$("#cr_name").value.trim() || "choose a creator"}` : ({all: "Everything", both: "Twitch + YouTube", live: "Live now", twitch: "Twitch clips", youtube: "YouTube"})[$("#source").value];
    const game = $("#game").selectedOptions[0] ? ($("#game").value === "auto" ? "Auto" : $("#game").selectedOptions[0].textContent) : "Auto";
    const aud = ({default: "My default", replace: "AI commentary", bed: "Original under music", original: "Original only"})[$("#audio").value];
    const aft = ({"": "My setting", auto: "Upload by itself", hold: "Wait for me"})[$("#after").value];
    $("#sumrows").innerHTML = [["Type", kindName], ["Clips from", srcName], ["Game", game], ["Moment", wantName()], ["Sound", aud], ["Then", aft]].map(([k, v]) => `<div class="sumrow"><span>${k}</span><b>${esc(v)}</b></div>`).join("");
  };
  ["change", "input", "click"].forEach(ev => $("#main").addEventListener(ev, () => setTimeout(sum, 0)));
  const _dg = drawGames; setTimeout(() => { _dg(); sum(); }, 0);
  api("/api/games").then(gs => { $("#game").innerHTML = `<option value="auto">Auto: take turns across all enabled games</option>` +
    gs.map(g => `<option value="${esc(g.id)}">${esc(g.name)}${g.enabled ? "" : " (disabled)"}</option>`).join(""); $("#game").dispatchEvent(new Event("change")); }).catch(() => {});
  api("/api/voices").then(vs => { $("#voice").insertAdjacentHTML("beforeend", vs.map(v => `<option value="${esc(v.id)}">${esc(v.name)} · ${esc(v.locale.replace("en-", ""))} · ${esc(v.gender.toLowerCase())}</option>`).join("")); }).catch(() => {});
  const showCost = async () => {
    if (!TOK) await refreshTokens(); if (!TOK) return;
    const n = kind === "auto-short" ? TOK.reserve.short : TOK.reserve.compilation, up = kind === "auto-short" ? TOK.upload_fee.short : TOK.upload_fee.compilation;
    let est = "";
    try {
      const d = await getDiy(), e = d.estimate.parts, ai = $("#ai_text").value, off = ai === "off";
      const pick = t => off ? 0 : (ai === "budget" ? e[t].deepseek : ai === "quality" ? e[t].gemini : e[t].default);
      if (kind === "auto-short") {
        let t = e.safety.gemini;
        if ($("#d_src").value !== "mine") t += pick("scoring") + pick("moments");
        if ($("#d_title").value !== "mine") t += pick("metadata");
        if (["default", "replace"].includes($("#audio").value) && $("#d_comm").value !== "mine") t += pick("commentary");
        if ($("#d_thumb").value !== "frame") {
          const tiers = d.tiers || [], lv = $("#d_tier").value || d.tier || "better", row = tiers.find(x => x.id === lv), med = row;
          const pics = ($("#d_pics").value || String(d.pictures || 1)) === "3" ? 3 : 1, first = lv === "better" || !row ? d.estimate.image : row.price;
          t += first + (pics - 1) * (lv === "better" || !med ? d.estimate.image : med.price);
        }
        const tf = ($("#d_trend") && $("#d_trend").checked && !$("#trend_box").hidden) ? d.estimate.trend.short : 0;
        est = ` Estimated for this Short: about ${Math.round(t * 10) / 10} tokens + ${d.estimate.upload} for the upload${tf ? ` + ${tf} for Trending mode` : ""}.`;
      } else est = " A compilation costs roughly 8 to 10 times a Short" + (($("#d_trend") && $("#d_trend").checked && !$("#trend_box").hidden) ? ` + ${d.estimate.trend.compilation} for Trending mode.` : ".");
    } catch (e) {}
    $("#costhint").textContent = TOK.owner ? "Free for the owner (the usage is still recorded)." :
      `You pay only for what the video really uses (AI, images …).${est} ${n} tokens are reserved now and the unused part comes back; a failed video costs nothing. You have ${TOK.balance}.`;
  };
  let kind = "auto-short";
  const diyShow = () => {
    $("#diy_comm").hidden = kind !== "auto-short"; $("#diy_src").hidden = kind !== "auto-short";
    $("#d_title_box").hidden = $("#d_title").value !== "mine"; $("#own_comm").hidden = $("#d_comm").value !== "mine"; $("#d_src_box").hidden = $("#d_src").value !== "mine";
  };
  getDiy().then(d => {
    wantKinds = d.want_kinds || []; drawWant();
    const f = d.flags, all = d.owner;
    for (const [id, flag] of [["diy_ai", "ai_choice"], ["diy_meta", "own_metadata"], ["diy_thumb", "own_thumbnail"], ["diy_comm", "own_commentary"], ["diy_src", "own_source"]]) { if ($("#" + id)) $("#" + id).dataset.off = (all || f[flag]) ? "" : "1"; }
    const shown = ["diy_ai", "diy_meta", "diy_thumb", "diy_comm", "diy_src"].filter(id => $("#" + id) && !$("#" + id).dataset.off);
    ["diy_ai", "diy_meta", "diy_thumb", "diy_comm", "diy_src"].forEach(id => { if ($("#" + id) && $("#" + id).dataset.off) $("#" + id).remove(); });
    if ($("#diybox")) $("#diybox").hidden = !shown.length;
    if ($("#srcmode")) $("#srcmode").hidden = !(all || f.pick_creator);
    if ($("#trend_box")) {                                // Trending mode: only where the owner allowed it
      const tr = d.trending || {}; $("#trend_box").hidden = !tr.allowed; $("#d_trend").checked = !!(tr.allowed && tr.default);
      $("#trend_price").textContent = tr.allowed ? `+${d.estimate.trend.short} tokens for a Short, +${d.estimate.trend.compilation} for a compilation` : "";
      $("#d_trend").addEventListener("change", () => showCost());
    }
    ["ai_text", "d_title", "d_thumb", "d_pics", "d_tier", "d_comm", "d_src", "audio", "source"].forEach(id => { if ($("#" + id)) $("#" + id).addEventListener("change", () => { diyShow(); showCost(); }); });
    const tierSel = $("#d_tier");
    if (tierSel && d.tiers) {
      tierSel.innerHTML = `<option value="">My setting (${esc((d.tiers.find(x => x.id === d.tier) || {name: "Better"}).name)})</option>` + d.tiers.filter(x => x.available).map(x => `<option value="${x.id}">${esc(x.name)}: ${esc(x.desc)} About ${x.price} token${x.price === 1 ? "" : "s"} a picture.</option>`).join("");
      const locked = d.tiers.filter(x => !x.available); $("#d_tier_help").textContent = locked.length ? locked.map(x => `${x.name}: ${x.reason}`).join(" · ") : "";
    }
    diyShow(); showCost();
  }).catch(() => {});
  setTimeout(() => { if ($("#source")) { $("#source").addEventListener("change", showCost); showCost(); } }, 0);
  document.querySelectorAll("#kind button").forEach(b => b.onclick = () => {
    kind = b.dataset.v; document.querySelectorAll("#kind button").forEach(x => x.classList.toggle("on", x === b)); showCost(); if ($("#d_title_box")) { $("#diy_comm") && ($("#diy_comm").hidden = kind !== "auto-short"); $("#diy_src") && ($("#diy_src").hidden = kind !== "auto-short"); }
    $("#shortOpts").hidden = kind !== "auto-short"; $("#compOpts").hidden = kind !== "auto-compilation";
  });
  $("#go").onclick = guard(async () => {
    const body = {mode: kind, game_id: $("#game").value, source: $("#source").value, audio_mode: $("#audio").value, hours: +$("#hours").value};
    if ($("#voice").value !== "default") body.voice = $("#voice").value;
    if (kind === "auto-short") body.layout = $("#layout").value; else { body.count = +$("#count").value; body.target_minutes = +$("#target").value; body.title = $("#title").value; }
    const wb = wantBody(); if (wb) body.want = wb;
    const diy = {};
    if ($("#ai_text") && $("#ai_text").value) diy.ai_text = $("#ai_text").value;
    if ($("#d_title") && $("#d_title").value === "mine") {
      if (!$("#own_title").value.trim()) throw new Error("Write your title, or choose 'AI writes them'.");
      Object.assign(diy, {own_title: $("#own_title").value, own_description: $("#own_desc").value, own_tags: $("#own_tags").value});
    }
    if ($("#d_thumb") && $("#d_thumb").value === "frame") diy.thumbnail = "frame";
    if ($("#d_pics") && $("#d_pics").value && $("#d_thumb").value !== "frame") body.thumb_pictures = $("#d_pics").value;
    if ($("#d_tier") && $("#d_tier").value && $("#d_thumb").value !== "frame") body.thumb_tier = $("#d_tier").value;
    if ($("#d_trend") && $("#d_trend").checked && !$("#trend_box").hidden && !$("#pn_game").hidden) body.trending = true;
    if (kind === "auto-short") {
      if ($("#d_comm") && $("#d_comm").value === "mine") { if (!$("#own_comm").value.trim()) throw new Error("Write your commentary, or choose 'AI writes it'."); diy.own_commentary = $("#own_comm").value; }
      if ($("#d_src") && $("#d_src").value === "mine") { if (!$("#own_url").value.trim()) throw new Error("Paste the YouTube link, or choose 'Find it for me'."); Object.assign(diy, {own_url: $("#own_url").value.trim(), own_start: +$("#own_start").value, own_end: +$("#own_end").value}); }
    }
    if (window.__crMode && window.__crMode() === "creator" && $("#cr_name").value.trim()) {
      if (diy.own_url) throw new Error("Choose either a creator or your own clip link, not both.");
      diy.creator = {platform: $("#cr_plat").value, name: $("#cr_name").value.trim()};
    }
    if (Object.keys(diy).length) body.diy = diy;
    if ($("#after") && $("#after").value) body.after = $("#after").value;
    const r = await api("/api/jobs", {method: "POST", body}); activeJob = r.job_id; toast(r.position > 1 ? `Queued: ${r.position - 1} job(s) ahead of yours` : "Started"); refreshTokens(); showCost(); refresh();
  });
  const drawSaved = (list) => {
    const box = $("#cr_saved"); if (!box) return;
    box.innerHTML = list.length ? list.map(c => `<span class="tschip" data-id="${esc(c.id)}" title="Use this creator">${c.platform === "twitch" ? "Twitch" : "YouTube"} · ${esc(c.label)} <b data-x="${esc(c.id)}" title="Remove from my list" style="margin-left:6px;opacity:.7">×</b></span>`).join("") : "";
    box.querySelectorAll(".tschip").forEach(ch => ch.onclick = guard(async e => {
      const c = list.find(x => x.id === ch.dataset.id);
      if (e.target.dataset.x) { const r = await api(`/api/creators/${e.target.dataset.x}`, {method: "DELETE"}); drawSaved(r.creators); return; }
      $("#cr_plat").value = c.platform; $("#cr_plat").dispatchEvent(new Event("change")); $("#cr_name").value = c.name; $("#cr_info").textContent = `Using ${c.label}. Clips will come only from them.`;
    }));
  };
  api("/api/creators").then(r => drawSaved(r.creators)).catch(() => {});
  $("#cr_save").onclick = guard(async () => {
    const r = await api("/api/creators", {method: "POST", body: {platform: $("#cr_plat").value, name: $("#cr_name").value, label: $("#cr_info").dataset.label || ""}});
    drawSaved(r.creators); toast("Saved to your list");
  });
  $("#cr_check").onclick = guard(async () => {
    const info = $("#cr_info"); info.textContent = "Looking…";
    try {
      const r = await api("/api/creator/check", {method: "POST", body: {platform: $("#cr_plat").value, name: $("#cr_name").value}});
      $("#cr_plat").value = r.platform; $("#cr_plat").dispatchEvent(new Event("change")); info.dataset.label = r.name; info.innerHTML = `Found: <b>${esc(r.name)}</b> on ${r.platform === "twitch" ? "Twitch" : "YouTube"} (<a href="${esc(r.url)}" target="_blank" rel="noopener">open</a>)${r.description ? " · " + esc(r.description) : ""}. Clips will come only from them.`;
    } catch (e) { info.textContent = e.message; }
  });
  $("#cancel").onclick = guard(async () => { await api(`/api/jobs/${activeJob}/cancel`, {method: "POST"}); toast("Cancelling…"); });
  const refresh = guard(async () => {
    const jobs = await api("/api/jobs");
    $("#jobs").innerHTML = jobs.length ? `<table><tr><th>Started</th><th>Type</th><th>How</th><th>Status</th><th>Result</th></tr>${jobs.map(j => `
      <tr class="click" data-j="${j.id}"><td>${when(j.created_at)}</td><td>${esc(j.mode.replace("auto-", ""))}</td><td>${j.source === "n8n" ? "scheduled" : "by hand"}</td><td>${badge(j.status)}</td>
      <td class="muted">${esc(j.error || (j.video_id ? "video saved" : ""))}</td></tr>`).join("")}</table>` : emptyState("film", "No runs yet", "Your runs will be listed here.");
    document.querySelectorAll("#jobs tr[data-j]").forEach(tr => tr.onclick = () => { activeJob = tr.dataset.j; refresh(); });
    const running = jobs.find(j => j.status === "running");
    $("#go").disabled = !!running; $("#hint").textContent = running ? "Something is already rendering." : "";
    if (!activeJob && running) activeJob = running.id; if (!activeJob && jobs[0]) activeJob = jobs[0].id;
    if (activeJob) {
      const j = await api(`/api/jobs/${activeJob}`);
      const dopen = $("#jobHead details") && $("#jobHead details").open;
      $("#jobHead").innerHTML = progressHtml(j);
      if (dopen && $("#jobHead details")) $("#jobHead details").open = true;
      $("#cancel").hidden = j.status !== "running" && j.status !== "queued";
      const vl = $("#vlink"); vl.hidden = !j.video_id; if (j.video_id) { vl.href = "#/videos"; vl.onclick = () => setTimeout(() => openVideo(j.video_id), 50); }
    }
  });
  await refresh(); timer = setInterval(refresh, 2000);
}

