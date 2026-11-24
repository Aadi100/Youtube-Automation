#!/usr/bin/env bash
# =====================================================================================================================================
# Clip Studio on a plain Ubuntu / Debian VPS. No Docker. The database is MongoDB Atlas (nothing database-related is installed here).
# Built to share the machine with OTHER APPS: everything it installs has its own name (folder /opt/<name>, user, services, port, database, nginx site),
# it brings its own Node.js and Python packages, and it never changes what your other apps use: no upgrade of the system Node.js or Python, no restart
# of nginx (only a reload), no removal of other nginx sites, no change of the firewall unless you ask for it.
#
#   BEFORE you start
#     * A VPS with Ubuntu 22.04 / 24.04 or Debian 12 (plan about 4 CPU cores, 8 GB RAM and 80 GB disk for each busy studio). Log in as root.
#     * A domain name with an A record  studio.yourdomain.com -> the VPS IP address (needed for HTTPS and for Google sign-in).
#     * MongoDB Atlas: a cluster, a database user, and in "Network Access" the VPS IP address allowed.
#       Your connection string looks like  mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
#       (if the password has special characters such as @ : / # ? they must be URL-encoded, for example @ becomes %40).
#
#   FIRST INSTALL
#     1. On your PC, in the project folder, pack the program WITHOUT your videos and WITHOUT your .env (it holds your keys):
#            tar --exclude=.git --exclude=outputs --exclude=inputs --exclude=temp --exclude=.env --exclude=__pycache__ --exclude=state/avatars --exclude=state/brands --exclude=state/filmstrips --exclude=state/cache -czf ../clipstudio.tar.gz .
#            scp ../clipstudio.tar.gz root@SERVER_IP:/root/
#     2. On the server:
#            ssh root@SERVER_IP
#            mkdir -p clipstudio-upload && tar -xzf clipstudio.tar.gz -C clipstudio-upload && cd clipstudio-upload
#            DOMAIN=studio.yourdomain.com LE_EMAIL=you@example.com MONGODB_URI='mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority' bash deploy/setup_vps.sh
#     No DOMAIN yet: run it with the server's public IP instead. No nginx, no HTTPS: the dashboard is then on http://SERVER_IP:PORT
#            PUBLIC_HOST=203.0.113.10 MONGODB_URI='...' bash deploy/setup_vps.sh
#     (Google refuses sign-in redirects to a bare IP, so connecting a NEW YouTube channel needs the domain; everything else works.)
#     LATER, WHEN YOU HAVE THE DOMAIN (A record -> the server IP): run the same command again with  DOMAIN=studio.yourdomain.com LE_EMAIL=you@example.com
#     instead of PUBLIC_HOST. It adds nginx + HTTPS, switches the studio's address to https://studio.yourdomain.com and keeps all your data.
#
#   ANOTHER CLIP STUDIO (optional) ON THE SAME MACHINE: the same command with another name, domain and database. Nothing else is shared.
#            APP_NAME=studio2 DOMAIN=studio2.yourdomain.com MONGODB_URI='...' bash deploy/setup_vps.sh
#
#   UPDATE LATER (pack and upload the new version the same way into a fresh folder, then run inside it; name the studio if it is not the first)
#            bash deploy/update.sh              or          APP_NAME=studio2 bash deploy/update.sh
#
#   SEE WHAT IT WILL DO WITHOUT CHANGING ANYTHING (no root needed; writes the service and nginx files for these settings into a folder):
#            APP_NAME=studio2 DOMAIN=studio2.yourdomain.com bash deploy/setup_vps.sh --preview /tmp/preview
#
#   Settings (put them in front of the command; every one has a default):
#       APP_NAME=clipstudio   the name of this studio. It names the folder /opt/<name>, the user, the services <name>-web / <name>-worker /
#                             <name>-backup, the nginx site, /var/backups/<name> and (unless you say otherwise) the database.  letters, digits, - only
#       DOMAIN=               its domain (nginx + HTTPS). Empty = no nginx
#       PUBLIC_HOST=          the server's PUBLIC IP, for a studio without a domain (the address people type). Needed on providers where the server
#                             only sees a private address; if empty it is looked up on the internet
#       PORT=8765             the fixed port of its dashboard (always this one, it never changes by itself). Choose another with PORT=... ;
#                             if the port is taken by something else the script stops and tells you, it does not pick one for you
#       MONGODB_URI=          the Atlas connection string       MONGODB_DB=<APP_NAME>   its own database (never share one between studios)
#       LE_EMAIL=             Let's Encrypt writes to it before a certificate runs out; without it nobody is warned
#       ENABLE_FIREWALL=1     turn the firewall (ufw) on if it is off, with SSH + the ports this studio needs. Without it a firewall that is off
#                             stays off (turning it on could block your other apps); a firewall that is already on only gets the new rules
#       SSH_PORT=22           if your SSH is on another port
#       APP_DIR=/opt/<name>   APP_USER=<name>
#
#   Everyday commands on the server (replace clipstudio by your APP_NAME)
#       The dashboard (gunicorn) and the video makers (worker) are two services:
#       systemctl status clipstudio-web clipstudio-worker           systemctl restart clipstudio-web      (restarting the dashboard never interrupts a video)
#       journalctl -u clipstudio-web -f      journalctl -u clipstudio-worker -f                            (live logs)
#       systemctl list-timers clipstudio-backup.timer                              ls /var/backups/clipstudio       (nightly backups)
#       cd /opt/clipstudio && sudo -u clipstudio venv/bin/python worker.py --show-setup-code     (code for the first owner account)
# =====================================================================================================================================
set -Eeuo pipefail

APP_NAME="${APP_NAME:-clipstudio}"
DOMAIN="${DOMAIN:-}"
PORT="${PORT:-}"
MONGODB_URI="${MONGODB_URI:-}"
ENABLE_FIREWALL="${ENABLE_FIREWALL:-0}"
LE_EMAIL="${LE_EMAIL:-}"
PUBLIC_HOST="${PUBLIC_HOST:-}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="install"
PREVIEW_DIR=""
case "${1:-}" in
  --update)  MODE="update" ;;
  --preview) MODE="preview"; PREVIEW_DIR="${2:-}" ;;
esac

say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
trap 'die "stopped at line $LINENO. Fix the problem and run the same command again (it is safe to repeat)."' ERR

# the name of this studio decides every other name, so it must be safe to use in file names, user names and service names
[[ "$APP_NAME" =~ ^[a-z][a-z0-9-]{1,30}$ ]] || die "APP_NAME must be 2 to 31 letters, digits or - and start with a letter (lower case), for example studio2"
APP_DIR="${APP_DIR:-/opt/$APP_NAME}"
APP_USER="${APP_USER:-$APP_NAME}"
MONGODB_DB="${MONGODB_DB:-$APP_NAME}"
[[ "$MONGODB_DB" =~ ^[A-Za-z0-9_-]{1,38}$ ]] || die "MONGODB_DB may only have letters, digits, _ and -"
[ -z "$PORT" ] || { [[ "$PORT" =~ ^[0-9]{2,5}$ ]] && [ "$PORT" -ge 1024 ] && [ "$PORT" -le 65535 ]; } || die "PORT must be a number from 1024 to 65535"
[ -z "$DOMAIN" ] || [[ "$DOMAIN" =~ ^[A-Za-z0-9.-]+\.[A-Za-z]{2,}$ ]] || die "DOMAIN must look like studio.example.com (no https://, no path)"
[ -z "$PUBLIC_HOST" ] || [[ "$PUBLIC_HOST" =~ ^[A-Za-z0-9.:-]+$ ]] || die "PUBLIC_HOST must be an IP address like 203.0.113.10 (no http://, no port)"
WEB_UNIT="/etc/systemd/system/${APP_NAME}-web.service"

as_app() { sudo -u "$APP_USER" env HOME="$APP_DIR" "$@"; }       # run a command as this studio's user

# ------------------------------------------------------------------------------------------------ the address people type (no domain yet)
guess_public_host() {
  # on many providers the machine itself only knows a private address (10.x, 172.x, 192.168.x); the studio must be told the public one,
  # because it only answers requests addressed to the address in PUBLIC_BASE_URL
  if [ -n "$PUBLIC_HOST" ]; then echo "$PUBLIC_HOST"; return; fi
  local ip; ip="$(curl -fsS --max-time 8 https://api.ipify.org 2>/dev/null || true)"
  if [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo "$ip"; return; fi
  hostname -I | awk '{print $1}'
}
set_env() {   # set_env KEY VALUE: change the line in this studio's .env, or add it
  local f="$APP_DIR/.env"
  if grep -q "^$1=" "$f"; then sed -i "s|^$1=.*|$1=$2|" "$f"; else printf '%s=%s\n' "$1" "$2" >> "$f"; fi
}

# ------------------------------------------------------------------------------------------------ ports
port_in_use() { ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]$1\$"; }
default_port() {
  # the port is fixed: the one you gave, else the one this studio already has, else 8765. It is never changed behind your back.
  local own; own="$(grep -hs '^Environment=STUDIO_PORT=' "$WEB_UNIT" 2>/dev/null | head -1 | cut -d= -f3 || true)"
  echo "${own:-8765}"
}

# ------------------------------------------------------------------------------------------------ the files for this studio, from the templates
render() {   # render <template> <destination>
  sed -e "s|@@APP_NAME@@|$APP_NAME|g" -e "s|@@APP_USER@@|$APP_USER|g" -e "s|@@APP_DIR@@|$APP_DIR|g" \
      -e "s|@@PORT@@|$PORT|g" -e "s|@@BIND@@|$BIND|g" -e "s|@@DOMAIN@@|$DOMAIN|g" "$SRC_DIR/deploy/$1" > "$2"
}

if [ "$MODE" = "preview" ]; then
  [ -n "$PREVIEW_DIR" ] || die "usage: bash deploy/setup_vps.sh --preview SOME_EMPTY_FOLDER"
  PORT="${PORT:-8765}"; if [ -n "$DOMAIN" ]; then BIND="127.0.0.1:$PORT"; else BIND="0.0.0.0:$PORT"; fi
  mkdir -p "$PREVIEW_DIR"
  render web.service "$PREVIEW_DIR/${APP_NAME}-web.service"; render worker.service "$PREVIEW_DIR/${APP_NAME}-worker.service"
  render backup.service "$PREVIEW_DIR/${APP_NAME}-backup.service"; render backup.timer "$PREVIEW_DIR/${APP_NAME}-backup.timer"
  render ytdlp.service "$PREVIEW_DIR/${APP_NAME}-ytdlp.service"; render ytdlp.timer "$PREVIEW_DIR/${APP_NAME}-ytdlp.timer"
  [ -z "$DOMAIN" ] || render nginx.conf "$PREVIEW_DIR/nginx-$APP_NAME"
  echo "This studio would be:  name=$APP_NAME  folder=$APP_DIR  user=$APP_USER  database=$MONGODB_DB  port=$PORT  domain=${DOMAIN:-(none, no nginx)}"
  echo "The files it would install are in $PREVIEW_DIR (nothing on this machine was changed):"; ls -1 "$PREVIEW_DIR"
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die "run this as root (ssh in as root, or:  sudo -E bash deploy/setup_vps.sh)"
command -v apt-get >/dev/null || die "this script is for Ubuntu / Debian (it needs apt-get)"
[ -f "$SRC_DIR/worker.py" ] || die "run it from the Clip Studio folder (worker.py not found next to deploy/)"

# ------------------------------------------------------------------------------------------------ copy the code
sync_code() {
  say "Copying the program to $APP_DIR"
  mkdir -p "$APP_DIR"
  if [ "$SRC_DIR" != "$APP_DIR" ]; then
    # app/ is replaced as a whole (old files must not stay behind); your videos, settings and keys are never touched
    rsync -a --delete "$SRC_DIR/app/" "$APP_DIR/app/"
    rsync -a --include 'state/' --include 'state/playbook.json' --exclude 'state/*' --exclude '.git' --exclude '.env' --exclude 'outputs' --exclude 'inputs' --exclude 'temp' --exclude 'app' \
          --exclude '__pycache__' --exclude 'venv' --exclude '*.mp4' --exclude '*.tar.gz' "$SRC_DIR/" "$APP_DIR/"
  fi
  mkdir -p "$APP_DIR"/{outputs,inputs,temp,state,music}
  chown -R "$APP_USER:$APP_USER" "$APP_DIR"
}

make_venv() {
  say "Installing the Python packages into $APP_DIR/venv (the first time this takes several minutes)"
  if [ ! -x "$APP_DIR/venv/bin/python" ]; then
    as_app python3 -m venv "$APP_DIR/venv"
  fi
  as_app "$APP_DIR/venv/bin/pip" install --quiet --upgrade pip wheel
  as_app "$APP_DIR/venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
}

install_units() {
  # an earlier one-service install (clipstudio.service) is replaced by the two services below
  if [ "$APP_NAME" = "clipstudio" ] && [ -f /etc/systemd/system/clipstudio.service ]; then
    systemctl disable --now clipstudio >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/clipstudio.service
  fi
  render web.service "/etc/systemd/system/${APP_NAME}-web.service"
  render worker.service "/etc/systemd/system/${APP_NAME}-worker.service"
  render backup.service "/etc/systemd/system/${APP_NAME}-backup.service"
  render backup.timer "/etc/systemd/system/${APP_NAME}-backup.timer"
  render ytdlp.service "/etc/systemd/system/${APP_NAME}-ytdlp.service"
  render ytdlp.timer "/etc/systemd/system/${APP_NAME}-ytdlp.timer"
  chmod 644 /etc/systemd/system/${APP_NAME}-{web,worker,backup,ytdlp}.service /etc/systemd/system/${APP_NAME}-backup.timer /etc/systemd/system/${APP_NAME}-ytdlp.timer
  mkdir -p "/var/backups/$APP_NAME"
  chown "$APP_USER:$APP_USER" "/var/backups/$APP_NAME"
}

install_private_node() {
  # yt-dlp needs Node.js to read YouTube. This studio gets its OWN copy in $APP_DIR/node (the services put it first in their PATH), so the
  # Node.js of your other apps is never upgraded or replaced.
  if [ -x "$APP_DIR/node/bin/node" ]; then return; fi
  say "Installing Node.js for this studio only (the system's own Node.js is not touched)"
  local arch file want tmp base="https://nodejs.org/dist/latest-v20.x"
  case "$(uname -m)" in x86_64) arch=x64 ;; aarch64|arm64) arch=arm64 ;; *) die "no Node.js download for this CPU ($(uname -m))" ;; esac
  file="$(curl -fsSL "$base/SHASUMS256.txt" | awk -v a="linux-$arch.tar.gz" '$2 ~ a"$" {print $2; exit}')"
  [ -n "$file" ] || die "could not find the Node.js download on nodejs.org"
  want="$(curl -fsSL "$base/SHASUMS256.txt" | awk -v f="$file" '$2 == f {print $1}')"
  tmp="$(mktemp -d)"
  curl -fsSL "$base/$file" -o "$tmp/node.tar.gz"
  echo "$want  $tmp/node.tar.gz" | sha256sum -c - >/dev/null || die "the Node.js download is damaged (checksum does not match)"
  mkdir -p "$APP_DIR/node"
  tar -xzf "$tmp/node.tar.gz" -C "$APP_DIR/node" --strip-components=1
  rm -rf "$tmp"
  chown -R "$APP_USER:$APP_USER" "$APP_DIR/node"
}

wait_for_studio() {
  say "Starting $APP_NAME"
  systemctl restart "${APP_NAME}-worker"
  systemctl restart "${APP_NAME}-web"
  for _ in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:$PORT/healthz" >/dev/null 2>&1; then
      echo "The dashboard answers on port $PORT."
      sleep 3
      systemctl is-active --quiet "${APP_NAME}-worker" || { journalctl -u "${APP_NAME}-worker" -n 30 --no-pager || true; die "the video workers did not stay up. The last log lines are above."; }
      echo "The video workers are running."
      return 0
    fi
    sleep 2
  done
  journalctl -u "${APP_NAME}-web" -n 40 --no-pager || true
  die "the dashboard did not start. The last log lines are above (usually the database address in $APP_DIR/.env, or Atlas not allowing this server's IP)."
}

# ------------------------------------------------------------------------------------------------ update only
if [ "$MODE" = "update" ]; then
  id "$APP_USER" >/dev/null 2>&1 && [ -f "$WEB_UNIT" ] || die "'$APP_NAME' is not installed here yet (no $WEB_UNIT). Run deploy/setup_vps.sh first, or give its APP_NAME"
  # keep what this studio already uses: its port, and whether it sits behind nginx
  PORT="$(grep -h '^Environment=STUDIO_PORT=' "$WEB_UNIT" | head -1 | cut -d= -f3 || true)"; PORT="${PORT:-8765}"
  BIND="$(grep -h '^Environment=WEB_BIND=' "$WEB_UNIT" | head -1 | cut -d= -f3 || true)"; BIND="${BIND:-127.0.0.1:$PORT}"
  install_private_node
  sync_code
  make_venv
  install_units
  systemctl daemon-reload
  systemctl enable --now "${APP_NAME}-backup.timer" "${APP_NAME}-ytdlp.timer" >/dev/null 2>&1 || true   # timers added by a newer version get switched on too
  wait_for_studio
  say "$APP_NAME is updated."
  exit 0
fi

# ------------------------------------------------------------------------------------------------ checks before anything is installed
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null || die "Python 3.10 or newer is needed (Ubuntu 22.04 or 24.04, Debian 12 have it)"
if [ -z "$MONGODB_URI" ] && ! grep -qs '^MONGODB_URI=' "$APP_DIR/.env" 2>/dev/null; then
  die "give the MongoDB Atlas connection string:  MONGODB_URI='mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority' bash deploy/setup_vps.sh"
fi
if [ -n "$MONGODB_URI" ]; then
  case "$MONGODB_URI" in mongodb://*|mongodb+srv://*) ;; *) die "MONGODB_URI must start with mongodb+srv:// (Atlas) or mongodb://" ;; esac
  case "$MONGODB_URI" in *"<"*|*">"*) die "the connection string still has < > in it (the user name and the password must be written without them)" ;; esac
fi
# another studio must not share this one's database, folder or domain by accident
for other in /etc/systemd/system/*-web.service; do
  [ -e "$other" ] && [ "$other" != "$WEB_UNIT" ] || continue
  o_dir="$(grep -h '^WorkingDirectory=' "$other" | head -1 | cut -d= -f2 || true)"
  [ "$o_dir" != "$APP_DIR" ] || die "the folder $APP_DIR already belongs to $(basename "$other" -web.service). Give this studio its own APP_NAME"
  if [ -f "$o_dir/.env" ] && grep -qs "^MONGODB_DB=$MONGODB_DB\$" "$o_dir/.env"; then
    die "the database '$MONGODB_DB' is already used by $(basename "$other" -web.service). Give this studio its own MONGODB_DB"
  fi
done
if [ -n "$DOMAIN" ] && grep -rlsE "server_name[^;]*[[:space:]]$DOMAIN[[:space:];]" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null | grep -v "/$APP_NAME\$" | grep -q .; then
  die "the domain $DOMAIN is already served by another nginx site on this machine (see /etc/nginx/sites-enabled). Use another domain or remove that site"
fi
[ -n "$PORT" ] || PORT="$(default_port)"
for other in /etc/systemd/system/*-web.service; do      # another studio on this machine that already has this port
  [ -e "$other" ] && [ "$other" != "$WEB_UNIT" ] && grep -qs "^Environment=STUDIO_PORT=$PORT\$" "$other" && die "port $PORT already belongs to $(basename "$other" -web.service). Give this studio its own, for example PORT=8766"
done
if [ -n "$DOMAIN" ]; then BIND="127.0.0.1:$PORT"; else BIND="0.0.0.0:$PORT"; fi    # no domain = no nginx: gunicorn itself is the public address (a first test only)
if port_in_use "$PORT" && ! systemctl is-active --quiet "${APP_NAME}-web"; then die "port $PORT is already in use by another program on this machine. Choose another one for this studio, for example PORT=8766 bash deploy/setup_vps.sh   (see what uses it:  ss -ltnp | grep :$PORT)"; fi
say "Installing: name=$APP_NAME  folder=$APP_DIR  database=$MONGODB_DB  port=$PORT  domain=${DOMAIN:-(none)}"

# ------------------------------------------------------------------------------------------------ system packages (shared by every studio)
say "Installing system packages (video tools, fonts, Python, rsync)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends python3 python3-venv python3-pip ffmpeg curl ca-certificates gnupg fontconfig \
        fonts-liberation fonts-dejavu-core libgl1 libglib2.0-0 rsync ufw sudo iproute2

if [ -n "$DOMAIN" ]; then
  if port_in_use 80 && ! ss -ltnpH 2>/dev/null | grep -E '[:.]80[[:space:]]' | grep -q nginx; then
    die "port 80 is already used by another web server (not nginx), for example Apache. Use that one for this site, or stop it first. Nothing was changed."
  fi
  say "Installing nginx and certbot (the HTTPS front door); parts that are already there are kept"
  apt-get install -y --no-install-recommends nginx certbot python3-certbot-nginx
fi

# ------------------------------------------------------------------------------------------------ the program
if ! id "$APP_USER" >/dev/null 2>&1; then
  say "Creating the user $APP_USER"
  useradd --system --create-home --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi
install_private_node
sync_code
make_venv

# ------------------------------------------------------------------------------------------------ settings (.env): written once, never overwritten
if [ ! -f "$APP_DIR/.env" ]; then
  say "Writing $APP_DIR/.env"
  if [ -n "$DOMAIN" ]; then BASE_URL="https://$DOMAIN"; else BASE_URL="http://$(guess_public_host):$PORT"; fi
  cat > "$APP_DIR/.env" <<EOF
# $APP_NAME (Clip Studio) settings. The dashboard (Settings) writes your keys here too. Keep this file private.
MONGODB_URI=$MONGODB_URI
MONGODB_DB=$MONGODB_DB
MONGODB_TIMEOUT_MS=20000
PUBLIC_BASE_URL=$BASE_URL
MAX_CONCURRENT_JOBS=2
UPLOAD_THREADS=2
MEMBER_STORAGE_MB=3000
# When you MOVE from your PC, copy the TOKEN_ENC_KEY line from the old .env here, or saved YouTube logins cannot be read:
# TOKEN_ENC_KEY=
EOF
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
else
  echo "$APP_DIR/.env already exists: your settings and keys are kept."
  if [ -n "$MONGODB_URI" ] && ! grep -q '^MONGODB_URI=' "$APP_DIR/.env"; then
    printf 'MONGODB_URI=%s\nMONGODB_DB=%s\nMONGODB_TIMEOUT_MS=20000\n' "$MONGODB_URI" "$MONGODB_DB" >> "$APP_DIR/.env"
  fi
  # a new domain (or a corrected public IP) changes the address the studio answers to and uses in links, so it is updated here
  if [ -n "$DOMAIN" ]; then set_env PUBLIC_BASE_URL "https://$DOMAIN"; echo "The studio's address is now https://$DOMAIN";
  elif [ -n "$PUBLIC_HOST" ]; then set_env PUBLIC_BASE_URL "http://$PUBLIC_HOST:$PORT"; echo "The studio's address is now http://$PUBLIC_HOST:$PORT"; fi
fi

# ------------------------------------------------------------------------------------------------ services
say "Installing the services of $APP_NAME"
install_units
systemctl daemon-reload
systemctl enable "${APP_NAME}-web" "${APP_NAME}-worker" >/dev/null 2>&1
systemctl enable --now "${APP_NAME}-backup.timer" "${APP_NAME}-ytdlp.timer" >/dev/null 2>&1

if [ -n "$DOMAIN" ]; then
  say "Setting up nginx for $DOMAIN (only this site; your other sites are not touched)"
  render nginx.conf "/etc/nginx/sites-available/$APP_NAME"
  chmod 644 "/etc/nginx/sites-available/$APP_NAME"
  ln -sf "/etc/nginx/sites-available/$APP_NAME" "/etc/nginx/sites-enabled/$APP_NAME"
  if ! nginx -t; then
    rm -f "/etc/nginx/sites-enabled/$APP_NAME"        # never leave a broken config that would take the other sites down
    die "nginx does not accept the new site. It was switched off again and your other sites are unchanged."
  fi
  systemctl enable nginx >/dev/null 2>&1
  systemctl reload nginx 2>/dev/null || systemctl start nginx    # reload keeps the other sites up without a break
fi

if ufw status 2>/dev/null | grep -q "Status: active" || [ "$ENABLE_FIREWALL" = "1" ]; then
  say "Firewall: adding what this studio needs (the rules of your other apps are kept)"
  SSH_PORT="${SSH_PORT:-$(awk '/^[[:space:]]*Port[[:space:]]/{print $2; exit}' /etc/ssh/sshd_config 2>/dev/null || true)}"
  ufw allow "${SSH_PORT:-22}/tcp" >/dev/null
  if [ -n "$DOMAIN" ]; then ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null; else ufw allow "$PORT/tcp" >/dev/null; fi
  if ufw status | grep -q "Status: inactive"; then ufw --force enable >/dev/null; echo "The firewall is now on (you asked for it with ENABLE_FIREWALL=1)."; fi
else
  echo "The firewall (ufw) is off and was left off, so your other apps keep working as they do. With a domain this studio listens only on 127.0.0.1 behind nginx."
  echo "To switch it on: ENABLE_FIREWALL=1 (it opens SSH and this studio's ports), or manage it yourself."
fi

if [ -n "$DOMAIN" ]; then
  say "Getting the HTTPS certificate for $DOMAIN (Let's Encrypt)"
  if [ -n "$LE_EMAIL" ]; then CERT_EMAIL=(-m "$LE_EMAIL"); else CERT_EMAIL=(--register-unsafely-without-email); fi
  if certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos "${CERT_EMAIL[@]}" --redirect; then
    echo "HTTPS is on. The certificate renews itself (certbot.timer)."
  else
    echo "WARNING: no certificate yet, so the site answers on http only. Check that the A record of $DOMAIN points at this server and that port 80 is open, then run:"
    echo "         certbot --nginx -d $DOMAIN --redirect"
  fi
fi

wait_for_studio

# ------------------------------------------------------------------------------------------------ what to do next
say "Done"
if [ -n "$DOMAIN" ]; then SITE="https://$DOMAIN"; else SITE="http://$(guess_public_host):$PORT"; fi
if [ -n "$DOMAIN" ]; then PORT_TEXT="80 and 443"; IPT_RULE="iptables -I INPUT 1 -p tcp --dport 80 -j ACCEPT; iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT"
else PORT_TEXT="$PORT"; IPT_RULE="iptables -I INPUT 1 -p tcp --dport $PORT -j ACCEPT"; fi
SETUP_CODE="$(cd "$APP_DIR" && as_app "$APP_DIR/venv/bin/python" worker.py --show-setup-code 2>/dev/null | tail -1 || true)"
cat <<EOF

  Studio:               $APP_NAME        folder $APP_DIR        database $MONGODB_DB        local port $PORT
  Open:                 $SITE      (with a domain the HTTPS certificate can take a minute the first time)
  If it does not open: the provider's own firewall (security group / security list in its control panel) must allow port $PORT_TEXT.
                        Some images (for example Oracle Cloud's Ubuntu) also block ports inside the server. Then run, as root:
                          $IPT_RULE
                          apt-get install -y iptables-persistent && netfilter-persistent save        (keeps it after a reboot)
  First account:        choose "Create the owner account". The one-time setup code is:  ${SETUP_CODE:-run: cd $APP_DIR && sudo -u $APP_USER venv/bin/python worker.py --show-setup-code}
  Google sign-in:       Google Cloud Console -> your OAuth client -> add this Authorized redirect URI:
                        $SITE/api/youtube/callback
                        then in the dashboard: Settings -> Accounts & keys -> paste the Google client ID and secret.
  Your keys:            Settings -> Accounts & keys (Gemini, DeepSeek, Claude, Twitch ...). They are saved in $APP_DIR/.env.
  Moving from your PC:  copy TOKEN_ENC_KEY from your PC's .env into $APP_DIR/.env, then  systemctl restart ${APP_NAME}-worker ${APP_NAME}-web.
  Services:             systemctl status ${APP_NAME}-web ${APP_NAME}-worker        logs: journalctl -u ${APP_NAME}-web -f
  Downloader:           yt-dlp is updated by itself every Monday (YouTube changes often; an old one stops working).
  Backups:              every night at about 03:30 into /var/backups/$APP_NAME (the last 7 are kept).
  Atlas:                keep this server's IP in Atlas -> Network Access. Atlas's free plan has no backups of its own.
  Another studio here:  APP_NAME=studio2 DOMAIN=studio2.yourdomain.com MONGODB_URI='...' bash deploy/setup_vps.sh   (own folder, port, database, nginx site)

EOF
