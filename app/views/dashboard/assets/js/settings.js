/* Settings. */
"use strict";
/* ------------------------------------------------------------ settings */
async function settings() {
  const isOwner = ME.role === "owner";
  const SECTIONS = [
    {id: "prefs", icon: "user", title: "My preferences",
     desc: "Your narrator, how the original audio is handled, where your approval emails go, and your password."},
    {id: "yt", icon: "videos", title: "YouTube",
     desc: "Connect your own YouTube channel. The studio then uploads your videos there for you, using your own channel's permission."},
    {id: "conn", icon: "key", title: "Accounts & keys",
     desc: "The keys that let the studio find clips, write commentary and sign off on videos. Secrets are stored on this computer only and never shown again.",
     keys: ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "YOUTUBE_API_KEY", "GEMINI_API_KEY", "GEMINI_MODEL", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_RESEARCH_MODEL", "TITLE_AI", "ANTHROPIC_TITLE_MODEL", "RESEARCH_PROVIDER", "TAVILY_API_KEY", "BRAVE_API_KEY", "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "LLM_SPLIT", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "YT_DAILY_UPLOADS", "YT_DAILY_UNITS", "CONTACT_EMAIL"],
     status: ["TWITCH_CLIENT_SECRET", "GEMINI_API_KEY"]},
    {id: "ytx", icon: "videos", title: "YouTube access",
     desc: "YouTube refuses many cloud servers (\"Sign in to confirm you're not a bot\"). The lasting fix is a proxy with a home-type address: paste it here, then press Test."},
    {id: "pricing", icon: "usage", title: "Pricing & costs",
     desc: "What the platforms charge you for each model, what one studio token is worth, what members pay, and what a video earns you. The same prices and costs as the Users and Reports pages."},
    {id: "aud", icon: "globe", title: "Audience & clips",
     desc: "The studio-wide defaults: what members get until they choose their own creator countries and languages, how live streams are watched, and the safety settings.",
     keys: ["CLIP_COUNTRIES", "CLIP_LANGUAGES", "SAFE_MODE", "DEFAULT_AUDIO_MODE", "TTS_VOICE", "LIVE_WATCH_MINUTES", "LIVE_STREAMS", "SOUND_PEAKS", "AI_THUMBNAILS", "AI_IMAGE_PROVIDER", "THUMB_TEXT", "THUMB_REVIEW", "SAFETY_AI_FRAMES", "SAFETY_AI_WIDTH", "SAFETY_FINAL_AI"]},
    {id: "clip", icon: "clips", title: "What to clip",
     desc: "Choose which kinds of moments the clipper looks for, add your own ideas, and say what it must never clip. The AI is given exactly these instructions."},
    {id: "audme", icon: "globe", title: "Creators & languages",
     desc: "Choose which creators' clips you want: the country they live in and the language of their streams. Every account sets its own, and it only applies to your own videos."},
    {id: "trend", icon: "clips", title: "Trending mode",
     desc: "Make your videos from what is trending right now: the studio looks at the game first, ranks clips and videos by how fast they are growing and clips from the fastest risers. It costs a little extra per video. Your choice is the default on the Create page and is used for your scheduled videos."},
    {id: "growth", icon: "usage", title: "Protection and growth",
     desc: "Keep your channel safe from reused-content problems, choose how your commentary sounds, and let the studio learn from your YouTube results and watch for clips that take off."},
    {id: "saver", icon: "usage", title: "AI saver",
     desc: "Make the AI cost fewer tokens for your own videos: short answers, a limit for each video, pictures read at low resolution, and a memory so the same clip is never analysed twice. It is off until you switch it on. Every account chooses for itself."},
    {id: "src", icon: "clips", title: "Clip sources",
     desc: "Choose where your videos look for clips: YouTube and / or Twitch. Every account sets its own, and it only applies to your own videos."},
    {id: "mail", icon: "mail", title: "Email alerts",
     desc: "Get an email when a video is uploaded, with Approve and Decline buttons. Failed scheduled runs are emailed too.",
     keys: ["SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM", "NOTIFY_TO", "PUBLIC_BASE_URL"],
     status: ["SMTP_HOST"]},
    {id: "tpl", icon: "mail", title: "Email templates",
     desc: "Change how the emails members receive look and read: the subject, heading, message, button and footer. Use one template for all emails, or give a kind of email its own."},
    {id: "airoute", icon: "key", title: "AI models",
     desc: "Choose which AI does each job and which one takes over if it fails: the provider and the model for every job, from titles to the safety review."},
    {id: "music", icon: "music", title: "Music",
     desc: "Royalty-free tracks used under the AI commentary. Only use tracks you have the licence for (for example the YouTube Audio Library)."},
  ];
  const TABGROUP = {prefs: 0, yt: 0, src: 0, audme: 0, clip: 0, saver: 0, trend: 0, growth: 0, conn: 1, airoute: 1, ytx: 1, aud: 1, pricing: 1, mail: 2, tpl: 2, music: 2};
  const TABHEAD = ["My account", "The studio (owner)", "Email and files (owner)"];
  const GROUPS = {   // [title, hint, [keys], opened?]
    conn: [["Find clips", "Twitch and YouTube. Needed for clips and live streams.", ["TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET", "YOUTUBE_API_KEY"], true],
           ["AI that writes", "Titles, descriptions and commentary.", ["GEMINI_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY", "TITLE_AI"], true],
           ["Best thumbnails", "FLUX on Cloudflare draws the Best thumbnail level.", ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"], true],
           ["Story narrator with feelings (optional)", "Azure Speech makes the narrator of story videos sound scared, sad or excited. Without it the free voice is used.", ["AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION"], false],
           ["Research search (optional)", "Only for the clipping research.", ["RESEARCH_PROVIDER", "TAVILY_API_KEY", "BRAVE_API_KEY"], false],
           ["Members signing in with YouTube", "Google sign-in for members, and the daily upload allowance.", ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "YT_DAILY_UPLOADS", "YT_DAILY_UNITS", "CONTACT_EMAIL"], false],
           ["Advanced: model names", "Leave these alone unless a model is retired.", ["GEMINI_MODEL", "DEEPSEEK_MODEL", "ANTHROPIC_MODEL", "ANTHROPIC_RESEARCH_MODEL", "ANTHROPIC_TITLE_MODEL", "LLM_SPLIT"], false]],
    aud: [["Who the clips are from", "What members get until they choose their own.", ["CLIP_COUNTRIES", "CLIP_LANGUAGES"], true],
          ["Voice and sound", "The narrator, the creator's own audio, and listening for loud moments.", ["DEFAULT_AUDIO_MODE", "TTS_VOICE", "SOUND_PEAKS"], true],
          ["Thumbnails", "How the artwork is made.", ["AI_THUMBNAILS", "THUMB_PROMPT_AI", "THUMB_FACE", "AI_IMAGE_PROVIDER", "THUMB_TEXT", "THUMB_REVIEW"], true],
          ["Safety", "The safety check always runs. These only change how it looks.", ["SAFE_MODE", "SAFETY_AI_FRAMES", "SAFETY_AI_WIDTH", "SAFETY_FINAL_AI"], false],
          ["Live streams", "How live streams are watched.", ["LIVE_WATCH_MINUTES", "LIVE_STREAMS"], false]],
    mail: [["Mail server", "", ["SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USER", "SMTP_PASSWORD"], true],
           ["Who sends and who receives", "", ["SMTP_FROM", "NOTIFY_TO", "PUBLIC_BASE_URL"], true]]};
  const groupedFields = (sec, st) => {
    const have = sec.keys.filter(k => st[k]), used = new Set();
    const groups = (GROUPS[sec.id] || []).map(([t, hint, keys, open]) => { const ks = keys.filter(k => st[k]); ks.forEach(k => used.add(k)); return [t, hint, ks, open]; });
    const rest = have.filter(k => !used.has(k));
    if (rest.length) groups.push(["Other", "", rest, false]);
    return groups.filter(g => g[2].length).map(([t, hint, ks, open]) => {
      const set = ks.filter(k => !SELECTS[k] && st[k] && (st[k].secret ? st[k].set : st[k].value)).length, shown = ks.filter(k => !SELECTS[k]).length;
      return `<details class="fgrp" ${open ? "open" : ""}><summary>${t}${shown > 1 || ks.some(k => st[k].secret) ? `<span class="fgn">${set} of ${shown} filled in</span>` : ""}</summary>${hint ? `<div class="help fgd">${hint}</div>` : ""}<div class="fields">${ks.map(k => field(k, st[k])).join("")}</div>${t === "Best thumbnails" ? `<div class="row" style="padding:0 16px 16px;gap:12px;align-items:center;flex-wrap:wrap"><button type="button" id="bt_test" class="pri">Test Best thumbnails now</button><span class="muted" id="bt_res">Save the keys first: the test uses what is saved.</span></div>` : ""}</details>`;
    }).join("");
  };
  if (!isOwner) SECTIONS.splice(0, SECTIONS.length, ...SECTIONS.filter(x => ["prefs", "yt", "clip", "audme", "src", "saver", "trend", "growth"].includes(x.id)));   // members never see server-wide settings
  const META = {
    TWITCH_CLIENT_ID: ["Twitch client ID", "Free at dev.twitch.tv/console. Needed for Twitch clips and live streams."],
    TWITCH_CLIENT_SECRET: ["Twitch client secret", ""],
    YOUTUBE_API_KEY: ["YouTube Data API key (optional)", "Better search results and channel countries. Works without it."],
    GEMINI_API_KEY: ["Gemini API key", "Writes titles, descriptions and the commentary, and plans the Best thumbnails."],
    CLOUDFLARE_ACCOUNT_ID: ["Cloudflare account ID", "Needed for the Best thumbnail level (FLUX draws it). dash.cloudflare.com -> AI -> Workers AI -> Use REST API: the Account ID is shown there."],
    AZURE_SPEECH_KEY: ["Azure Speech key", "portal.azure.com -> your Speech resource -> Keys and Endpoint -> KEY 1. About 500,000 characters a month are free (Free F0 tier). Saved only on this computer."],
    AZURE_SPEECH_REGION: ["Azure Speech region", "From the same page, for example westeurope or eastus (lower case, no spaces)."],
    CLOUDFLARE_API_TOKEN: ["Cloudflare API token", "Create it on the same page with 'Create a Workers AI API token'. About 170 thumbnails a day are free, then a fraction of a cent each. It is saved only on this computer."],
    GEMINI_MODEL: ["Gemini model", "Leave as is unless a model is retired."],
    ANTHROPIC_API_KEY: ["Claude API key", "Optional. Used to write titles and descriptions when Claude is the chosen writer, and for the clipping research. Get one at console.anthropic.com. It is saved only on this computer."],
    ANTHROPIC_RESEARCH_MODEL: ["Claude model for research", "Optional. The clipping research can use a stronger model than thumbnails. Leave empty to use the Claude model above. Web search must be switched on for your Anthropic account."],
    TITLE_AI: ["AI that writes titles and descriptions", "Titles decide whether people click, so a stronger writer is worth the few cents. Auto: Claude when you have a Claude key, else Gemini, else DeepSeek (or the choice you made under 'How to share the work'). The others stay as backup."],
    ANTHROPIC_TITLE_MODEL: ["Claude model for titles", "Optional. Leave empty to use the Claude model above. A larger model costs more per title."],
    TAVILY_API_KEY: ["Search key: Tavily (for DeepSeek research)", "Optional. DeepSeek cannot browse the web, so it needs a search service to find pages. Tavily has a free plan (app.tavily.com). Gemini is not needed."],
    BRAVE_API_KEY: ["Search key: Brave Search (alternative)", "Optional. Used only when no Tavily key is set. Brave Search API has a free plan (brave.com/search/api)."],
    RESEARCH_PROVIDER: ["AI for clipping research", "Which AI does the research by default. Claude and Gemini search the web themselves. DeepSeek cannot browse, so it writes the searches, a search service finds the pages (a free Tavily or Brave key, below), and DeepSeek reads them. Gemini is not needed. You can also pick per research on the Research page."],
    ANTHROPIC_MODEL: ["Claude model","Used for thumbnails and everything else Claude does. The list is every model your Claude key can use. A larger model gives better results at a higher price. Remember to enter its rates under Reports."],
    DEEPSEEK_API_KEY: ["DeepSeek API key", "Optional. DeepSeek writes the commentary and reads transcripts, so Gemini's free limit lasts longer. Get one at platform.deepseek.com."],
    DEEPSEEK_MODEL: ["DeepSeek model", "deepseek-chat is the cheap, fast one."],
    LLM_SPLIT: ["How to share the work", "Balanced: DeepSeek writes and reads, Gemini does titles and scoring. Each is the other's backup."],
    GOOGLE_CLIENT_ID: ["Google client ID (YouTube sign-in)", "From Google Cloud Console -> APIs & Services -> Credentials -> OAuth client (Web application). Members use it to connect their channels."],
    GOOGLE_CLIENT_SECRET: ["Google client secret", ""],
    YT_DAILY_UPLOADS: ["YouTube uploads allowed per day", "100 by default (Google counts uploads on their own). Raise it only after Google approves more; see the Quotas page in Google Cloud Console."],
    YT_DAILY_UNITS: ["YouTube daily pool (units)", "10000. Thumbnails and publishing use 50 units each from this pool; uploads do not."],
    CONTACT_EMAIL: ["Contact email", "Shown in video descriptions."],
    CLIP_COUNTRIES: ["Default creator countries for members", "Country codes separated by commas. What a member gets until they choose their own under Settings → Creators & languages. The owner starts with all countries."],
    CLIP_LANGUAGES: ["Default stream languages for members", "Language codes, for example en,de,fr. What a member gets until they choose their own. The owner starts with all languages."],
    LIVE_WATCH_MINUTES: ["Live scan: minutes to watch", "Longer finds better moments but takes more time per run."],
    LIVE_STREAMS: ["Live scan: streams at once", "How many live streams are watched together."],
    SOUND_PEAKS: ["Listen to the video to find moments", "On: the studio also listens to the sound of a video (shouting, laughing, a loud reaction after a quiet part) and uses those moments next to the captions and YouTube's most-replayed curve. It downloads only the sound (about 6 MB for 20 minutes) and adds roughly 30 seconds per video. Off: captions and replays only."],
    SAFE_MODE: ["Skip sexual / adult content", "Screens every clip and finished video for nudity, sexual and suggestive content. Keep this on."],
    DEFAULT_AUDIO_MODE: ["Original audio", "Applies to every automatic and manual video unless you choose otherwise on the Create page."],
    TTS_VOICE: ["Narrator voice", "Who reads the AI commentary. You can also choose one per video on the Create page."],
    AI_THUMBNAILS: ["AI thumbnails (on / off)", "Creates artwork for each thumbnail. The picture prompt is a description of the scene (game, action, mood): it never contains names, links or your title as written."],
    THUMB_FACE: ["Streamer's face from the webcam", "When a video has a face camera (a face that stays in one place), the sharpest and most expressive frame of that face is cut out and placed on the thumbnail in a corner free of the headline. No webcam, no face: nothing changes. Members can also switch it off for themselves. It uses OpenCV on your server: no AI service, no tokens."],
    THUMB_PROMPT_AI: ["Write a new picture prompt for every thumbnail", "On: an AI (DeepSeek first, Gemini as backup) reads the game, the kind of video and what happens in the clip and writes a prompt made for this scene, for both Better and Best. Off: one fixed template with the game name (saves a few AI tokens)."],
    SAFETY_AI_FRAMES: ["Safety review: frames per clip", "How many frames Gemini looks at per clip (3-12). 6 is the default; more frames catch more but cost more tokens."],
    SAFETY_AI_WIDTH: ["Safety review: frame width (px)", "Size of each frame sent to Gemini (256-768). 384 is the default; bigger frames cost more tokens."],
    SAFETY_FINAL_AI: ["Safety review of the finished video", "Off: the clips were already reviewed, so the finished video gets only the free checks (cheaper). On: Gemini reviews it a second time."],
    THUMB_TEXT: ["Best thumbnails: who writes the headline", "FLUX writes it into the picture (one step, but a word is sometimes misspelled). Or the studio writes it on top of FLUX's picture (always spelled right, in the member's own style and font)."],
    THUMB_REVIEW: ["Best thumbnails: Gemini checks the result", "On: Gemini looks at each finished Best thumbnail once and, if the headline is misspelled or hard to read, FLUX draws it again once. Costs a few AI tokens and sometimes one more picture."],
    AI_IMAGE_PROVIDER: ["Better level: AI image service", "free = keyless free service. gemini = Google image models (needs billing enabled on your Gemini key)."],
    SMTP_HOST: ["SMTP server", "Gmail: smtp.gmail.com"],
    SMTP_PORT: ["SMTP port", "587 for STARTTLS, 465 for SSL."],
    SMTP_SECURITY: ["Security", ""],
    SMTP_USER: ["SMTP username", "Usually your email address."],
    SMTP_PASSWORD: ["SMTP password", "Gmail needs an App Password, not your normal password."],
    SMTP_FROM: ["Send from", "The sender address."],
    NOTIFY_TO: ["Send notifications to", "Where the alerts and approval emails go."],
    PUBLIC_BASE_URL: ["Address used in the Approve link", "Leave as is unless you reach this page from another device."],
  };
  const SECURITY = [["starttls", "STARTTLS (port 587)"], ["ssl", "SSL/TLS (port 465)"], ["none", "None (not recommended)"]];
  const AUDIO_OPTS = [["replace", "Mute it and replace with AI commentary + music (safest for copyright)"], ["bed", "Keep it, quietly under the music"], ["original", "Keep it exactly as is (high copyright risk)"]];
  let voices = []; try { voices = await api("/api/voices"); } catch (e) {}
  const VOICE_OPTS = [["random", "Random: a different narrator for each video"]].concat(voices.map(v => [v.id, `${v.name} · ${v.locale.replace("en-", "")} · ${v.gender.toLowerCase()}`]));
  let cmods = []; if (isOwner) { try { cmods = (await api("/api/claude/models")).models; } catch (e) {} }
  const CM = cmods.map(m => [m.id, m.name === m.id ? m.id : `${m.name} (${m.id})`]);
  const SELECTS = {TITLE_AI: [["auto", "Auto (the strongest writer you have a key for)"], ["claude", "Claude"], ["gemini", "Gemini"], ["deepseek", "DeepSeek"]], ANTHROPIC_TITLE_MODEL: [["", "Same as the Claude model above"]].concat(CM), THUMB_PROMPT_AI: [["on", "On (a new prompt for each thumbnail)"], ["off", "Off (the fixed template)"]], THUMB_FACE: [["on", "On (use the webcam face when the video has one)"], ["off", "Off (never)"]], THUMB_TEXT: [["flux", "FLUX writes the headline in the picture"], ["code", "The studio writes the headline on top"]], THUMB_REVIEW: [["off", "Off"], ["on", "On (Gemini checks each Best thumbnail once)"]], SOUND_PEAKS: [["on", "On (listen to the video)"], ["off", "Off (captions and replays only)"]], RESEARCH_PROVIDER: [["claude", "Claude (web search)"], ["gemini", "Gemini (Google Search)"], ["deepseek", "DeepSeek (needs a free Tavily or Brave search key)"]], ANTHROPIC_MODEL: [["", "Default (claude-sonnet-5-5)"]].concat(CM), ANTHROPIC_RESEARCH_MODEL: [["", "Same as the Claude model above"]].concat(CM), LLM_SPLIT: [["balanced", "Balanced (recommended)"], ["deepseek", "DeepSeek first for everything"], ["gemini", "Gemini first for everything"]], TTS_VOICE: VOICE_OPTS, SMTP_SECURITY: SECURITY, DEFAULT_AUDIO_MODE: AUDIO_OPTS, SAFE_MODE: [["on", "On (recommended)"], ["off", "Off"]], AI_THUMBNAILS: [["on", "On"], ["off", "Off"]], SAFETY_FINAL_AI: [["off", "Off (cheaper, recommended)"], ["on", "On (Gemini reviews it twice)"]], AI_IMAGE_PROVIDER: [["free", "Free service (no key)"], ["gemini", "Google Gemini (needs billing)"]]};
  const field = (k, v) => {
    const [label, help] = META[k] || [k, ""];
    if (SELECTS[k] && v.value && !SELECTS[k].some(o => o[0] === v.value)) SELECTS[k].push([v.value, v.value]);
    const input = SELECTS[k]
      ? `<select data-k="${k}">${SELECTS[k].map(([o, t]) => `<option value="${o}" ${v.value === o ? "selected" : ""}>${t}</option>`).join("")}</select>` + (k === "TTS_VOICE" ? `<button type="button" data-prev style="margin-top:8px">▶ Listen to this voice</button>` : "")
      : `<input data-k="${k}" ${v.secret ? `type="password" autocomplete="off" placeholder="${v.set ? "Saved (leave blank to keep)" : "Not set"}"` : `value="${esc(v.value)}"`}>`;
    const chip = v.secret && v.set ? `<span class="keyhint st ok">Saved</span>` : "";
    return `<div><label>${label}${chip}</label>${input}${help ? `<div class="help">${help}</div>` : ""}</div>`;
  };
  $("#main").innerHTML = `<h1>Settings</h1><p class="lede">${SUBS.settings}</p>
    <div class="settings"><div class="stabs" id="stabs"></div><div id="spanes"></div></div>`;
  const state = {tab: isOwner ? "conn" : "prefs"};
  const paintTabs = (s) => {
    let lastHead = -1;
    $("#stabs").innerHTML = SECTIONS.slice().sort((a, b) => (TABGROUP[a.id] ?? 1) - (TABGROUP[b.id] ?? 1)).map(sec => {
      const g = TABGROUP[sec.id] ?? 1, head = (isOwner && g !== lastHead) ? `<div class="stabh">${TABHEAD[g]}</div>` : ""; lastHead = g;
      const ok = sec.status ? sec.status.every(k => s[k] && (s[k].secret ? s[k].set : s[k].value)) : null;
      return head + `<button data-t="${sec.id}" class="${state.tab === sec.id ? "on" : ""}">${svg(sec.icon)}<span>${sec.title}</span>` +
        (ok === null ? "" : `<span class="st ${ok ? "ok" : "warn"}">${ok ? "Ready" : "Set up"}</span>`) + `</button>`;
    }).join("");
    document.querySelectorAll("#stabs button").forEach(b => b.onclick = () => {
      state.tab = b.dataset.t; document.querySelectorAll("#stabs button").forEach(x => x.classList.toggle("on", x === b));
      document.querySelectorAll(".spane").forEach(p => p.hidden = p.dataset.p !== state.tab);
    });
  };
  const saveAll = guard(async () => {
    const body = {}; document.querySelectorAll("#spanes input[data-k], #spanes select[data-k], #spanes textarea[data-k]").forEach(i => body[i.dataset.k] = i.value);
    await api("/api/settings", {method: "PUT", body}); toast("Settings saved"); loadS();
  });
  const loadS = guard(async () => {
    const s = isOwner ? await api("/api/settings") : {};
    const known = new Set(SECTIONS.flatMap(x => x.keys || []));
    const conn = SECTIONS.find(x => x.id === "conn");   // (YouTube lives in its own section) if (conn) conn.keys = conn.keys.concat(Object.keys(s).filter(k => !known.has(k)));   // any future setting still shows up
    paintTabs(s);
    $("#spanes").innerHTML = SECTIONS.map(sec => `<div class="card spane" data-p="${sec.id}" ${state.tab === sec.id ? "" : "hidden"}>
      <h2>${svg(sec.icon).replace("<svg", '<svg width="18" height="18" style="stroke:currentColor;fill:none;stroke-width:1.8"')}${sec.title}</h2><p class="secdesc">${sec.desc}</p>
      ${sec.id === "audme" ? `<div id="audcfg" class="muted">Loading…</div>` : sec.id === "src" ? `<div id="srccfg" class="muted">Loading…</div>` : sec.id === "saver" ? `<div id="savercfg" class="muted">Loading…</div>` : sec.id === "growth" ? `<div id="growthcfg" class="muted">Loading…</div>` : sec.id === "trend" ? `<div id="trendcfg" class="muted">Loading…</div>` : sec.id === "pricing" ? `<div id="pricecfg" class="muted">Loading…</div>` : sec.id === "prefs" ? `<div id="prefscfg" class="muted">Loading…</div>` : sec.id === "yt" ? `<div id="ytcfg" class="muted">Loading…</div>` : sec.id === "ytx" ? `<div id="ytxcfg" class="muted">Loading…</div>` : sec.id === "tpl" ? `<div id="tplcfg" class="muted">Loading…</div>` : sec.id === "airoute" ? `<div id="airoutecfg" class="muted">Loading…</div>` : sec.id === "clip" ? `<div id="clipcfg" class="muted">Loading…</div>` : sec.keys ? `${GROUPS[sec.id] || sec.id === "conn" ? groupedFields(sec, s) : `<div class="fields">${sec.keys.filter(k => s[k]).map(k => field(k, s[k])).join("")}</div>`}
        <div class="savebar"><button class="pri" data-save>Save changes</button>${sec.id === "mail" ? `<button id="mt">Send test email</button><span class="muted" id="mres"></span>` : ""}
        <span class="muted">Stored in the local .env file.</span></div>`
      : `<div class="row"><input type="file" id="mf" accept=".mp3,.wav,.m4a,.ogg,.flac" class="grow"><button id="mu" class="pri">Upload track</button></div><div id="mlist" style="margin-top:14px"></div>`}
    </div>`).join("");
    document.querySelectorAll("[data-save]").forEach(b => b.onclick = saveAll);
    document.querySelectorAll("[data-prev]").forEach(b => b.onclick = () => {
      const v = document.querySelector('[data-k="TTS_VOICE"]').value;
      if (!v || v === "random") { toast("Pick one voice to listen to it"); return; }
      b.textContent = "Loading…"; const a = new Audio("/api/voices/preview?voice=" + encodeURIComponent(v));
      a.onplaying = () => { b.textContent = "▶ Listen to this voice"; }; a.onerror = () => { b.textContent = "▶ Listen to this voice"; toast("Could not play the sample", true); };
      a.play().catch(() => { b.textContent = "▶ Listen to this voice"; });
    });
    if ($("#mt")) $("#mt").onclick = guard(async () => {
      $("#mres").textContent = "Saving and sending…";
      const body = {}; document.querySelectorAll("#spanes input[data-k], #spanes select[data-k], #spanes textarea[data-k]").forEach(i => body[i.dataset.k] = i.value);
      await api("/api/settings", {method: "PUT", body});
      try { const r = await api("/api/email/test", {method: "POST"}); $("#mres").innerHTML = `<span style="color:var(--ok)">✔</span> ${esc(r.message)}`; }
      catch (e) { $("#mres").innerHTML = `<span style="color:var(--bad)">✖</span> ${esc(e.message)}`; }
    });
    loadClipCfg(); loadPrefs(); loadYt(); loadAud(); loadSrc(); loadSaver(); loadTrend(); loadGrowth();
    if (isOwner && $("#bt_test")) {
      api("/api/thumb-best").then(st => { if (st.last_error && $("#bt_res")) $("#bt_res").innerHTML = `<span style="color:var(--bad)">✖ The last Best thumbnail fell back to Better: ${esc(st.last_error)}</span>`; else if (st.last_ok && $("#bt_res")) $("#bt_res").innerHTML = `<span style="color:var(--ok)">✔ The last Best thumbnail worked.</span>`; }).catch(() => {});
      $("#bt_test").onclick = guard(async () => {
        $("#bt_res").textContent = "Testing (up to a minute)…"; $("#bt_test").disabled = true;
        try { const r = await api("/api/thumb-best/test", {method: "POST"}); $("#bt_res").innerHTML = `<span style="color:var(--${r.ok ? "ok" : "bad"})">${r.ok ? "✔" : "✖"}</span> ${esc(r.message)}`; }
        finally { $("#bt_test").disabled = false; }
      });
    } if (isOwner) { loadPricing(); loadYtx(); loadTpl(); loadAiRoutes(); }
    if ($("#mu")) {
      $("#mu").onclick = guard(async () => {
        const f = $("#mf").files[0]; if (!f) throw new Error("Choose a file first");
        await api("/api/music?name=" + encodeURIComponent(f.name), {method: "POST", body: f, raw: true}); toast("Uploaded"); $("#mf").value = ""; loadM();
      });
      await loadM();
    }
  });
  /* ---- AI models (owner): which AI does which job, and its backup */
  const loadAiRoutes = guard(async () => {
    const box = $("#airoutecfg"); if (!box) return;
    const o = await api("/api/ai-routes");
    if (!box.isConnected) return;
    box.className = "";
    const provOpts = (sel, none, vision) => (none ? `<option value="" ${sel ? "" : "selected"}>None (no backup)</option>` : "") +
      o.providers.filter(p => !vision || p.id === "gemini").map(p => `<option value="${p.id}" ${sel === p.id ? "selected" : ""}>${esc(p.name)}${p.ready ? "" : " (no key saved)"}</option>`).join("");
    const lists = Object.entries(o.models).map(([k, v]) => `<datalist id="dl_${k}">${v.map(m => `<option value="${esc(m)}"></option>`).join("")}</datalist>`).join("");
    const row = t => {
      const p = t.primary || {provider: "gemini", model: ""}, f = t.fallback || {provider: "", model: ""};
      const model = (role, x) => `<input data-r="${role}_model" list="dl_${x.provider || "gemini"}" value="${esc(x.model || "")}" placeholder="${esc(o.defaults[x.provider || "gemini"])} (default)" ${role === "f" && !x.provider ? "disabled" : ""}>`;
      return `<details class="fgrp" data-task="${t.id}" ${t.custom ? "open" : ""}><summary>${esc(t.label)}<span class="fgn" data-r="state">${t.custom ? "your choice" : "built-in order"}</span></summary>
        <div class="help fgd">${esc(t.desc)}${t.vision ? " Only Gemini can look at pictures." : ""}</div>
        <div class="fields">
          <div><label>First choice</label><select data-r="p_provider">${provOpts(p.provider, false, t.vision)}</select></div>
          <div><label>Its model</label>${model("p", p)}</div>
          <div><label>Backup, if the first fails</label><select data-r="f_provider">${provOpts(f.provider, true, t.vision)}</select></div>
          <div><label>Its model</label>${model("f", f)}</div>
        </div>
        <div class="row" style="padding:0 16px 16px;gap:10px;flex-wrap:wrap;align-items:center"><button type="button" data-r="test">Test the saved choice</button>${t.custom ? `<button type="button" data-r="reset">Back to the built-in order</button>` : ""}<span class="muted" data-r="msg"></span></div></details>`;
    };
    box.innerHTML = `<div class="audnote">Choose which AI does each job, and which one takes over if it fails, for example titles on DeepSeek chat with Gemini flash lite as the backup. A model you leave empty uses that AI's default model (Accounts &amp; keys → Advanced). A job you do not change keeps the built-in order. Prices are per AI, not per model: change them in Pricing &amp; costs.</div>
      ${lists}${o.tasks.map(row).join("")}
      <div class="row" style="gap:12px;align-items:center;margin-top:14px;flex-wrap:wrap"><button class="pri" id="air_save">Save AI choices</button><button type="button" id="air_reset">Back to the built-in order for everything</button><span class="muted" id="air_msg"></span></div>`;
    const dirty = new Set();
    const rowOf = el => el.closest("details[data-task]");
    box.querySelectorAll("details[data-task]").forEach(d => {
      const q = r => d.querySelector(`[data-r="${r}"]`);
      for (const role of ["p", "f"]) {
        q(role + "_provider").onchange = () => {
          const v = q(role + "_provider").value, m = q(role + "_model");
          m.disabled = !v; m.setAttribute("list", "dl_" + (v || "gemini")); m.placeholder = (v ? o.defaults[v] : "") + (v ? " (default)" : ""); if (!v) m.value = "";
          dirty.add(d.dataset.task); q("state").textContent = "changed: not saved yet";
        };
        q(role + "_model").oninput = () => { dirty.add(d.dataset.task); q("state").textContent = "changed: not saved yet"; };
      }
      q("test").onclick = guard(async () => {
        q("msg").textContent = "Testing…";
        const r = await api("/api/ai-routes/test", {method: "POST", body: {task: d.dataset.task}});
        q("msg").innerHTML = r.results.map(x => `<span style="color:var(--${x.ok ? "ok" : "bad"})">${x.ok ? "✔" : "✖"}</span> ${x.role === "primary" ? "First" : "Backup"}: ${esc(x.provider)} ${esc(x.model)} - ${esc(x.message)}`).join("<br>");
      });
      if (q("reset")) q("reset").onclick = guard(async () => { await api("/api/ai-routes?task=" + encodeURIComponent(d.dataset.task), {method: "DELETE"}); toast("Back to the built-in order"); loadAiRoutes(); });
    });
    $("#air_save").onclick = guard(async () => {
      if (!dirty.size) { $("#air_msg").textContent = "Nothing was changed."; return; }
      const routes = {};
      dirty.forEach(id => {
        const d = box.querySelector(`details[data-task="${id}"]`), g = r => d.querySelector(`[data-r="${r}"]`).value.trim();
        routes[id] = {primary: {provider: g("p_provider"), model: g("p_model")}, fallback: g("f_provider") ? {provider: g("f_provider"), model: g("f_model")} : null};
      });
      await api("/api/ai-routes", {method: "PUT", body: {routes}}); toast("AI choices saved"); loadAiRoutes();
    });
    $("#air_reset").onclick = guard(async () => { if (!confirm("Go back to the built-in order for every job?")) return; await api("/api/ai-routes", {method: "DELETE"}); toast("Back to the built-in order"); loadAiRoutes(); });
  });
  /* ---- Email templates (owner): how the emails members receive look and read */
  const loadTpl = guard(async () => {
    const box = $("#tplcfg"); if (!box) return;
    const o = await api("/api/email-templates");
    if (!box.isConnected) return;
    box.classList.remove("muted");
    const q = s => box.querySelector(s);
    box.innerHTML = `
      <div class="field"><label>Which email</label><select id="tpl_s"><option value="default">All emails (the standard template)</option>${o.kinds.map(k => `<option value="${esc(k.id)}">Only: ${esc(k.name)}</option>`).join("")}</select>
        <div class="help">Change the wording for all emails, or give one kind of email its own wording. A field you leave empty uses the standard template.</div></div>
      <div class="help" style="margin:8px 0 14px">Words you can use (they are filled in when the email is sent): ${o.placeholders.map(p => `<code>${esc(p)}</code>`).join(" ")}. Every member who gets an email pays a small token fee, set in Pricing &amp; costs.</div>
      <div id="tpl_f"></div>
      <div class="row" style="margin-top:14px;gap:10px;flex-wrap:wrap"><button class="pri" id="tpl_sv">Save this template</button><button id="tpl_rs">Back to the standard wording</button><button id="tpl_t">Send me a test email</button><span class="muted" id="tpl_r"></span></div>
      <h3 style="margin:18px 0 6px">Preview</h3><div class="help" id="tpl_sub" style="margin-bottom:6px"></div>
      <iframe id="tpl_pv" sandbox="" style="width:100%;height:300px;border:1px solid var(--line);border-radius:10px;background:#fff"></iframe>`;
    const scope = () => q("#tpl_s").value;
    const mine = () => scope() === "default" ? (o.default || {}) : ((o.by_kind || {})[scope()] || {});
    const paint = () => {
      const inherit = scope() === "default" ? o.standard : {...o.standard, ...(o.default || {})};
      q("#tpl_f").innerHTML = o.fields.map(f => `<div class="field"><label>${esc(f.label)}</label>${f.big
        ? `<textarea data-tf="${f.k}" rows="3" maxlength="${f.max}" placeholder="${esc(inherit[f.k] || "")}">${esc(mine()[f.k] || "")}</textarea>`
        : `<input data-tf="${f.k}" maxlength="${f.max}" value="${esc(mine()[f.k] || "")}" placeholder="${esc(inherit[f.k] || "")}">`}<div class="help">${esc(f.help)}</div></div>`).join("");
      q("#tpl_f").querySelectorAll("[data-tf]").forEach(i => i.oninput = preview);
      preview();
    };
    const fields = () => { const r = {}; q("#tpl_f").querySelectorAll("[data-tf]").forEach(i => r[i.dataset.tf] = i.value); return r; };
    let timer = null;
    const preview = () => { clearTimeout(timer); timer = setTimeout(async () => {
      try { const r = await api("/api/email-templates/preview", {method: "POST", body: {scope: scope(), fields: fields()}}); q("#tpl_sub").innerHTML = "Subject: <b>" + esc(r.subject) + "</b>"; q("#tpl_pv").srcdoc = r.html; }
      catch (e) { q("#tpl_sub").textContent = e.message; }
    }, 250); };
    q("#tpl_s").onchange = paint;
    q("#tpl_sv").onclick = guard(async () => { const r = await api("/api/email-templates", {method: "PUT", body: {scope: scope(), fields: fields()}}); Object.assign(o, r); toast("Template saved"); paint(); });
    q("#tpl_rs").onclick = guard(async () => { const r = await api("/api/email-templates?scope=" + encodeURIComponent(scope()), {method: "DELETE"}); Object.assign(o, r); toast("Back to the standard wording"); paint(); });
    q("#tpl_t").onclick = guard(async () => {
      q("#tpl_r").textContent = "Sending…";
      try { const r = await api("/api/email-templates/test", {method: "POST", body: {scope: scope(), fields: fields()}}); q("#tpl_r").innerHTML = `<span style="color:var(--ok)">✔</span> ${esc(r.message)}`; }
      catch (e) { q("#tpl_r").innerHTML = `<span style="color:var(--bad)">✖</span> ${esc(e.message)}`; }
    });
    paint();
  });
  /* ---- YouTube access (owner): the proxy that lets YouTube talk to this server, and a Test button */
  const loadYtx = guard(async () => {
    const box = $("#ytxcfg"); if (!box) return;
    const st = await api("/api/yt-access");
    if (!box.isConnected) return;                       // the page was drawn again while this was loading: the new box loads itself
    const q = s => box.querySelector(s);
    const chip = (ok, yes, no) => `<span class="st ${ok ? "ok" : "warn"}">${ok ? yes : no}</span>`;
    box.classList.remove("muted");
    box.innerHTML = `
      <div class="row" style="gap:10px;flex-wrap:wrap;margin-bottom:12px">
        ${st.blocked ? `<span class="st warn">YouTube is refusing this server</span>` : st.last_ok ? `<span class="st ok">Working</span>` : `<span class="st">Not tested yet</span>`}
        ${chip(st.has_proxy, "Proxy: " + esc(st.proxy_host), "No proxy")}
        ${st.has_proxy && !st.proxy_ok_type ? `<span class="st warn">Not an http:// address</span>` : ""}
      </div>
      ${st.blocked && st.last_error ? `<div class="help" style="margin-bottom:12px">Last refusal: ${esc(st.last_error)}</div>` : ""}
      <h3 style="margin:14px 0 6px">A proxy with a home-type address</h3>
      <div class="help" style="margin-bottom:8px">YouTube trusts the addresses of real home internet connections and refuses most data-center servers, so the lasting fix is a proxy. Rent a <b>static residential ("ISP") proxy</b> from a proxy provider and paste its address below. Nothing has to be signed in, so nothing expires.</div>
      <div class="help" style="margin-bottom:8px">When you order: choose the <b>HTTP</b> protocol (SOCKS does not work for cutting clips), a country such as the United States, and allow this server's IP address in the provider's account if it offers that. The address looks like <code>http://user:password@host:port</code>. It is used for YouTube only and is stored on this server and never shown again.</div>
      <div class="row"><input type="password" autocomplete="off" id="ytx_p" class="grow" placeholder="${st.has_proxy ? "Saved (paste a new one to replace it)" : "http://user:password@host:port"}"><button id="ytx_ps" class="pri">Save proxy</button>${st.has_proxy ? `<button id="ytx_pr">Remove</button>` : ""}</div>
      <div class="row" style="margin-top:18px;gap:12px;align-items:center"><button id="ytx_t" class="pri">Test YouTube access now</button><span id="ytx_r" class="muted"></span></div>`;
    q("#ytx_ps").onclick = guard(async () => {
      const v = q("#ytx_p").value.trim(); if (!/^https?:\/\/\S+$/i.test(v)) throw new Error("The proxy must be an HTTP proxy: http://user:password@host:port (SOCKS does not work for cutting clips)");
      await api("/api/settings", {method: "PUT", body: {YTDLP_PROXY: v}}); toast("Proxy saved. Press Test."); loadYtx();
    });
    if (q("#ytx_pr")) q("#ytx_pr").onclick = guard(async () => { await api("/api/yt-access/proxy", {method: "DELETE"}); toast("Proxy removed"); loadYtx(); });
    q("#ytx_t").onclick = guard(async () => {
      q("#ytx_r").textContent = "Testing (up to a minute)…"; q("#ytx_t").disabled = true;
      try { const r = await api("/api/yt-access/test", {method: "POST"}); q("#ytx_r").innerHTML = `<span style="color:var(--${r.ok ? "ok" : "bad"})">${r.ok ? "✔" : "✖"}</span> ${esc(r.message)}`; loadYtx_status(r); }
      finally { q("#ytx_t").disabled = false; }
    });
  });
  const loadYtx_status = r => { if (r.ok) { const chip = document.querySelector("#ytxcfg .st"); if (chip) { chip.className = "st ok"; chip.textContent = "Working"; } } };
  /* ---- Pricing & costs (owner): what the platforms charge you, what a token is worth, what members pay, and what a video earns */
  const PX_COST_KEYS = ["gemini_in_per_1m", "gemini_out_per_1m", "deepseek_in_per_1m", "deepseek_out_per_1m", "claude_in_per_1m", "claude_out_per_1m", "claude_search_usd", "image_gemini_usd", "image_free_usd", "image_flux_usd", "token_usd"];
  const PX_PRICE_GROUPS = [
    ["AI text, per 1,000 AI tokens", [["gemini_per_1k", "Gemini (text and safety review)"], ["deepseek_per_1k", "DeepSeek (text)"], ["claude_per_1k", "Claude (titles)"]]],
    ["Thumbnail pictures, each", [["image_free", "Better level (free image service)"], ["image_flux", "Best level (FLUX; Gemini planning is charged on top)"], ["image_gemini", "Gemini picture (only if chosen as the Better image service)"]]],
    ["Parts that run on your own computer (0 = free)", [["tts_per_1k_chars", "Voice, per 1,000 characters"], ["whisper_per_min", "Captions, per minute of speech"], ["safety_local_per_clip", "Local safety check, per clip"]]],
    ["Costs of finding and making a video (charged only when a video is made)", [["search_per_video", "Finding the clip"], ["render_short", "Rendering a Short"], ["render_compilation", "Rendering a compilation"], ["server_per_video", "Server usage (every video made)"], ["trend_short", "Trending mode: Short"], ["trend_compilation", "Trending mode: compilation"]]],
    ["Searching for clips: every clip found", [["youtube_source", "YouTube clip"], ["twitch_source", "Twitch clip"], ["kick_source", "Kick clip"]]],
    ["Other actions", [["finder_scan", "Clip Finder scan"], ["editor_render", "Editor render"], ["research_run", "Research run"], ["email_send", "Each email sent to a member"], ["social_caption", "AI caption rewrite (Other platforms)"], ["story_script", "Story video: writing the script"], ["story_scene_video", "Story video: one scene made by AI video (costs real money)"], ["story_scene_motion", "Story video: one scene with camera movement"], ["storage_extra_gb_month", "Extra storage: per GB above the free part, per month"]]],
    ["Uploading to YouTube, each", [["upload_short", "Short"], ["upload_compilation", "Compilation"]]],
    ["Reserve taken when a video starts (the unused part comes back)", [["hold_short", "Short"], ["hold_compilation", "Compilation"]]],
    ["Members", [["signup_bonus", "Welcome gift (tokens)"], ["daily_uploads", "Uploads per member per day"]]]];
  const loadPricing = guard(async () => {
    const box = $("#pricecfg"); if (!box) return;
    const o = await api("/api/admin/price/overview"), C = o.catalog;
    box.className = "";
    const fmt = (n, p = 4) => { const x = +n; return Number.isFinite(x) ? String(+x.toFixed(p)) : ""; };
    const usd = n => n >= 1 ? "$" + (+n).toFixed(2) : n >= 0.01 ? "$" + (+n).toFixed(3) : "$" + (+n).toFixed(4);
    const ROWS = [
      {id: "gemini", title: "Gemini · AI text and safety review", kind: "text", plat: "gemini", use: "gemini", ik: "gemini_in_per_1m", ok: "gemini_out_per_1m"},
      {id: "deepseek", title: "DeepSeek · AI text", kind: "text", plat: "deepseek", use: "deepseek", ik: "deepseek_in_per_1m", ok: "deepseek_out_per_1m"},
      {id: "claude", title: "Claude · thumbnails and research", kind: "text", plat: "claude", use: "claude", ik: "claude_in_per_1m", ok: "claude_out_per_1m"},
      {id: "gimg", title: "Gemini · one picture", kind: "image", plat: "gemini", use: "gemini_image", pk: "image_gemini_usd"},
      {id: "csearch", title: "Claude · one web search", kind: "search", plat: "claude", pk: "claude_search_usd"}];
    const opts = r => C.filter(x => x.kind === r.kind && x.platform === r.plat);
    const label = x => `${x.name}${x.deprecated ? " (deprecated)" : ""}${x.verified ? "" : " *"}`;
    const same = (a, b) => Math.abs(+a - +b) < 1e-9;
    const startPick = r => {                                       // the model Settings uses, else the row whose price equals what is saved now
      const m = r.use && o.in_use[r.use] && o.in_use[r.use].match; if (m && opts(r).some(x => x.id === m)) return m;
      const c = o.costs; const hit = opts(r).find(x => r.kind === "text" ? same(x.in, c[r.ik]) && same(x.out, c[r.ok]) : same(x.per, c[r.pk]));
      return hit ? hit.id : "";
    };
    const mixTxt = p => { const m = o.mix[p]; return `${Math.round(100 * m.share_in)}% input${m.measured ? "" : " (usual figure, not measured yet)"}`; };
    box.innerHTML = `<div class="pxnote">Prices below were read from each platform's own price page on <b>${esc(o.checked)}</b>. They change, so every number can be edited. A <b>*</b> means it came from a summary: check it on the live page
        (<a href="${esc(o.sources.claude)}" target="_blank" rel="noopener noreferrer">Claude</a> · <a href="${esc(o.sources.gemini)}" target="_blank" rel="noopener noreferrer">Gemini</a> · <a href="${esc(o.sources.deepseek)}" target="_blank" rel="noopener noreferrer">DeepSeek</a>).
        This page edits the same prices and costs as the Users and Reports pages.</div>
      <h3 class="pxh"><span>1</span> What is one studio token worth?</h3>
      <div class="pxrow"><div class="pxf"><label>One token, in dollars</label><input data-px="token_usd" type="number" min="0.0001" step="0.001" value="${fmt(o.costs.token_usd, 6)}"></div>
        <div class="pxhint" id="px_tok"></div></div>
      <h3 class="pxh"><span>2</span> What the platforms charge you</h3>
      <div class="pxtbl nopk">${ROWS.map(r => `<div class="pxm" data-r="${r.id}"><div class="pxmh"><b>${esc(r.title)}</b><span class="pxuse" id="pxu_${r.id}"></span></div>
          <div class="pxmb"><div class="pxf grow"><label>Which model's price</label><select data-pxm="${r.id}"><option value="">My own numbers</option>${opts(r).map(x => `<option value="${esc(x.id)}">${esc(label(x))}</option>`).join("")}</select></div>
          ${r.kind === "text" ? `<div class="pxf"><label>Input, $ per 1M tokens</label><input data-px="${r.ik}" type="number" min="0" step="0.01" value="${fmt(o.costs[r.ik], 4)}"></div><div class="pxf"><label>Output, $ per 1M tokens</label><input data-px="${r.ok}" type="number" min="0" step="0.01" value="${fmt(o.costs[r.ok], 4)}"></div>`
            : `<div class="pxf"><label>$ each</label><input data-px="${r.pk}" type="number" min="0" step="0.001" value="${fmt(o.costs[r.pk], 5)}"></div>`}</div>
          <div class="pxinfo" id="pxi_${r.id}"></div></div>`).join("")}
        <div class="pxm"><div class="pxmh"><b>Free image service (Better level)</b></div><div class="pxmb"><div class="pxf"><label>$ each</label><input data-px="image_free_usd" type="number" min="0" step="0.001" value="${fmt(o.costs.image_free_usd, 5)}"></div></div></div>
        <div class="pxm"><div class="pxmh"><b>FLUX on Cloudflare (Best level)</b></div><div class="pxmb"><div class="pxf"><label>$ each thumbnail</label><input data-px="image_flux_usd" type="number" min="0" step="0.0001" value="${fmt(o.costs.image_flux_usd, 5)}"></div></div><div class="pxinfo">Free for about 170 thumbnails a day; after that about $0.0006 each. Gemini's planning is counted under Gemini above.</div></div></div>
      <h3 class="pxh"><span>3</span> What members pay (in tokens)</h3>
      <div class="pxhelper"><b>Set the AI and picture prices from my costs</b><span class="muted">Price = what the platform charges × (1 + margin) ÷ what one token is worth. Uses how your AI tokens split between input and output
          (Gemini ${mixTxt("gemini")}, DeepSeek ${mixTxt("deepseek")}, Claude ${mixTxt("claude")}). Nothing is saved until you press Save.</span>
        <div class="row" style="gap:10px;margin-top:8px"><div class="pxf"><label>Margin on top, %</label><input id="px_margin" type="number" min="0" max="10000" step="10" value="100" style="max-width:140px"></div><button type="button" id="px_fill">Fill in the prices</button><span class="muted" id="px_fillmsg"></span></div></div>
      ${PX_PRICE_GROUPS.map(([t, items], gi) => `<details class="fgrp" ${gi < 3 ? "open" : ""}><summary>${esc(t)}</summary><div class="fields">${items.map(([k, l]) => `<div><label>${esc(l)}</label><input data-pp="${k}" type="number" min="0" step="0.01" value="${fmt(o.pricing[k], 4)}"><div class="help" id="pph_${k}"></div></div>`).join("")}</div></details>`).join("")}
      <h3 class="pxh"><span>4</span> What one video earns you</h3>
      <div class="pxpreview" id="px_prev"></div>
      <div class="savebar"><button class="pri" id="px_save">Save prices and costs</button><button type="button" id="px_reset">Undo my changes</button><span class="muted" id="px_msg"></span></div>`;
    (() => {                                   // each numbered step folds away; the long "what the platforms charge you" list starts closed
      let cur = null;
      [...box.children].forEach(k => {
        if (k.matches("h3.pxh")) {
          cur = document.createElement("details"); cur.className = "fgrp fold"; cur.open = !/platforms charge/i.test(k.textContent);
          const sm = document.createElement("summary"); sm.innerHTML = k.innerHTML; cur.append(sm); box.replaceChild(cur, k);
        } else if (k.classList.contains("savebar")) cur = null;        // the Save button always stays in view
        else if (cur) cur.append(k);
      });
    })();
    /* ---- reading the form */
    const num = el => { const v = parseFloat(el.value); return Number.isFinite(v) ? v : 0; };
    const costs = () => { const c = {}; box.querySelectorAll("[data-px]").forEach(i => c[i.dataset.px] = num(i)); return c; };
    const prices = () => { const p = {}; box.querySelectorAll("[data-pp]").forEach(i => p[i.dataset.pp] = num(i)); return p; };
    const blend = (c, p, k) => (o.mix[p].share_in * c[k + "_in_per_1m"] + (1 - o.mix[p].share_in) * c[k + "_out_per_1m"]) / 1000;     // dollars per 1,000 AI tokens
    /* ---- the live explanations */
    const refresh = () => {
      const c = costs(), p = prices(), tu = c.token_usd || o.defaults.token_usd;
      $("#px_tok").innerHTML = `So <b>20 tokens = ${usd(20 * tu)}</b>, and <b>100 tokens = ${usd(100 * tu)}</b>. This is only what a member pays you; it is not a cost.`;
      for (const [key, plat, k] of [["gemini_per_1k", "gemini", "gemini"], ["deepseek_per_1k", "deepseek", "deepseek"], ["claude_per_1k", "claude", "claude"]]) {
        const real = blend(c, plat, k), price = p[key], el = $("#pph_" + key); if (!el) continue;
        el.innerHTML = price > 0 ? `1 token = ${Math.round(1000 / price).toLocaleString()} ${plat} tokens charged · you pay about ${usd(real)} per 1,000${real > 0 ? ` · members pay ${usd(price * tu)} (${(price * tu / real).toFixed(1)}×)` : " (enter the platform price above)"}` : "Free for members";
      }
      const pf = $("#pph_image_flux"); if (pf) pf.innerHTML = p.image_flux > 0 ? `Members pay ${usd(p.image_flux * tu)} · you pay ${usd(c.image_flux_usd)}${c.image_flux_usd > 0 ? ` (${(p.image_flux * tu / c.image_flux_usd).toFixed(1)}×)` : ""}` : "Free for members";
      const pg = $("#pph_image_gemini"); if (pg) pg.innerHTML = p.image_gemini > 0 ? `Members pay ${usd(p.image_gemini * tu)} · you pay ${usd(c.image_gemini_usd)}${c.image_gemini_usd > 0 ? ` (${(p.image_gemini * tu / c.image_gemini_usd).toFixed(1)}×)` : ""}` : "Free for members";
      for (const r of ROWS) {
        const sel = box.querySelector(`[data-pxm="${r.id}"]`), row = C.find(x => x.id === sel.value), inf = $("#pxi_" + r.id);
        inf.innerHTML = row ? `${esc(row.note || "")}${row.next ? ` <b>From ${esc(row.next.from)}: $${row.next.in} in / $${row.next.out} out.</b> <button type="button" class="pxlink" data-next="${r.id}">Use that price</button>` : ""}${row.verified ? "" : " Read from a summary: check it on the platform's page."}` : "";
        const use = r.use && o.in_use[r.use], u = $("#pxu_" + r.id);
        if (use) u.innerHTML = `Settings uses <code>${esc(use.model)}</code>${use.match ? "" : ` <span class="pxwarn">not in the list: choose the model it really is</span>`}`;
      }
      box.querySelectorAll("[data-next]").forEach(b => b.onclick = () => { const r = ROWS.find(x => x.id === b.dataset.next), row = C.find(x => x.id === box.querySelector(`[data-pxm="${r.id}"]`).value); box.querySelector(`[data-px="${r.ik}"]`).value = row.next.in; box.querySelector(`[data-px="${r.ok}"]`).value = row.next.out; refresh(); });
      /* a typical video */
      const T = o.typical, fix = (kind, label) => {
        const t = T[kind], gem = t.gemini_tokens, ds = t.deepseek_tokens, cl = t.claude_tokens || 0, extra = +(($("#px_pics_" + kind) || {}).value || 0);
        const tokens = gem / 1000 * p.gemini_per_1k + ds / 1000 * p.deepseek_per_1k + cl / 1000 * p.claude_per_1k + (t.images || 0) * p.image_free + extra * p.image_flux + (kind === "short" ? p.safety_local_per_clip : p.safety_local_per_clip * 4) + p.search_per_video + p.server_per_video + (kind === "short" ? p.render_short : p.render_compilation);
        const up = kind === "short" ? p.upload_short : p.upload_compilation, pay = (tokens + up) * tu;
        const real = gem / 1000 * blend(c, "gemini", "gemini") + ds / 1000 * blend(c, "deepseek", "deepseek") + cl / 1000 * blend(c, "claude", "claude") + (t.images || 0) * c.image_free_usd + extra * c.image_flux_usd;
        const profit = pay - real;
        return `<div class="pxv"><div class="pxvh"><b>${label}</b><span class="muted">${t.measured ? `average of your last ${t.videos} video${t.videos === 1 ? "" : "s"}` : "example numbers: no videos measured yet"}</span></div>
          <div class="pxvn"><div><span>Member pays</span><b>${(tokens + up).toFixed(1)} tokens</b><em>${usd(pay)}</em></div><div><span>You pay platforms</span><b>${usd(real)}</b><em>${Math.round(gem).toLocaleString()} Gemini + ${Math.round(ds).toLocaleString()} DeepSeek tokens${cl ? " + Claude" : ""}</em></div>
            <div class="${profit >= 0 ? "ok" : "bad"}"><span>You keep</span><b>${usd(profit)}</b><em>${pay > 0 ? Math.round(100 * profit / pay) + "% of what they pay" : "-"}</em></div></div>
          <div class="pxvf"><label>Best thumbnails (FLUX pictures) in this video</label><input id="px_pics_${kind}" type="number" min="0" max="10" step="1" value="${extra}"><span class="muted">${tokens.toFixed(1)} tokens for the AI and pictures + ${up} for the upload (the upload costs you nothing). Reserve held at the start: ${kind === "short" ? p.hold_short : p.hold_compilation}.</span></div></div>`;
      };
      const keep = {short: ($("#px_pics_short") || {}).value, compilation: ($("#px_pics_compilation") || {}).value};
      $("#px_prev").innerHTML = fix("short", "A Short") + fix("compilation", "A compilation");
      for (const k of ["short", "compilation"]) { const i = $("#px_pics_" + k); if (i && keep[k] != null) i.value = keep[k]; i.oninput = refresh; }
    };
    /* ---- the model pickers fill the prices */
    for (const r of ROWS) {
      const sel = box.querySelector(`[data-pxm="${r.id}"]`); sel.value = startPick(r);
      sel.onchange = () => {
        const row = C.find(x => x.id === sel.value); if (!row) return refresh();
        if (r.kind === "text") { box.querySelector(`[data-px="${r.ik}"]`).value = row.in; box.querySelector(`[data-px="${r.ok}"]`).value = row.out; } else box.querySelector(`[data-px="${r.pk}"]`).value = row.per;
        refresh();
      };
    }
    box.querySelectorAll("[data-px],[data-pp]").forEach(i => i.addEventListener("input", refresh));
    $("#px_fill").onclick = guard(async () => {
      const r = await api("/api/admin/price/suggest", {method: "POST", body: {costs: costs(), token_usd: costs().token_usd, margin_pct: num($("#px_margin"))}});
      const got = Object.entries(r.prices); got.forEach(([k, v]) => { const i = box.querySelector(`[data-pp="${k}"]`); if (i) i.value = v; });
      $("#px_fillmsg").textContent = got.length ? `Filled in ${got.length} price${got.length === 1 ? "" : "s"}. Check them, then Save.` : "Enter the platform prices above first.";
      refresh();
    });
    $("#px_save").onclick = guard(async () => {
      const c = costs(); if (!(c.token_usd > 0)) throw new Error("One token must be worth more than $0.");
      await api("/api/admin/price/save", {method: "PUT", body: {costs: c, pricing: prices()}}); toast("Prices and costs saved"); await loadPricing(); $("#px_msg").textContent = "Saved. The Users and Reports pages use the same numbers.";
    });
    $("#px_reset").onclick = () => loadPricing();
    refresh();
  });
  /* ---- Creators & languages: every account chooses which creators' clips it wants (their country, the language of their streams) */
  const loadSrc = guard(async () => {
    const box = $("#srccfg"); if (!box) return;
    const d = await api("/api/sources");
    if (!box.isConnected) return;                        // the page was drawn again while this was loading
    box.className = "";
    const on = new Set(d.mine);
    const cap = x => ({youtube: "YouTube", twitch: "Twitch", kick: "Kick"})[x] || x;
    const needKeys = c => c.id === "twitch" && d.owner && !d.twitch_keys;
    box.innerHTML = `<div class="audnote">Choose where your videos look for clips. This is only for your own videos: every account sets its own. If you pick a place on the Create page that is switched off here, you are told so (it is never changed quietly).</div>` +
      d.choices.map(c => `<div class="row" style="gap:14px;align-items:center;margin:14px 0"><label class="switch"><input type="checkbox" data-src="${c.id}" ${on.has(c.id) ? "checked" : ""} ${c.works ? "" : "disabled"}><span></span></label><div class="grow" style="min-width:0"><b>${esc(c.name)}</b>${c.works ? "" : ` <span class="st warn">Not available yet</span>`}${needKeys(c) ? ` <span class="st warn">Needs Twitch keys</span>` : ""}<div class="help">${esc(c.note)}${needKeys(c) ? " Add its keys in Accounts &amp; keys first." : ""}</div></div></div>`).join("") +
      `<div class="row" style="gap:12px;align-items:center"><button class="pri" id="src_save">Save sources</button><span class="muted" id="src_msg"></span></div>`;
    box.querySelector("#src_save").onclick = guard(async () => {
      const picked = [...box.querySelectorAll("input[data-src]:checked")].map(i => i.dataset.src);
      if (!picked.length) throw new Error("Choose at least one place to look for clips");
      await api("/api/sources", {method: "PUT", body: {sources: picked}}); toast("Clip sources saved");
      box.querySelector("#src_msg").textContent = "Saved: " + picked.map(cap).join(" + ");
    });
  });
  const loadGrowth = guard(async () => {
    const box = $("#growthcfg"); if (!box) return;
    const d = await api("/api/growth"); if (!box.isConnected) return; box.className = "";
    const row = p => p.kind === "bool" ? `<div class="row" style="gap:14px;align-items:flex-start;margin:12px 0"><label class="switch"><input type="checkbox" data-g="${p.key}" ${p.value ? "checked" : ""}><span></span></label><div><b>${esc(p.label)}</b><div class="muted">${esc(p.help)}</div></div></div>`
      : p.kind === "choice" ? `<div style="margin:12px 0"><label>${esc(p.label)}</label><select data-g="${p.key}">${p.options.map(o => `<option value="${esc(o.id)}" ${o.id === p.value ? "selected" : ""}>${esc(o.label)}</option>`).join("")}</select><div class="muted">${esc(p.help)}</div></div>`
      : `<div style="margin:12px 0;max-width:260px"><label>${esc(p.label)}</label><input type="number" data-g="${p.key}" min="${p.min}" max="${p.max}" value="${p.value}"><div class="muted">${esc(p.help)}</div></div>`;
    box.innerHTML = `<div class="audnote">Everything here is only about your own videos. Written permission from creators is kept in <a href="#/permissions">Creator permissions</a>.</div>${d.prefs.map(row).join("")}
      <div class="row" style="gap:12px;align-items:center"><button class="pri" id="g_save">Save</button><span class="muted" id="g_msg"></span></div>`;
    $("#g_save").onclick = guard(async () => {
      const body = {}; box.querySelectorAll("[data-g]").forEach(i => body[i.dataset.g] = i.type === "checkbox" ? i.checked : i.type === "number" ? +i.value : i.value);
      await api("/api/growth", {method: "PUT", body}); toast("Saved"); $("#g_msg").textContent = "Saved";
    });
    box.insertAdjacentHTML("beforeend", `<h2 style="margin-top:26px">Your YouTube results</h2><div id="resbox" class="muted">Loading…</div>`);
    const loadRes = guard(async () => {
      const r = await api("/api/analytics"), rb = $("#resbox"); if (!rb) return; rb.className = "";
      if (!r.connected) { rb.innerHTML = `<div class="audnote">Connect your YouTube channel first (the YouTube tab). Then you can allow the studio to read how your videos did.</div>`; return; }
      if (!r.granted) { rb.innerHTML = `<div class="audnote">To learn from how long people watch, the studio needs ONE extra, read-only permission: YouTube Analytics. It only reads numbers about your own videos. You can take it away at myaccount.google.com/permissions.</div><button class="pri" id="an_allow">Allow YouTube Analytics</button>`;
        $("#an_allow").onclick = guard(async () => { const x = await api("/api/youtube/connect-analytics", {method: "POST"}); location.href = x.url; }); return; }
      rb.innerHTML = `<div class="row" style="gap:12px;align-items:center;margin-bottom:10px"><button id="an_sync">Refresh now</button><span class="muted" id="an_msg">${r.count} video${r.count === 1 ? "" : "s"} with results${r.average ? ` · on average ${r.average.avp}% watched${r.average.stayed !== null ? `, ${r.average.stayed}% stayed to watch` : ""}` : ""}</span></div>
        ${r.videos.length ? `<table><tr><th>Video</th><th>Views</th><th>% watched</th><th>Stayed to watch</th><th>Watch time</th></tr>${r.videos.map(v => `<tr><td>${esc((v.title || "").slice(0, 60))}</td><td>${(v.views || 0).toLocaleString()}</td><td>${v.avp === null ? "-" : Math.round(v.avp) + "%"}</td><td>${v.stayed === null ? "-" : Math.round(v.stayed * 100) + "%"}</td><td>${v.avd === null ? "-" : Math.round(v.avd) + " s"}</td></tr>`).join("")}</table>` : `<div class="muted">No results yet. A video needs a day on YouTube. They are read every few hours.</div>`}`;
      $("#an_sync").onclick = guard(async () => { $("#an_msg").textContent = "Reading…"; const x = await api("/api/analytics/sync", {method: "POST"}); toast(x.message); loadRes(); });
    });
    loadRes();
    box.insertAdjacentHTML("beforeend", `<h2 style="margin-top:26px">Clips taking off</h2><div id="spikebox" class="muted">Loading…</div>`);
    const loadSpikes = guard(async () => {
      const r = await api("/api/spikes"), sb = $("#spikebox"); if (!sb) return; sb.className = "";
      const modeNote = r.mode === "off" ? `Spike alerts are off. Switch them on above ("Spike alerts"), save, and the studio watches Twitch for your games.` : r.mode === "alert" ? "You are told when a clip takes off, and you decide." : "You are told, and a Short is made by itself (up to your daily limit).";
      sb.innerHTML = `<div class="audnote">${modeNote} Only Twitch is watched (YouTube's search would use up its daily allowance). It looks every ten minutes.</div>` + (r.alerts.length ? `<table><tr><th>Clip</th><th>Views</th><th>Growing</th><th>When</th><th></th></tr>${r.alerts.map(a => `<tr><td><b>${esc((a.title || "").slice(0, 60))}</b><div class="muted">${esc(a.streamer || "")} · ${esc(a.category || "")}${a.url ? ` · <a href="${esc(a.url)}" target="_blank" rel="noopener">watch</a>` : ""}</div></td>
        <td>${(a.views || 0).toLocaleString()}</td><td>${a.per_hour ? a.per_hour.toLocaleString() + " an hour" : "-"}</td><td class="muted">${when(a.created_at)}</td>
        <td style="text-align:right">${a.status === "new" ? `<button data-mk="${a.id}">Make a Short now</button>` : a.status === "making" ? `<span class="badge running">Being made</span>` : `<span class="badge uploaded">${esc(a.status)}</span>`}</td></tr>`).join("")}</table>` : `<div class="muted" style="margin-top:8px">No clip has taken off yet.</div>`);
      sb.querySelectorAll("[data-mk]").forEach(b => b.onclick = guard(async () => { b.disabled = true; b.textContent = "Starting…"; await api(`/api/spikes/${b.dataset.mk}/make`, {method: "POST"}); toast("A Short is being made. See Make a video for its progress."); loadSpikes(); }));
    });
    loadSpikes();
    if (ME.role === "owner") {                                  // the owner's rules for story videos
      box.insertAdjacentHTML("beforeend", `<h2 style="margin-top:26px">Story video rules (owner)</h2><div id="storyrules" class="muted">Loading…</div>`);
      const st = await api("/api/stories/settings"), rb = $("#storyrules"); rb.className = "";
      rb.innerHTML = `<div class="audnote">AI video (the characters really move) costs real money for every second of video, so it is off for members until you switch it on. Set the price a member pays for it in Settings → Pricing (Story video).</div>
        <div class="row" style="gap:14px;align-items:flex-start;margin:12px 0"><label class="switch"><input type="checkbox" id="sr_vid" ${st.members_video ? "checked" : ""}><span></span></label><div><b>Let members use AI video</b><div class="muted">You can always use it yourself.</div></div></div>
        <div class="pmgrid"><div><label>Story videos a member may make a day</label><input type="number" id="sr_day" min="0" max="50" value="${st.daily_limit}"></div><div><label>AI video scenes a member may make a day</label><input type="number" id="sr_vpd" min="0" max="200" value="${st.video_per_day}"></div>
          <div><label>Most AI video scenes in one story</label><input type="number" id="sr_max" min="0" max="12" value="${st.max_video_scenes}"></div></div>
        <div class="row" style="gap:12px;align-items:center;margin-top:10px"><button class="pri" id="sr_save">Save the rules</button><span class="muted" id="sr_msg"></span></div>`;
      $("#sr_save").onclick = guard(async () => { await api("/api/stories/settings", {method: "PUT", body: {members_video: $("#sr_vid").checked, daily_limit: +$("#sr_day").value, video_per_day: +$("#sr_vpd").value, max_video_scenes: +$("#sr_max").value}}); toast("Saved"); $("#sr_msg").textContent = "Saved"; });
    }
  });
  const loadTrend = guard(async () => {
    const box = $("#trendcfg"); if (!box) return;
    const d = await api("/api/trending");
    if (!box.isConnected) return;
    box.className = "";
    if (!d.allowed) { box.innerHTML = `<div class="audnote">The owner has not switched Trending mode on for you yet. Ask the owner to allow it.</div>`; return; }
    box.innerHTML = `<div class="audnote">With Trending mode the studio looks back two days, ranks Twitch and YouTube clips and videos by how fast they are growing (views per hour), takes the best live stream too, and an AI can read what is hot for the game. Everything else (safety check, credits, captions) stays the same. It costs <b>${d.price.short} tokens for a Short</b> and <b>${d.price.compilation} for a compilation</b>, charged only when the video is made.</div>
      <div class="row" style="gap:14px;align-items:center;margin:14px 0"><label class="switch"><input type="checkbox" id="trend_on" ${d.on ? "checked" : ""}><span></span></label><b>Use Trending mode for my videos (Create page and scheduled videos)</b></div>
      <div class="row" style="gap:12px;align-items:center"><button class="pri" id="trend_save">Save</button><span class="muted" id="trend_msg"></span></div>`;
    box.querySelector("#trend_save").onclick = guard(async () => {
      const r = await api("/api/trending", {method: "PUT", body: {on: box.querySelector("#trend_on").checked}});
      toast(r.on ? "Trending mode is on" : "Trending mode is off"); box.querySelector("#trend_msg").textContent = r.on ? "On: new videos and scheduled videos use it" : "Off";
    });
  });
  const loadSaver = guard(async () => {
    const box = $("#savercfg"); if (!box) return;
    const d = await api("/api/ai-saver");
    if (!box.isConnected) return;
    box.className = "";
    box.innerHTML = `<div class="audnote">When this is on, the studio spends fewer AI tokens on your own videos: each answer has a size limit, a video has a token budget, pictures are read at low resolution (the safety check is never skipped, only made cheaper) and an answer that was already paid for is reused. When it is off, the AI works with no limits, as before.</div>
      <div class="row" style="gap:14px;align-items:center;margin:14px 0"><label class="switch"><input type="checkbox" id="saver_on" ${d.on ? "checked" : ""}><span></span></label><b>Use the AI saver for my videos</b></div>
      <div class="row" style="gap:12px;align-items:center"><button class="pri" id="saver_save">Save</button><span class="muted" id="saver_msg"></span></div>`;
    box.querySelector("#saver_save").onclick = guard(async () => {
      const r = await api("/api/ai-saver", {method: "PUT", body: {on: box.querySelector("#saver_on").checked}});
      toast(r.on ? "AI saver is on" : "AI saver is off"); box.querySelector("#saver_msg").textContent = r.on ? "On for your videos" : "Off";
    });
  });
  const loadAud = guard(async () => {
    const box = $("#audcfg"); if (!box) return;
    const d = await api("/api/audience"), cat = d.catalog;
    box.className = "";
    const S = {countries: d.mine.countries === "all" ? "all" : new Set(d.mine.countries), languages: d.mine.languages === "all" ? "all" : new Set(d.mine.languages), q: {countries: "", languages: ""}};
    const WHAT = {countries: ["Creator countries", "Where the creator lives. YouTube shows a channel's country when the creator filled it in; a channel with no country listed is accepted. Twitch does not tell us a creator's country, so for Twitch the stream language decides."],
      languages: ["Stream languages", "The language the creator streams or speaks in. All means no language filter, even for clips that list no language."]};
    const sel = k => S[k] === "all" ? [] : [...S[k]];
    const draw = () => {
      box.innerHTML = `<div class="audnote">${d.owner ? "As the owner you start with <b>All countries and all languages</b>." : "Until you choose, you get the studio's usual list (Europe, the US and Canada)."} Your choice is only for your own videos.</div>
        <div class="pkbar audpre"><button type="button" class="pkc" data-pre="all">🌍 Everything: all countries, all languages</button><button type="button" class="pkc" data-pre="default">Europe + US + Canada</button><button type="button" class="pkc" data-pre="english">English-speaking only</button></div>
        ${["countries", "languages"].map(k => {
          const items = cat[k], all = S[k] === "all", n = sel(k).length;
          return `<h3 class="audh">${WHAT[k][0]} <span class="audsum">${all ? "All" : n + " selected"}</span></h3><div class="help" style="margin:0 0 10px">${WHAT[k][1]}</div>
            <div class="audtools"><button type="button" class="pkc ${all ? "on" : ""}" data-all="${k}">${k === "countries" ? "All countries" : "All languages"}</button><input type="search" data-aq="${k}" placeholder="Search ${k}" value="${esc(S.q[k])}" style="max-width:240px">
              ${all ? "" : `<button type="button" data-clear="${k}" class="audclr">Clear</button>`}</div>
            <div class="audgrid ${all ? "off" : ""}" data-grid="${k}">${items.filter(x => !S.q[k] || x.name.toLowerCase().includes(S.q[k].toLowerCase()) || x.code.toLowerCase() === S.q[k].toLowerCase()).map(x =>
              `<button type="button" class="audchip ${!all && S[k].has(x.code) ? "on" : ""}" data-k="${k}" data-c="${x.code}"><i>${esc(x.code.toUpperCase())}</i>${esc(x.name)}</button>`).join("") || `<span class="muted">Nothing matches.</span>`}</div>`;
        }).join("")}
        <div class="savebar"><button class="pri" id="aud_save">Save my choice</button><button type="button" id="aud_reset" ${d.mine.custom.countries || d.mine.custom.languages ? "" : "disabled"}>Back to the default</button><span class="muted" id="aud_msg"></span></div>`;
      const setPre = (c, l) => { S.countries = c === "all" ? "all" : new Set(c); S.languages = l === "all" ? "all" : new Set(l); draw(); };
      box.querySelectorAll("[data-pre]").forEach(b => b.onclick = () => { const p = b.dataset.pre; if (p === "all") setPre("all", "all"); else { const x = cat.presets[p]; setPre(x.countries, x.languages); } });
      box.querySelectorAll("[data-all]").forEach(b => b.onclick = () => { const k = b.dataset.all; S[k] = S[k] === "all" ? new Set() : "all"; draw(); });
      box.querySelectorAll("[data-clear]").forEach(b => b.onclick = () => { S[b.dataset.clear] = new Set(); draw(); });
      box.querySelectorAll(".audchip").forEach(b => b.onclick = () => { const k = b.dataset.k; if (S[k] === "all") S[k] = new Set(); S[k].has(b.dataset.c) ? S[k].delete(b.dataset.c) : S[k].add(b.dataset.c); const all = box.querySelector(`[data-all="${k}"]`); b.classList.toggle("on"); draw(); });
      box.querySelectorAll("[data-aq]").forEach(i => i.oninput = () => { S.q[i.dataset.aq] = i.value; const pos = i.selectionStart; draw(); const n = box.querySelector(`[data-aq="${i.dataset.aq}"]`); n.focus(); n.setSelectionRange(pos, pos); });
      $("#aud_save").onclick = guard(async () => {
        const body = {}; for (const k of ["countries", "languages"]) { if (S[k] !== "all" && !S[k].size) throw new Error(`Choose at least one of the ${k}, or choose All.`); body[k] = S[k] === "all" ? "all" : [...S[k]]; }
        const r = await api("/api/audience", {method: "PUT", body}); d.mine = r.mine; toast("Saved"); draw(); $("#aud_msg").textContent = "Saved. It applies to your next video and your next live scan.";
      });
      $("#aud_reset").onclick = guard(async () => { const r = await api("/api/audience", {method: "PUT", body: {reset: true}}); d.mine = r.mine; S.countries = r.mine.countries === "all" ? "all" : new Set(r.mine.countries); S.languages = r.mine.languages === "all" ? "all" : new Set(r.mine.languages); toast("Back to the default"); draw(); });
    };
    draw();
  });
  const loadYt = guard(async () => {
    const box = $("#ytcfg"); if (!box) return;
    const st = await api("/api/youtube/status");
    box.className = "";
    const quota = isOwner && st.quota_total ? `<div class="help" style="margin-top:14px">YouTube uploads today: ${st.uploads_used} of ${st.uploads_total} (for everyone together). Thumbnails and publishing: ${st.quota_used} of ${st.quota_total} units.</div>` : "";
    const setup = isOwner && !st.configured ? `<div class="authmsg bad" style="margin:0 0 14px">Google sign-in is not set up yet. In Google Cloud Console create an OAuth client (type: Web application), add this Authorized redirect URI: <b>${esc(st.redirect_uri)}</b>, then paste the client ID and secret in <b>Accounts &amp; keys</b>.</div>`
      : isOwner ? `<div class="help" style="margin:0 0 14px">Authorized redirect URI to register in Google Cloud: <b>${esc(st.redirect_uri)}</b></div>` : "";
    box.innerHTML = setup + (st.connected
      ? `<div class="row"><span class="chip live">Connected</span><b>${esc(st.channel_title)}</b><span class="muted">${esc(st.email || "")}</span></div>
         <p class="muted">Your videos are uploaded to this channel as <b>Unlisted</b> first. You approve them, and then they go Public.${st.queued_uploads ? ` ${st.queued_uploads} video(s) are waiting for an upload slot.` : ""}</p>
         <div class="row"><button class="dng" id="yt_off">Disconnect</button></div>`
      : st.configured ? `<p class="muted" style="margin-top:0">Not connected yet. You will sign in with Google and allow the studio to upload videos to your channel. You can disconnect at any time.</p>
         <div class="row"><button class="pri" id="yt_on">Connect YouTube</button></div>`
      : `<p class="muted" style="margin-top:0">The owner has not finished setting up YouTube sign-in yet.</p>`) + quota;
    if ($("#yt_on")) $("#yt_on").onclick = guard(async () => { const r = await api("/api/youtube/connect", {method: "POST"}); location.href = r.url; });
    if ($("#yt_off")) $("#yt_off").onclick = guard(async () => { if (!confirm("Disconnect this channel? Videos stop uploading until you connect again.")) return; await api("/api/youtube/disconnect", {method: "POST"}); toast("Disconnected"); loadYt(); });
  });
  const loadPrefs = guard(async () => {
    const box = $("#prefscfg"); if (!box) return;
    const p = ME.prefs || {};
    let to = {styles: [], fonts: [], brand: {style: "auto", text: "#FFE600", accent: "#FF2D87", font: "anton", has_logo: false}};
    try { to = await api("/api/thumb/options"); } catch (e) {}
    const b = to.brand;
    const sel = (id, label, opts, cur, help) => `<div><label>${label}</label><select id="${id}">${opts.map(([o, t]) => `<option value="${esc(o)}" ${cur === o ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>${help ? `<div class="help">${help}</div>` : ""}</div>`;
    box.className = "";
    box.innerHTML = `<div class="fields">
        ${sel("pf_voice", "Narrator voice", [["", "Use the server default"]].concat(VOICE_OPTS), p.tts_voice || "", "Who reads your AI commentary. You can also choose one per video on the Create page.")}
        ${sel("pf_audio", "Original audio", [["", "Use the server default"]].concat(AUDIO_OPTS), p.default_audio || "", "What happens to the creator's original audio.")}
        ${sel("pf_hold", "After a video is made", [["0", "Upload it automatically as Unlisted"], ["1", "Wait for me: I check it and choose the audio first"]], p.hold_uploads ? "1" : "0", "With 'Wait for me' nothing goes to YouTube until you press Upload on the video. You can still change a single run on the Create page.")}
        <div class="full"><h3 style="margin:14px 0 2px">My thumbnail look</h3><div class="help">New videos use this automatically, so your channel has its own look. You can still change any single video in its Thumbnail studio.</div></div>
        ${sel("pf_tstyle", "Style", [["auto", "Vary automatically (never the same as your last two)"]].concat(to.styles.map(x => [x.id, x.name])), b.style, "")}
        ${sel("pf_tfont", "Font", to.fonts.map(f => [f.id, f.name]), b.font, "")}
        ${sel("pf_ttier", "Thumbnail level", (to.tiers || [{id: "better", name: "Better", available: true, price: 1}]).filter(x => x.available || x.id === b.tier).map(x => [x.id, `${x.name}: about ${x.price} token${x.price === 1 ? "" : "s"} a picture`]), b.tier || "better", (to.tiers || []).filter(x => !x.available).map(x => `${x.name}: ${x.reason}`).join(" · "))}
        ${sel("pf_tface", "Streamer's face on the thumbnail", [["on", "Use it when the video has a webcam"], ["off", "Never"]], b.face || "on", "Only when the video has a face camera: the sharpest, most expressive moment of the face is cut out and put in a corner. No webcam, no face: nothing changes.")}
        ${sel("pf_tpics", "AI pictures for each new thumbnail", [["1", "1 picture"], ["3", "3 pictures to choose from (3 times the picture cost)"]], String(b.pictures || 1), "With 3, the other two are kept for you to pick from in the Thumbnail studio. You can still choose for each video on the Create page.")}
        <div><label>Text colour</label><input type="color" id="pf_tcol" value="${b.text}" style="width:70px;height:36px;padding:0"></div>
        <div><label>Accent colour</label><input type="color" id="pf_acol" value="${b.accent}" style="width:70px;height:36px;padding:0"></div>
        <div class="full"><label>My logo (top right of every thumbnail)</label><div class="row">${b.has_logo ? `<img src="/api/brand/logo?t=${Date.now()}" alt="Logo" style="height:42px;background:#888;border-radius:8px;padding:4px">` : '<span class="muted">No logo yet</span>'}
          <button type="button" id="pf_logo">${b.has_logo ? "Change logo" : "Upload a logo"}</button>${b.has_logo ? '<button type="button" class="dng" id="pf_logo_rm">Remove</button>' : ""}<input type="file" id="pf_logof" accept="image/png,image/jpeg" hidden></div><div class="help">A PNG with a transparent background looks best.</div></div>
        <div class="full"><label>Send approval emails to</label><input id="pf_mail" type="email" value="${esc(p.notify_to || "")}" placeholder="${esc(ME.email)}"><div class="help">Leave empty to use your account email (${esc(ME.email)}).</div></div></div>
      <div class="row" style="margin-top:8px"><button type="button" id="pf_listen">▶ Listen to the chosen voice</button></div>
      <div class="savebar"><button class="pri" id="pf_save">Save</button><span class="muted">Used for your next video.</span></div>
      <h3 style="margin:26px 0 4px">Change password</h3>
      <div class="fields"><div><label>Current password</label><input id="pw_old" type="password" autocomplete="current-password"></div>
        <div><label>New password (8+ characters)</label><input id="pw_new" type="password" autocomplete="new-password"></div></div>
      <div class="row" style="margin-top:12px"><button id="pw_save">Change password</button></div>`;
    $("#pf_listen").onclick = () => { const v = $("#pf_voice").value; if (!v || v === "random") { toast("Pick one voice to listen to it"); return; } new Audio("/api/voices/preview?voice=" + encodeURIComponent(v)).play().catch(() => toast("Could not play the sample", true)); };
    $("#pf_save").onclick = guard(async () => {
      const r = await api("/api/prefs", {method: "PUT", body: {tts_voice: $("#pf_voice").value, default_audio: $("#pf_audio").value, hold_uploads: $("#pf_hold").value === "1", notify_to: $("#pf_mail").value}});
      ME = r.user;
      await api("/api/brand", {method: "PUT", body: {style: $("#pf_tstyle").value, font: $("#pf_tfont").value, text: $("#pf_tcol").value, accent: $("#pf_acol").value, pictures: $("#pf_tpics").value, tier: $("#pf_ttier").value, face: $("#pf_tface").value}});
      toast("Preferences saved");
    });
    $("#pf_logo").onclick = () => $("#pf_logof").click();
    $("#pf_logof").onchange = guard(async () => { const f = $("#pf_logof").files[0]; if (!f) return; await api("/api/brand/logo", {method: "POST", body: f, raw: true}); toast("Logo saved"); loadPrefs(); });
    if ($("#pf_logo_rm")) $("#pf_logo_rm").onclick = guard(async () => { await api("/api/brand/logo", {method: "DELETE"}); toast("Logo removed"); loadPrefs(); });
    $("#pw_save").onclick = guard(async () => {
      const r = await api("/api/auth/password", {method: "POST", body: {old: $("#pw_old").value, new: $("#pw_new").value}});
      $("#pw_old").value = $("#pw_new").value = ""; toast(r.message);
    });
  });
  const loadClipCfg = guard(async () => {
    const d = await api("/api/clipping"), c = d.config, box = $("#clipcfg"); if (!box) return;
    const num = (id, label, v, lo, hi, help) => `<div><label>${label}</label><input type="number" id="${id}" min="${lo}" max="${hi}" value="${v}">${help ? `<div class="help">${help}</div>` : ""}</div>`;
    box.className = "";
    box.innerHTML = `<h3 style="margin:6px 0 10px">Kinds of moments to look for</h3>
      <div class="typegrid">${d.types.map(t => `<label class="typecard"><span class="tt"><input type="checkbox" data-ct="${t.id}" ${c.types[t.id] ? "checked" : ""}><b>${esc(t.name)}</b></span><span class="muted">${esc(t.desc)}</span></label>`).join("")}</div>
      <div class="fields" style="margin-top:18px">
        <div class="full"><label>Your own ideas (one per line)</label><textarea id="cc_custom" rows="4" placeholder="e.g. police chases that end in a crash&#10;streamers getting jump-scared&#10;first reactions to new missions">${esc(c.custom.join("\n"))}</textarea><div class="help">The AI looks specifically for these, on top of the kinds above.</div></div>
        <div class="full"><label>Never clip (one per line)</label><textarea id="cc_avoid" rows="3" placeholder="e.g. political arguments&#10;long cutscenes">${esc(c.avoid.join("\n"))}</textarea></div>
        ${num("cc_len", "Clip length (seconds)", c.clip_seconds, 20, 58, "Shorts must stay under 60 seconds.")}
        ${num("cc_min", "Minimum AI score", c.min_score, 30, 95, "Higher means fewer but better clips.")}
        <div><label>Live-stream sensitivity</label><select id="cc_sens">${[["strict", "Strict: only big spikes"], ["normal", "Normal"], ["loose", "Loose: more candidates"]].map(([v, t]) => `<option value="${v}" ${c.live_sensitivity === v ? "selected" : ""}>${t}</option>`).join("")}</select></div>
        ${num("cc_per", "Moments taken from one long video", c.moments_per_video, 1, 8, "The extra good ones go to the clip bank for later videos.")}
        ${num("cc_bank", "Keep banked moments (days)", c.bank_days, 1, 30, `${d.bank} moment(s) are waiting in the bank now.`)}</div>
      <details class="more" style="margin-top:16px"><summary>See exactly what the AI is told</summary><pre class="log" id="cc_crit" style="max-height:220px;white-space:pre-wrap">${esc(d.criteria)}</pre></details>
      <div class="savebar"><button class="pri" id="cc_save">Save</button><span class="muted">Applies to the next run. No restart needed.</span></div>`;
    $("#cc_save").onclick = guard(async () => {
      const types = {}; box.querySelectorAll("[data-ct]").forEach(i => types[i.dataset.ct] = i.checked);
      const r = await api("/api/clipping", {method: "PUT", body: {types, custom: $("#cc_custom").value, avoid: $("#cc_avoid").value, clip_seconds: +$("#cc_len").value,
        min_score: +$("#cc_min").value, live_sensitivity: $("#cc_sens").value, moments_per_video: +$("#cc_per").value, bank_days: +$("#cc_bank").value}});
      toast("Clipping settings saved"); $("#cc_crit").textContent = r.criteria;
    });
  });
  const loadM = guard(async () => {
    const m = await api("/api/music");
    $("#mlist").innerHTML = m.length ? `<table>${m.map(t => `<tr><td>${esc(t.name)}</td><td class="muted">${t.mb} MB</td><td style="text-align:right"><button class="dng" data-m="${esc(t.name)}">Delete</button></td></tr>`).join("")}</table>` : `<div class="empty">No tracks yet. Upload your first one above.</div>`;
    document.querySelectorAll("button[data-m]").forEach(b => b.onclick = guard(async () => {
      await api("/api/music?name=" + encodeURIComponent(b.dataset.m), {method: "DELETE"}); loadM();
    }));
  });
  await loadS();
}
