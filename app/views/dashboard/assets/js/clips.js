/* Source clips. */
"use strict";
/* ------------------------------------------------------------ clips */
async function clips() {
  $("#main").innerHTML = `<h1>Source clips</h1><div class="toolbar"><select id="cs"><option value="">All statuses</option><option value="downloaded">Ready to use</option><option value="used">Used</option></select>
    <select id="cc"><option value="">All sources</option><option value="live">Live streams</option><option value="twitch">Twitch</option><option value="youtube">YouTube</option></select>
    <input type="search" id="cq" placeholder="Search creator or title"></div><div class="card" id="clist"></div>`;
  let all = [];
  const draw = () => {
    const q = $("#cq").value.trim().toLowerCase(), s = $("#cs").value, c = $("#cc").value;
    const list = all.filter(x => (!s || x.status === s) && (!c || (c === "live" ? String(x.id).startsWith("live_") : (x.source || "twitch") === c && !String(x.id).startsWith("live_"))) &&
      (!q || `${x.streamer} ${x.title}`.toLowerCase().includes(q)));
    $("#clist").innerHTML = list.length ? `<table><tr><th>Source</th><th>Creator</th><th>Title</th><th>Views</th><th>Status</th><th>File</th><th>Added</th><th></th></tr>${list.map(c => `
      <tr><td>${String(c.id).startsWith("live_") ? '<span class="chip live">Live</span>' : `<span class="chip">${esc(c.source || "twitch")}</span>`}</td><td><b>${esc(c.streamer)}</b></td>
      <td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.title)}</a>` : esc(c.title)}</td><td>${esc(c.views)}</td><td>${badge(c.status)}</td>
      <td style="white-space:nowrap">${c.file_exists ? "on disk" : '<span class="muted">missing</span>'}</td><td class="muted" style="white-space:nowrap">${when(c.created_at)}</td><td><button class="dng" data-c="${esc(c.id)}">Remove</button></td></tr>`).join("")}</table>`
      : emptyState("clips", "No clips found", "Clips appear here once the studio has downloaded or recorded some.");
    document.querySelectorAll("button[data-c]").forEach(b => b.onclick = guard(async () => {
      if (!confirm("Remove this clip record and its downloaded file?")) return;
      await api(`/api/clips/${encodeURIComponent(b.dataset.c)}?file=1`, {method: "DELETE"}); load();
    }));
  };
  const load = guard(async () => { all = await api("/api/clips"); draw(); });
  $("#cs").onchange = $("#cc").onchange = draw; $("#cq").oninput = draw; await load();
}

