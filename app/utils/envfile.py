"""Read/write the local .env file (the dashboard Settings tab and the mailer both use it)."""
import secrets
from typing import Dict

from app.config import BASE_DIR

ENV_FILE = BASE_DIR / ".env"


def read_env() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def write_env(updates: Dict[str, str]) -> None:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    done = set()
    for i, line in enumerate(lines):
        k = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and k in updates:
            lines[i] = f"{k}={updates[k]}"
            done.add(k)
    lines += [f"{k}={v}" for k, v in updates.items() if k not in done]
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def studio_secret() -> str:
    """Shared secret between this server and the n8n 'approve & publish' webhook (created once)."""
    env = read_env()
    if not env.get("STUDIO_SECRET"):
        write_env({"STUDIO_SECRET": secrets.token_urlsafe(32)})
        env = read_env()
    return env["STUDIO_SECRET"]


def setup_code() -> str:
    """One-time code that proves you control the server when you create the very first (owner) account from another computer."""
    env = read_env()
    if not env.get("OWNER_SETUP_CODE"):
        write_env({"OWNER_SETUP_CODE": secrets.token_hex(4).upper()})
        env = read_env()
    return env["OWNER_SETUP_CODE"]
