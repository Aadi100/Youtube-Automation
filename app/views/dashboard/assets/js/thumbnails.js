/* The thumbnail editor and the thumbnail studio. */
"use strict";
/* ------------------------------------------------------------ thumbnail editor (crop, arrows, emoji, shapes, text) */
async function openThumbEditor(id, src, mode, onSaved) {
  const OUT = mode === "16:9" ? {w: 1280, h: 720} : {w: 1080, h: 1920}, ASP = OUT.w / OUT.h;
  const FONTS = [["anton", "Anton"], ["bebas", "Bebas Neue"], ["bangers", "Bangers"], ["righteous", "Righteous"], ["marker", "Permanent Marker"]];
  await Promise.all(FONTS.map(([f]) => new FontFace("th-" + f, `url(/api/font/${f})`).load().then(ff => document.fonts.add(ff)).catch(() => {})));
  let img;
  try { img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("Could not open the picture")); i.src = src; }); } catch (e) { toast(e.message, true); return; }
  const fit = () => { const w = img.width / img.height > ASP ? img.height * ASP : img.width, h = w / ASP; return {x: (img.width - w) / 2, y: (img.height - h) / 2, w, h}; };
  let crop = fit(), adj = {b: 100, c: 100, s: 100}, layers = [], sel = -1, cropMode = false, drag = null;
  const EMOJI = ["😱", "😂", "🔥", "💀", "😡", "🤯", "👀", "❗", "❓", "💥", "⚡", "🏆", "👑", "💯", "😭", "🥶"];
  const COL = ["#FFE600", "#FFFFFF", "#FF3B30", "#FF2D87", "#18A0FB", "#22D3A0", "#FF7A18", "#000000"];
  const host = document.createElement("div"); host.className = "tsm"; host.style.zIndex = 95;
  host.innerHTML = `<div class="tsbox edbox"><div class="dhead" style="margin:0"><div><h1>Edit the thumbnail</h1><div class="muted">Crop it, add arrows, emoji, shapes and text. Free. Click a thing to move it.</div></div><button id="ed_x">Close</button></div>
    <div class="edgrid"><div>
      <div class="edtools"><button id="ed_crop">✂ Crop</button><button data-add="arrow">➜ Arrow</button><button data-add="circle">◯ Circle</button><button data-add="box">▭ Box</button><button data-add="text">T Text</button><span class="grow"></span><button id="ed_undo">↶ Undo</button><button id="ed_redo">↷ Redo</button></div>
      <div class="edemo" id="ed_emo">${EMOJI.map(e => `<button data-emo="${e}" title="Add this emoji">${e}</button>`).join("")}</div>
      <div class="edstage"><canvas id="ed_cv"></canvas></div></div>
    <div>
      <div class="edsec" id="ed_props"><h4>Selected</h4><div id="ed_none" class="muted">Click something on the picture, or add one on the left.</div>
        <div id="ed_have" hidden><div id="ed_textrow"><label>Text</label><input id="ed_text" maxlength="40"><label>Font</label><select id="ed_font">${FONTS.map(([f, n]) => `<option value="${f}">${n}</option>`).join("")}</select></div>
          <label>Colour</label><div class="sws" id="ed_cols">${COL.map(c => `<span class="sw" data-c="${c}" style="background:${c}"></span>`).join("")}<input type="color" id="ed_col" value="#ffe600"></div>
          <label>Size</label><input type="range" id="ed_size" min="30" max="900" step="2"><label>Turn</label><input type="range" id="ed_rot" min="-180" max="180" step="1">
          <div class="row" style="margin-top:10px"><button id="ed_dup">Copy</button><button id="ed_front">To front</button><button class="dng" id="ed_del">Delete</button></div></div></div>
      <div class="edsec"><h4>The picture</h4><label>Brightness <b id="ed_bv"></b></label><input type="range" id="ed_b" min="50" max="170"><label>Contrast <b id="ed_cv2"></b></label><input type="range" id="ed_c" min="50" max="170"><label>Colour <b id="ed_sv"></b></label><input type="range" id="ed_s" min="0" max="220">
        <div class="row" style="margin-top:10px"><button id="ed_reset">Reset the picture</button></div></div>
      <div class="dactions"><button class="pri" id="ed_save">Use this as the thumbnail</button><button id="ed_cancel">Cancel</button></div>
    </div></div></div>`;
  document.body.appendChild(host);
  const q = sel2 => host.querySelector(sel2), qa = sel2 => host.querySelectorAll(sel2);
  const cv = q("#ed_cv"), ctx = cv.getContext("2d");
  const view = () => cropMode ? {x: 0, y: 0, w: img.width, h: img.height} : crop;
  // ---- history
  const snap = () => JSON.stringify({layers, adj, crop});
  let hist = [snap()], hi = 0;
  const commit = () => { hist = hist.slice(0, hi + 1); hist.push(snap()); if (hist.length > 60) hist.shift(); hi = hist.length - 1; };
  const restore = i => { const o = JSON.parse(hist[i]); layers = o.layers; adj = o.adj; crop = o.crop; sel = -1; sync(); paint(); };
  // ---- drawing
  const rr = (c, x, y, w, h, r) => { c.beginPath(); c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r); c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath(); };
  const layerPath = (c, L) => {
    const s = L.size; c.lineJoin = "round"; c.lineCap = "round"; c.textAlign = "center"; c.textBaseline = "middle";
    if (L.type === "emoji") { c.font = `${s}px "Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif`; c.fillText(L.text, 0, 0); }
    else if (L.type === "arrow") {
      c.beginPath(); c.moveTo(-s * .95, -s * .13); c.lineTo(s * .25, -s * .13); c.lineTo(s * .25, -s * .42); c.lineTo(s * .98, 0); c.lineTo(s * .25, s * .42); c.lineTo(s * .25, s * .13); c.lineTo(-s * .95, s * .13); c.closePath();
      c.lineWidth = s * .08; c.strokeStyle = "#000"; c.stroke(); c.fillStyle = L.color; c.fill();
    } else if (L.type === "circle") { c.beginPath(); c.ellipse(0, 0, s * .62, s * .62, 0, 0, Math.PI * 2); c.lineWidth = s * .2; c.strokeStyle = "#000"; c.stroke(); c.lineWidth = s * .11; c.strokeStyle = L.color; c.stroke(); }
    else if (L.type === "box") { rr(c, -s * .8, -s * .55, s * 1.6, s * 1.1, s * .12); c.lineWidth = s * .2; c.strokeStyle = "#000"; c.stroke(); c.lineWidth = s * .11; c.strokeStyle = L.color; c.stroke(); }
    else if (L.type === "text") { c.font = `${s}px "th-${L.font}", Impact, sans-serif`; c.lineWidth = s * .16; c.strokeStyle = "#000"; c.strokeText(L.text, 0, 0); c.fillStyle = L.color; c.fillText(L.text, 0, 0); }
  };
  const drawLayer = (c, L, v, k) => { c.save(); c.translate((L.x - v.x) * k, (L.y - v.y) * k); c.rotate(L.rot * Math.PI / 180); c.scale(k, k); layerPath(c, L); c.restore(); };
  const filt = () => `brightness(${adj.b}%) contrast(${adj.c}%) saturate(${adj.s}%)`;
  const paint = () => {
    const v = view(), cssW = Math.min(host.querySelector(".edstage").clientWidth - 20 || 520, v.w / v.h < 1 ? Math.min(520, innerHeight * .6 * v.w / v.h) : 700);
    const cssH = cssW * v.h / v.w, dpr = devicePixelRatio || 1;
    cv.style.width = cssW + "px"; cv.style.height = cssH + "px"; cv.width = Math.round(cssW * dpr); cv.height = Math.round(cssH * dpr);
    const k = cv.width / v.w;
    ctx.filter = filt(); ctx.drawImage(img, v.x, v.y, v.w, v.h, 0, 0, v.w * k, v.h * k); ctx.filter = "none";
    layers.forEach(L => drawLayer(ctx, L, v, k));
    if (cropMode) {
      ctx.fillStyle = "rgba(0,0,0,.6)"; const X = crop.x * k, Y = crop.y * k, W = crop.w * k, H = crop.h * k;
      ctx.fillRect(0, 0, cv.width, Y); ctx.fillRect(0, Y + H, cv.width, cv.height - Y - H); ctx.fillRect(0, Y, X, H); ctx.fillRect(X + W, Y, cv.width - X - W, H);
      ctx.strokeStyle = "#fff"; ctx.lineWidth = 3 * dpr; ctx.strokeRect(X, Y, W, H);
      ctx.fillStyle = "#fff"; [[X, Y], [X + W, Y], [X, Y + H], [X + W, Y + H]].forEach(([a, b]) => ctx.fillRect(a - 9 * dpr, b - 9 * dpr, 18 * dpr, 18 * dpr));
    } else if (sel >= 0 && layers[sel]) {
      const L = layers[sel]; ctx.save(); ctx.translate((L.x - v.x) * k, (L.y - v.y) * k); ctx.rotate(L.rot * Math.PI / 180); ctx.strokeStyle = "#00e5ff"; ctx.lineWidth = 2.5 * dpr; ctx.setLineDash([8 * dpr, 6 * dpr]);
      const b = bounds(L); ctx.strokeRect(-b.w * k, -b.h * k, b.w * 2 * k, b.h * 2 * k); ctx.restore();
    }
    q("#ed_bv").textContent = adj.b + "%"; q("#ed_cv2").textContent = adj.c + "%"; q("#ed_sv").textContent = adj.s + "%";
  };
  const bounds = L => { const s = L.size; if (L.type === "arrow") return {w: s, h: s * .45}; if (L.type === "box") return {w: s * .85, h: s * .6};
    if (L.type === "text") { ctx.save(); ctx.font = `${s}px "th-${L.font}", Impact, sans-serif`; const w = ctx.measureText(L.text).width / 2; ctx.restore(); return {w: w + s * .1, h: s * .6}; } return {w: s * .65, h: s * .65}; };
  const toImg = e => { const r = cv.getBoundingClientRect(), v = view(); return {x: v.x + (e.clientX - r.left) / r.width * v.w, y: v.y + (e.clientY - r.top) / r.height * v.h, k: v.w / r.width}; };
  const hit = pt => { for (let i = layers.length - 1; i >= 0; i--) { const L = layers[i], a = -L.rot * Math.PI / 180, dx = pt.x - L.x, dy = pt.y - L.y, lx = dx * Math.cos(a) - dy * Math.sin(a), ly = dx * Math.sin(a) + dy * Math.cos(a), b = bounds(L); if (Math.abs(lx) <= b.w && Math.abs(ly) <= b.h) return i; } return -1; };
  // ---- the panel for the selected thing
  const sync = () => {
    const L = layers[sel]; q("#ed_none").hidden = !!L; q("#ed_have").hidden = !L; q("#ed_crop").classList.toggle("on", cropMode); q("#ed_crop").textContent = cropMode ? "✓ Done cropping" : "✂ Crop";
    q("#ed_b").value = adj.b; q("#ed_c").value = adj.c; q("#ed_s").value = adj.s;
    if (!L) return;
    q("#ed_textrow").hidden = L.type !== "text"; q("#ed_text").value = L.text || ""; q("#ed_font").value = L.font || "anton"; q("#ed_col").value = L.color || "#ffe600";
    q("#ed_cols").style.display = L.type === "emoji" ? "none" : "flex"; q("#ed_size").value = L.size; q("#ed_rot").value = L.rot;
    qa("#ed_cols .sw").forEach(c => c.classList.toggle("on", (L.color || "").toLowerCase() === c.dataset.c.toLowerCase()));
  };
  const add = (type, extra) => {
    const v = view(), base = Math.min(crop.w, crop.h);
    layers.push({type, x: v.x + v.w / 2, y: v.y + v.h / 2, size: Math.round(base * (type === "emoji" ? .3 : type === "text" ? .16 : .26)), rot: type === "arrow" ? -20 : 0, color: type === "arrow" ? "#FF3B30" : "#FFE600", text: type === "text" ? "WOW" : "", font: "anton", ...extra});
    sel = layers.length - 1; commit(); sync(); paint();
  };
  qa("[data-add]").forEach(b => b.onclick = () => add(b.dataset.add));
  qa("[data-emo]").forEach(b => b.onclick = () => add("emoji", {text: b.dataset.emo}));
  q("#ed_crop").onclick = () => { cropMode = !cropMode; if (!cropMode) commit(); sel = -1; sync(); paint(); };
  const change = fn => { if (!layers[sel]) return; fn(layers[sel]); paint(); };
  q("#ed_text").oninput = e => change(L => { L.text = e.target.value; }); q("#ed_font").onchange = e => { change(L => { L.font = e.target.value; }); commit(); };
  q("#ed_col").oninput = e => change(L => { L.color = e.target.value; sync(); }); qa("#ed_cols .sw").forEach(c => c.onclick = () => { change(L => { L.color = c.dataset.c; }); commit(); sync(); });
  q("#ed_size").oninput = e => change(L => { L.size = +e.target.value; }); q("#ed_rot").oninput = e => change(L => { L.rot = +e.target.value; });
  [["#ed_text", "change"], ["#ed_col", "change"], ["#ed_size", "change"], ["#ed_rot", "change"]].forEach(([i]) => q(i).addEventListener("change", commit));
  q("#ed_del").onclick = () => { if (layers[sel]) { layers.splice(sel, 1); sel = -1; commit(); sync(); paint(); } };
  q("#ed_dup").onclick = () => { if (layers[sel]) { layers.push({...layers[sel], x: layers[sel].x + 30, y: layers[sel].y + 30}); sel = layers.length - 1; commit(); sync(); paint(); } };
  q("#ed_front").onclick = () => { if (layers[sel]) { layers.push(layers.splice(sel, 1)[0]); sel = layers.length - 1; commit(); paint(); } };
  [["#ed_b", "b"], ["#ed_c", "c"], ["#ed_s", "s"]].forEach(([i, k]) => { q(i).oninput = e => { adj[k] = +e.target.value; paint(); }; q(i).onchange = commit; });
  q("#ed_reset").onclick = () => { adj = {b: 100, c: 100, s: 100}; commit(); sync(); paint(); };
  q("#ed_undo").onclick = () => { if (hi > 0) restore(--hi); }; q("#ed_redo").onclick = () => { if (hi < hist.length - 1) restore(++hi); };
  // ---- mouse / finger
  cv.addEventListener("pointerdown", e => {
    cv.setPointerCapture(e.pointerId); const pt = toImg(e);
    if (cropMode) {
      const m = 22 * pt.k, c = crop, corners = [[c.x, c.y, c.x + c.w, c.y + c.h], [c.x + c.w, c.y, c.x, c.y + c.h], [c.x, c.y + c.h, c.x + c.w, c.y], [c.x + c.w, c.y + c.h, c.x, c.y]];
      const k = corners.find(([cx, cy]) => Math.abs(pt.x - cx) < m && Math.abs(pt.y - cy) < m);
      drag = k ? {t: "resize", ax: k[2], ay: k[3]} : (pt.x > c.x && pt.x < c.x + c.w && pt.y > c.y && pt.y < c.y + c.h ? {t: "cmove", ox: pt.x - c.x, oy: pt.y - c.y} : null); return;
    }
    sel = hit(pt); if (sel >= 0) drag = {t: "move", ox: pt.x - layers[sel].x, oy: pt.y - layers[sel].y}; sync(); paint();
  });
  cv.addEventListener("pointermove", e => {
    if (!drag) return; const pt = toImg(e);
    if (drag.t === "move") { layers[sel].x = pt.x - drag.ox; layers[sel].y = pt.y - drag.oy; paint(); }
    else if (drag.t === "cmove") { crop.x = Math.max(0, Math.min(img.width - crop.w, pt.x - drag.ox)); crop.y = Math.max(0, Math.min(img.height - crop.h, pt.y - drag.oy)); paint(); }
    else if (drag.t === "resize") {
      let w = Math.abs(pt.x - drag.ax), h = w / ASP; if (Math.abs(pt.y - drag.ay) > h) { h = Math.abs(pt.y - drag.ay); w = h * ASP; }
      const dirx = pt.x < drag.ax ? -1 : 1, diry = pt.y < drag.ay ? -1 : 1;
      w = Math.max(img.width * .1, Math.min(w, dirx < 0 ? drag.ax : img.width - drag.ax)); h = w / ASP; if (diry < 0 ? h > drag.ay : drag.ay + h > img.height) { h = diry < 0 ? drag.ay : img.height - drag.ay; w = h * ASP; }
      crop = {x: dirx < 0 ? drag.ax - w : drag.ax, y: diry < 0 ? drag.ay - h : drag.ay, w, h}; paint();
    }
  });
  const end = () => { if (drag) { drag = null; commit(); } }; cv.addEventListener("pointerup", end); cv.addEventListener("pointercancel", end);
  const key = e => { if (!document.body.contains(host)) return document.removeEventListener("keydown", key); if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
    if ((e.key === "Delete" || e.key === "Backspace") && layers[sel]) { e.preventDefault(); q("#ed_del").click(); } if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); (e.shiftKey ? q("#ed_redo") : q("#ed_undo")).click(); } };
  document.addEventListener("keydown", key);
  const close = () => { document.removeEventListener("keydown", key); host.remove(); };
  q("#ed_x").onclick = q("#ed_cancel").onclick = close;
  q("#ed_save").onclick = guard(async () => {
    q("#ed_save").disabled = true;
    try {
      const o = document.createElement("canvas"); o.width = OUT.w; o.height = OUT.h; const c2 = o.getContext("2d"), k = OUT.w / crop.w;
      c2.filter = filt(); c2.drawImage(img, crop.x, crop.y, crop.w, crop.h, 0, 0, OUT.w, OUT.h); c2.filter = "none"; layers.forEach(L => drawLayer(c2, L, crop, k));
      const blob = await new Promise(res => o.toBlob(res, "image/jpeg", 0.92));
      const r = await api(`/api/videos/${id}/thumb-edited`, {method: "POST", body: blob, raw: true}); toast(r.message); close(); if (onSaved) onSaved();
    } finally { if (q("#ed_save")) q("#ed_save").disabled = false; }
  });
  addEventListener("resize", () => { if (document.body.contains(host)) paint(); });
  sync(); paint();
}

/* ------------------------------------------------------------ thumbnail studio */
async function openThumbStudio(id, onSaved) {
  let opt, inf;
  try { [opt, inf] = await Promise.all([api("/api/thumb/options"), api(`/api/videos/${id}/thumb-info`)]); } catch (e) { toast(e.message, true); return; }
  const S = {source: "frame", t: Math.round(inf.duration * 0.65 * 10) / 10, style: opt.styles.some(x => x.id === inf.style) ? inf.style : "classic", headline: inf.headline, subtext: inf.subtext,
             text: inf.brand.text, accent: inf.brand.accent, font: inf.brand.font};
  let hasArt = inf.has_art, url = null, busy = 0, tm = null, nPics = (opt.brand && opt.brand.pictures) === 3 ? 3 : 1;
  const free = opt.owner ? "free" : null;
  const artLabel = () => `Draw ${nPics} AI picture${nPics > 1 ? "s" : ""}${free ? "" : ` (${opt.prices.art * nPics} token${opt.prices.art * nPics > 1 ? "s" : ""})`}`;
  const host = document.createElement("div"); host.className = "tsm"; host.id = "tsm";
  const sw = (key) => `<div class="sws" id="sw_${key}">${opt.colors.map(c => `<span class="sw" data-c="${c}" style="background:${c}"></span>`).join("")}<input type="color" data-ci="${key}" value="${S[key]}" title="Any colour"></div>`;
  host.innerHTML = `<div class="tsbox"><div class="dhead" style="margin:0"><div><h1>Thumbnail studio</h1><div class="muted">Shape this video's thumbnail. Styles, text, colours and moments are free.</div></div><button id="ts_x">Close</button></div>
    <div class="tsgrid"><div>
      <div class="tsprev"><img id="ts_img" alt="Preview"><div class="tsbusy" id="ts_busy" hidden>Drawing…</div></div>
      <div style="margin-top:12px"><label>Moment of the video <b id="ts_tlab"></b></label><input type="range" id="ts_t" min="0" max="${inf.duration}" step="0.1" value="${S.t}" style="width:100%"></div>
      <div class="tschips" id="ts_src"><span class="tschip on" data-s="frame">A moment of my video</span><span class="tschip ${hasArt ? "" : "off"}" data-s="art" id="ts_srcart" style="${hasArt ? "" : "opacity:.45"}">A picture (AI or mine)</span></div>
      <input id="ts_scene" maxlength="200" placeholder="Describe the picture, e.g. a guard panicking in a neon room (optional)">
      <div class="row" style="margin-top:12px"><button class="pri" id="ts_cmp3" title="Three different looks of this video, drawn at once. Free.">⚖ Compare 3 options</button><button id="ts_edit" title="Crop it, add arrows, emoji, shapes and text">✎ Edit this picture…</button></div>
      <div id="ts_cmp"></div>
      <div style="margin-top:14px"><label>AI pictures</label>
        <div class="tschips" id="ts_npics" style="margin:4px 0 8px"><span class="tschip" data-n="1">1 picture</span><span class="tschip" data-n="3">3 pictures to choose from</span></div>
        <div class="row"><button id="ts_art"></button><button id="ts_up">Use my own picture</button><input type="file" id="ts_upf" accept="image/jpeg,image/png" hidden></div></div>
    </div><div>
      <label>Style</label><div class="tschips" id="ts_styles"><span class="tschip" data-st="auto">🎲 Surprise me</span>${opt.styles.map(x => `<span class="tschip" data-st="${x.id}">${esc(x.name)}</span>`).join("")}</div>
      <label>Headline</label><input id="ts_head" maxlength="60" value="${esc(S.headline)}">
      <div class="row" style="margin:8px 0"><button id="ts_sug">Suggest headlines${free ? "" : ` (${opt.prices.suggest} token)`}</button></div><div class="tschips" id="ts_ideas"></div>
      <label>Small text (the tag)</label><input id="ts_sub" maxlength="30" value="${esc(S.subtext)}">
      <div class="grid g2"><div><label>Text colour</label>${sw("text")}</div><div><label>Accent colour</label>${sw("accent")}</div></div>
      <label>Font</label><select id="ts_font">${opt.fonts.map(f => `<option value="${f.id}" ${f.id === S.font ? "selected" : ""}>${esc(f.name)}</option>`).join("")}</select>
      <div class="dactions" style="margin-top:16px"><button class="pri" id="ts_save">Use this thumbnail</button><button id="ts_cancel">Cancel</button></div>
    </div></div></div>`;
  document.body.appendChild(host);
  const q = sel => host.querySelector(sel), qa = sel => host.querySelectorAll(sel);
  const close = () => { if (url) URL.revokeObjectURL(url); host.remove(); };
  const fmt = t => `${Math.floor(t / 60)}:${(t % 60).toFixed(1).padStart(4, "0")}`;
  const mark = () => {
    q("#ts_tlab").textContent = fmt(S.t);
    qa("#ts_styles .tschip").forEach(c => c.classList.toggle("on", c.dataset.st === S.style));
    qa("#ts_src .tschip").forEach(c => c.classList.toggle("on", c.dataset.s === S.source));
    ["text", "accent"].forEach(k => qa(`#sw_${k} .sw`).forEach(c => c.classList.toggle("on", c.dataset.c.toLowerCase() === S[k].toLowerCase())));
    q("#ts_srcart").style.opacity = hasArt ? 1 : .45; q("#ts_t").disabled = S.source === "art";
  };
  const draw = () => {
    clearTimeout(tm);
    tm = setTimeout(async () => {
      busy++; q("#ts_busy").hidden = false;
      try {
        const r = await fetch(`/api/videos/${id}/thumb-preview`, {method: "POST", credentials: "same-origin", headers: {"X-Requested-With": "studio", "Content-Type": "application/json"}, body: JSON.stringify(S)});
        if (!r.ok) { const e = await r.json().catch(() => ({})); toast(e.error || "Could not draw the preview", true); }
        else { const b = await r.blob(); if (url) URL.revokeObjectURL(url); url = URL.createObjectURL(b); q("#ts_img").src = url; }
      } finally { busy--; if (!busy) q("#ts_busy").hidden = true; }
    }, 220);
  };
  const set = (k, v) => { S[k] = v; mark(); draw(); };
  qa("#ts_styles .tschip").forEach(c => c.onclick = () => set("style", c.dataset.st));
  qa("#ts_src .tschip").forEach(c => c.onclick = () => { if (c.dataset.s === "art" && !hasArt) { toast("Make a new AI picture or use your own picture first"); return; } set("source", c.dataset.s); });
  q("#ts_t").oninput = e => set("t", +e.target.value);
  q("#ts_head").oninput = e => set("headline", e.target.value); q("#ts_sub").oninput = e => set("subtext", e.target.value);
  q("#ts_font").onchange = e => set("font", e.target.value);
  ["text", "accent"].forEach(k => { qa(`#sw_${k} .sw`).forEach(c => c.onclick = () => { q(`[data-ci=${k}]`).value = c.dataset.c; set(k, c.dataset.c); }); q(`[data-ci=${k}]`).oninput = e => set(k, e.target.value); });
  const gotArt = r => { hasArt = true; S.source = "art"; mark(); draw(); return r; };
  const drawOne = guard(async () => {
    q("#ts_art").disabled = true; q("#ts_art").textContent = "Drawing the picture… (up to a minute)";
    try { const r = await api(`/api/videos/${id}/thumb-art`, {method: "POST", body: {scene: q("#ts_scene").value}}); gotArt(r); toast(r.charged ? `New picture ready (${r.charged} token${r.charged > 1 ? "s" : ""})` : "New picture ready"); refreshTokens(); }
    finally { q("#ts_art").disabled = false; q("#ts_art").textContent = artLabel(); }
  });
  q("#ts_up").onclick = () => q("#ts_upf").click();
  q("#ts_upf").onchange = guard(async () => { const f = q("#ts_upf").files[0]; if (!f) return; const r = await api(`/api/videos/${id}/thumb-art-upload`, {method: "POST", body: f, raw: true}); gotArt(r); toast("Your picture is ready"); q("#ts_upf").value = ""; });
  q("#ts_sug").onclick = guard(async () => {
    q("#ts_sug").disabled = true;
    try { const r = await api(`/api/videos/${id}/thumb-suggest`, {method: "POST", body: {}}); q("#ts_ideas").innerHTML = r.headlines.map(h => `<span class="tschip" data-h="${esc(h)}">${esc(h)}</span>`).join(""); refreshTokens();
      qa("#ts_ideas .tschip").forEach(c => c.onclick = () => { q("#ts_head").value = c.dataset.h; set("headline", c.dataset.h); }); }
    finally { q("#ts_sug").disabled = false; }
  });
  q("#ts_save").onclick = guard(async () => { q("#ts_save").disabled = true; try { const r = await api(`/api/videos/${id}/thumb-save`, {method: "POST", body: S}); toast(r.message); close(); if (onSaved) onSaved(); } finally { if (q("#ts_save")) q("#ts_save").disabled = false; } });
  const syncInputs = () => { q("#ts_t").value = S.t; q("#ts_font").value = S.font; q("[data-ci=text]").value = S.text; q("[data-ci=accent]").value = S.accent; q("#ts_head").value = S.headline; q("#ts_sub").value = S.subtext; };
  q("#ts_cmp3").onclick = guard(async () => {
    q("#ts_cmp3").disabled = true; q("#ts_cmp3").textContent = "Drawing 3 options…";
    try {
      const r = await api(`/api/videos/${id}/thumb-variants`, {method: "POST", body: S});
      q("#ts_cmp").innerHTML = `<div class="muted" style="margin-top:12px">Click the one you like. You can still change it after.</div><div class="tsvars">${r.variants.map((v, i) => `<div class="tsvar" data-i="${i}"><span class="tag">${i + 1}</span><img src="${v.image}" alt="Option ${i + 1}"></div>`).join("")}</div>`;
      qa("#ts_cmp .tsvar").forEach(el => el.onclick = () => { Object.assign(S, r.variants[+el.dataset.i].opts); syncInputs(); mark(); draw(); toast("Option " + (+el.dataset.i + 1) + " loaded"); });
      q("#ts_cmp").scrollIntoView({behavior: "smooth", block: "nearest"});
    } finally { q("#ts_cmp3").disabled = false; q("#ts_cmp3").textContent = "⚖ Compare 3 options"; }
  });
  let pollT = null;
  const showSlots = async (info2) => {
    const slots = [1, 2, 3], b = info2.batch;
    q("#ts_cmp").innerHTML = `<div class="muted" style="margin-top:12px">${b.running ? "Drawing the pictures… each one takes up to a minute. You can keep working." : b.error ? esc(b.error) : `${info2.slots.length} picture(s) ready${b.charged ? ` · ${b.charged} token${b.charged > 1 ? "s" : ""} used` : ""}${b.failed ? ` · ${b.failed} failed (not charged)` : ""}. Click the one you like.`}</div><div class="tsvars">${slots.map(n => info2.slots.includes(n) ? `<div class="tsvar" data-slot="${n}"><span class="tag">${n}</span><img id="sl${n}" alt="Picture ${n}"></div>` : `<div class="tsvar wait">${b.running ? "waiting…" : "—"}</div>`).join("")}</div>`;
    for (const n of info2.slots) {
      const r = await fetch(`/api/videos/${id}/thumb-preview`, {method: "POST", credentials: "same-origin", headers: {"X-Requested-With": "studio", "Content-Type": "application/json"}, body: JSON.stringify({...S, source: "art", art_slot: n})});
      if (r.ok && q(`#sl${n}`)) q(`#sl${n}`).src = URL.createObjectURL(await r.blob());
    }
    qa("#ts_cmp .tsvar[data-slot]").forEach(el => el.onclick = guard(async () => { await api(`/api/videos/${id}/thumb-pick`, {method: "POST", body: {slot: +el.dataset.slot}}); hasArt = true; S.source = "art"; mark(); draw(); toast("Picture " + el.dataset.slot + " chosen"); }));
  };
  const drawMany = guard(async () => {
    q("#ts_art").disabled = true; q("#ts_art").textContent = "Drawing the pictures…";
    try { await api(`/api/videos/${id}/thumb-batch`, {method: "POST", body: {scene: q("#ts_scene").value, n: nPics}}); } catch (e) { q("#ts_art").disabled = false; q("#ts_art").textContent = artLabel(); throw e; }
    clearInterval(pollT);
    const tick = async () => { if (!document.body.contains(host)) return clearInterval(pollT); const i2 = await api(`/api/videos/${id}/thumb-batch`); await showSlots(i2); refreshTokens(); if (!i2.batch.running) { clearInterval(pollT); q("#ts_art").disabled = false; q("#ts_art").textContent = artLabel(); } };
    await tick(); pollT = setInterval(guard(tick), 5000);
  });
  q("#ts_edit").onclick = guard(async () => {
    q("#ts_edit").disabled = true;
    try {
      const r = await fetch(`/api/videos/${id}/thumb-preview`, {method: "POST", credentials: "same-origin", headers: {"X-Requested-With": "studio", "Content-Type": "application/json"}, body: JSON.stringify({...S, full: true})});
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || "Could not open the picture");
      openThumbEditor(id, URL.createObjectURL(await r.blob()), inf.mode, () => { close(); if (onSaved) onSaved(); });
    } finally { q("#ts_edit").disabled = false; }
  });
  q("#ts_x").onclick = q("#ts_cancel").onclick = () => { clearInterval(pollT); close(); };
  host.addEventListener("mousedown", e => { if (e.target === host) { clearInterval(pollT); close(); } });
  const markN = () => { qa("#ts_npics .tschip").forEach(c => c.classList.toggle("on", +c.dataset.n === nPics)); q("#ts_art").textContent = artLabel(); };
  qa("#ts_npics .tschip").forEach(c => c.onclick = () => { if (q("#ts_art").disabled) return; nPics = +c.dataset.n; markN(); });
  q("#ts_art").onclick = () => (nPics === 1 ? drawOne() : drawMany());
  markN();
  if (inf.slots && inf.slots.length) showSlots(inf);          // pictures that were drawn when the video was made (the 3-picture setting)
  mark(); draw();
}

