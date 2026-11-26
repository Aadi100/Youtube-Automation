/* Schedule. */
"use strict";
/* ------------------------------------------------------------ schedule */
async function schedule() {
  $("#main").innerHTML = `<h1>Schedule</h1><div id="schov"></div><div id="scheditor" style="margin-top:18px"></div><div id="trendnote" class="muted" style="margin-top:14px"></div>`;
  api("/api/trending").then(t => { if ($("#trendnote")) $("#trendnote").innerHTML = t.allowed ? `Trending mode for scheduled videos: <b>${t.on ? "on" : "off"}</b> (+${t.price.short} tokens for a Short, +${t.price.compilation} for a compilation). Change it in <a href="#/settings">Settings → Trending mode</a>.` : ""; }).catch(() => {});
  let tz = "UTC", prevRunning = false;
  const at = (iso, long) => iso ? new Date(iso).toLocaleString("en-GB", {timeZone: tz, weekday: "short", day: "numeric", month: "short",
    hour: "2-digit", minute: "2-digit"}) : "-";
  const span = ms => { const m = Math.max(0, Math.round(ms / 60000)); return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`; };
  const kindName = k => k === "compilation" ? "Compilation" : "Short";
  const refresh = async () => {
    let o; try { o = await api("/api/schedule/overview"); } catch (e) { return; }
    if (!$("#schov")) return;
    tz = o.timezone;
    const now = new Date(o.now).getTime();
    const r = o.running, nxt = o.upcoming[0];
    const stateCard = r
      ? `<div class="card"><h2><span class="dot ok"></span>Working now</h2><div style="font-size:18px"><b>${esc(r.game || "choosing game…")}</b> · ${kindName(r.kind)}</div>
         <p class="muted">Started ${at(r.started)} · running ${span(now - new Date(r.started))}${r.scheduled ? " · scheduled run" : " · started by hand"}</p>
         <p class="muted">${esc(r.last_line || "starting…")}</p><button id="seeprog2">See live progress</button></div>`
      : `<div class="card"><h2><span class="dot"></span>Idle</h2><p class="muted" style="margin:0">Nothing is rendering right now.</p></div>`;
    const nextCard = nxt
      ? `<div class="card"><h2>Next run</h2><div style="font-size:18px"><b>${esc(nxt.creator ? nxt.creator + " (creator)" : nxt.game || "-")}</b> · ${kindName(nxt.kind)}</div>
         <p class="muted">${at(nxt.at)} (${tz}) · in ${span(new Date(nxt.at) - now)}</p>
         <p class="muted" style="margin-bottom:0">${nxt.creator ? "Your saved creators take turns." : "Games take turns: the one used longest ago goes next."}</p></div>`
      : `<div class="card"><h2>Next run</h2><p class="muted" style="margin:0">Nothing scheduled - turn a schedule on below.</p></div>`;
    const off = Object.entries(o.enabled).filter(([, v]) => !v).map(([k]) => k === "shorts" ? "Shorts" : "Compilations");
    const up = o.upcoming.map(u => `<tr><td>${at(u.at)}</td><td class="muted">in ${span(new Date(u.at) - now)}</td><td>${kindName(u.kind)}</td><td><b>${esc(u.creator ? u.creator + " (creator)" : u.game || "-")}</b></td></tr>`).join("");
    const hist = o.history.map(j => `<tr><td>${at(j.started)}</td><td>${kindName(j.kind)}</td><td>${esc(j.game || "-")}</td>
      <td>${j.scheduled ? "scheduled" : "by hand"}</td><td>${badge(j.status)}</td>
      <td>${j.finished ? span(new Date(j.finished) - new Date(j.started)) : "-"}</td>
      <td>${j.video ? `<a href="#/videos">${esc((j.video.title || "").slice(0, 48))}</a> ${badge(j.video.status || "")}` : `<span class="muted">${esc(j.error || "-")}</span>`}</td></tr>`).join("");
    $("#schov").innerHTML = `<div class="grid g2">${stateCard}${nextCard}</div>
      ${off.length ? `<p class="muted">⏸ ${off.join(" and ")} switched off - nothing will be made for them.</p>` : ""}
      <div class="card" style="margin-top:14px"><h2>Coming up (${tz} time)</h2>
        ${up ? `<table><tr><th>When</th><th></th><th>Type</th><th>Game</th></tr>${up}</table>` : `<div class="empty">Nothing scheduled.</div>`}
        <div class="row" style="margin-top:10px;flex-wrap:wrap"><span class="muted">Don't want to wait?</span>
          <button id="rn1">Make a Short now</button><button id="rn2">Make a Compilation now</button></div></div>
      <div class="card" style="margin-top:14px"><h2>Recent runs</h2>
        ${hist ? `<table><tr><th>Started</th><th>Type</th><th>Game</th><th>How</th><th>Result</th><th>Took</th><th>Video</th></tr>${hist}</table>` : `<div class="empty">No runs yet.</div>`}</div>`;
    const go = (mode, extra) => guard(async () => {
      await api("/api/jobs", {method: "POST", body: {mode, game_id: "auto", source: "all", audio_mode: "default", ...extra}});
      toast("Started"); refresh();
    });
    if ($("#seeprog2")) $("#seeprog2").onclick = () => openProgress(r.id);
    $("#rn1").onclick = go("auto-short", {}); $("#rn2").onclick = go("auto-compilation", {count: 14, target_minutes: 8});
    if (prevRunning && !r) scheduleEditor();   // a run finished: refresh the edit box's "next runs" too
    prevRunning = !!r;
  };
  stopTimer(); await refresh(); timer = setInterval(refresh, 10000);
  await scheduleEditor();
}

async function scheduleEditor() {
  const kinds = [["shorts", "Shorts (9:16)", [1, 2, 3, 4, 6, 8, 12]], ["compilation", "Compilation (8-10 min)", [1, 2, 3]]];
  if (!$("#scheditor")) return;
  $("#scheditor").innerHTML = `<h2>Edit schedule</h2><p class="muted">Choose when new videos are made and uploaded (Unlisted). Changes apply within a few minutes - no need to touch n8n.
    One video renders at a time; a slot that arrives while something is rendering is retried for 30 minutes.</p>
    <div class="grid g2" id="schcards"></div><div class="card"><label>Time zone (e.g. Asia/Karachi, Europe/London, America/New_York)</label>
    <input id="schtz"><div class="row" style="margin-top:14px"><button class="pri" id="schsave">Save schedule</button></div><div class="muted" id="schnow" style="margin-top:8px"></div></div>`;
  const fmt = iso => iso.replace("T", " ").slice(0, 16);
  const load = guard(async () => {
    const [s, cr] = await Promise.all([api("/api/schedule"), api("/api/creators").catch(() => ({allowed: false, creators: []}))]);
    $("#schtz").value = s.timezone;
    $("#schnow").textContent = "Now in that time zone: " + fmt(s.now);
    $("#schcards").innerHTML = kinds.map(([k, title]) => `<div class="card"><h2>${title}</h2>
      <label><input type="checkbox" data-en="${k}" ${s[k].enabled ? "checked" : ""} style="width:auto"> Enabled</label>
      <label>Times each day (24h, comma separated)</label><input data-times="${k}" value="${esc(s[k].times.join(", "))}">
      <div class="row" style="margin-top:8px;flex-wrap:wrap"><span class="muted">Quick fill: every</span>
      ${kinds.find(x => x[0] === k)[2].map(n => `<button data-fill="${k}:${n}">${n}h</button>`).join("")}</div>
      ${cr.allowed ? `<label>Take clips from (optional)</label>${cr.creators.length ? `<div class="tschips" style="margin:4px 0 6px">${cr.creators.map(c => `<label class="tschip ${(s[k].creators || []).includes(c.id) ? "on" : ""}" style="margin:0"><input type="checkbox" data-cr="${k}" value="${esc(c.id)}" ${(s[k].creators || []).includes(c.id) ? "checked" : ""} style="display:none">${c.platform === "twitch" ? "Twitch" : "YouTube"} · ${esc(c.label)}</label>`).join("")}</div>
        <p class="help" style="margin:0 0 8px">Pick none to search by game. Pick several and each run uses the next one in turn.</p>` : `<p class="help">Save creators on the Create page first, then choose them here.</p>`}` : ""}
      <p class="muted" style="margin-bottom:0">Next runs: ${s.next[k].length ? s.next[k].map(fmt).join(" · ") : "-"}</p></div>`).join("");
    document.querySelectorAll("input[data-cr]").forEach(i => i.onchange = () => i.parentElement.classList.toggle("on", i.checked));
    document.querySelectorAll("button[data-fill]").forEach(b => b.onclick = () => {
      const [k, n] = b.dataset.fill.split(":"); const step = +n, out = [];
      const first = (document.querySelector(`[data-times="${k}"]`).value.match(/:(\d\d)/) || [0, "30"])[1];
      for (let h = 0; h < 24; h += step) out.push(String(h).padStart(2, "0") + ":" + first);
      document.querySelector(`[data-times="${k}"]`).value = out.join(", ");
    });
  });
  $("#schsave").onclick = guard(async () => {
    const body = {timezone: $("#schtz").value.trim()};
    kinds.forEach(([k]) => body[k] = {enabled: document.querySelector(`[data-en="${k}"]`).checked, times: document.querySelector(`[data-times="${k}"]`).value,
      creators: [...document.querySelectorAll(`input[data-cr="${k}"]:checked`)].map(i => i.value)});
    await api("/api/schedule", {method: "PUT", body}); toast("Schedule saved"); load();
  });
  await load();
}

