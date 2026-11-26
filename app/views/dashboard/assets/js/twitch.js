/* Post on Twitch. */
"use strict";
/* ------------------------------------------------------------ twitch helper */
async function twitch() {
  $("#main").innerHTML = `<h1>Post on Twitch</h1>
    <p class="muted" style="margin:-6px 0 14px">No Twitch connection needed. Every video gets a ready-made Twitch pack (title, description, file) so you can post it in a minute. Twitch does not allow automatic uploads.</p>
    <div class="steps4"><div class="step"><span class="no">1</span><div><b>Download</b><span>Get the video file, or show it in its folder.</span></div></div>
      <div class="step"><span class="no">2</span><div><b>Open Twitch</b><span>Content → Video Producer → Upload.</span></div></div>
      <div class="step"><span class="no">3</span><div><b>Copy &amp; paste</b><span>Use the ready title and description below.</span></div></div>
      <div class="step"><span class="no">4</span><div><b>Mark as uploaded</b><span>So the dashboard keeps track of both platforms.</span></div></div></div>
    <div class="toolbar"><select id="tf"><option value="pending">Waiting for Twitch</option><option value="uploaded">Uploaded to Twitch</option><option value="skipped">Skipped</option></select></div>
    <div id="tlist"></div>`;
  const setTw = guard(async (id, status, url) => { await api(`/api/videos/${id}/twitch`, {method: "POST", body: {status, url: url || ""}}); toast("Saved"); load(); });
  const copy = guard(async text => { await navigator.clipboard.writeText(text); toast("Copied"); });
  const load = guard(async () => {
    const list = await api("/api/videos?twitch=" + $("#tf").value);
    const box = $("#tlist");
    if (!list.length) { box.innerHTML = `<div class="card">${emptyState("check", "Nothing here", "No videos in this list.")}</div>`; return; }
    box.innerHTML = list.map(v => { const p = v.twitch_pack, t = v.twitch || {status: "pending"}; return `
      <div class="card vcard" style="margin-bottom:16px" data-id="${v.id}"><img alt="" loading="lazy" src="/media/${v.id}/thumb"><div>
        <div class="row"><b class="grow">${esc(v.title)}</b>${badge(t.status)}<span class="muted">${kindLabel(v.kind)}${v.file_mb ? " · " + v.file_mb + " MB" : ""}</span></div>
        <label>Twitch title</label><div class="row"><input class="grow" readonly value="${esc(p.title)}"><button data-a="ct">Copy</button></div>
        <label>Twitch description</label><div class="row" style="align-items:flex-start"><textarea class="grow" readonly style="min-height:90px">${esc(p.description)}</textarea><button data-a="cd">Copy</button></div>
        ${p.category ? `<label>Twitch category to pick</label><div class="row"><input class="grow" readonly value="${esc(p.category)}"><button data-a="cc">Copy</button></div>` : ""}${p.tags && p.tags.length ? `<label>Tags (Twitch allows up to 10)</label><div class="row"><input class="grow" readonly value="${esc(p.tags.join(", "))}"><button data-a="cg">Copy</button></div>` : ""}
        <div class="row" style="margin-top:14px"><a class="btn" href="/media/${v.id}/video?download=1">Download video</a>${ME.role === "owner" ? `<button data-a="rv">Show in folder</button>` : ""}<a class="btn" href="https://dashboard.twitch.tv/" target="_blank" rel="noopener">Open Twitch</a></div>
        <div class="row" style="margin-top:12px">${t.status === "uploaded" ? `${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">Open on Twitch</a>` : ""}<button data-a="undo">Undo</button>`
          : `<input class="grow" data-f="url" placeholder="Twitch video link (optional)"><button class="pri" data-a="done">Mark as uploaded</button><button data-a="skip">Skip</button>`}</div></div></div>`; }).join("");
    box.querySelectorAll(".vcard").forEach(card => {
      const id = card.dataset.id, v = list.find(x => x.id === id);
      card.querySelectorAll("button[data-a]").forEach(b => b.onclick = () => ({
        ct: () => copy(v.twitch_pack.title), cd: () => copy(v.twitch_pack.description), cc: () => copy(v.twitch_pack.category), cg: () => copy(v.twitch_pack.tags.join(", ")),
        rv: guard(async () => { await api(`/api/videos/${id}/reveal`, {method: "POST"}); }),
        done: () => setTw(id, "uploaded", (card.querySelector("[data-f=url]") || {}).value), skip: () => setTw(id, "skipped"), undo: () => setTw(id, "pending"),
      })[b.dataset.a]());
    });
  });
  $("#tf").onchange = load; await load();
}

