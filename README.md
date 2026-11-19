# GTA 6 Auto YouTube Studio

Twitch clips -> AI commentary + royalty-free music -> 9:16 Short or 8-10 min compilation -> thumbnail + metadata -> n8n uploads as **Unlisted**.

## Dashboard
`python worker.py` then open **http://localhost:8765** (needs MongoDB running; data lives in database `gta6_studio`).
Overview (health + stats) | Create (start/cancel jobs, live log) | Videos (preview, edit title/description/tags/status, delete) |
Clips (downloaded Twitch clips) | Settings (API keys saved to `.env`, upload royalty-free music).
The same server is what the n8n workflows call, and they report the YouTube video ID back so records show "uploaded".

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

## Credits
Every description lists each featured creator with their **channel link** and the **original video link** (also shortened
into the Twitch helper text). Credit is good practice, not a legal shield - see "Copyright" below.

## Email approval (Settings -> Email notifications)
Fill SMTP host/port/user/password + "send to", click **Send test email**. After each YouTube upload you get an email with
**Approve & publish**; clicking it opens a confirmation page on this PC and, when confirmed, the n8n workflow
"Approve & publish (webhook)" makes the video Public (status-only change: title/description untouched).
Scheduled runs that fail are emailed too. The Approve link only works on the computer running Clip Studio
(set "Address used in the Approve link" if you expose it through a tunnel). You can also publish from the Videos tab.
**n8n must be restarted after workflows are activated from the command line.**

## Schedule (dashboard -> Schedule tab)
Set the daily times (and time zone) for Shorts and Compilations on the **Schedule** tab; defaults are Shorts 00:30/06:30/12:30/18:30
and Compilation 02:00 (Asia/Karachi). The n8n workflows wake every 5 minutes and ask the dashboard "is a slot due?", so changes apply
within minutes with no n8n edits (a slot is retried for 30 min if something is already rendering). One job runs at a time.
A Short takes ~6-8 min to render. The workflows' "Manual test run" trigger still runs immediately.

## Publishing
- **YouTube: automatic** via the n8n workflows (uploads Unlisted, reports the video ID back to the dashboard).
- **Twitch: manual, made quick.** Twitch has no upload API, so the **Twitch helper** tab gives each finished video a
  Download / Show-in-folder button, a ready title + description to copy, a link to the Twitch dashboard, and a
  "Mark as uploaded" button so the dashboard tracks both platforms.
- Twitch is also a clip *source* (Create tab -> "Find clips on").

## One-time setup
1. `pip install -r requirements.txt` (ffmpeg must be installed)
2. Copy `.env.example` to `.env`, fill in Twitch keys (free, dev.twitch.tv/console), `GEMINI_API_KEY`, `CONTACT_EMAIL`.
   `TWITCH_GAME_NAME` must match a real Twitch category (use `Grand Theft Auto V` until the GTA 6 one exists).
3. Put royalty-free tracks (YouTube Audio Library etc.) in `music/`.
4. In n8n: open the two **GTA6 -** workflows, attach your YouTube OAuth2 credential to the upload node (and the thumbnail node in the compilation one).
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
python -m app.engine.pipeline --mode auto-compilation --title "GTA 6 Best Moments"
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
  views/         (V)       dashboard/index.html (the web app), templates/ (Jinja pages, e.g. the email approval page), serializers.py (JSON)
  controllers/   (C)       Flask blueprints, one per area: auth, admin, video, job, game, clip, schedule, settings, youtube, approve, system
  services/                business logic: queue_service, upload_service, schedule_service, maintenance_service, auth_service,
                           token_service, youtube_service, notify_service, storage_service, backup_service
  engine/                  the video pipeline: pipeline, discovery, live_scanner, moment_ai, llm, audio_shield, video_processor, subtitles,
                           thumbnail_generator, ai_metadata, safety, region, clipcfg ...
  http.py / runtime.py     shared Flask helpers / process-wide settings;  utils/ = .env file, process control, path safety
n8n/*.json                 the optional n8n workflows (owner's legacy setup)
```

Keep Unlisted until Content ID has finished checking, then switch to Public.
