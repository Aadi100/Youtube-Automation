"""WSGI entry for gunicorn (Linux server):  gunicorn -c deploy/gunicorn.conf.py wsgi:app

This process is the DASHBOARD AND API ONLY. Rendering videos, the schedule, uploads and the clean-up run in the separate worker service
(`python -u worker.py` with STUDIO_ROLE=worker, see deploy/clipstudio-worker.service). Several gunicorn workers can therefore run side by side
without each of them also starting its own video makers.
On a Windows PC keep using `python worker.py` (it serves the dashboard with waitress and runs the workers in the same process).
"""
import os

os.environ["STUDIO_ROLE"] = "web"          # must be set before the app is imported: it decides which background parts start

from app.services.maintenance_service import boot  # noqa: E402

boot()                                      # database check, indexes, the first-start message (no background threads for the web role)

from app import create_app  # noqa: E402

app = create_app()
