/* The sidebar, page subtitles, the page router (nav) and the live job pill. */
"use strict";
/* ------------------------------------------------------------ shell: sidebar, subtitles, status */
const ICON = {
  overview: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  create: '<circle cx="12" cy="12" r="9"/><path d="M12 8v8M8 12h8"/>',
  videos: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M10 9.5v5l4.5-2.5z"/>',
  clips: '<path d="M4 7h16M4 12h16M4 17h10"/>',
  editor: '<circle cx="6" cy="6.5" r="2.5"/><circle cx="6" cy="17.5" r="2.5"/><path d="M8 8l12 9M8 16l12-9"/>',
  games: '<rect x="2.5" y="7" width="19" height="11" rx="4"/><path d="M7 12h4M9 10v4M15.5 11.5h.01M18 13h.01"/>',
  schedule: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M8 3v4M16 3v4M3.5 10h17"/>',
  twitch: '<path d="M4 4h16v10l-4 4h-4l-3 3v-3H4z"/><path d="M12 8v4M16 8v4"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M16 7l3 3"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6 8.5-6"/>',
  music: '<path d="M9 18V6l11-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  stories: '<rect x="3" y="4" width="18" height="14" rx="2"/><path d="M7 9h6M7 13h10"/><path d="M8 21h8"/>',
  permissions: '<path d="M12 3l8 3v5c0 4.5-3.2 8.2-8 10-4.8-1.8-8-5.5-8-10V6z"/><path d="M8.5 12l2.5 2.5L15.5 9.5"/>',
  projects: '<rect x="3" y="4" width="18" height="11" rx="2"/><path d="M3 19h5M11 19h4M18 19h3"/><path d="M10 7.5v4l3.5-2z"/>',
  social: '<circle cx="6" cy="12" r="2.6"/><circle cx="18" cy="6" r="2.6"/><circle cx="18" cy="18" r="2.6"/><path d="M8.3 10.8l7.4-3.6M8.3 13.2l7.4 3.6"/>',
  more: '<circle cx="5.5" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18.5" cy="12" r="1.6"/>',
};
const svg = (n) => `<svg viewBox="0 0 24 24" aria-hidden="true">${ICON[n]}</svg>`;
let ME = null;
Object.assign(ICON, {usage: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5v9"/><path d="M14.5 9.5h-3.2a1.6 1.6 0 0 0 0 3.2h1.4a1.6 1.6 0 0 1 0 3.2H9.5"/>', reports: '<path d="M4 20V4"/><path d="M4 20h16"/><rect x="7" y="11" width="3" height="6"/><rect x="12" y="7" width="3" height="10"/><rect x="17" y="13" width="3" height="4"/>', users: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.6-3.6 3.2-5.5 6.5-5.5s5.9 1.9 6.5 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M17.5 14.5c2.2.3 3.6 1.8 4 4.5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c.8-4.2 4-6.5 8-6.5s7.2 2.3 8 6.5"/>', logout: '<path d="M9 4H5v16h4M16 8l4 4-4 4M20 12H9"/>'});
function buildShell() {
  const owner = ME.role === "owner";
  const NAV = [["", [["overview", "Home"], ["create", "Make a video"], ["stories", "Story videos"], ["videos", "My videos"], ["games", "Games"], ["schedule", "Schedule"]]],
               ["More tools", [["editor", "Video editor"], ["projects", "Edit projects"], ["permissions", "Creator permissions"], ["clips", "Source clips"], ["research", "Find ideas"], ["social", "Other platforms"]].concat(owner ? [["reactions", "Reaction Lab"], ["lab", "Learning Lab"]] : []), "fold"],
               ["Account", [["usage", "Tokens and usage"], ["settings", "Settings"], ["profile", "My profile"], ["notifications", "Notifications"]]]]
    .concat(owner ? [["Owner", [["users", "Users"], ["reports", "Reports"]]]] : []);
  const navLink = ([r, t]) => `<a href="#/${r}" data-r="${r}">${svg(r)}<span>${t}</span>${r === "reactions" || r === "lab" ? `<i class="betatag">BETA</i>` : ""}</a>`;
  const navHtml = NAV.map(([g, items, fold]) => fold
    ? `<details class="navmore" id="navmore"><summary>${svg("more")}<span>${g}</span></summary>${items.map(navLink).join("")}</details>`
    : (g ? `<div class="navgroup">${g}</div>` : "") + items.map(navLink).join("")).join("");
  const initials = (ME.name || ME.email).split(/\s+/).map(w => w[0]).join("").slice(0, 2).toUpperCase();
  $("#nav").innerHTML = `<div class="brand"><div class="logo">${svg("videos")}</div><div>CLIP <span>STUDIO</span></div><button class="bell" id="bell" title="Notifications" aria-label="Notifications">${svg("bell")}<i id="bellc" hidden>0</i></button><button class="menubtn" id="menubtn" aria-label="Menu" aria-expanded="false"><svg viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></svg></button></div>` +
    `<div class="navlinks">` + navHtml + `</div>` +
    `<div class="sp"></div><div class="sidefoot"><div class="pill" id="jobpill"><span class="d"></span><span id="jobtxt">Idle</span></div>
     <button id="themebtn" title="Switch light / dark">${svg("moon")}<span>Light / dark</span></button>
     <div class="userchip">${avatarMini(initials)}<div class="who"><b>${esc(ME.name)}</b><span id="whoSub">${owner ? "Owner" : "Member"}</span></div><button id="logoutbtn" title="Log out">${svg("logout")}</button></div></div>`;
  $("#bell").onclick = toggleNotifPanel; setBadge(NOTIF.unread);
  const navEl = $("#nav"), mb = $("#menubtn");
  const closeMenu = () => { navEl.classList.remove("open"); mb.setAttribute("aria-expanded", "false"); };
  mb.onclick = () => { const o = navEl.classList.toggle("open"); mb.setAttribute("aria-expanded", o ? "true" : "false"); };
  navEl.addEventListener("click", e => { if (e.target.closest("a")) closeMenu(); });
  window.addEventListener("hashchange", closeMenu);
  $("#jobpill").style.cursor = "pointer"; $("#jobpill").title = "Click to see what is running"; $("#jobpill").onclick = () => openProgress();
  $("#themebtn").onclick = () => {
    const dark = (document.documentElement.dataset.theme || "dark") === "dark";
    document.documentElement.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("theme", document.documentElement.dataset.theme); } catch (e) {}
  };
  $("#logoutbtn").onclick = async () => { try { await api("/api/auth/logout", {method: "POST"}); } catch (e) {} location.hash = ""; location.reload(); };
  try { const t = localStorage.getItem("theme"); if (t) document.documentElement.dataset.theme = t; } catch (e) {}
}
const SUBS = {
  lab: "Beta. Teach the studio your taste: the titles and descriptions you like, and what works on your own videos. Off until you switch a part on.",
  reactions: "Beta. Find the moments people react to in a video, judge them, and let the studio learn what a good reaction means for your channel. Runs on its own: it changes nothing else.",
  research: "Claude searches the web for creators that allow clipping, clipping programmes and campaigns, what they want, and whether you can earn on your own channel. Every answer comes with proof.",
  notifications: "What happened with your videos, uploads and tokens.",
  editor: "Cut a stream replay, a YouTube video or your own file, choose the screen shape, add captions and text, and save it to your Videos.",
  overview: "",
  games: "Add every game you want to cover, each with its own clip sources and branding. Runs pick one game, or take turns through all enabled games (Auto).",
  create: "Pick what to make, where the clips come from, and press Start. You can watch it being made.",
  videos: "Every video made for you. Open one to watch it, change it, approve it or throw it away.",
  stories: "Make short story videos: the studio finds what is trending, writes (or uses your) story, draws the scenes, adds a narrator and builds a project you can edit.",
  permissions: "Write down which creators allowed you to clip them, when, and the proof. Trending mode prefers them and your risk score goes down.",
  projects: "Put several clips on a timeline, trim and reorder them, add text, and make one finished video. Your work saves by itself.",
  social: "Post your videos on TikTok, Instagram, Facebook and Twitch. Your Shorts are already vertical, so they fit the first three; any video can go on Twitch. Each platform gets its own caption. Download the video, open the platform, paste and post. Nothing needs to be connected.",
  clips: "The clips the studio found and saved. Videos are made from these.",
  schedule: "Let the studio make videos for you at times you choose, with no clicking.",
  settings: "Connect your accounts and choose how your videos should look and sound.",
  users: "Approve new members, switch accounts on or off, and watch how busy the server is.",
  reports: "What the studio used, what it cost you in real dollars, what members were billed, and what is left over.",
  usage: "Tokens are what you pay with. Here is what you have left and what each video used.",
};
async function pollJobPill() {
  try {
    const jobs = await api("/api/jobs"); const r = jobs.find(j => j.status === "running");
    $("#jobpill").classList.toggle("live", !!r);
    $("#jobtxt").textContent = r ? `Working: ${r.mode.replace("auto-", "")}` : "Idle";
  } catch (e) {}
}

/* reload by itself when the dashboard was updated, so an old tab never keeps running old code */
let uiVersion = null;
async function checkUiVersion() {
  try {
    const v = (await api("/api/ui-version")).v;
    if (uiVersion === null) uiVersion = v;
    else if (v !== uiVersion && !$("#drawer").classList.contains("open")) location.reload();
  } catch (e) {}
}



function nav() {
  stopTimer();
  const r = (location.hash.replace("#/", "") || "overview").split("/")[0];
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.r === r));
  const fold = document.getElementById("navmore"); if (fold && fold.querySelector(`a[data-r="${r}"]`)) fold.open = true;
  const run = (routes[r] || overview)();
  if (r === "progress") setTimeout(() => openProgress(), 400);
  const h1 = $("#main h1"); if (h1 && !$("#main .lede") && SUBS[r]) h1.insertAdjacentHTML("afterend", `<p class="lede">${SUBS[r]}</p>`);
  run.catch(e => { $("#main").innerHTML = `<div class="card">Error: ${esc(e.message)}</div>`; });
}
addEventListener("hashchange", nav);
