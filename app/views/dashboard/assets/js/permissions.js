/* Creator permissions: who allowed you to clip them, when, and the proof. Every member keeps their own list. */
"use strict";
const PERM_STATUS = {allowed: ["Allowed", "uploaded"], asked: ["Asked, no answer yet", "rendered"], declined: ["Said no", "declined"]};
const PERM_PLATFORMS = [["twitch", "Twitch"], ["youtube", "YouTube"], ["kick", "Kick"], ["other", "Somewhere else"]];

async function permissions() {
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);       // the member's own date
  let editing = null;
  $("#main").innerHTML = `<h1>Creator permissions</h1>
    <div class="card" style="margin-bottom:16px"><h2 id="pm_h">Add a creator</h2>
      <p class="muted" style="margin:-6px 0 12px">Write down who said you may clip them, when, and where the proof is (a link to the message or post, or a note of what was said). Trending mode prefers these creators and your videos from them get a lower reused-content risk.</p>
      <div class="pmgrid"><div><label>Where they are</label><select id="pm_pl">${PERM_PLATFORMS.map(([k, t]) => `<option value="${k}">${t}</option>`).join("")}</select></div>
        <div><label>Creator name</label><input id="pm_name" maxlength="80" placeholder="Their name as people know them"></div>
        <div><label>Channel link (helps the studio recognise their clips)</label><input id="pm_url" maxlength="300" placeholder="https://twitch.tv/name"></div>
        <div><label>What they said</label><select id="pm_st">${Object.entries(PERM_STATUS).map(([k, [t]]) => `<option value="${k}">${t}</option>`).join("")}</select></div>
        <div><label>Date they said yes</label><input type="date" id="pm_date" max="${today}" value="${today}"></div>
        <div><label>Until (optional)</label><input type="date" id="pm_end"></div>
        <div class="pmwide"><label>Link to the proof (message, post, email)</label><input id="pm_proof" maxlength="400" placeholder="https://…"></div>
        <div class="pmwide"><label>Or write what was said and where</label><textarea id="pm_note" rows="2" maxlength="600" placeholder="e.g. They answered my DM on 1 Oct: 'yes, clip me, just credit me'"></textarea></div></div>
      <div class="row" style="gap:8px;margin-top:10px"><button class="pri" id="pm_save">Add</button><button id="pm_cancel" hidden>Cancel</button><span class="muted" id="pm_msg"></span></div></div>
    <div class="toolbar"><select id="pm_f"><option value="">Everyone</option><option value="allowed">Allowed</option><option value="asked">Asked</option><option value="declined">Said no</option></select><span class="muted" id="pm_count"></span></div>
    <div id="pm_list"></div>`;
  const form = () => ({platform: $("#pm_pl").value, creator: $("#pm_name").value, channel_url: $("#pm_url").value, status: $("#pm_st").value, granted_on: $("#pm_date").value,
                       expires_on: $("#pm_end").value, proof_url: $("#pm_proof").value, proof_note: $("#pm_note").value});
  const reset = () => { editing = null; $("#pm_h").textContent = "Add a creator"; $("#pm_save").textContent = "Add"; $("#pm_cancel").hidden = true; ["pm_name", "pm_url", "pm_end", "pm_proof", "pm_note"].forEach(i => $("#" + i).value = ""); $("#pm_date").value = today; $("#pm_st").value = "allowed"; $("#pm_pl").value = "twitch"; };
  const load = guard(async () => {
    const d = await api("/api/permissions" + ($("#pm_f").value ? `?status=${$("#pm_f").value}` : ""));
    $("#pm_count").textContent = `${d.permissions.length} creator${d.permissions.length === 1 ? "" : "s"}`;
    $("#pm_list").innerHTML = d.permissions.length ? `<div class="card"><table><tr><th>Creator</th><th>Status</th><th>Date</th><th>Proof</th><th></th></tr>${d.permissions.map(p => `<tr data-id="${p.id}">
        <td><b>${esc(p.creator)}</b><div class="muted">${esc((PERM_PLATFORMS.find(x => x[0] === p.platform) || [0, p.platform])[1])}${p.channel_url ? ` · <a href="${esc(p.channel_url)}" target="_blank" rel="noopener">channel</a>` : ""}</div></td>
        <td><span class="badge ${PERM_STATUS[p.status][1]}">${PERM_STATUS[p.status][0]}</span>${p.expired ? ` <span class="badge declined">ended</span>` : ""}</td>
        <td>${esc(p.granted_on || "-")}${p.expires_on ? `<div class="muted">until ${esc(p.expires_on)}</div>` : ""}</td>
        <td>${p.proof_url ? `<a href="${esc(p.proof_url)}" target="_blank" rel="noopener">Open the proof</a>` : ""}${p.proof_note ? `<div class="muted" style="max-width:340px">${esc(p.proof_note)}</div>` : ""}${!p.proof_url && !p.proof_note ? `<span class="muted">none yet</span>` : ""}</td>
        <td style="text-align:right;white-space:nowrap"><button data-a="edit">Change</button> <button class="dng" data-a="del">Delete</button></td></tr>`).join("")}</table></div>`
      : `<div class="card">${emptyState("check", "No creators yet", "Add the first one above. Keep the proof, so you can show it if anyone asks.")}</div>`;
    $("#pm_list").querySelectorAll("tr[data-id]").forEach(tr => {
      const p = d.permissions.find(x => x.id === tr.dataset.id);
      tr.querySelector("[data-a=del]").onclick = guard(async () => { if (!confirm(`Delete ${p.creator} from your list? The proof is deleted too.`)) return; await api(`/api/permissions/${p.id}`, {method: "DELETE"}); toast("Deleted"); if (editing === p.id) reset(); load(); });
      tr.querySelector("[data-a=edit]").onclick = () => {
        editing = p.id; $("#pm_h").textContent = `Change ${p.creator}`; $("#pm_save").textContent = "Save"; $("#pm_cancel").hidden = false;
        $("#pm_pl").value = p.platform; $("#pm_name").value = p.creator; $("#pm_url").value = p.channel_url || ""; $("#pm_st").value = p.status; $("#pm_date").value = p.granted_on || today;
        $("#pm_end").value = p.expires_on || ""; $("#pm_proof").value = p.proof_url || ""; $("#pm_note").value = p.proof_note || ""; window.scrollTo({top: 0, behavior: "smooth"});
      };
    });
  });
  $("#pm_save").onclick = guard(async () => {
    const body = form();
    if (editing) await api(`/api/permissions/${editing}`, {method: "PUT", body}); else await api("/api/permissions", {method: "POST", body});
    toast(editing ? "Saved" : "Added"); reset(); load();
  });
  $("#pm_cancel").onclick = reset; $("#pm_f").onchange = load;
  await load();
}
