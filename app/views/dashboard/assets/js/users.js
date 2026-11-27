/* Users (owner). */
"use strict";
/* ------------------------------------------------------------ users (owner) */
async function users() {
  $("#main").innerHTML = `<h1>Users</h1><div class="kpis" id="usys"></div>
    <div class="toolbar"><input type="search" id="usearch" placeholder="Search name or email" style="max-width:280px"><span class="grow"></span><label style="margin:0">New sign-ups</label><select id="smode"><option value="approval">Need my approval</option><option value="open">Open: active at once</option><option value="closed">Closed: nobody can sign up</option></select></div>
    <section class="card" id="uprice" style="margin-bottom:18px"></section>
    <section class="card" id="udiy" style="margin-bottom:18px"></section>
    <div class="card" id="ulist"></div><div class="row" id="upager" style="margin-top:14px;justify-content:center"></div>`;
  let page = 1;
  const load = guard(async () => {
    const q = $("#usearch") ? $("#usearch").value.trim() : "";
    const [d, sys] = await Promise.all([api(`/api/admin/users?page=${page}&q=${encodeURIComponent(q)}`), api("/api/admin/system")]);
    $("#smode").value = d.signup;
    const k = (n, l, tone) => `<div class="card kpi"><span class="ic ${tone}">${svg("users")}</span><div><div class="n">${n}</div><div class="l">${l}</div></div></div>`;
    const yq = sys.yt_quota, quotaPct = yq.uploads_total ? Math.round(100 * yq.uploads_used / yq.uploads_total) : 0;
    $("#usys").innerHTML = k(d.accounts, "Accounts", "info") + k(d.pending, "Waiting for approval", d.pending ? "warn" : "ok") +
      k(`${sys.running}/${sys.max_jobs}`, `Jobs running · ${sys.workers.length} worker(s)`, sys.workers.length ? "ok" : "bad") + k(sys.queued, "Jobs waiting in the queue", sys.queued ? "warn" : "ok") +
      k(sys.failed_24h, `Failed in 24 h (${sys.done_24h} made)`, sys.failed_24h > 5 ? "bad" : "ok") + k(`${sys.disk.free_gb} GB`, `Disk free (${sys.disk.free_pct}%)`, sys.disk.free_pct < 15 ? "bad" : "ok") +
      k(`${quotaPct}%`, `YouTube uploads today: ${yq.uploads_used} of ${yq.uploads_total}${sys.uploads_waiting ? " · " + sys.uploads_waiting + " waiting" : ""}`, quotaPct > 90 ? "warn" : "ok");
    $("#uprice").innerHTML = `<div class="sechead"><h2>Token prices</h2><a class="btn" href="#/settings/pricing">Open the prices</a></div><p class="muted" style="margin:0">Prices are set in one place only: Settings → Pricing &amp; costs. Members pay for what each video really used. A failed step or a failed video is never charged. Your own videos are free but are recorded.</p>`;
    const dd = await api("/api/admin/diy");
    $("#udiy").innerHTML = `<div class="sechead"><h2>What members may do themselves</h2><span class="muted">Each thing a member does by hand is something the AI is not charged for. The content-safety check can never be skipped.</span></div>
      ${Object.entries(dd.labels).map(([k, l]) => `<label style="display:flex;gap:10px;align-items:center;margin:8px 0"><input type="checkbox" data-df="${k}" ${dd.flags[k] ? "checked" : ""}> ${esc(l)}</label>`).join("")}`;
    document.querySelectorAll("[data-df]").forEach(c => c.onchange = guard(async () => { await api("/api/admin/diy", {method: "PUT", body: {[c.dataset.df]: c.checked}}); DIY = null; toast("Saved"); }));
    const pill = u => `<span class="badge ${u.status === "active" ? "uploaded" : u.status === "pending" ? "pending" : "declined"}">${esc(u.status)}</span>`;
    $("#ulist").innerHTML = `<table><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Tokens</th><th>Uploads/day</th><th>YouTube</th><th>Videos</th><th>Last login</th><th></th></tr>${d.users.map(u => `
      <tr><td><b>${esc(u.name)}</b></td><td>${esc(u.email)}</td><td>${u.role === "owner" ? '<span class="chip acc">Owner</span>' : "Member"}</td><td>${pill(u)}</td><td>${u.role === "owner" ? "free" : u.tokens}</td><td>${u.role === "owner" ? '<span class="muted">no limit</span>' : `<input type="number" min="0" max="1000" style="width:64px" data-lim="${u.id}" value="${u.upload_limit ?? ""}" placeholder="${u.upload_limit_now}" title="Empty = the default"> <span class="muted">${u.uploads_today} today</span>`}</td><td>${u.youtube ? esc(u.youtube) : '<span class="muted">not connected</span>'}</td><td>${u.videos}</td>
      <td class="muted">${when(u.last_login)}</td><td style="white-space:nowrap;text-align:right">${u.role === "owner" ? "" :
        (u.status !== "active" ? `<button class="pri" data-st="${u.id}:active">Approve</button> ` : `<button data-tok="${u.id}">+ Tokens</button> <button data-st="${u.id}:disabled">Disable</button> `) + `<button class="dng" data-del="${u.id}">Delete</button>`}</td></tr>`).join("")}</table>`;
    $("#upager").innerHTML = d.pages > 1 ? `<button id="pg_prev" ${d.page <= 1 ? "disabled" : ""}>Previous</button><span class="muted">Page ${d.page} of ${d.pages} · ${d.total} accounts</span><button id="pg_next" ${d.page >= d.pages ? "disabled" : ""}>Next</button>` : `<span class="muted">${d.total} account(s)</span>`;
    if ($("#pg_prev")) $("#pg_prev").onclick = () => { page--; load(); };
    if ($("#pg_next")) $("#pg_next").onclick = () => { page++; load(); };
    document.querySelectorAll("[data-st]").forEach(b => b.onclick = guard(async () => { const [id, st] = b.dataset.st.split(":"); await api(`/api/admin/users/${id}/status`, {method: "POST", body: {status: st}}); toast("Updated"); load(); }));
    document.querySelectorAll("[data-tok]").forEach(b => b.onclick = guard(async () => {
      const n = prompt("How many tokens to add? (use a negative number to remove)", "100"); if (n === null) return;
      await api(`/api/admin/users/${b.dataset.tok}/tokens`, {method: "POST", body: {delta: parseInt(n, 10)}}); toast("Tokens updated"); load();
    }));
    document.querySelectorAll("[data-lim]").forEach(i => i.onchange = guard(async () => { await api(`/api/admin/users/${i.dataset.lim}/limit`, {method: "POST", body: {upload_limit: i.value === "" ? null : +i.value}}); toast("Upload limit saved"); load(); }));
    document.querySelectorAll("[data-del]").forEach(b => b.onclick = guard(async () => { if (!confirm("Delete this account and all of their games, clips and jobs? This cannot be undone.")) return; await api(`/api/admin/users/${b.dataset.del}`, {method: "DELETE"}); toast("Deleted"); load(); }));
  });
  let tm = null;
  $("#usearch").oninput = () => { clearTimeout(tm); tm = setTimeout(() => { page = 1; load(); }, 300); };
  $("#smode").onchange = guard(async () => { await api("/api/admin/signup", {method: "PUT", body: {mode: $("#smode").value}}); toast("Saved"); load(); });
  await load();
}


