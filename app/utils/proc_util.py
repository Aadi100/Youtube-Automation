"""Starting and stopping child processes the same way on Windows (your PC) and Linux (the VPS)."""
import os
import signal
import subprocess

POSIX = os.name != "nt"
NEW_GROUP = {"start_new_session": True} if POSIX else {}   # children get their own group so the whole tree can be stopped


def kill_tree(proc) -> None:
    """Stop a process and everything it started (yt-dlp -> ffmpeg, pipeline -> ffmpeg ...)."""
    if proc is None:
        return
    try:
        if POSIX:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
