/* My videos and the video drawer. */
"use strict";
/* ------------------------------------------------------------ videos */
async function videos() {
  $("#main").innerHTML = `<h1>My videos</h1>
    <div class="toolbar"><div class="seg" id="vtabs"><button data-t="" class="on">All</button><button data-t="wait">Waiting</button><button data-t="public">Public</button><button data-t="declined">Declined</button></div>
      <select id="fk"><option value="">All types</option><option value="short">Shorts</option><option value="compilation">Compilations</option></select>
      <select id="fg"><option value="">All games</option></select><input type="search" id="fq" placeholder="Search titles"></div>
    <div id="vlist"></div>`;
  let all = [], tab = "";
  const draw = () => {
    const q = $("#fq").value.trim().toLowerCase(), k = $("#fk").value, g = $("#fg").value;
    const list = all.filter(v => (!k || v.kind === k) && (!g || v.game_name === g) && (!q || (v.title || "").toLowerCase().includes(q)) &&
      (!tab || (tab === "wait" ? (v.status === "rendered" || v.status === "uploaded") : v.status === tab)));
    $("#vlist").innerHTML = list.length ? `<div class="vgrid">${list.map(vcard).join("")}</div>` : `<div class="card">${emptyState("film", "No videos here", "Try another filter, or make a new video on the Create page.")}</div>`;
    bindVcards($("#vlist"));
  };
  const load = guard(async () => {
    all = await api("/api/videos");
    const names = [...new Set(all.map(v => v.game_name).filter(Boolean))];
    $("#fg").innerHTML = `<option value="">All games</option>` + names.map(n => `<option>${esc(n)}</option>`).join(""); draw();
  });
  document.querySelectorAll("#vtabs button").forEach(b => b.onclick = () => { tab = b.dataset.t; document.querySelectorAll("#vtabs button").forEach(x => x.classList.toggle("on", x === b)); draw(); });
  $("#fk").onchange = $("#fg").onchange = draw; $("#fq").oninput = draw; await load();
}

const openVideo = guard(async id => {
  const v = await api(`/api/videos/${id}`);
  const canAct = v.status === "uploaded" || v.status === "rendered";
  $("#drawerBody").innerHTML = `<div class="dhead"><div><h1>${esc(v.title)}</h1><div class="row" style="margin-top:8px">${sbadge(v.status)}<span class="muted">${esc(v.game_name || "")} · ${kindLabel(v.kind)} · ${when(v.created_at)}</span>
      ${v.youtube_url ? `<a href="${esc(v.youtube_url)}" target="_blank" rel="noopener">Open on YouTube</a>` : ""}</div></div><button id="x">Close</button></div>
    <div class="media" style="margin-top:14px"><video controls preload="metadata" src="/media/${v.id}/video"></video><img alt="Thumbnail" src="/media/${v.id}/thumb"></div>
    ${canAct ? `<div class="dsec"><h3>Publishing</h3><p class="muted" style="margin:2px 0 12px">${v.youtube_id ? "Uploaded as Unlisted. Check YouTube Studio → Checks, then publish." : v.upload_status === "hold" ? "This video is waiting for you. Check it, change the audio below if you want, then upload it." : "Not on YouTube yet. Approving uploads it and makes it Public."}</p>
      <div class="dactions">${!v.youtube_id && v.status === "rendered" && ["hold", "needs_youtube", "error"].includes(v.upload_status || "hold") ? '<button id="upunl" title="Goes to YouTube as Unlisted, so you can check it there first">Upload as Unlisted</button>' : ""}<button class="pri" id="pub">${v.youtube_id ? "Approve & publish" : "Approve & upload"}</button><button class="dng" id="dcl">Decline</button></div></div>` : ""}
    ${v.receipt ? `<div class="dsec"><h3>Cost of this video</h3><table>${v.receipt.map(r => `<tr><td>${esc(r.label)}</td><td class="muted">${r.qty != null && r.unit ? `${r.qty} ${esc(r.unit)}` : ""}</td><td style="text-align:right">${r.tokens} tokens</td></tr>`).join("")}
      ${v.upload_receipt ? `<tr><td>Upload to YouTube</td><td class="muted">1 upload</td><td style="text-align:right">${v.upload_receipt.tokens} tokens</td></tr>` : ""}
      <tr><td><b>Total</b></td><td></td><td style="text-align:right"><b>${Math.round(((v.cost_tokens || 0) + (v.upload_cost_tokens || 0)) * 100) / 100} tokens</b></td></tr></table>
      <p class="muted" style="margin:8px 0 0">${ME.role === "owner" ? "Record only: the owner is never charged." : `You paid ${(v.charged_tokens || 0) + (v.upload_charged || 0)} tokens for this video.`}</p></div>` : ""}
    ${v.status === "rendered" && !v.youtube_id && !["queued", "uploading", "done"].includes(v.upload_status) ? `<div class="dsec"><h3>Audio</h3>
      <p class="muted" style="margin:2px 0 10px">Now: <b>${esc(AUDIO_LABEL[v.audio_mode] || v.audio_mode || "-")}</b>. You can change it until the video is on YouTube. The title, description and thumbnail stay as they are.</p>
      <select id="aud_mode"><option value="replace">AI commentary + music (original audio muted)</option><option value="bed">Original audio under music</option><option value="original">Original audio, untouched (high copyright-claim risk)</option></select>
      <textarea id="aud_own" hidden maxlength="1200" style="min-height:64px;margin-top:8px" placeholder="Optional: write your own commentary (free voice). Leave empty to let the AI write it."></textarea>
      <div class="dactions" style="margin-top:10px"><button id="aud_go">Remake with this audio</button></div>
      <p class="muted" style="margin:8px 0 0">It takes a few minutes and costs only what the AI uses, usually under 1 token (nothing for original audio).</p></div>` : ""}
    <div class="dsec"><h3>Details</h3><label>Title</label><input id="vt" value="${esc(v.title)}" maxlength="100">
      <label>Description</label><textarea id="vd">${esc(v.description)}</textarea>
      <label>Tags (comma separated)</label><input id="vg" value="${esc((v.tags || []).join(", "))}">
      <div class="dactions" style="margin-top:14px"><button class="pri" id="save">Save changes</button><button id="copy">Copy description</button><button class="pri" id="tstudio" title="Pick the moment, the style, the text and the colours">Thumbnail studio</button><button id="vedit" title="Cut it, change the screen shape, add captions and text">Edit video</button><button id="tedit" title="Crop it, add arrows, emoji, shapes and text to the current thumbnail">Edit thumbnail</button><button id="regen" title="Create a new AI thumbnail">New AI thumbnail</button><button id="mythumb" title="Free: no AI, no tokens" hidden>Upload my own thumbnail</button><input type="file" id="mythumbf" accept="image/jpeg,image/png" hidden>${v.youtube_id ? `<button id="ytthumb" title="Send the thumbnail to YouTube">Put thumbnail on YouTube</button>` : ""}<a class="btn" href="/media/${v.id}/thumb?download=1">Download thumbnail</a></div></div>
    <div class="dsec"><details class="more"><summary>Advanced</summary>
      <div class="grid g2"><div><label>Status</label><select id="vs">${["rendered", "uploaded", "public", "declined", "failed", "discarded"].map(s => `<option ${s === v.status ? "selected" : ""}>${s}</option>`).join("")}</select></div>
        <div><label>YouTube video ID</label><input id="vy" value="${esc(v.youtube_id || "")}" placeholder="after upload"></div></div>
      <div><label>Notes</label><input id="vn" value="${esc(v.notes || "")}"></div><p class="muted">Files: ${esc(v.video_path)}</p>
      <div class="dactions"><label style="margin:0"><input type="checkbox" id="rmf"> also delete the files</label><button class="dng" id="del">Delete video</button></div></details></div>`;
  $("#drawer").classList.add("open");
  $("#x").onclick = closeDrawer;
  if ($("#aud_mode")) {
    $("#aud_mode").value = v.audio_mode || "replace";
    const own = d => { $("#aud_own").hidden = !($("#aud_mode").value === "replace" && v.kind === "short" && (d.owner || d.flags.own_commentary)); };
    getDiy().then(d => { own(d); $("#aud_mode").onchange = () => own(d); }).catch(() => {});
    $("#aud_go").onclick = guard(async () => {
      if ($("#aud_mode").value === (v.audio_mode || "replace") && !$("#aud_own").value.trim() && !confirm("That is the audio it already has. Remake it anyway?")) return;
      $("#aud_go").disabled = true; $("#aud_go").textContent = "Starting…";
      try { const r = await api(`/api/videos/${id}/audio`, {method: "POST", body: {audio_mode: $("#aud_mode").value, own_commentary: $("#aud_own").value}}); toast(r.message); refreshTokens(); openProgress(r.job_id); }
      finally { if ($("#aud_go")) { $("#aud_go").disabled = false; $("#aud_go").textContent = "Remake with this audio"; } }
    });
  }
  if ($("#upunl")) $("#upunl").onclick = guard(async () => {
    $("#upunl").disabled = true; const r = await api(`/api/videos/${id}/upload`, {method: "POST", body: {privacy: "unlisted"}}); toast(r.message); closeDrawer(); nav();
  });
  $("#save").onclick = guard(async () => {
    await api(`/api/videos/${id}`, {method: "PATCH", body: {title: $("#vt").value, description: $("#vd").value, tags: $("#vg").value, status: $("#vs").value, youtube_id: $("#vy").value, notes: $("#vn").value}});
    toast("Saved"); closeDrawer(); nav();
  });
  $("#copy").onclick = guard(async () => { await navigator.clipboard.writeText($("#vd").value); toast("Description copied"); });
  if ($("#ytthumb")) $("#ytthumb").onclick = guard(async () => {
    $("#ytthumb").disabled = true; $("#ytthumb").textContent = "Sending…";
    try { const r = await api(`/api/videos/${id}/yt-thumbnail`, {method: "POST"}); toast(r.message); }
    finally { $("#ytthumb").disabled = false; $("#ytthumb").textContent = "Put thumbnail on YouTube"; }
  });
  $("#regen").onclick = guard(async () => {
    $("#regen").disabled = true; $("#regen").textContent = "Creating… (about 30 s)";
    try { const r = await api(`/api/videos/${id}/thumbnail`, {method: "POST"}); toast(r.message); $("#drawerBody img[alt=Thumbnail]").src = `/media/${id}/thumb?t=${Date.now()}`; }
    finally { $("#regen").disabled = false; $("#regen").textContent = "New AI thumbnail"; }
  });
  $("#tedit").onclick = () => openThumbEditor(id, `/media/${id}/thumb?t=${Date.now()}`, v.kind === "compilation" ? "16:9" : "9:16", () => { $("#drawerBody img[alt=Thumbnail]").src = `/media/${id}/thumb?t=${Date.now()}`; });
  $("#vedit").onclick = guard(async () => { const r = await api("/api/editor/from-video", {method: "POST", body: {video_id: id}}); closeDrawer(); openEditor(r.source); });
  $("#tstudio").onclick = () => openThumbStudio(id, () => { $("#drawerBody img[alt=Thumbnail]").src = `/media/${id}/thumb?t=${Date.now()}`; });
  getDiy().then(d => { if ($("#mythumb") && (d.owner || d.flags.own_thumbnail)) $("#mythumb").hidden = false; }).catch(() => {});
  $("#mythumb").onclick = () => $("#mythumbf").click();
  $("#mythumbf").onchange = guard(async () => {
    const f = $("#mythumbf").files[0]; if (!f) return;
    $("#mythumb").disabled = true; $("#mythumb").textContent = "Uploading…";
    try { const r = await api(`/api/videos/${id}/my-thumbnail`, {method: "POST", body: f, raw: true}); toast(r.message); $("#drawerBody img[alt=Thumbnail]").src = `/media/${id}/thumb?t=${Date.now()}`; }
    finally { $("#mythumb").disabled = false; $("#mythumb").textContent = "Upload my own thumbnail"; $("#mythumbf").value = ""; }
  });
  if ($("#pub")) $("#pub").onclick = guard(async () => {
    if (!confirm("Put this video on YouTube as PUBLIC now?")) return;
    $("#pub").disabled = true; $("#pub").textContent = "Working…";
    try { const r = await api(`/api/videos/${id}/publish`, {method: "POST"}); toast(r.message); closeDrawer(); nav(); }
    catch (e) { $("#pub").disabled = false; $("#pub").textContent = "Try again"; throw e; }
  });
  if ($("#dcl")) $("#dcl").onclick = guard(async () => {
    if (!confirm("Decline this video? It will never be published.")) return;
    const r = await api(`/api/videos/${id}/decline`, {method: "POST"}); toast(r.message); closeDrawer(); nav();
  });
  $("#del").onclick = guard(async () => {
    if (!confirm("Delete this record" + ($("#rmf").checked ? " and its video/thumbnail files" : "") + "?")) return;
    await api(`/api/videos/${id}${$("#rmf").checked ? "?files=1" : ""}`, {method: "DELETE"}); toast("Deleted"); closeDrawer(); nav();
  });
});

