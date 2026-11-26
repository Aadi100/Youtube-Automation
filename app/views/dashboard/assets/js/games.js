/* Games. */
"use strict";
/* ------------------------------------------------------------ games */
const gameFields = g => `
  <div class="grid g2" style="gap:0 16px">
    <div><label>Game name</label><input data-f="name" maxlength="60" value="${esc(g.name || "")}" placeholder="e.g. Fortnite"></div>
    <div><label>Thumbnail label</label><input data-f="thumb_label" maxlength="20" value="${esc(g.thumb_label || "")}" placeholder="short text on thumbnails"></div>
    <div><label>Twitch categories (exact names, one per line)</label><textarea data-f="twitch_category" rows="3" style="min-height:74px" placeholder="as shown on twitch.tv/directory">${esc(g.twitch_category || "")}</textarea></div>
    <div><label>YouTube searches (one per line, each one is searched)</label><textarea data-f="youtube_query" rows="3" style="min-height:74px" placeholder="e.g. Fortnite funny moments&#10;Fortnite best clips&#10;Fortnite fails">${esc(g.youtube_query || "")}</textarea></div>
  </div>
  <label>Hashtags (comma separated, no #)</label><input data-f="hashtags" value="${esc((g.hashtags || []).join(", "))}" placeholder="Fortnite, FortniteClips">`;
const readFields = root => { const o = {}; root.querySelectorAll("[data-f]").forEach(i => o[i.dataset.f] = i.value); return o; };

async function games() {
  $("#main").innerHTML = `<h1>Games</h1>
    <div class="toolbar"><button class="pri" id="newbtn">${svg("create")}<span>Add a game</span></button></div>
    <div class="card" id="newcard" hidden style="margin-bottom:18px"><h2>Add a game</h2><div id="newg">${gameFields({})}</div>
      <div class="row" style="margin-top:16px"><button class="pri" id="addg">Add game</button><button id="cancelnew">Cancel</button>
      <span class="muted">Leave the other fields blank to fill them in automatically from the name.</span></div></div>
    <div class="gcards" id="glist"></div>`;
  $("#newbtn").onclick = () => { $("#newcard").hidden = false; $("#newg [data-f=name]").focus(); };
  $("#cancelnew").onclick = () => { $("#newcard").hidden = true; };
  const load = guard(async () => {
    const list = await api("/api/games");
    $("#glist").innerHTML = list.length ? list.map(g => `<article class="gcard ${g.enabled ? "" : "off"}" data-id="${esc(g.id)}">
        <header><div class="gicon">${esc((g.name || "?")[0].toUpperCase())}</div><div class="gt"><b>${esc(g.name)}</b><div class="muted">${g.videos} videos · ${g.clips} clips</div></div>
          <label class="switch" title="${g.enabled ? "Enabled" : "Disabled"}"><input type="checkbox" data-f-en ${g.enabled ? "checked" : ""}><span></span></label></header>
        <dl class="gmeta"><div><dt>Twitch categories</dt><dd>${esc((g.twitch_category || "-").split("\n").join(" · "))}</dd></div><div><dt>YouTube searches</dt><dd>${esc((g.youtube_query || "-").split("\n").join(" · "))}</dd></div></dl>
        <div class="chips">${(g.hashtags || []).map(t => `<span class="chip">#${esc(t)}</span>`).join("") || '<span class="muted">No hashtags</span>'}</div>
        <details class="more"><summary>Edit settings</summary>${gameFields(g)}
          <div class="row"><button class="pri" data-a="save">Save</button><button data-a="test">Test sources</button><button class="dng" data-a="del">Delete</button></div></details>
        <div class="muted" data-out></div></article>`).join("")
      : emptyState("games", "No games yet", "Add your first game to start making videos.");
    $("#glist").querySelectorAll(".gcard[data-id]").forEach(card => {
      const id = card.dataset.id, out = card.querySelector("[data-out]");
      card.querySelector("[data-f-en]").onchange = guard(async e => { await api(`/api/games/${id}`, {method: "PATCH", body: {enabled: e.target.checked}}); toast(e.target.checked ? "Game enabled" : "Game disabled"); load(); });
      card.querySelector("[data-a=save]").onclick = guard(async () => { await api(`/api/games/${id}`, {method: "PATCH", body: readFields(card)}); toast("Saved"); load(); });
      card.querySelector("[data-a=del]").onclick = guard(async () => {
        if (!confirm("Delete this game? Its existing videos and clips are kept.")) return;
        await api(`/api/games/${id}`, {method: "DELETE"}); toast("Deleted"); load();
      });
      card.querySelector("[data-a=test]").onclick = guard(async () => {
        out.textContent = "Testing (can take ~10 seconds)…";
        await api(`/api/games/${id}`, {method: "PATCH", body: readFields(card)});
        const r = await api(`/api/games/${id}/test`, {method: "POST"});
        const mark = x => `<span style="color:var(--${x.ok ? "ok" : "warn"})">${x.ok ? "✔" : "!"}</span>`;
        out.innerHTML = `${mark(r.twitch)} Twitch: ${esc(r.twitch.message)}<br>${mark(r.youtube)} YouTube: ${esc(r.youtube.message)}`;
      });
    });
  });
  $("#addg").onclick = guard(async () => { await api("/api/games", {method: "POST", body: readFields($("#newg"))}); toast("Game added"); games(); });
  await load();
}

