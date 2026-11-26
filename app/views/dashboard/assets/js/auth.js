/* Sign in and sign up. */
"use strict";
/* ------------------------------------------------------------ sign in / sign up */
let authShown = false;
async function showAuth() {
  if (authShown) return; authShown = true;
  let st = {needs_owner: false, signup: "approval", local: true};
  try { st = await fetch("/api/auth/status").then(r => r.json()); } catch (e) {}
  const ov = document.createElement("div"); ov.id = "authov";
  const first = st.needs_owner;
  let mode = first || (/[?&]signup=1/.test(location.search) && st.signup !== "closed") ? "signup" : "login";
  const draw = (msg, ok) => {
    const signup = mode === "signup";
    ov.innerHTML = `<div class="authwrap"><div class="authhero"><h2>Turn game clips into <em>channel growth</em>.</h2>
      <p>Find the best moments, edit them into videos, make the thumbnail and upload to your own YouTube channel.</p>
      <ul><li>Finds clips from Twitch and YouTube for you</li><li>Edits, adds voice, captions and thumbnails</li><li>You pay only for what each video really uses</li></ul></div>
      <div class="authbox"><div class="brand" style="margin:0 0 6px"><div class="logo">${svg("videos")}</div><div>CLIP <span>STUDIO</span></div></div>
      <h1 style="margin:14px 0 4px">${first ? "Create the owner account" : signup ? "Create your account" : "Welcome back"}</h1>
      <p class="muted" style="margin:0 0 6px">${first ? "This is the first account, so it becomes the owner with full access." : signup ? (st.signup === "open" ? "You can log in right after you sign up." : "The owner has to approve your account before you can log in.") : "Log in to your workspace."}</p>
      ${msg ? `<div class="authmsg ${ok ? "ok" : "bad"}">${esc(msg)}</div>` : ""}
      ${signup ? `<label>Name</label><input id="a_name" autocomplete="name" maxlength="60">` : ""}
      <label>Email</label><input id="a_email" type="email" autocomplete="email">
      <label>Password ${signup ? "(at least 8 characters)" : ""}</label><input id="a_pw" type="password" autocomplete="${signup ? "new-password" : "current-password"}">
      ${first && !st.local ? `<label>Setup code</label><input id="a_code" autocomplete="off" placeholder="shown in the server console"><div class="help">Run <code>python worker.py --show-setup-code</code> on the server to see it.</div>` : ""}
      <button class="pri" id="a_go" style="width:100%;justify-content:center;margin-top:18px">${first ? "Create owner account" : signup ? "Sign up" : "Log in"}</button>
      ${first || st.signup === "closed" ? "" : `<p class="muted" style="text-align:center;margin:14px 0 0">${signup ? "Already have an account?" : "New here?"} <a href="#" id="a_sw">${signup ? "Log in" : "Create an account"}</a></p>`}
      ${first ? "" : `<a class="authlink" href="/">&larr; Back to the home page</a>`}</div></div>`;
    $("#a_go").onclick = go; ov.querySelectorAll("input").forEach(i => i.onkeydown = e => { if (e.key === "Enter") go(); });
    const sw = $("#a_sw"); if (sw) sw.onclick = e => { e.preventDefault(); mode = signup ? "login" : "signup"; draw(); };
    (signup ? $("#a_name") : $("#a_email")).focus();
  };
  const go = async () => {
    const body = {email: $("#a_email").value, password: $("#a_pw").value};
    if (mode === "signup") { body.name = $("#a_name").value; if ($("#a_code")) body.setup_code = $("#a_code").value; }
    $("#a_go").disabled = true;
    try {
      const r = await api(mode === "signup" ? "/api/auth/signup" : "/api/auth/login", {method: "POST", body});
      if (mode === "login" || r.logged_in) { location.reload(); return; }
      mode = "login"; draw(r.message, true);
    } catch (e) { draw(e.message, false); }
  };
  document.body.appendChild(ov); draw();
}
let TOK = null;
let DIY = null;
async function getDiy() { if (!DIY) DIY = await api("/api/diy"); return DIY; }
async function refreshTokens() {
  try { TOK = await api("/api/tokens"); const el = $("#whoSub"); if (el) el.textContent = TOK.owner ? "Owner · free" : `${TOK.balance} tokens · ${TOK.uploaded_today}/${TOK.daily_uploads} uploads today`; } catch (e) {}
}
async function boot() {
  try { ME = (await api("/api/me")).user; } catch (e) { return; }   // not logged in: showAuth() is already open
  buildShell();
  refreshTokens(); setInterval(refreshTokens, 20000);
  const q = new URLSearchParams(location.search);   // back from Google sign-in
  if (q.get("yt")) { toast(q.get("yt") === "ok" ? `YouTube connected: ${q.get("msg")}` : `YouTube sign-in failed: ${q.get("msg") || ""}`, q.get("yt") !== "ok"); history.replaceState(null, "", location.pathname + location.hash); }
  pollJobPill(); setInterval(pollJobPill, 8000);
  pollNotifs(); setInterval(pollNotifs, 8000);
  checkUiVersion(); setInterval(checkUiVersion, 15000);
  nav();
}
addEventListener("DOMContentLoaded", boot);
$("#drawer").addEventListener("click", e => { if (e.target.id === "drawer") closeDrawer(); });
addEventListener("keydown", e => { if (e.key === "Escape") closeDrawer(); });
let progTimer = null;
function closeDrawer() { if (progTimer) { clearInterval(progTimer); progTimer = null; } $("#drawer").classList.remove("open"); const v = $("#drawerBody video"); if (v) v.pause(); }

