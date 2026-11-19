"""Command line entry:  python worker.py [--role web|worker|all] [--show-setup-code]"""
import os
import sys
import time

from app.runtime import HOST, PORT, ROLE


def main() -> None:
    if "--show-setup-code" in sys.argv:
        from app.utils.envfile import setup_code
        print("Setup code:", setup_code())
        sys.exit(0)
    from app.services.maintenance_service import boot
    boot()
    if ROLE == "worker":      # no website in this process: it only renders, schedules and uploads
        while True:
            time.sleep(3600)
    from waitress import serve

    from app import create_app
    print(f"Studio dashboard: http://localhost:{PORT}")
    serve(create_app(), host=HOST, port=PORT, threads=int(os.environ.get("WEB_THREADS") or 48), ident="Studio",
          clear_untrusted_proxy_headers=False, channel_timeout=300)
