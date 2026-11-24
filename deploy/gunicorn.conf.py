"""gunicorn settings for the Clip Studio dashboard.  Started by deploy/clipstudio-web.service:   gunicorn -c deploy/gunicorn.conf.py wsgi:app

Change the numbers with environment variables in the service file (or `systemctl edit clipstudio-web`), no need to edit this file:
    WEB_WORKERS   how many gunicorn processes (default 2)          WEB_THREADS   requests each one handles at once (default 16)
    WEB_BIND      address (default 127.0.0.1:8765, nginx talks to it)   WEB_TIMEOUT   seconds a worker may be silent (default 600)
"""
import os

bind = os.environ.get("WEB_BIND", "127.0.0.1:8765")
workers = int(os.environ.get("WEB_WORKERS", "2"))
threads = int(os.environ.get("WEB_THREADS", "16"))
worker_class = "gthread"                  # threads per worker: video preview streaming, uploads and long polling need many requests at once
timeout = int(os.environ.get("WEB_TIMEOUT", "600"))     # the editor takes uploads of up to 2 GB: a slow upload must not be cut off
graceful_timeout = 30
keepalive = 5
max_requests = 0                          # never recycle a worker on a counter: scans and research run in a worker's background threads
worker_tmp_dir = "/dev/shm"               # keeps gunicorn's heartbeat file off the disk
forwarded_allow_ips = "127.0.0.1"         # only nginx on this machine may say "this request came over https"
proc_name = os.environ.get("WEB_NAME", "clipstudio-web")      # shows in `ps` and in the journal, one name per studio on this machine
accesslog = "-"                           # to the journal: journalctl -u clipstudio-web -f
errorlog = "-"
loglevel = "info"
