/* The first-visit tour for members: a spotlight that walks them page by page. The owner does not get it. */
"use strict";
(() => {
  const money = n => (Math.round(Number(n || 0) * 10) / 10).toString();
  const STEPS = [
    {title: "Welcome to Clip Studio",
     text: () => `This studio makes YouTube videos for you in two ways: from <b>gameplay clips</b>, or as an <b>AI story</b> with pictures, a narrator and captions.<br><br>This quick tour (about 2 minutes) shows where everything is and how tokens work. You can stop at any time.`},
    {title: "Your menu", route: "overview", sel: "#nav .navlinks", place: "right", open: true,
     text: () => `Everything lives in this menu. <b>Make a video</b> and <b>Story videos</b> are where you create. <b>My videos</b> is where finished videos wait for you. <b>More tools</b> has the editor, creator permissions and ideas.`},
    {title: "Tokens: how you pay", route: "overview", sel: ".userchip", place: "right", open: true,
     text: () => {
       const t = (typeof TOK !== "undefined" && TOK) || {}, r = t.reserve || {}, u = t.upload_fee || {}, bal = t.balance;
       return `Tokens are what you pay with. ${bal === undefined ? "" : `You have <b>${bal}</b> now, shown here.`}${bal === 0 ? ` <b>You have none yet: ask the owner for tokens.</b>` : ""}
         <ul class="tr-list"><li>When you start a video, a small amount is <b>held first</b> (about ${money(r.short)} for a Short, ${money(r.compilation)} for a compilation). What the video does not use <b>comes back</b>.</li>
         <li>A step or a whole video that <b>fails costs nothing</b>.</li>
         <li>Sending a video to YouTube costs ${money(u.short)} for a Short and ${money(u.compilation)} for a compilation.</li>
         <li>Story videos show their <b>price before you start</b> and a <b>receipt</b> when they are done.</li></ul>`;
     }},
    {title: "Connect your YouTube channel", route: "profile/connections", check: "yt", sel: "#ptab section.card", place: "bottom",
     text: () => `Press <b>Connect YouTube</b> and sign in with Google. Videos are uploaded to your channel as <b>Unlisted</b> first. You look at them, and only then do they go Public. You can disconnect at any time.`},
    {title: "Your voice and look", route: "settings/prefs", check: "voice", sel: ".spane:not([hidden])", place: "left",
     text: () => `Choose your <b>narrator voice</b>, what happens to the creator's own audio, and your <b>thumbnail style</b>, colours and logo. Press the play button to hear a voice before you choose it.`},
    {title: "What should it clip?", route: "settings/clip", sel: ".spane:not([hidden])", place: "left",
     text: () => `Say which kinds of moments you want (funny, intense, fails) and what it must <b>never</b> clip. The AI gets exactly these instructions. <b>Creators &amp; languages</b> and <b>Clip sources</b> are next to this in the Settings menu.`},
    {title: "Make a video from clips", route: "create", check: "video", sel: ".crt-sum", place: "left",
     text: () => `Choose a game or a creator, what kind of moment, the voice and what happens after. Under <b>Your video</b> you see the <b>price</b> before you press <b>Start making it</b>. Progress shows here while it works.`},
    {title: "Make a story video", route: "stories", check: "story", sel: ".stgenres", place: "bottom",
     text: () => `Pick a genre, get story ideas, and the AI writes the script scene by scene. You can change any line. A long story can be split into <b>parts</b>. Each scene gets a picture, a narrator and captions. The price is shown first, and a receipt after. Use the ↻ button on a scene to make one picture again.`},
    {title: "My videos", route: "videos", check: "mine", sel: "#main h1", place: "bottom",
     text: () => `Finished videos wait here. Open one to watch it, change the title or thumbnail, send it to the editor, approve it or upload it. Nothing becomes Public until you say so.`},
    {title: "Tokens and usage", route: "usage", sel: ".kpis", place: "bottom",
     text: () => `Every token you spend is listed here, with a receipt for each video: what each part cost and what came back. Come here whenever you want to check your balance.`},
    {title: "The bell", route: "overview", sel: "#bell", place: "bottom", open: true,
     text: () => `You are told here when a video is ready, when something needs your decision or when something went wrong. Choose which messages also come by email in <b>My profile → Notifications</b>.`},
    {title: "You are ready", route: "overview", summary: true,
     text: () => `That is it. This is where you are:<div class="tr-sum" id="tr-sum">Checking…</div>You can open this tour again any time from the menu: <b>Take the tour</b>.`},
  ];

  /* What the member has really done. Each answer comes from the server, so a step ticks by itself. */
  const DONE = {
    yt: async () => { const r = await api("/api/youtube/status"); return !!(r && r.connected); },
    voice: async () => { const r = await api("/api/me"); return !!((r.user.prefs || {}).tts_voice); },
    video: async () => (await api("/api/jobs")).length > 0,
    story: async () => ((await api("/api/stories")).stories || []).length > 0,
    mine: async () => (await api("/api/videos")).length > 0,
  };
  async function safe(fn) { try { return await fn(); } catch (e) { return null; } }

  let st = null;                                                    // {i, ov, hole, pop, timer, token}
  const $q = s => document.querySelector(s);
  const small = () => innerWidth <= 980;
  const hashNow = () => location.hash.replace(/^#\//, "").replace(/\/$/, "") || "overview";
  const visible = el => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 4 && r.height > 4; };

  function menu(open) { const n = $q("#nav"), b = $q("#menubtn"); if (!n || !small()) return; n.classList.toggle("open", !!open); if (b) b.setAttribute("aria-expanded", open ? "true" : "false"); }

  async function save(value) {
    try { const r = await api("/api/prefs", {method: "PUT", body: {tour: value}}); if (r && r.user) ME = r.user; } catch (e) {}
  }

  function close(value) {
    if (!st) return;
    clearInterval(st.timer); removeEventListener("keydown", onKey, true); removeEventListener("resize", place); removeEventListener("scroll", place, true);
    st.ov.remove(); st.hole.remove(); st.pop.remove(); menu(false);
    document.body.classList.remove("tr-on");
    st = null;
    if (value) save(value).then(() => { if (hashNow() === "overview" && typeof nav === "function") nav(); });   // the Home checklist appears once the tour is over
  }

  function onKey(e) {
    if (!st) return;
    if (e.key === "Escape") { e.preventDefault(); close("skipped"); }
    else if (e.key === "ArrowRight" || e.key === "Enter" && !(e.target && e.target.tagName === "BUTTON")) { e.preventDefault(); go(st.i + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); go(st.i - 1); }
    else if (e.key === "Tab") {                                     // keep the keyboard inside the tour box
      const f = [...st.pop.querySelectorAll("button")]; if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      else if (!st.pop.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
    }
  }

  function place() {
    if (!st) return;
    const step = STEPS[st.i], el = step.sel ? $q(step.sel) : null, pop = st.pop, hole = st.hole;
    const vw = innerWidth, vh = innerHeight, pw = pop.offsetWidth, ph = pop.offsetHeight;
    if (!el || !visible(el)) {                                       // no target: a centred card on a dimmed page
      hole.style.cssText = `left:${vw / 2}px;top:${vh / 2}px;width:0;height:0;box-shadow:0 0 0 9999px rgba(8,5,3,.72)`;
      pop.style.left = Math.max(12, (vw - pw) / 2) + "px"; pop.style.top = Math.max(12, (vh - ph) / 2) + "px"; pop.dataset.at = "center"; return;
    }
    const r = el.getBoundingClientRect(), pad = 6;
    const hx = Math.max(4, r.left - pad), hy = Math.max(4, r.top - pad), hw = Math.min(vw - 8, r.width + pad * 2), hh = Math.min(vh - 8, r.height + pad * 2);
    hole.style.cssText = `left:${hx}px;top:${hy}px;width:${hw}px;height:${Math.min(hh, vh - hy - 4)}px`;
    if (small()) {                                                   // phone: the box docks at the bottom, or at the top when the target is in the lower half
      const low = r.top + r.height / 2 > vh / 2;
      pop.style.left = "12px"; pop.style.top = low ? "12px" : Math.max(12, vh - ph - 12) + "px"; pop.dataset.at = low ? "docktop" : "dock"; return;
    }
    let want = step.place || "bottom", x, y;
    const fits = {right: r.right + 16 + pw <= vw - 8, left: r.left - 16 - pw >= 8, bottom: r.bottom + 16 + ph <= vh - 8, top: r.top - 16 - ph >= 8};
    if (!fits[want]) want = ["right", "bottom", "left", "top"].find(k => fits[k]) || "center";
    if (want === "right") { x = r.right + 16; y = r.top; }
    else if (want === "left") { x = r.left - 16 - pw; y = r.top; }
    else if (want === "bottom") { x = r.left; y = r.bottom + 16; }
    else if (want === "top") { x = r.left; y = r.top - 16 - ph; }
    else { x = (vw - pw) / 2; y = (vh - ph) / 2; }
    pop.style.left = Math.min(Math.max(8, x), vw - pw - 8) + "px"; pop.style.top = Math.min(Math.max(8, y), vh - ph - 8) + "px"; pop.dataset.at = want;
  }

  async function waitFor(step, token) {
    if (!step.sel) { await new Promise(r => setTimeout(r, 250)); return null; }
    for (let k = 0; k < 50; k++) {                                   // up to about 7 seconds for the page to draw
      if (!st || st.token !== token) return null;
      const el = $q(step.sel); if (visible(el)) return el;
      await new Promise(r => setTimeout(r, 140));
    }
    return null;
  }

  async function go(i) {
    if (!st) return;
    if (i < 0) i = 0;
    if (i >= STEPS.length) { close("done"); return; }
    const step = STEPS[i], token = (st.token || 0) + 1; st.token = token; st.i = i;
    st.pop.classList.add("busy");
    if (step.route && hashNow() !== step.route) location.hash = "#/" + step.route;
    menu(!!step.open);
    if (step.sel === ".userchip" || step.sel === "#nav .navlinks") { try { if (typeof refreshTokens === "function") await refreshTokens(); } catch (e) {} }
    const el = await waitFor(step, token);
    if (!st || st.token !== token) return;
    if (el) el.scrollIntoView({block: small() && !step.open ? "start" : "center", behavior: "auto"});
    draw();
    st.pop.classList.remove("busy"); place();
    const next = st.pop.querySelector("[data-next]"); if (next) next.focus({preventScroll: true});
  }

  function draw() {
    const i = st.i, step = STEPS[i], last = i === STEPS.length - 1;
    st.pop.innerHTML = `<div class="tr-top"><span class="tr-count">Step ${i + 1} of ${STEPS.length}</span><button class="tr-x" data-skip aria-label="Close the tour" title="Close the tour">✕</button></div>
      <h3 id="tr-title">${step.title}</h3><div class="tr-text">${step.text()}</div>
      <div class="tr-dots" aria-hidden="true">${STEPS.map((_, k) => `<i class="${k === i ? "on" : k < i ? "past" : ""}"></i>`).join("")}</div>
      <div class="tr-act">${i ? `<button data-back>Back</button>` : `<button data-skip>Skip the tour</button>`}<span class="grow"></span><button class="pri" data-next>${last ? "Finish" : i === 0 ? "Start the tour" : "Next"}</button></div>`;
    const token = st.token;
    if (step.check) {                                                // tick by itself when the thing is really done
      const box = document.createElement("div"); box.className = "tr-check"; st.pop.querySelector(".tr-text").after(box);
      safe(DONE[step.check]).then(ok => { if (!st || st.token !== token || ok === null) return; box.className = "tr-check " + (ok ? "ok" : "todo"); box.textContent = ok ? "✔ You have already done this." : "Not done yet. You can do it after the tour."; place(); });
    }
    if (step.summary) {
      const rows = [["Connected your YouTube channel", "yt", "#/profile/connections"], ["Chose your voice", "voice", "#/settings/prefs"], ["Made a video from clips", "video", "#/create"], ["Made a story video", "story", "#/stories"]];
      Promise.all(rows.map(r => safe(DONE[r[1]]))).then(res => { const el = st && st.token === token ? st.pop.querySelector("#tr-sum") : null; if (!el) return;
        el.innerHTML = rows.map((r, k) => res[k] ? `<div class="tr-row ok">✔ ${r[0]}</div>` : `<div class="tr-row"><span>○ ${r[0]}</span> <a href="${r[2]}" data-close>Do it</a></div>`).join(""); el.querySelectorAll("[data-close]").forEach(a => a.onclick = () => close("done")); place(); });
    }
    st.pop.querySelectorAll("[data-skip]").forEach(b => b.onclick = () => close("skipped"));
    const back = st.pop.querySelector("[data-back]"); if (back) back.onclick = () => go(st.i - 1);
    st.pop.querySelector("[data-next]").onclick = () => go(st.i + 1);
  }

  window.startTour = function (again) {
    if (st || !ME) return;
    if (ME.role === "owner") return;                                // the owner has no tour
    const ov = document.createElement("div"), hole = document.createElement("div"), pop = document.createElement("div");
    ov.className = "tr-ov"; hole.className = "tr-hole"; pop.className = "tr-pop busy";
    pop.setAttribute("role", "dialog"); pop.setAttribute("aria-modal", "true"); pop.setAttribute("aria-labelledby", "tr-title");
    document.body.append(ov, hole, pop); document.body.classList.add("tr-on");
    st = {i: 0, ov, hole, pop, token: 0, timer: setInterval(place, 400)};
    ov.onclick = e => e.stopPropagation();
    addEventListener("keydown", onKey, true); addEventListener("resize", place); addEventListener("scroll", place, true);
    go(0);
  };

  /* A new member sees the tour once, a little after the first page has drawn. */
  window.maybeTour = function () {
    try { if (ME && ME.role !== "owner" && !(ME.prefs || {}).tour && !new URLSearchParams(location.search).get("yt")) setTimeout(() => window.startTour(), 1500); } catch (e) {}
  };
})();
