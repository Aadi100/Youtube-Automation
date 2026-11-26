/* The bell, notifications and the profile page. */
"use strict";
/* ------------------------------------------------------------ notifications (the bell) and my profile */
let AVT = Date.now();
const NOTE_ICON = {success: '<path d="M5 12.5l4.5 4.5L19 7.5"/>', info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>', warn: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>', error: '<circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/>'};
Object.assign(ICON, {notifications: '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>', bell: '<path d="M6 9a6 6 0 0 1 12 0c0 6 2 7 2 7H4s2-1 2-7"/><path d="M10 20a2 2 0 0 0 4 0"/>', profile: '<circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.2 4-6.5 8-6.5s7.2 2.3 8 6.5"/>', cam: '<path d="M4 8h3l1.5-2h7L17 8h3v11H4z"/><circle cx="12" cy="13" r="3.4"/>'});
const noteIcon = l => `<svg viewBox="0 0 24 24" aria-hidden="true">${NOTE_ICON[l] || NOTE_ICON.info}</svg>`;
const ago = iso => { if (!iso) return ""; const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000); if (s < 60) return "just now"; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} h ago`; if (s < 7 * 86400) return `${Math.floor(s / 86400)} d ago`; return new Date(iso).toLocaleDateString([], {day: "numeric", month: "short"}); };
const avatarMini = initials => ME.avatar ? `<a class="av" href="#/profile" title="My profile"><img src="/api/profile/avatar?t=${AVT}" alt=""></a>` : `<a class="av" href="#/profile" title="My profile">${esc(initials)}</a>`;
const noteRow = n => `<div class="nitem ${n.read ? "" : "unread"}" data-id="${n.id}" data-link="${esc(n.link)}"><span class="nic ${esc(n.level)}">${noteIcon(n.level)}</span>
  <div class="nbody"><b>${esc(n.title)}</b>${n.body ? `<span>${esc(n.body)}</span>` : ""}<em>${ago(n.created_at)}</em></div>${n.read ? "" : '<i class="ndot" title="Unread"></i>'}</div>`;
const NOTIF = {seen: null, unread: 0, open: false};
function setBadge(n) { NOTIF.unread = n; const b = $("#bellc"); if (b) { b.hidden = !n; b.textContent = n > 99 ? "99+" : n; } document.title = (n ? `(${n}) ` : "") + "Clip Studio"; }
async function pollNotifs() {
  try {
    const r = await api("/api/notifications/count");
    setBadge(r.unread);
    if (NOTIF.seen !== null && r.latest && r.latest.id !== NOTIF.seen && !r.latest.read) toast(r.latest.title, r.latest.level === "error");
    NOTIF.seen = r.latest ? r.latest.id : "";
    if (NOTIF.open) drawNotifPanel();
  } catch (e) {}
}
async function openNote(el, close) {
  const id = el.dataset.id, link = el.dataset.link;
  if (el.classList.contains("unread")) { try { const r = await api("/api/notifications/read", {method: "POST", body: {ids: [id]}}); setBadge(r.unread); } catch (e) {} }
  if (close) closeNotifPanel();
  if (link) { if (location.hash === link) nav(); else location.hash = link; }
}
async function drawNotifPanel() {
  const box = $("#npanel"); if (!box) return;
  let d; try { d = await api("/api/notifications?limit=12"); } catch (e) { return; }
  box.innerHTML = `<div class="nhead"><h2>Notifications</h2><div class="row"><button id="n_all" ${d.unread ? "" : "disabled"}>Mark all read</button><a class="btn" href="#/profile/notifications" id="n_set" title="Choose what you are told about">${svg("settings")}</a></div></div>
    <div class="nlist">${d.items.length ? d.items.map(noteRow).join("") : `<div class="empty" style="padding:34px 10px">${svg("bell")}You're all caught up.<br><span class="muted">Messages about your videos, uploads and tokens appear here.</span></div>`}</div>
    <div class="nfoot"><a href="#/notifications" id="n_see">See all notifications</a></div>`;
  box.querySelectorAll(".nitem").forEach(el => el.onclick = () => openNote(el, true));
  $("#n_all").onclick = guard(async () => { await api("/api/notifications/read", {method: "POST", body: {}}); setBadge(0); drawNotifPanel(); });
  $("#n_set").onclick = () => closeNotifPanel(); $("#n_see").onclick = () => closeNotifPanel();
}
function closeNotifPanel() { NOTIF.open = false; const b = $("#npanel"); if (b) b.hidden = true; }
function toggleNotifPanel(e) {
  if (e) e.stopPropagation();
  let box = $("#npanel"); if (!box) { box = document.createElement("div"); box.id = "npanel"; box.className = "npanel"; box.hidden = true; document.body.appendChild(box); }
  if (!box.hidden) return closeNotifPanel();
  box.hidden = false; NOTIF.open = true; box.innerHTML = `<div class="edbusy"><div class="spin"></div></div>`; drawNotifPanel();
}
document.addEventListener("click", e => { const b = $("#npanel"); if (b && !b.hidden && !b.contains(e.target) && !e.target.closest("#bell")) closeNotifPanel(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeNotifPanel(); });

async function notifications() {
  $("#main").innerHTML = `<h1>Notifications</h1><div class="toolbar"><div class="seg" id="nf"><button class="on" data-f="all">All</button><button data-f="unread">Unread</button></div><span class="grow"></span>
    <button id="nf_all">Mark all read</button><button id="nf_clear">Clear read</button><a class="btn" href="#/profile/notifications">${svg("settings")}<span>Choose what I am told</span></a></div><div class="card" id="nflist"></div>`;
  let f = "all";
  const load = guard(async () => {
    const d = await api(`/api/notifications?limit=100${f === "unread" ? "&unread=1" : ""}`); setBadge(d.unread);
    $("#nflist").innerHTML = d.items.length ? `<div class="nlist big">${d.items.map(n => noteRow(n).replace('</div></div>', `</div><button class="nx" data-x="${n.id}" title="Delete">×</button></div>`)).join("")}</div>` : emptyState("check", f === "unread" ? "Nothing unread" : "No notifications yet", "Messages about your videos, uploads and tokens appear here.");
    $("#nflist").querySelectorAll(".nitem").forEach(el => el.onclick = e => { if (e.target.dataset.x) return; openNote(el, false); });
    $("#nflist").querySelectorAll("[data-x]").forEach(b => b.onclick = guard(async e => { e.stopPropagation(); await api(`/api/notifications/${b.dataset.x}`, {method: "DELETE"}); load(); }));
  });
  document.querySelectorAll("#nf button").forEach(b => b.onclick = () => { f = b.dataset.f; document.querySelectorAll("#nf button").forEach(x => x.classList.toggle("on", x === b)); load(); });
  $("#nf_all").onclick = guard(async () => { await api("/api/notifications/read", {method: "POST", body: {}}); load(); });
  $("#nf_clear").onclick = guard(async () => { await api("/api/notifications/clear", {method: "POST", body: {}}); load(); });
  await load();
}

async function profile() {
  const tabs = [["profile", "Profile"], ["security", "Security"], ["notifications", "Notifications"], ["connections", "Connections"]];
  let tab = location.hash.split("/")[2]; if (!tabs.some(t => t[0] === tab)) tab = "profile";
  let d = await api("/api/profile"); const u = d.user, owner = u.role === "owner";
  const initials = (u.name || u.email).split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
  const big = () => d.avatar ? `<img class="avimg" src="/api/profile/avatar?t=${AVT}" alt="">` : `<div class="avinit">${esc(initials)}</div>`;
  const stat = (n, l) => `<div class="pstat"><b>${n}</b><span>${l}</span></div>`;
  $("#main").innerHTML = `<section class="hero2 prof"><div class="profwho"><div class="avbig" id="avbig">${big()}<button class="avcam" id="av_pick" title="Change picture">${svg("cam")}</button><input type="file" id="av_file" accept="image/jpeg,image/png" hidden></div>
      <div><div class="eyebrow2">${owner ? "Owner" : "Member"}</div><h1 style="margin:2px 0 4px;font-size:32px">${esc(u.name)}</h1><div class="muted">${esc(u.email)}</div>
      <div class="chips" style="margin-top:10px"><span class="chip">Member since ${u.created_at ? new Date(u.created_at).toLocaleDateString([], {month: "short", year: "numeric"}) : "-"}</span><span class="chip">Last sign-in ${ago(u.last_login) || "-"}</span>${owner ? '<span class="chip acc">Owner · free</span>' : `<span class="chip acc">${u.tokens} tokens</span>`}</div></div></div>
      <div class="pstats">${stat(d.stats.videos, "Videos made")}${stat(d.stats.live, "Live on YouTube")}${stat(d.stats.waiting, "Waiting for me")}${stat(d.stats.runs, "Finished runs")}</div></section>
    <div class="seg" id="ptabs">${tabs.map(([k, n]) => `<button data-t="${k}" class="${k === tab ? "on" : ""}">${n}</button>`).join("")}</div><div id="ptab" style="margin-top:18px"></div>`;
  document.querySelectorAll("#ptabs button").forEach(b => b.onclick = () => { location.hash = "#/profile" + (b.dataset.t === "profile" ? "" : "/" + b.dataset.t); });
  const sync = r => { ME = r.user; AVT = Date.now(); buildShell(); document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.r === "profile")); refreshTokens(); };
  $("#av_pick").onclick = () => $("#av_file").click();
  $("#av_file").onchange = guard(async () => { const f = $("#av_file").files[0]; if (!f) return; const r = await api("/api/profile/avatar", {method: "POST", body: f, raw: true}); d.avatar = true; sync(r); $("#avbig").firstElementChild.outerHTML = big(); toast("Picture saved"); });
  const T = $("#ptab");
  if (tab === "profile") {
    T.innerHTML = `<div class="grid g2"><section class="card"><h2>My details</h2>
        <label>Name</label><input id="p_name" value="${esc(u.name)}" maxlength="60"><label>Email</label><input id="p_email" type="email" value="${esc(u.email)}">
        <div id="p_pwbox" hidden><label>Current password (needed to change your email)</label><input id="p_pw" type="password" autocomplete="current-password"></div>
        <div class="row" style="margin-top:16px"><button class="pri" id="p_save">Save changes</button></div></section>
      <section class="card"><h2>Picture</h2><div class="row" style="gap:18px"><div class="avbig sm">${big()}</div><div><div class="row"><button id="p_up">Upload a picture</button>${d.avatar ? '<button class="dng" id="p_rm">Remove</button>' : ""}</div>
        <p class="help" style="margin:8px 0 0">A JPG or PNG up to 5 MB. It is cropped to a square.</p></div></div>
        <h2 style="margin-top:22px">Quick links</h2><div class="row"><a class="btn" href="#/usage">${svg("usage")}<span>My usage</span></a><a class="btn" href="#/settings">${svg("settings")}<span>Voice, audio &amp; thumbnail look</span></a></div></section></div>`;
    $("#p_email").oninput = () => { $("#p_pwbox").hidden = $("#p_email").value.trim().toLowerCase() === u.email; };
    $("#p_up").onclick = () => $("#av_file").click(); if ($("#p_rm")) $("#p_rm").onclick = guard(async () => { const r = await api("/api/profile/avatar", {method: "DELETE"}); sync(r); profile(); });
    $("#p_save").onclick = guard(async () => { const r = await api("/api/profile", {method: "PUT", body: {name: $("#p_name").value, email: $("#p_email").value, current_password: $("#p_pw") ? $("#p_pw").value : ""}}); ME = r.user; toast("Saved"); sync(r); profile(); });
  } else if (tab === "security") {
    const load = guard(async () => {
      const s = (await api("/api/profile/sessions")).sessions;
      $("#p_sess").innerHTML = s.length ? s.map(x => `<div class="sess"><span class="edsi">${svg("globe")}</span><div style="flex:1;min-width:0"><b>${esc(x.device)}</b>${x.current ? ' <span class="chip live">This device</span>' : ""}<div class="muted" style="font-size:12.5px">${x.ip ? esc(x.ip) + " · " : ""}signed in ${ago(x.created_at)}</div></div>${x.current ? "" : `<button data-s="${x.id}">Sign out</button>`}</div>`).join("") : '<div class="muted">No other devices.</div>';
      $("#p_sess").querySelectorAll("[data-s]").forEach(b => b.onclick = guard(async () => { await api(`/api/profile/sessions/${b.dataset.s}`, {method: "DELETE"}); toast("Signed out"); load(); }));
      $("#p_others").hidden = s.filter(x => !x.current).length === 0;
    });
    T.innerHTML = `<div class="grid g2"><section class="card"><h2>Change password</h2><label>Current password</label><input id="pw_old" type="password" autocomplete="current-password"><label>New password (8+ characters)</label><input id="pw_new" type="password" autocomplete="new-password">
        <p class="help">Changing your password signs every other device out.</p><div class="row" style="margin-top:12px"><button class="pri" id="pw_save">Change password</button></div></section>
      <section class="card"><div class="sechead"><h2>Where I am signed in</h2><button id="p_others" hidden>Sign out all other devices</button></div><div id="p_sess" class="sesslist"></div></section></div>
      ${owner ? "" : `<section class="card danger" style="margin-top:18px"><h2>Close my account</h2><p class="muted" style="margin-top:0">You will be signed out everywhere and cannot sign in again. Your videos and history are kept; the owner can switch the account back on.</p>
        <div class="row"><input id="c_pw" type="password" placeholder="Your password" style="max-width:220px"><input id="c_word" placeholder="Type CLOSE" style="max-width:160px"><button class="dng" id="c_go">Close my account</button></div></section>`}`;
    $("#pw_save").onclick = guard(async () => { await api("/api/auth/password", {method: "POST", body: {old: $("#pw_old").value, new: $("#pw_new").value}}); $("#pw_old").value = $("#pw_new").value = ""; toast("Password changed. Other devices were signed out."); load(); });
    $("#p_others").onclick = guard(async () => { const r = await api("/api/profile/sessions/others", {method: "POST", body: {}}); toast(`Signed out ${r.ended} device(s)`); load(); });
    if ($("#c_go")) $("#c_go").onclick = guard(async () => { if (!confirm("Close your account? You will be signed out and cannot sign in again.")) return; await api("/api/profile/close", {method: "POST", body: {password: $("#c_pw").value, confirm: $("#c_word").value}}); location.hash = ""; location.reload(); });
    await load();
  } else if (tab === "notifications") {
    const p = await api("/api/notifications/prefs");
    const sw = (k, f, on) => `<label class="switch"><input type="checkbox" data-k="${k}" data-f="${f}" ${on ? "checked" : ""}><span></span></label>`;
    T.innerHTML = `<section class="card"><h2>What should I be told about?</h2><p class="muted" style="margin-top:0">Messages appear in the bell. You can also get an email for the ones you choose.</p>
      <table class="ntable"><tr><th>When…</th><th>In the app</th><th>By email</th></tr>${p.prefs.map(x => `<tr><td>${esc(x.label)}</td><td>${sw(x.kind, "app", x.app)}</td><td>${sw(x.kind, "email", x.email)}</td></tr>`).join("")}</table>
      <div class="fields" style="margin-top:14px"><div><label>Send emails to</label><input id="n_to" type="email" value="${esc(p.notify_to)}" placeholder="${esc(p.account_email)}"><div class="help">Leave empty to use your account email (${esc(p.account_email)}).</div></div></div>
      ${p.email_ready ? "" : `<div class="authmsg bad" style="margin:12px 0 0">Email is not set up on this server yet, so email choices have no effect until the owner finishes it (Settings → Email).</div>`}
      <div class="row" style="margin-top:14px"><button class="pri" id="n_save">Save email address</button></div></section>`;
    T.querySelectorAll("input[type=checkbox]").forEach(c => c.onchange = guard(async () => { await api("/api/notifications/prefs", {method: "PUT", body: {prefs: {[c.dataset.k]: {[c.dataset.f]: c.checked}}}}); toast("Saved"); }));
    $("#n_save").onclick = guard(async () => { await api("/api/notifications/prefs", {method: "PUT", body: {notify_to: $("#n_to").value}}); toast("Saved"); });
  } else {
    const yt = await api("/api/youtube/status").catch(() => null);
    T.innerHTML = `<section class="card"><div class="row" style="gap:16px;align-items:center"><span class="edsi" style="width:48px;height:48px;border-radius:16px">${svg("videos")}</span><div style="flex:1;min-width:200px"><h2 style="margin:0">YouTube</h2>
      <div class="muted">${!yt ? "Could not read the connection." : yt.connected ? `Connected to <b>${esc(yt.channel_title || "your channel")}</b>. Videos go to this channel as Unlisted first.` : yt.configured ? "Not connected. Connect your channel so your videos can be uploaded." : "The owner has not finished setting up YouTube sign-in yet."}</div></div>
      ${yt && yt.connected ? '<button class="dng" id="yt_off">Disconnect</button>' : yt && yt.configured ? '<button class="pri" id="yt_on">Connect YouTube</button>' : ""}</div></section>`;
    if ($("#yt_on")) $("#yt_on").onclick = guard(async () => { const r = await api("/api/youtube/connect", {method: "POST"}); location.href = r.url; });
    if ($("#yt_off")) $("#yt_off").onclick = guard(async () => { if (!confirm("Disconnect this channel? Videos stop uploading until you connect again.")) return; await api("/api/youtube/disconnect", {method: "POST"}); toast("Disconnected"); profile(); });
  }
}

