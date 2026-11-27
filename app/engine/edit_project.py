"""The editor's projects: a timeline of several clips (from the member's sources) turned into one finished video.

A project is plain data (JSON):
    {"aspect": "9:16",
     "audio": {"music": {"ref": "lib:Song.mp3" | "src:<audio source id>", "start": 0, "volume": 0.3, "fade_in": 1, "fade_out": 2, "loop": true, "duck": true} | null},
     "clips": [{"id": "c1", "source": "<source id>", "start": 12.0, "end": 30.5,           # the part of the source this clip uses (seconds)
                "fit": "crop", "focus": {"x": .5, "y": .5}, "cam": null, "captions": false, "volume": 1.0, "fade_in": 0, "fade_out": 0,   # volume 0..2 (0 = silent)
                "speed": 1.0,                                                              # 0.25 (slow motion) .. 4 (fast forward)
                "zoom": null | {"from": 1.0, "to": 1.4, "x": .5, "y": .5},                  # the picture grows from `from` to `to` over the clip around the point x,y
                "transition": {"type": "fade", "duration": 0.6},                           # how this clip comes in after the previous one (not used on the first clip)
                "look": {"preset": "warm", "brightness": 0, "contrast": 1, "saturation": 1},   # colour: a preset and/or the member's own adjustments
                "pip": {"source": "<another video of the member>", "start": 0, "x": 1, "y": 0, "scale": .3, "t0": 0, "t1": 3, "border": true} | null,   # a reaction in a corner; its sound is not used
                "overlays": [{"id", "ref": "img:<image source id>", "x": .9, "y": .1, "scale": .15, "opacity": 1, "t0": 0, "t1": 3}]],   # stickers and logos (the member's own pictures); times like texts
                "texts": [{"text", "t0", "t1", "x", "y", "size", "color"}]}]}          # t0 / t1 are seconds INSIDE the clip (0 = the clip's first second)

Rendering reuses the single-video editor for every clip (cut, layout, captions, text), then joins the pieces without re-encoding them again.
Everything here is plain functions on files: no web, no accounts. Who may render what, and how many at a time, is decided by the service that calls this.
"""
import json
import re
import secrets
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from app.config import FFMPEG_BIN, FFPROBE_BIN
from app.engine import editor

MAX_CLIPS = 40
MAX_TEXTS_PER_CLIP = 10
MAX_OVERLAYS_PER_CLIP = 8
IMG_RE = re.compile(r"^img:[0-9a-f]{24}$")
MAX_DATA_BYTES = 200_000
MIN_CLIP = 0.3
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,24}$")


def empty() -> Dict:
    return {"aspect": "9:16", "clips": [], "audio": {"music": None}, "export": {"preset": None, "quality": "standard"}}


PRESETS = {      # where the video is going: its shape, and the longest it may be there (seconds)
    "yt_short": {"name": "YouTube Short", "aspect": "9:16", "max": 180},
    "tiktok": {"name": "TikTok", "aspect": "9:16", "max": 600},
    "reel": {"name": "Instagram Reel", "aspect": "9:16", "max": 90},
    "fb_reel": {"name": "Facebook Reel", "aspect": "9:16", "max": 90},
    "yt_video": {"name": "YouTube video", "aspect": "16:9", "max": 1800},
    "ig_feed": {"name": "Instagram feed", "aspect": "4:5", "max": 600},
}
QUALITY = {"draft": (0.5, 28, "Draft: small and fast, to check your work"), "standard": (1.0, 20, "Standard: full size"), "high": (1.0, 17, "High: full size, bigger file")}      # scale, crf, label


def export_of(data: Dict) -> Dict:
    ex = data.get("export") or {}
    return {"preset": ex.get("preset") if ex.get("preset") in PRESETS else None, "quality": ex.get("quality") if ex.get("quality") in QUALITY else "standard"}


def check_export(data: Dict) -> None:
    """The preset the member chose must fit the video: the right shape, and not longer than that place allows. Raises ValueError with a plain message."""
    ex = export_of(data)
    p = PRESETS.get(ex["preset"])
    if not p:
        return
    if data.get("aspect") != p["aspect"]:
        raise ValueError(f"{p['name']} needs the {p['aspect']} shape. Choose that preset again (it sets the shape) or pick another preset.")
    if total_seconds(data) > p["max"] + 0.5:
        raise ValueError(f"{p['name']} allows up to {int(p['max']) // 60}:{int(p['max']) % 60:02d}. Your video is {int(total_seconds(data)) // 60}:{int(total_seconds(data)) % 60:02d}. Shorten it or choose another preset.")


TRANSITIONS = {"none": "fade", "fade": "fade", "dissolve": "dissolve", "slideleft": "slideleft", "wipeleft": "wipeleft", "circleopen": "circleopen"}      # name -> ffmpeg's xfade
CUT = 0.04                       # a 'cut' inside a project that has transitions is a transition of one frame


def clip_seconds(c: Dict) -> float:
    """How long the clip is in the result: the part that is kept, divided by its speed."""
    return max(0.0, float(c["end"]) - float(c["start"])) / max(0.25, float(c.get("speed", 1.0)))


def total_seconds(data: Dict) -> float:
    """The clips one after the other (transitions overlap neighbouring clips a little, so the finished video is a little shorter)."""
    return round(sum(clip_seconds(c) for c in data.get("clips") or []), 2)


def transition_of(clips: List[Dict], i: int) -> float:
    """Seconds of overlap between clip i-1 and clip i (0 when the project uses no transitions at all)."""
    if i == 0 or not any((c.get("transition") or {}).get("type", "none") != "none" for c in clips):
        return 0.0
    t = clips[i].get("transition") or {}
    want = CUT if t.get("type", "none") == "none" else float(t.get("duration", 0.6))
    return max(CUT, min(want, 0.5 * clip_seconds(clips[i - 1]), 0.5 * clip_seconds(clips[i])))


def _num(v, default: float, lo: float, hi: float) -> float:
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return default


def clean_music(m, music_ok: Optional[Callable[[str], bool]]) -> Optional[Dict]:
    """The project's one music track. `music_ok(ref)` says whether this member may use that track (a library track, or an audio file of their own)."""
    if not isinstance(m, dict) or not m.get("ref"):
        return None
    ref = str(m["ref"])
    if not re.fullmatch(r"(lib:[\w .()\-]{1,120}|src:[0-9a-f]{24})", ref):
        raise ValueError("That music track is not valid.")
    if music_ok is not None and not music_ok(ref):
        raise ValueError("That music track is not available to you any more. Choose another one.")
    return {"ref": ref, "start": round(_num(m.get("start"), 0.0, 0.0, 36000.0), 2), "volume": round(_num(m.get("volume"), 0.3, 0.0, 1.0), 3),
            "fade_in": round(_num(m.get("fade_in"), 1.0, 0.0, 10.0), 2), "fade_out": round(_num(m.get("fade_out"), 2.0, 0.0, 10.0), 2),
            "loop": bool(m.get("loop", True)), "duck": bool(m.get("duck", True))}


def clean(data, infos: Dict[str, Dict], music_ok: Optional[Callable[[str], bool]] = None, image_ok: Optional[Callable[[str], bool]] = None) -> Dict:
    """Check and tidy what the browser sent. `infos` = {source id: {duration, width, height, has_audio}} of the sources this member owns.
    Raises ValueError with a plain message. Anything unknown is dropped, so a project can never carry surprises."""
    if not isinstance(data, dict):
        raise ValueError("The project is not valid.")
    aspect = data.get("aspect") if data.get("aspect") in editor.ASPECTS else "9:16"
    raw_clips = data.get("clips") or []
    if not isinstance(raw_clips, list):
        raise ValueError("The project is not valid.")
    if len(raw_clips) > MAX_CLIPS:
        raise ValueError(f"A project can have up to {MAX_CLIPS} clips.")
    clips, used = [], set()
    for c in raw_clips:
        if not isinstance(c, dict):
            continue
        sid = str(c.get("source") or "")
        if sid not in infos:
            raise ValueError("A clip uses a video that is not in your editor any more. Remove that clip or add the video again.")
        dur = float(infos[sid]["duration"])
        start = _num(c.get("start"), 0.0, 0.0, max(0.0, dur - MIN_CLIP))
        end = _num(c.get("end"), dur, start + MIN_CLIP, dur)
        if end - start < MIN_CLIP:
            continue
        cid = str(c.get("id") or "")
        if not ID_RE.match(cid) or cid in used:
            cid = secrets.token_hex(4)
        used.add(cid)
        fit = c.get("fit") if c.get("fit") in editor.FITS else "crop"
        if fit == "split" and aspect != "9:16":
            fit = "crop"
        focus = c.get("focus") if isinstance(c.get("focus"), dict) else {}
        cam = c.get("cam") if isinstance(c.get("cam"), dict) else None
        texts = []
        for t in (c.get("texts") or [])[:MAX_TEXTS_PER_CLIP]:
            if not isinstance(t, dict) or not str(t.get("text") or "").strip():
                continue
            col = str(t.get("color") or "#ffffff")
            t0 = _num(t.get("t0"), 0.0, 0.0, end - start)
            t1 = _num(t.get("t1"), end - start, t0, end - start)
            hx = lambda v, d: v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else d
            texts.append({"text": " ".join(str(t["text"]).split())[:120], "t0": round(t0, 2), "t1": round(t1 if t1 > t0 else end - start, 2),
                          "x": _num(t.get("x"), 0.5, 0, 1), "y": _num(t.get("y"), 0.5, 0, 1), "size": int(_num(t.get("size"), 64, 20, 200)),
                          "color": col if re.fullmatch(r"#[0-9a-fA-F]{6}", col) else "#ffffff",
                          "bold": bool(t.get("bold", True)), "italic": bool(t.get("italic", False)), "upper": bool(t.get("upper", False)),
                          "outline": hx(t.get("outline"), "#000000"), "ow": int(_num(t.get("ow"), 4, 0, 16)), "shadow": int(_num(t.get("shadow"), 1, 0, 8)),
                          "bg": hx(t.get("bg"), ""), "anim": t.get("anim") if t.get("anim") in editor.ANIMS else "none"})
        lk = c.get("look") if isinstance(c.get("look"), dict) else {}
        look = {"preset": lk.get("preset") if lk.get("preset") in editor.LOOKS else "none", "brightness": round(_num(lk.get("brightness"), 0.0, -0.5, 0.5), 3),
                "contrast": round(_num(lk.get("contrast"), 1.0, 0.5, 2.0), 3), "saturation": round(_num(lk.get("saturation"), 1.0, 0.0, 3.0), 3)}
        pp = c.get("pip") if isinstance(c.get("pip"), dict) else None
        pip = None
        if pp:
            psid = str(pp.get("source") or "")
            if psid not in infos:
                raise ValueError("The reaction video of a clip is not in your editor any more. Remove the picture-in-picture or choose another video.")
            pd = float(infos[psid]["duration"])
            p0 = _num(pp.get("t0"), 0.0, 0.0, end - start)
            p1 = _num(pp.get("t1"), end - start, p0, end - start)
            pip = {"source": psid, "start": round(_num(pp.get("start"), 0.0, 0.0, max(0.0, pd - 0.5)), 2), "x": round(_num(pp.get("x"), 1.0, 0, 1), 3), "y": round(_num(pp.get("y"), 0.0, 0, 1), 3),
                   "scale": round(_num(pp.get("scale"), 0.3, 0.1, 0.6), 3), "t0": round(p0, 2), "t1": round(p1 if p1 > p0 else end - start, 2), "border": bool(pp.get("border", True))}
        overlays = []
        for o in (c.get("overlays") or [])[:MAX_OVERLAYS_PER_CLIP]:
            if not isinstance(o, dict):
                continue
            ref = str(o.get("ref") or "")
            if not IMG_RE.match(ref):
                raise ValueError("A sticker or logo is not valid.")
            if image_ok is not None and not image_ok(ref):
                raise ValueError("A sticker or logo picture is not available to you any more. Remove it or upload it again.")
            o0 = _num(o.get("t0"), 0.0, 0.0, end - start)
            o1 = _num(o.get("t1"), end - start, o0, end - start)
            oid_ = str(o.get("id") or "")
            overlays.append({"id": oid_ if ID_RE.match(oid_) else secrets.token_hex(4), "ref": ref, "x": round(_num(o.get("x"), 0.9, 0, 1), 3), "y": round(_num(o.get("y"), 0.1, 0, 1), 3),
                             "scale": round(_num(o.get("scale"), 0.15, 0.03, 1.0), 3), "opacity": round(_num(o.get("opacity"), 1.0, 0.1, 1.0), 2),
                             "t0": round(o0, 2), "t1": round(o1 if o1 > o0 else end - start, 2)})
        length = end - start
        fi, fo = _num(c.get("fade_in"), 0.0, 0.0, length / 2), _num(c.get("fade_out"), 0.0, 0.0, length / 2)
        speed = _num(c.get("speed"), 1.0, 0.25, 4.0)
        zm = c.get("zoom") if isinstance(c.get("zoom"), dict) else None
        zf, zt = (_num(zm.get("from"), 1.0, 1.0, 3.0), _num(zm.get("to"), 1.0, 1.0, 3.0)) if zm else (1.0, 1.0)
        zoom = {"from": round(zf, 3), "to": round(zt, 3), "x": round(_num(zm.get("x"), 0.5, 0, 1), 3), "y": round(_num(zm.get("y"), 0.5, 0, 1), 3)} if (zm and (zf > 1.001 or zt > 1.001)) else None
        tr = c.get("transition") if isinstance(c.get("transition"), dict) else {}
        ttype = tr.get("type") if tr.get("type") in TRANSITIONS else "none"
        transition = {"type": ttype, "duration": round(_num(tr.get("duration"), 0.6, 0.2, 2.0), 2)}
        clips.append({"id": cid, "source": sid, "start": round(start, 2), "end": round(end, 2), "fit": fit,
                      "volume": round(_num(c.get("volume"), 1.0, 0.0, 2.0), 3), "fade_in": round(fi, 2), "fade_out": round(fo, 2),
                      "speed": round(speed, 3), "zoom": zoom, "transition": transition, "look": look, "pip": pip, "overlays": overlays,
                      "focus": {"x": _num(focus.get("x"), 0.5, 0, 1), "y": _num(focus.get("y"), 0.5, 0, 1)},
                      "cam": {k: _num(cam.get(k), d, 0, 1) for k, d in (("x", 0.0), ("y", 0.0), ("w", 0.3), ("h", 0.3))} if cam else None,
                      "captions": bool(c.get("captions")), "texts": texts})
    audio = data.get("audio") if isinstance(data.get("audio"), dict) else {}
    out = {"aspect": aspect, "clips": clips, "audio": {"music": clean_music(audio.get("music"), music_ok)}, "export": export_of(data)}
    st = data.get("story") if isinstance(data.get("story"), dict) else None
    if st:                                       # made by the Story videos feature: the finished video is marked as AI-made (and as realistic, which YouTube wants labelled)
        out["story"] = {"synthetic": bool(st.get("synthetic", True)), "realistic": bool(st.get("realistic"))}
    if total_seconds(out) > editor.MAX_OUTPUT_SECONDS:
        raise ValueError(f"A finished video can be up to {editor.MAX_OUTPUT_SECONDS // 60} minutes. Shorten some clips.")
    return out


def clip_spec(c: Dict, aspect: str, info: Dict, images: Optional[Dict[str, Path]] = None, quality: str = "standard", pip_files: Optional[Dict[str, Path]] = None) -> Dict:
    """One timeline clip as a spec of the single-video editor (its text times move from 'inside the clip' to 'seconds of the source').
    `images` = {image ref: file} for the stickers and logos of this clip; a sticker whose picture is not in it is left out."""
    s = float(c["start"])
    spec = {"segments": [[s, float(c["end"])]], "aspect": aspect, "fit": c["fit"], "focus": c["focus"], "cam": c["cam"], "captions": c["captions"],
            "texts": [{**t, "t0": s + t["t0"], "t1": s + t["t1"]} for t in c["texts"]],
            "volume": c.get("volume", 1.0), "fade_in": c.get("fade_in", 0.0), "fade_out": c.get("fade_out", 0.0), "speed": c.get("speed", 1.0), "zoom": c.get("zoom"), "look": c.get("look"), "scale": QUALITY.get(quality, QUALITY["standard"])[0], "crf": QUALITY.get(quality, QUALITY["standard"])[1]}
    out = editor.clean_spec(spec, info)
    length = max(0.1, float(c["end"]) - s)
    out["overlays"] = [{"path": str((images or {})[o["ref"]]), "x": o["x"], "y": o["y"], "scale": o["scale"], "opacity": o["opacity"], "t0": min(o["t0"], length), "t1": min(max(o["t1"], o["t0"] + 0.1), length)}
                       for o in (c.get("overlays") or []) if o["ref"] in (images or {})]
    pp = c.get("pip")
    if pp and pip_files and pp["source"] in pip_files:
        length = max(0.1, float(c["end"]) - s)
        out["pip"] = {"path": str(pip_files[pp["source"]]), "start": pp["start"], "x": pp["x"], "y": pp["y"], "scale": pp["scale"], "border": pp["border"],
                      "t0": min(pp["t0"], length), "t1": min(max(pp["t1"], pp["t0"] + 0.1), length)}
    return out


def _has_audio(p: Path) -> bool:
    try:
        return bool(editor.probe(p)["has_audio"])
    except Exception:
        return False


def _with_silence(src: Path, out: Path) -> Path:
    """A copy of a clip with a silent sound track, so that it can be joined to clips that have sound."""
    subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-i", str(src), "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)], check=True, timeout=600)
    return out


def xfade_join(parts: List[Path], clips: List[Dict], out: Path, threads: int = 0, crf: int = 20) -> Path:
    """Join the rendered clips with the chosen transitions. Needs a re-encode of the joined video (a plain join does not). Every part has a sound track, or none does."""
    n = len(parts)
    durs = [editor.probe(p)["duration"] for p in parts]
    audio = _has_audio(parts[0])
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y"] + (["-threads", str(int(threads))] if threads else [])
    for p in parts:
        cmd += ["-i", str(p)]
    g, acc, vlabel, alabel = [], durs[0], "[0:v]", "[0:a]"
    for i in range(1, n):
        t = min(transition_of(clips, i), 0.5 * acc, 0.5 * durs[i])
        t = max(CUT, t)
        name = TRANSITIONS[(clips[i].get("transition") or {}).get("type", "none")]
        g.append(f"{vlabel}[{i}:v]xfade=transition={name}:duration={t:.3f}:offset={max(0.0, acc - t):.3f}[v{i}]")
        vlabel = f"[v{i}]"
        if audio:
            g.append(f"{alabel}[{i}:a]acrossfade=d={t:.3f}[a{i}]")
            alabel = f"[a{i}]"
        acc = acc + durs[i] - t
    cmd += ["-filter_complex", ";".join(g), "-map", vlabel] + (["-map", alabel, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2"] if audio else [])
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", str(int(crf)), "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True, timeout=3600, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError("The transitions could not be added: " + " ".join((e.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-2:])[:200]) from e
    return out


def probe_audio(path: Path) -> float:
    """Length in seconds of an audio file. Raises ValueError when it is not audio."""
    try:
        d = json.loads(subprocess.check_output([FFPROBE_BIN, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60))
    except Exception:
        raise ValueError("That file could not be read as audio.")
    if not any(s.get("codec_type") == "audio" for s in d.get("streams", [])):
        raise ValueError("That file has no sound.")
    dur = float(d.get("format", {}).get("duration") or 0)
    if dur <= 0:
        raise ValueError("That audio file is empty.")
    return dur


def mix_music(video: Path, music: Dict, track: Path, out: Path, total: float, has_audio: bool, threads: int = 0) -> Path:
    """Lay the music track under the joined video without touching the picture (the video stream is copied). The music is faded in and out, can loop, and (when `duck`)
    gets quieter whenever the video's own sound is loud, so speech stays clear."""
    start, vol = float(music["start"]), float(music["volume"])
    fi, fo = float(music["fade_in"]), float(music["fade_out"])
    chain = ["aresample=48000", "aformat=channel_layouts=stereo"] + ([f"atrim=start={start:.2f}", "asetpts=PTS-STARTPTS"] if start > 0 else []) + [f"volume={vol:.3f}"]
    if fi > 0:
        chain.append(f"afade=t=in:st=0:d={fi:.2f}")
    if fo > 0:
        chain.append(f"afade=t=out:st={max(0.0, total - fo):.2f}:d={fo:.2f}")
    g = [f"[1:a]{','.join(chain)}[m]"]
    if has_audio and music.get("duck", True):
        g += ["[0:a]asplit=2[sc][vo]", "[m][sc]sidechaincompress=threshold=0.03:ratio=10:attack=15:release=400[md]", "[vo][md]amix=inputs=2:duration=first:normalize=0[aout]"]
    elif has_audio:
        g += ["[0:a][m]amix=inputs=2:duration=first:normalize=0[aout]"]
    else:
        g += [f"[m]atrim=duration={total:.2f}[aout]"]
    cmd = [FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y"] + (["-threads", str(int(threads))] if threads else []) + ["-i", str(video)]
    cmd += (["-stream_loop", "-1"] if music.get("loop", True) else []) + ["-i", str(track), "-filter_complex", ";".join(g), "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
    try:
        subprocess.run(cmd, check=True, timeout=1800, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise RuntimeError("The music could not be added: " + " ".join((e.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-2:])[:200]) from e
    return out


def render(data: Dict, sources: Dict[str, Dict], out: Path, work: Path, tag: str, report: Callable[[float, str], None], threads: int = 0, music_path: Optional[Path] = None,
           images: Optional[Dict[str, Path]] = None) -> Path:
    """Render every clip, then join them. `sources` = {source id: {"path", "duration", "width", "height", "has_audio"}}.
    `tag` makes every temporary file name unique to this render, so many members can render at the same time without ever touching each other's files.
    `report(percent 0-100, message)` is called often; it may raise to stop the render (a cancel)."""
    clips = data["clips"]
    if not clips:
        raise ValueError("Add at least one clip to the timeline.")
    work.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    total = max(0.1, total_seconds(data))
    parts: List[Path] = []
    done = 0.0
    try:
        for i, c in enumerate(clips):
            s = sources[c["source"]]
            info = {k: s[k] for k in ("duration", "width", "height", "has_audio")}
            spec = clip_spec(c, data["aspect"], info, images, export_of(data)["quality"], {k: v["path"] for k, v in sources.items()})
            part = work / f"{tag}_p{i:03d}.mp4"
            dur = clip_seconds(c)
            base = done

            def prog(f: float, base=base, dur=dur, i=i):
                report(3 + 87 * (base + f * dur) / total, f"Rendering clip {i + 1} of {len(clips)}…")
            editor.render(Path(s["path"]), part, spec, info, prog, threads=threads)
            parts.append(part)
            done += dur
        report(91, "Joining the clips…")
        audio = [_has_audio(p) for p in parts]
        if any(audio) and not all(audio):
            for i, p in enumerate(parts):
                if not audio[i]:
                    parts[i] = _with_silence(p, work / f"{tag}_s{i:03d}.mp4")
        lst = work / f"{tag}_list.txt"
        lst.write_text("".join("file '" + str(p).replace("\\", "/").replace("'", "'\\''") + "'\n" for p in parts), encoding="utf-8")
        music = (data.get("audio") or {}).get("music")
        joined = work / f"{tag}_joined.mp4" if (music and music_path) else out
        if any((c.get("transition") or {}).get("type", "none") != "none" for c in clips) and len(parts) > 1:
            report(91, "Adding the transitions…")
            xfade_join(parts, clips, joined, threads, QUALITY[export_of(data)["quality"]][1])
        else:
            subprocess.run([FFMPEG_BIN, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", "-movflags", "+faststart", str(joined)],
                           check=True, timeout=1800)
        if music and music_path:
            report(95, "Adding the music…")
            mix_music(joined, music, music_path, out, editor.probe(joined)["duration"], _has_audio(joined), threads)
    except subprocess.CalledProcessError as e:
        out.unlink(missing_ok=True)
        raise RuntimeError("The clips could not be joined into one video.") from e
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    finally:
        for f in work.glob(f"{tag}_*"):
            try:
                f.unlink()
            except OSError:
                pass
    return out
