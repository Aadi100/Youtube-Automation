/* AI usage (owner): what the AI services really did, in each service's own numbers. */
"use strict";
/* ------------------------------------------------------------ AI usage (owner) */
async function aiusage() {
  let days = 7, user = "";
  const num = n => Number(n || 0).toLocaleString();
  const min = s => num(Math.round(s / 60 * 10) / 10);
  $("#main").innerHTML = `<h1>AI usage</h1>
    <div class="toolbar"><label style="margin:0">Period</label>
      <select id="aiu_days">${[[1, "Last 24 hours"], [7, "Last 7 days"], [30, "Last 30 days"], [90, "Last 90 days"], [365, "Last year"]].map(([v, l]) => `<option value="${v}" ${v === days ? "selected" : ""}>${l}</option>`).join("")}</select>
      <label style="margin:0">Member</label><select id="aiu_user"><option value="">Everyone</option></select>
      <span class="grow"></span><a class="btn" id="aiu_csv" href="#">Download CSV</a></div>
    <div class="audnote">These are the real numbers each AI service reported to the studio: tokens in and out, pictures, characters, seconds. They are not studio tokens and not dollars. They should be close to your provider dashboards, but they are not the invoice. A call marked <b>counted by size</b> is one where the service did not report its tokens, so the studio counted about 4 characters per token.</div>
    <div class="kpis" id="aiu_kpi"></div><div id="aiu_groups"></div>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>Day by day</h2><select id="aiu_svc"></select></div><div id="aiu_chart"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>What it was used for</h2><span class="muted">Each kind of work, per service.</span></div><div id="aiu_task"></div></section>
    <section class="card" style="margin-bottom:18px"><div class="sechead"><h2>By member</h2></div><div id="aiu_mem"></div></section>
    <section class="card"><div class="sechead"><h2>Latest calls</h2><span class="muted">The most recent ones, newest first.</span></div><div id="aiu_recent"></div></section>`;
  let data = null;
  const draw = () => {
    const d = data, rows = d.groups.flatMap(g => g.rows);
    const sum = (kind, f) => rows.filter(r => r.kind === kind).reduce((a, r) => a + f(r), 0);
    const k = (n, l, sub) => `<div class="card kpi"><div><div class="n">${n}</div><div class="l">${l}${sub ? `<br><span class="muted">${sub}</span>` : ""}</div></div></div>`;
    $("#aiu_kpi").innerHTML = k(num(sum("text", r => r.tokens_in)), "Text AI: input tokens", `${num(sum("text", r => r.calls - r.failed))} calls answered`) + k(num(sum("text", r => r.tokens_out)), "Text AI: output tokens") +
      k(num(sum("image", r => r.units)), "Pictures made", `${num(sum("image", r => r.failed_units))} refused or failed tries`) + k(num(sum("voice", r => r.units)), "Voice: characters spoken") +
      k(num(sum("video", r => r.units)), "AI video: seconds", `${num(sum("video", r => r.calls - r.failed))} clips`) + k(num(rows.reduce((a, r) => a + r.failed, 0)), "Calls that failed", "the service said no or did not answer");
    const est = r => r.estimated ? ` <span class="muted" title="The service did not report its tokens, so they were counted by size">(${num(r.estimated)} counted by size)</span>` : "";
    const head = cols => `<tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr>`;
    const tbl = {
      text: g => `<table>${head(["Service", "Calls", "Failed", "Input tokens", "Output tokens", "Total", "Average per call (in / out)"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.calls)}${est(r)}</td><td>${num(r.failed)}</td><td>${num(r.tokens_in)}</td><td>${num(r.tokens_out)}</td><td>${num(r.tokens_in + r.tokens_out)}</td><td class="muted">${num(r.avg_in)} / ${num(r.avg_out)}</td></tr>`).join("")}</table>`,
      image: g => `<table>${head(["Service", "Pictures made", "Refused or failed tries", "Calls"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.units)}</td><td>${num(r.failed)}</td><td>${num(r.calls)}</td></tr>`).join("")}</table>`,
      voice: g => `<table>${head(["Service", "Lines", "Characters spoken", "Failed"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.calls - r.failed)}</td><td>${num(r.units)}</td><td>${num(r.failed)}</td></tr>`).join("")}</table>`,
      video: g => `<table>${head(["Service", "Clips made", "Seconds asked for", "Failed tries"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.calls - r.failed)}</td><td>${num(r.units)}</td><td>${num(r.failed)}</td></tr>`).join("")}</table>`,
      captions: g => `<table>${head(["Service", "Videos", "Minutes of speech"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.calls)}</td><td>${min(r.units)}</td></tr>`).join("")}</table>`,
      search: g => `<table>${head(["Service", "Searches"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.units)}</td></tr>`).join("")}</table>`,
      safety: g => `<table>${head(["Service", "Clips checked"])}${g.rows.map(r => `<tr><td><b>${esc(r.name)}</b></td><td>${num(r.units)}</td></tr>`).join("")}</table>`,
    };
    const shown = d.groups.filter(g => g.rows.length);
    $("#aiu_groups").innerHTML = shown.length ? shown.map(g => `<section class="card" style="margin-bottom:18px"><div class="sechead"><h2>${esc(g.title)}</h2></div>${tbl[g.kind](g)}</section>`).join("")
      : `<section class="card" style="margin-bottom:18px"><p class="muted" style="margin:0">No AI calls were recorded in this period. The page started counting when it was added, so older work is not here.</p></section>`;
    // day by day
    const keys = Object.keys(d.per_day).sort(), sel = $("#aiu_svc"), keep = sel.value;
    const nameOf = key => { const [kind, svc] = key.split(":"), r = rows.find(x => x.kind === kind && x.service === svc); return r ? r.name : key; };
    sel.innerHTML = keys.map(x => `<option value="${x}">${esc(nameOf(x))}</option>`).join("") || `<option value="">No data</option>`; if (keys.includes(keep)) sel.value = keep;
    const chart = () => {
      const key = sel.value, series = d.per_day[key]; if (!series) { $("#aiu_chart").innerHTML = `<p class="muted">Nothing to draw yet.</p>`; return; }
      const kind = key.split(":")[0], isText = kind === "text";
      const val = x => isText ? x.tokens_in + x.tokens_out : kind === "captions" ? Math.round(x.units / 60 * 10) / 10 : x.units;
      const unit = isText ? "tokens (in + out)" : { image: "pictures", voice: "characters", video: "seconds", captions: "minutes", search: "searches", safety: "clips" }[kind];
      const span = Math.min(d.days, 90), out = [];
      for (let i = span - 1; i >= 0; i--) { const dt = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10); out.push([dt, series[dt] ? val(series[dt]) : 0, series[dt] ? series[dt].calls : 0]); }
      const max = Math.max(1, ...out.map(o => o[1]));
      $("#aiu_chart").innerHTML = `<div class="aibars" role="img" aria-label="Usage per day">${out.map(([dt, v, c]) => `<i style="height:${Math.max(v ? 4 : 1, Math.round(100 * v / max))}%" title="${dt}: ${num(v)} ${unit}, ${c} call${c === 1 ? "" : "s"}"></i>`).join("")}</div>
        <div class="row muted" style="justify-content:space-between;margin-top:6px"><span>${out[0][0]}</span><span>Tallest day: ${num(max)} ${unit}</span><span>${out[out.length - 1][0]} (today)</span></div>`;
    };
    sel.onchange = chart; chart();
    $("#aiu_task").innerHTML = d.by_task.length ? `<table>${head(["For", "Service", "Calls", "Failed", "Input tokens", "Output tokens", "Pictures / characters / seconds"])}${d.by_task.map(t => `<tr><td>${esc(t.task)}</td><td>${esc(nameOf(t.kind + ":" + t.service))}</td><td>${num(t.calls)}</td><td>${num(t.failed)}</td><td>${num(t.tokens_in)}</td><td>${num(t.tokens_out)}</td><td>${t.units ? num(t.units) : '<span class="muted">-</span>'}</td></tr>`).join("")}</table>` : `<p class="muted">Nothing yet.</p>`;
    $("#aiu_mem").innerHTML = d.by_member.length ? `<table>${head(["Member", "Calls", "Input tokens", "Output tokens", "Pictures", "Voice characters", "AI video seconds", "Caption minutes", "Searches"])}${d.by_member.map(m => `<tr><td><b>${esc(m.name)}</b>${m.role === "owner" ? ' <span class="muted">(owner)</span>' : ""}</td><td>${num(m.calls)}</td><td>${num(m.tokens_in)}</td><td>${num(m.tokens_out)}</td><td>${num(m.images)}</td><td>${num(m.voice_characters)}</td><td>${num(m.video_seconds)}</td><td>${min(m.caption_seconds)}</td><td>${num(m.searches)}</td></tr>`).join("")}</table>` : `<p class="muted">Nothing yet.</p>`;
    $("#aiu_recent").innerHTML = d.recent.length ? `<table>${head(["When", "Member", "Service", "For", "Size", "Result"])}${d.recent.map(c => `<tr><td class="muted">${when(c.t)}</td><td>${esc(c.member)}</td><td>${esc(c.name)}</td><td>${esc(c.task || "-")}</td>
      <td>${c.kind === "text" ? `${num(c.tokens_in)} in / ${num(c.tokens_out)} out${c.estimated ? ' <span class="muted">(by size)</span>' : ""}` : `${num(c.units)} ${esc(c.unit)}`}</td><td>${c.ok ? '<span class="badge uploaded">ok</span>' : `<span class="badge declined" title="${esc(c.error)}">failed</span> <span class="muted">${esc(c.error.slice(0, 60))}</span>`}</td></tr>`).join("")}</table>` : `<p class="muted">Nothing yet.</p>`;
  };
  const load = guard(async () => {
    days = +$("#aiu_days").value; user = $("#aiu_user").value;
    data = await api(`/api/admin/ai-usage?days=${days}${user ? "&user=" + encodeURIComponent(user) : ""}`);
    const u = $("#aiu_user"); if (u.options.length <= 1) { data.users.forEach(x => u.insertAdjacentHTML("beforeend", `<option value="${esc(x.id)}">${esc(x.name)}</option>`)); u.value = user; }
    $("#aiu_csv").href = `/api/admin/ai-usage.csv?days=${days}${user ? "&user=" + encodeURIComponent(user) : ""}`;
    draw();
  });
  $("#aiu_days").onchange = load; $("#aiu_user").onchange = load;
  await load();
}
