/* The live progress panel. */
"use strict";
/* ------------------------------------------------------------ live progress panel */
const fmtDur = sec => { const m = Math.floor(sec / 60); return m ? `${m} min ${sec % 60} s` : `${sec} s`; };
function progressHtml(j) {
  const p = j.progress, owner = ME.role === "owner";
  const done = j.status === "done", failed = j.status === "failed" || j.status === "cancelled", queued = j.status === "queued", running = !done && !failed && !queued;
  const what = p.kind === "remix" ? "Remaking your video with the new audio" : `Making a ${p.kind === "compilation" ? "compilation" : "Short"}${p.game ? " · " + esc(p.game) : ""}`;
  const left = running ? Math.max(15, p.typical - p.elapsed) : 0;
  const meta = done ? `Finished in ${fmtDur(p.elapsed)}` : failed ? "" : queued ? "Not started yet" :
    `Running for ${fmtDur(p.elapsed)} · usually about ${Math.max(1, Math.round(p.typical / 60))} min${p.elapsed < p.typical ? ` · about ${Math.max(1, Math.round(left / 60))} min left` : " · almost there"}`;
  const steps = p.steps.map((s, i) => {
    const icon = s.state === "done" ? "✓" : s.state === "now" ? '<span class="spin"></span>' : s.state === "bad" ? "!" : i + 1;
    return `<div class="pstep ${s.state}"><span class="pi">${icon}</span><span>${esc(s.label)}</span></div>`;
  }).join("");
  return `<div class="pgx ${done ? "ok" : failed ? "bad" : ""}">
    <div class="pgx-top"><div class="pgx-ring" style="--p:${p.percent}"><span>${p.percent}%</span></div>
      <div style="min-width:0"><div class="pgx-title">${what}</div><div class="pgx-now">${esc(p.message)}${running ? '<span class="dots"></span>' : ""}</div><div class="muted" style="margin-top:3px">${meta}</div></div></div>
    <div class="pgx-bar"><i style="width:${p.percent}%"></i></div>
    <div class="pstepsl">${steps}</div>
    ${p.highlights.length ? `<div class="pgx-so"><h4>So far</h4>${p.highlights.map(x => `<div>${esc(x)}</div>`).join("")}</div>` : ""}
    ${owner && j.log ? `<details class="more" style="margin-top:14px"><summary>Technical log (owner only)</summary><pre class="log" style="max-height:300px">${esc((j.log || []).join("\n") || "(no output yet)")}</pre></details>` : ""}
  </div>`;
}
async function openProgress(id) {
  if (!id) { try { const jobs = await api("/api/jobs"); const r = jobs.find(j => j.status === "running") || jobs[0]; id = r && r.id; } catch (e) {} }
  if (!id) { toast("Nothing is running right now"); return; }
  $("#drawerBody").innerHTML = `<div class="dhead"><div><h1 id="ph">Progress</h1><div class="row" style="margin-top:8px" id="pmeta"></div></div><button id="x">Close</button></div>
    <div class="dsec" id="pgbox">Loading…</div>
    <div class="dactions" style="margin-top:12px"><button class="dng" id="pcancel" hidden>Cancel this run</button><button class="pri" id="pvideo" hidden>Open the video</button></div>`;
  $("#drawer").classList.add("open"); $("#x").onclick = closeDrawer;
  const tick = async () => {
    let j; try { j = await api(`/api/jobs/${id}`); } catch (e) { return; }
    if (!$("#pgbox")) return;
    $("#ph").textContent = j.progress.kind === "remix" ? "Remaking your video" : `Making a ${j.progress.kind === "compilation" ? "compilation" : "Short"}`;
    $("#pmeta").innerHTML = `${badge(j.status)}<span class="muted">${j.source === "n8n" ? "scheduled run" : j.source === "remix" ? "new audio" : "started by hand"}</span>`;
    const open = $("#pgbox details") && $("#pgbox details").open;
    $("#pgbox").innerHTML = progressHtml(j);
    if (open && $("#pgbox details")) $("#pgbox details").open = true;
    $("#pcancel").hidden = j.status !== "running" && j.status !== "queued";
    $("#pcancel").onclick = guard(async () => { if (!confirm("Cancel this run? Nothing is charged for a cancelled run.")) return; await api(`/api/jobs/${id}/cancel`, {method: "POST"}); toast("Cancelling…"); });
    $("#pvideo").hidden = !(j.status === "done" && j.video_id);
    if (j.video_id) $("#pvideo").onclick = () => openVideo(j.video_id);
    if (j.status !== "running" && j.status !== "queued" && progTimer) { clearInterval(progTimer); progTimer = null; }
  };
  if (progTimer) clearInterval(progTimer);
  await tick(); progTimer = setInterval(tick, 2000);
}

