/* Post on TikTok, Instagram and Facebook: a ready-made caption for each, the video file, and a record of where it was posted. */
"use strict";
const SOCIAL_LIST = [["tiktok", "TikTok", "https://www.tiktok.com/upload", "Open TikTok upload", "Upload the video, paste the caption, post."],
                     ["instagram", "Instagram Reels", "https://www.instagram.com/", "Open Instagram", "Tap + (Create), choose Reel, upload, paste the caption, share."],
                     ["facebook", "Facebook Reels", "https://www.facebook.com/reels/create", "Open Facebook Reels", "Upload the video, paste the caption, publish."]];
async function social() {
  $("#main").innerHTML = `<h1>Post on TikTok, Instagram and Facebook</h1>
    <div class="steps4"><div class="step"><span class="no">1</span><div><b>Download</b><span>Get the video file.</span></div></div>
      <div class="step"><span class="no">2</span><div><b>Open the platform</b><span>Use the button on its card.</span></div></div>
      <div class="step"><span class="no">3</span><div><b>Copy &amp; paste</b><span>Each caption is written for that platform.</span></div></div>
      <div class="step"><span class="no">4</span><div><b>Mark as posted</b><span>So you always know what is left.</span></div></div></div>
    <div class="toolbar"><select id="sf"><option value="todo">Not posted everywhere yet</option><option value="all">All my Shorts</option></select></div>
    <div id="slist"></div>`;
  const mark = guard(async (id, platform, status, url) => { await api(`/api/videos/${id}/social`, {method: "POST", body: {platform, status, url: url || ""}}); toast("Saved"); load(); });
  const copy = guard(async text => { await navigator.clipboard.writeText(text); toast("Copied"); });
  let price = {rewrite: 1, free: false};
  const tok = n => `${+(+n).toFixed(2)} token${+n === 1 ? "" : "s"}`;
  try { price = await api("/api/social/price"); } catch (e) {}
  const caption = guard(async (id, platform, action, btn) => {
    if (action === "rewrite") { btn.disabled = true; btn.textContent = "Writing…"; }
    const r = await api(`/api/videos/${id}/social/caption`, {method: "POST", body: {platform, action}});
    toast(action === "reset" ? "Back to the first caption" : (r.charged ? `New caption written (${tok(r.charged)})` : "New caption written"));
    load();
  });
  const load = guard(async () => {
    const all = (await api("/api/videos?kind=short")).filter(v => !["failed", "discarded", "declined"].includes(v.status));
    const list = $("#sf").value === "all" ? all : all.filter(v => SOCIAL_LIST.some(([p]) => (v.social[p] || {}).status === "pending"));
    const box = $("#slist");
    if (!all.length) { box.innerHTML = `<div class="card">${emptyState("film", "No Shorts yet", "Make a Short and it appears here, ready to post.")}</div>`; return; }
    if (!list.length) { box.innerHTML = `<div class="card">${emptyState("check", "All posted", "Every Short has been posted or skipped on all three platforms.")}</div>`; return; }
    box.innerHTML = list.map(v => `
      <div class="card" style="margin-bottom:16px" data-id="${v.id}">
        <div class="row" style="gap:14px;align-items:center;flex-wrap:wrap"><img alt="" loading="lazy" src="/media/${v.id}/thumb" style="width:54px;height:96px;object-fit:cover;border-radius:8px">
          <div class="grow" style="min-width:200px"><b>${esc(v.title)}</b><div class="muted">${esc(v.game_name || "")} · ${v.file_mb ? v.file_mb + " MB" : "Short"}</div></div>
          <a class="btn" href="/media/${v.id}/video?download=1">Download video</a></div>
        <div class="socgrid">${SOCIAL_LIST.map(([p, name, open, openText, how]) => { const s = v.social[p] || {status: "pending"}; return `
          <div class="socbox" data-p="${p}"><div class="row"><b class="grow">${name}</b>${(v.social_ai || {})[p] ? `<span class="badge running" title="Written by the AI">AI</span>` : ""}${s.status === "posted" ? `<span class="badge uploaded">Posted</span>` : s.status === "skipped" ? `<span class="badge declined">Skipped</span>` : `<span class="badge rendered">Waiting</span>`}</div>
            <label>Caption for ${name}</label><textarea readonly rows="7">${esc(v.social_pack[p])}</textarea>
            <div class="row" style="margin-top:8px;gap:8px;flex-wrap:wrap"><button data-a="copy">Copy caption</button><button data-a="ai" title="${price.free ? "Free" : "Costs " + tok(price.rewrite) + " each time"}">Rewrite with AI${price.free ? "" : ` (${tok(price.rewrite)})`}</button>${(v.social_ai || {})[p] ? `<button data-a="orig">Back to the first caption</button>` : ""}<a class="btn" href="${open}" target="_blank" rel="noopener">${openText}</a></div>
            <div class="muted" style="font-size:12.5px;margin:6px 0">${how}</div>
            ${s.status === "pending" ? `<div class="row" style="gap:8px;flex-wrap:wrap"><input class="grow" data-f="url" placeholder="Link to the post (optional)"><button class="pri" data-a="done">Mark as posted</button><button data-a="skip">Skip</button></div>`
              : `<div class="row" style="gap:8px">${s.url ? `<a href="${esc(s.url)}" target="_blank" rel="noopener">Open the post</a>` : ""}<button data-a="undo">Undo</button></div>`}</div>`; }).join("")}</div></div>`).join("");
    box.querySelectorAll(".card[data-id]").forEach(card => {
      const id = card.dataset.id, v = list.find(x => x.id === id);
      card.querySelectorAll(".socbox").forEach(sb => {
        const p = sb.dataset.p;
        sb.querySelectorAll("button[data-a]").forEach(b => b.onclick = () => ({
          copy: () => copy(v.social_pack[p]), ai: () => caption(id, p, "rewrite", sb.querySelector("[data-a=ai]")), orig: () => caption(id, p, "reset"), done: () => mark(id, p, "posted", (sb.querySelector("[data-f=url]") || {}).value),
          skip: () => mark(id, p, "skipped"), undo: () => mark(id, p, "pending"),
        })[b.dataset.a]());
      });
    });
  });
  $("#sf").onchange = load; await load();
}
