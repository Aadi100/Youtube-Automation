# Clip Studio

Twitch clips -> AI commentary + royalty-free music -> 9:16 Short or 8-10 min compilation -> thumbnail + metadata -> uploaded to the connected YouTube channel as **Unlisted** until you approve it.

## Dashboard
`python worker.py` then open **http://localhost:8765** (needs MongoDB running; data lives in database `clipstudio`).
Overview (health + stats) | Create (start/cancel jobs, live log) | Videos (preview, edit title/description/tags/status, delete) |
Clips (downloaded Twitch clips) | Settings (API keys saved to `.env`, upload royalty-free music).
Every account connects its own YouTube channel (Settings -> YouTube); the studio uploads to it and the records show "uploaded".

## Games (works for any game)
Add games on the **Games** tab (name, Twitch category, YouTube search terms, hashtags, thumbnail label). Jobs pick one game,
or **Auto** rotates through every enabled game (the one used longest ago goes next). Use **Test sources** to check a game's
Twitch category and YouTube search. Titles, commentary, hashtags and thumbnails use the game's name.

## Live streams + long videos (source "Everything" / "Live streams only")
`live_scanner.py` finds streams that are live now for the game (Twitch needs the Twitch keys; YouTube needs none, node is used as
yt-dlp's JS runtime), records several at once for LIVE_WATCH_MINUTES (default 8, Settings), listens to Twitch chat (anonymous,
read-only) and measures audio loudness, and cuts ~38 s around the strongest moments (chat speed-up + laughs/hype + shouting).
The clip is credited to the streamer + channel and goes through the normal pipeline. With source "all" a Short alternates between a
live moment and a normal clip. Long YouTube videos / past streams (up to 4 h) are used when YouTube has "most replayed" data.
Scheduled runs that find nothing new in 24 h widen the search to 3 and then 7 days.
`python -m app.engine.live_scanner --game roblox --minutes 1 --streams 2 --min-score 0.3` tests it without the pipeline.

## Learning Lab (beta, owner only)

A separate page (**Learning Lab**) that teaches the studio the owner's taste. It has three parts, each with its own switch, all **off** until switched on:

- **Protection and growth** (every member, Settings -> Protection and growth): *Reused-content risk* (engine/risk.py): every video gets a 0-100 score from plain rules (untouched original sound, no commentary or own work on top, one clip only, a very popular source, written permission lowers it) with the reasons and what to do; a high-risk video is held for the member's review instead of being uploaded by itself (switchable). *Creator permissions* (services/permission_service.py): who allowed clipping, the date and the proof, per member; Trending mode prefers these creators. *Commentary styles* (7) and an optional *context card* (who and what you see, first 4 s of a Short). *YouTube results* (services/analytics_service.py): with a separate read-only Analytics permission each video's views, average % watched and 'stayed to watch' (engagedViews / views; the API has no swipe-away number) are read every 6 h and feed the Learning Lab. *Spike alerts* (services/spike_service.py): the worker looks at Twitch every 10 minutes (once per game, shared by members), tells a member when a clip suddenly takes off and, if they chose, makes the Short through the normal job queue (their tokens, a daily limit, Trending mode ranks that clip first).
- **Story videos** (menu: Story videos): the studio ranks story genres by how fast the best Shorts of the last 7 days grow (engine/story_trends.py, one YouTube look shared by everybody and kept 12 h), writes original story ideas from what works, writes the script (or cuts the member's own story into scenes; engine/story_script.py), draws one picture per scene with FLUX in one art style with fixed character looks, makes each scene MOVE (engine/story_media.py: Google Veo through the Gemini key when the owner allows it, otherwise camera movement over the picture, and a scene Veo refuses falls back to camera movement), adds an edge-tts narrator and burned-in captions, and builds a PROJECT in Edit projects (scenes in order, music, YouTube Short preset). Queue in the worker (services/story_service.py): one story per member, tokens reserved at the start and what is not used returned, a failed or cancelled story is free, daily limits and the AI-video switch are the owner's (Settings -> Protection and growth, owner block; prices in Pricing -> Story video). The finished video is marked AI-made; a realistic art style also ticks YouTube's `containsSyntheticMedia` on upload.
- **Edit projects (timeline editor)**: a member puts several clips on a timeline, trims, splits, reorders, adds text and captions, and makes one video. Every project and render belongs to one member; saving is version-checked (two tabs never overwrite each other); renders go through a shared database queue that the *worker* service runs (EDITOR_RENDERERS at a time, default 1; EDITOR_THREADS ffmpeg threads each, default 2; one waiting/running render per member; 40 waiting at most); a member's editor uploads are limited by EDITOR_QUOTA_GB (default 6). Audio: every clip has its own volume (0-200%) and fades, and a project has one music track (a studio library track or the member's own upload, 60 MB max) with volume, fades, start point, loop and 'lower the music under speech' (ducking); the music is mixed in after the clips are joined, so the picture is never re-encoded. Motion: every clip can be sped up or slowed down (0.25x-4x, picture and sound together), given a slow zoom in / out or a punch-in around a chosen point, and come in with a transition (fade, dissolve, slide, wipe, circle open). Transitions overlap neighbouring clips a little and need one extra re-encode of the joined video, so they cost more server time than plain cuts; a project without transitions is still joined without re-encoding. Look: every clip has a colour look (warm, cool, vivid, black and white, vintage, cinematic, bright) with its own brightness / contrast / colour strength, up to 8 stickers or logos from the member's own pictures (cleaned and re-saved as PNG, 8 MB and 4096 px at most, counted in the editor storage limit, never visible to other members), and styled text (templates: Classic, Bold pop, Boxed, Neon, Big title, Lower third; plus bold, italic, capitals, outline, box behind, fade or pop animation). All of it is drawn in the same pass that renders the clip, so it costs no extra encode. Export: the member chooses where the video is going (YouTube Short, TikTok, Instagram Reel, Facebook Reel, YouTube video, Instagram feed): the preset sets the picture shape and the longest length (checked when the render is asked for, so a video that is too long or the wrong shape is never queued), and a quality (Draft = half size and fast, Standard, High). When it is ready the page offers My videos and, for a Short, the 'Other platforms' page for TikTok / Instagram / Facebook posting.
- **Titles**: titles you like are shown to the AI that writes titles; a small model learns from the views per day of your own videos which kinds of titles do better and nudges the title choice (at most 12 points of 100).
- **Descriptions**: descriptions you like, and the ones you rewrite by hand in the Videos page, are shown to the AI that writes descriptions.
- **Clipping**: a small model learns from the videos you publish or decline which kinds of clips are worth making and nudges a moment's score (at most 10 points of 100).

It only affects videos made for the owner account. A model needs enough data before it speaks (12 videos with view counts for titles; 20 decisions, 6 of each kind, for clipping), and it is a small nudge, never a replacement for the normal scoring. View counts come from the YouTube Data API key (Settings -> Accounts & keys). This is learning from results, not a trained language model: a channel does not have the data for that.

## AI saver (off until you switch it on) and thumbnail levels

Switch it on in Settings -> AI saver (every member and the owner choose for their own videos; it is off by default). When it is on, every AI call follows the same rules (`app/engine/ai_saver.py`): small answer limits per task, a token budget for each video (`AI_JOB_BUDGET`, default 60,000),
pictures read at low resolution (`AI_MEDIA_RESOLUTION`, default low: the safety review costs about a quarter of the tokens for the same answer),
and a cache (`ai_cache`, 30 days) so the same clip or video is never analysed twice. Reports -> "AI tokens saved" shows the effect.
The safety check is never skipped, only made cheaper.

Thumbnails have two levels (Create -> Do it yourself, or Settings -> My preferences): **Better** (a free AI picture behind the real frame; the headline is added by the studio) and
**Best** (Gemini looks at the best frames and plans the thumbnail, then **FLUX.1 [schnell]** draws the finished thumbnail with its headline in the picture). Best needs the Gemini key
and a Cloudflare account ID and API token (Settings -> Accounts & keys; Cloudflare Workers AI gives about 170 thumbnails a day for free, then about $0.0006 each). If Gemini or FLUX
cannot do it, the thumbnail is made the Better way and billed as Better. Two optional settings (Settings -> Audience & clips): `THUMB_TEXT` (`flux` writes the headline in the picture,
`code` lets the studio write it on top of FLUX's picture) and `THUMB_REVIEW` (`on`: Gemini checks each Best thumbnail once). The owner switches Best on for members under Users.
The best frame and the kind of video are found by code (no tokens), and `python -m app.engine.playbook build` studies popular YouTube thumbnails and stores the measurements in `state/playbook.json`.

## Credits
Every description lists each featured creator with their **channel link** and the **original video link** (also shortened
into the Twitch helper text). Credit is good practice, not a legal shield - see "Copyright" below.

## Email approval (Settings -> Email notifications)
Fill SMTP host/port/user/password + "send to", click **Send test email**. After each YouTube upload you get an email with
**Approve & publish**; clicking it opens a confirmation page and, when confirmed, the studio makes the video Public
(status-only change: title/description untouched).
Scheduled runs that fail are emailed too. The Approve link opens the studio at the address in "Address used in the Approve link" (the site's own address on a server).
You can also publish from the Videos tab.

## Schedule (dashboard -> Schedule tab)
Set the daily times (and time zone) for Shorts and Compilations on the **Schedule** tab; defaults are Shorts 00:30/06:30/12:30/18:30
and Compilation 02:00 (Asia/Karachi). The studio's own scheduler checks every few minutes whether a slot is due, so changes apply within minutes
(a slot is retried for 30 min if something is already rendering). A Short takes ~6-8 min to render.

## Publishing
- **YouTube: automatic** to the channel each account connected (uploads Unlisted, then Public when you approve).
- **Twitch: manual, made quick.** Twitch has no upload API, so the **Twitch helper** tab gives each finished video a
  Download / Show-in-folder button, a ready title + description to copy, a link to the Twitch dashboard, and a
  "Mark as uploaded" button so the dashboard tracks both platforms.
- Twitch is also a clip *source* (Create tab -> "Find clips on").

## One-time setup
1. `pip install -r requirements.txt` (ffmpeg must be installed)
2. Start the studio once (`python worker.py`) and enter your keys under **Settings -> Accounts & keys** (Twitch keys are free at dev.twitch.tv/console, `GEMINI_API_KEY`, `CONTACT_EMAIL` ...). They are saved to a private `.env` file next to `worker.py`.
   Add the games you cover on the **Games** tab (each with its Twitch category and YouTube search words).
3. Put royalty-free tracks (YouTube Audio Library etc.) in `music/`.
4. Connect your YouTube channel: Settings -> YouTube.
5. Start the worker and leave it running: `python worker.py`

## Audio modes (`--audio-mode`)
| mode | what happens | Content ID risk |
|---|---|---|
| `replace` (default) | original audio muted; AI commentary voiceover + music; captions = commentary | lowest |
| `bed` | original ducked under music | streamer voice / game radio still audible |
| `original` | untouched | high |
`replace` falls back to `bed` if there is no Gemini key, and to `original` if `music/` is empty.

## CLI
```
python -m app.engine.pipeline --mode auto-short                      # download top clip, render, write outputs/last_run.json
python -m app.engine.pipeline --mode auto-compilation --title "Best Gaming Moments"
python -m app.engine.pipeline --mode short --input inputs/clip.mp4 --layout split --cam-crop "0:0:640:360"
python -m app.engine.pipeline --mode compilation --input-dir inputs  # files named "Streamer - Title.mp4"
python -m app.engine.discovery --count 6                             # just download clips
```

## Project structure (MVC, Flask + MongoEngine)
```
worker.py                  entry point: python worker.py [--role web|worker|all]
app/
  __init__.py              create_app(): the Flask application factory
  models/        (M)       MongoEngine documents + data access: accounts.py, content.py (games, clips, videos, jobs, claims),
                           system.py, billing.py, youtube.py, base.py (connection, base class)
  views/         (V)       dashboard/index.html (the page shell) with assets/css/ (base.css ... calm.css: the LAST file is the look of the whole dashboard) and assets/js/ (core.js, shell.js, then one file per page, routes.js last), templates/ (Jinja pages, e.g. the email approval page), serializers.py (JSON)
  controllers/   (C)       Flask blueprints, one per area: auth, admin, video, job, game, clip, schedule, settings, youtube, approve, system
  services/                business logic: queue_service, upload_service, schedule_service, maintenance_service, auth_service,
                           token_service, youtube_service, notify_service, storage_service, backup_service
  engine/                  the video pipeline: pipeline, discovery, live_scanner, moment_ai, llm, audio_shield, video_processor, subtitles,
                           thumbnail_generator, ai_metadata, safety, region, clipcfg ...
  http.py / runtime.py     shared Flask helpers / process-wide settings;  utils/ = .env file, process control, path safety
deploy/                    setup for a VPS (gunicorn + worker services, nginx + certbot, nightly backup); wsgi.py = the gunicorn entry
```

Keep Unlisted until Content ID has finished checking, then switch to Public.

## Reaction Lab (beta, owner only)

A separate page (Automation -> Reaction Lab) that finds the moments people react to in a past video or stream replay, lets you judge them
(good reaction / not a reaction) and learns your taste. It is isolated from the rest of the studio: its own collections (`rx_scans`, `rx_labels`,
`rx_models`), its own files under `outputs/reactions/`, its own endpoints (`/api/reactions/*`); it never starts a video job, uploads, schedules or spends AI tokens.

- Signals: loud / sudden jump / laugh-like rhythm / quiet-then-shout (sound), chat speed and hype emotes (when the chat replay can be read), smile and jolt on a face camera and sudden
  screen changes (OpenCV), reaction words (local faster-whisper, optional), YouTube's most-replayed curve.
- Model: a small logistic regression in numpy, started from sensible weights and pulled toward them, so it only drifts away as your judgments accumulate
  (needs 5 good + 5 not-good to start; a kind of reaction such as funny or rage gets its own model after 20 judgments of its own).
- Code: `app/engine/reaction_signals.py`, `app/engine/reaction_model.py`, `app/services/reaction_service.py`, `app/controllers/reaction_controller.py`, `app/models/reactions.py`.

## Settings -> Pricing & costs (owner)

One tab for the money side: what one studio token is worth, what each platform charges you per model (a catalogue of Claude, Gemini text and image, DeepSeek and the search
services, read from their price pages on the date shown; every number is editable), what members pay in tokens, and what a typical Short / compilation earns you.
It saves the same data as the price list on the Users page and the real costs on the Reports page (`token_service`). "Fill in the prices" turns your costs and a margin into token prices
using how your AI tokens split between input and output. Code: `app/services/price_catalog.py`, `app/services/price_service.py`, endpoints `/api/admin/price/*`.

## Creators & languages (every account)

Settings -> Creators & languages: every account (owner and members) chooses which creators' clips it wants: the country they live in and the language of their streams, or All.
The owner starts with All; a member starts with the studio's list (Settings -> Audience & clips, now the "default for members"). The choice is stored with the account's "What to clip"
settings and used by the clip search of that account's own runs (`app/engine/audience.py`, read by `discovery.py`, `live_scanner.py` and `region.py` through CLIPSTUDIO_USER_ID).
Members see plain wording only: receipts, usage and thumbnail levels name what was done, never which AI service or model did it.
