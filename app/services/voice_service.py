"""Narrator voices (Microsoft neural voices)."""



_VOICES = None


def list_voices() -> list:
    """English neural narrators (from Microsoft's free voice service); a built-in list if that service is unreachable."""
    global _VOICES
    if _VOICES:
        return _VOICES
    out = []
    try:
        import asyncio

        import edge_tts
        for v in asyncio.run(edge_tts.list_voices()):
            if v["Locale"] in ("en-US", "en-GB", "en-CA", "en-AU", "en-IE") and v["ShortName"].endswith("Neural"):
                out.append({"id": v["ShortName"], "name": v["ShortName"].split("-")[2].replace("Neural", ""),
                            "locale": v["Locale"], "gender": v["Gender"]})
    except Exception:
        pass
    if not out:
        from app.engine import audio_shield
        out = [{"id": i, "name": i.split("-")[2].replace("Neural", ""), "locale": "-".join(i.split("-")[:2]),
                "gender": "Female" if i.split("-")[2].replace("Neural", "") in ("Aria", "Jenny", "Sonia") else "Male"} for i in audio_shield.VOICE_POOL]
    out.sort(key=lambda v: (v["locale"], v["gender"], v["name"]))
    _VOICES = out
    return out
