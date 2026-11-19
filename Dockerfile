# Clip Studio: one image, used for the website (web) and for the render workers (worker).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/state/cache/hf XDG_CACHE_HOME=/app/state/cache

# ffmpeg = video, nodejs = lets yt-dlp read YouTube, liberation/dejavu fonts = captions look right (Arial-compatible), curl = health check
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg curl ca-certificates gnupg fontconfig fonts-liberation fonts-dejavu-core libgl1 libglib2.0-0 \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN useradd -m -u 1000 app && mkdir -p /app/outputs /app/inputs /app/temp /app/state /app/music /app/backups && chown -R app:app /app
USER app

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD curl -fsS http://127.0.0.1:8765/healthz || exit 1

# STUDIO_ROLE decides what this container does: web | worker (set in docker-compose.yml)
CMD ["sh", "-c", "touch /app/.env && exec python -u worker.py"]
