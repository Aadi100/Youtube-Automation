"""Backup, restore and "move to another server" for the whole studio, without needing mongodump.

  python datatool.py export  studio-data.tar.gz            everything: accounts, members' games/videos/clips, schedules, tokens, ledger ...
  python datatool.py import  studio-data.tar.gz            load it into the database this machine points at (MONGODB_URI / MONGODB_DB)
  python datatool.py backup  [--dir backups] [--keep 7]    a dated backup file; the oldest ones are deleted (run it every night)
  python datatool.py files   studio-files.tar.gz           the video / thumbnail files too (can be large; optional)

Not included on purpose: login sessions and rate-limit counters. Your .env is NOT included (it holds secrets).
IMPORTANT when you move to a new server: copy TOKEN_ENC_KEY from the old .env to the new one, otherwise the saved YouTube
logins of your members cannot be decrypted and they would have to connect their channels again.
"""
import argparse
import io
import json
import tarfile
import time
from pathlib import Path

import bson

from app.config import BASE_DIR, MONGODB_DB
from app.models import connect, create_indexes

SKIP = {"sessions", "auth_attempts", "oauth_states", "yt_quota"}


def _add(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = time.time()
    tar.addfile(info, io.BytesIO(data))


def _models() -> dict:
    """collection name -> model, for every model except the short-lived ones (sessions, login attempts ...)."""
    from app import models
    return {m._meta["collection"]: m for m in models.ALL if m._meta["collection"] not in SKIP}


def export_db(path: Path) -> dict:
    connect()
    counts = {}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tar:
        for name, M in sorted(_models().items()):
            buf = io.BytesIO()
            n = 0
            for doc in M.objects.as_pymongo():     # the stored documents exactly as they are (BSON), no model validation
                buf.write(bson.encode(doc))
                n += 1
            counts[name] = n
            _add(tar, f"{name}.bson", buf.getvalue())
        _add(tar, "meta.json", json.dumps({"made": time.strftime("%Y-%m-%d %H:%M:%S"), "database": MONGODB_DB, "counts": counts}).encode())
    return counts


def import_db(path: Path, replace: bool = True) -> dict:
    connect()
    counts = {}
    known = _models()
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            if not m.name.endswith(".bson"):
                continue
            name = m.name[:-5]
            M = known.get(name)
            if M is None:
                continue
            docs = bson.decode_all(tar.extractfile(m).read())
            if replace:
                M.objects.delete()
            col = M._get_collection()       # bulk restore of already-valid documents
            for i in range(0, len(docs), 500):
                col.insert_many(docs[i:i + 500], ordered=False)
            counts[name] = len(docs)
    create_indexes()
    return counts


def backup(directory: Path, keep: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / f"studio-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    export_db(out)
    old = sorted(directory.glob("studio-*.tar.gz"))
    for f in old[:-keep]:
        f.unlink()
    return out


def export_files(path: Path) -> int:
    n = 0
    with tarfile.open(path, "w:gz") as tar:
        for sub in ("outputs/shorts", "outputs/compilations", "music"):
            p = BASE_DIR / sub
            if p.exists():
                tar.add(p, arcname=sub)
                n += sum(1 for _ in p.rglob("*") if _.is_file())
    return n


def import_files(path: Path) -> None:
    with tarfile.open(path, "r:gz") as tar:
        for m in tar.getmembers():
            target = (BASE_DIR / m.name).resolve()
            if not str(target).startswith(str(BASE_DIR.resolve())):   # never write outside the app folder
                raise SystemExit(f"unsafe path in archive: {m.name}")
        tar.extractall(BASE_DIR)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["export", "import", "backup", "files", "unpack-files"])
    ap.add_argument("file", nargs="?")
    ap.add_argument("--dir", default="backups")
    ap.add_argument("--keep", type=int, default=7)
    a = ap.parse_args()
    if a.cmd == "export":
        print(export_db(Path(a.file or "studio-data.tar.gz")))
    elif a.cmd == "import":
        print(import_db(Path(a.file)))
    elif a.cmd == "backup":
        print("backup written:", backup(Path(a.dir), a.keep))
    elif a.cmd == "files":
        print("files packed:", export_files(Path(a.file or "studio-files.tar.gz")))
    else:
        import_files(Path(a.file))
        print("files restored")
