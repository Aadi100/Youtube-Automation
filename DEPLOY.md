# Putting Clip Studio on your VPS

Everything runs in Docker: the website (`web`), the video makers (`worker`), the database (`mongo`), the HTTPS front door (`caddy`)
and a nightly backup (`backup`). You do not need to install Python or ffmpeg on the server.

## 0. What you need
- A VPS with **Ubuntu 22.04 / 24.04** (or Debian 12), at least 4 CPU cores, 8 GB RAM, 80 GB disk to start (see "Size" below).
- A **domain name**. Create an `A` record `studio.yourdomain.com -> your VPS IP address`.
- Your own **Google Cloud OAuth client** (the same one you used for YouTube) and your Gemini / DeepSeek keys.

## 1. Prepare the server (once)
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 ufw
sudo ufw allow 22 && sudo ufw allow 80 && sudo ufw allow 443 && sudo ufw --force enable
```

## 2. Copy the project to the server
From your PC (in the project folder; PowerShell or any terminal with `scp`):
```bash
scp -r . youruser@YOUR_SERVER_IP:~/clipstudio
```

## 3. Settings
```bash
cd ~/clipstudio
mkdir -p config data
cp .env.production.example config/.env        # then edit it: see the comments inside
nano .env                                      # next to docker-compose.yml, put:  DOMAIN=studio.yourdomain.com
```
Set at least `PUBLIC_BASE_URL=https://studio.yourdomain.com` in `config/.env`.

## 4. Start
```bash
docker compose up -d --build
docker compose ps                              # everything should say "running" / "healthy"
```
Open `https://studio.yourdomain.com` (the certificate is created automatically; it can take a minute).

## 5. Create the owner account
The first account on a new server needs the one-time setup code so nobody else can claim it:
```bash
docker compose exec web python worker.py --show-setup-code
```
Open the site -> "Create the owner account" -> enter your details and the code.

## 6. Connect Google sign-in (so members can connect YouTube)
In Google Cloud Console -> Credentials -> your OAuth client, add this Authorized redirect URI:
`https://studio.yourdomain.com/api/youtube/callback`. Then in the dashboard: Settings -> Accounts & keys -> paste the Google client ID and secret.

## Moving your data from your PC (do this BEFORE you ask members to join)
On your PC, in the project folder:
```bash
python -m app.services.backup_service export studio-data.tar.gz        # accounts, games, clips, videos, schedules, tokens ...
python -m app.services.backup_service files  studio-files.tar.gz        # optional: your existing video files and music (can be large)
```
Also copy the value of **TOKEN_ENC_KEY** from your PC's `.env` into `config/.env` on the server. Without it, saved YouTube
logins cannot be decrypted and everybody would have to reconnect their channel.
Upload both files to the server, then:
```bash
docker compose cp studio-data.tar.gz web:/app/studio-data.tar.gz
docker compose exec web python -m app.services.backup_service import studio-data.tar.gz
# optional files:
docker compose cp studio-files.tar.gz web:/app/ && docker compose exec web python -m app.services.backup_service unpack-files studio-files.tar.gz
docker compose restart
```
Your owner login, games, schedule and history are now on the server. n8n is **not needed** any more: connect your own channel
(Settings -> YouTube) like every member does, and the server posts for you.

## Everyday commands
| What | Command |
|---|---|
| See logs | `docker compose logs -f web worker` |
| Update after a new version | upload the new files, then `docker compose up -d --build` |
| More rendering power | `docker compose up -d --scale worker=3` |
| Backups | automatic every night in `data/backups` (last 7 kept) |
| Restore a backup | `docker compose exec web python -m app.services.backup_service import /app/backups/studio-XXXX.tar.gz` (needs the file copied in) |
| Stop everything | `docker compose down` (your data stays in `./data`) |

## What watches the server for you
The Users page (owner) shows: workers alive, videos running / waiting, failures in the last 24 h, free disk, and how much of
YouTube's daily allowance is used. You also get an email (once per problem every 6 hours) when the disk is nearly full,
many videos fail, or no worker is running while videos are waiting. Old files are removed automatically (see below).

## Size: how big a server do I need?
These are estimates. A Short needs about 5 CPU-minutes, a Compilation about 30. Measure on your server and adjust.

| Members (about 3 Shorts a day each) | Videos a day | CPU cores (busy 24 h) | Server to start with |
|---|---|---|---|
| 50 | 150 | about 1 | 4 cores, 8 GB RAM |
| 200 | 600 | about 2-3 | 8 cores, 16 GB RAM |
| 1,000 | 3,000 | about 11 | 16+ cores, 32 GB RAM, several workers |

* Set `MAX_CONCURRENT_JOBS` to the number of cores you can spare, and no more than RAM / 2.5 GB per video.
* **Disk:** a finished video is 30-80 MB. Once a video is on YouTube you do not need the local copy: for many members set
  `RETENTION_PUBLIC_DAYS=1` and keep `MEMBER_STORAGE_MB` modest. Defaults: public 7 days, declined 2 days, waiting for a decision 30 days.
* **YouTube is the real limit.** Google gives a new project about 10,000 units a day = **about 6 uploads for everybody together**.
  For hundreds of members you must request a bigger quota from Google (YouTube API Services -> quota extension form). Until it is
  approved, uploads wait in the queue and go out as the daily allowance allows. Start small and apply for the extension early.
* **Several machines:** all workers must see the same `outputs/inputs` folders (network storage) and the same database. One big
  server is far simpler; add machines only when one is not enough.

## Security checklist
- Change the owner password to a long one (Settings -> My preferences). Never leave a short password on a public server.
- The database is not reachable from the internet (no published port). Only ports 22, 80, 443 are open.
- `config/.env` holds your keys: keep it private (`chmod 600 config/.env`) and out of any shared folder.
- The server limits requests per visitor, blocks repeated wrong passwords, and sends strict security headers.
- Keep Ubuntu updated: `sudo apt update && sudo apt upgrade -y` now and then.
