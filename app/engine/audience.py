"""Which creators' clips a person wants: the countries the creators live in and the language of their streams.

Every person (the owner and every member) sets their own, on Settings -> Creators & languages. It is saved with their "What to clip" settings and is read by the
clip search of THEIR runs (the run knows its person through CLIPSTUDIO_USER_ID).

  * "All" means no filter at all (every country / every language).
  * Nothing saved yet: the owner gets All; a member gets the server's list (Settings -> Audience & clips -> the owner's default for members), as before.
  * Twitch does not tell us a creator's country, so there the language decides. YouTube shows a channel's country when the creator filled it in:
    a channel with no country listed is accepted.
"""
import os
from typing import Dict, List, Optional, Set

# code -> (name shown, other names YouTube may use for the same country)
COUNTRIES: Dict[str, tuple] = {
    "US": ("United States", []), "CA": ("Canada", []), "GB": ("United Kingdom", ["UK", "Great Britain"]), "IE": ("Ireland", []), "AU": ("Australia", []), "NZ": ("New Zealand", []),
    "DE": ("Germany", []), "FR": ("France", []), "ES": ("Spain", []), "IT": ("Italy", []), "NL": ("Netherlands", []), "BE": ("Belgium", []), "LU": ("Luxembourg", []),
    "CH": ("Switzerland", []), "AT": ("Austria", []), "SE": ("Sweden", []), "NO": ("Norway", []), "DK": ("Denmark", []), "FI": ("Finland", []), "IS": ("Iceland", []),
    "PL": ("Poland", []), "PT": ("Portugal", []), "CZ": ("Czechia", ["Czech Republic"]), "RO": ("Romania", []), "GR": ("Greece", []), "HU": ("Hungary", []),
    "SK": ("Slovakia", []), "BG": ("Bulgaria", []), "HR": ("Croatia", []), "RS": ("Serbia", []), "SI": ("Slovenia", []), "LT": ("Lithuania", []), "LV": ("Latvia", []), "EE": ("Estonia", []),
    "UA": ("Ukraine", []), "RU": ("Russia", ["Russian Federation"]), "TR": ("Turkey", ["Türkiye", "Turkiye"]), "IL": ("Israel", []),
    "BR": ("Brazil", []), "MX": ("Mexico", []), "AR": ("Argentina", []), "CL": ("Chile", []), "CO": ("Colombia", []), "PE": ("Peru", []), "VE": ("Venezuela", []), "UY": ("Uruguay", []),
    "JP": ("Japan", []), "KR": ("South Korea", ["Korea, Republic of", "Korea"]), "TW": ("Taiwan", []), "HK": ("Hong Kong", []), "CN": ("China", []),
    "IN": ("India", []), "PK": ("Pakistan", []), "BD": ("Bangladesh", []), "LK": ("Sri Lanka", []), "NP": ("Nepal", []),
    "ID": ("Indonesia", []), "PH": ("Philippines", []), "VN": ("Vietnam", ["Viet Nam"]), "TH": ("Thailand", []), "MY": ("Malaysia", []), "SG": ("Singapore", []),
    "SA": ("Saudi Arabia", []), "AE": ("United Arab Emirates", ["UAE"]), "EG": ("Egypt", []), "MA": ("Morocco", []), "DZ": ("Algeria", []), "QA": ("Qatar", []), "KW": ("Kuwait", []),
    "ZA": ("South Africa", []), "NG": ("Nigeria", []), "KE": ("Kenya", []),
}
LANGUAGES: Dict[str, str] = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French", "de": "German", "it": "Italian", "nl": "Dutch", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "fi": "Finnish",
    "pl": "Polish", "cs": "Czech", "sk": "Slovak", "ro": "Romanian", "el": "Greek", "hu": "Hungarian", "bg": "Bulgarian", "hr": "Croatian", "sr": "Serbian", "sl": "Slovenian",
    "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian", "uk": "Ukrainian", "ru": "Russian", "tr": "Turkish", "he": "Hebrew", "ar": "Arabic", "fa": "Persian",
    "ja": "Japanese", "ko": "Korean", "zh": "Chinese", "hi": "Hindi", "bn": "Bengali", "ur": "Urdu", "ta": "Tamil", "te": "Telugu", "id": "Indonesian", "ms": "Malay",
    "th": "Thai", "vi": "Vietnamese", "tl": "Filipino",
}
# the choices offered as one tap on the page
PRESET_ENGLISH = {"countries": ["US", "CA", "GB", "IE", "AU", "NZ"], "languages": ["en"]}

_cache: Dict[str, Dict] = {}


def server_default() -> Dict[str, List[str]]:
    """What a member gets until they choose: the list kept in Settings -> Audience & clips (the owner's default for members)."""
    from app.config import CLIP_COUNTRIES, CLIP_LANGUAGES
    return {"countries": sorted(c for c in CLIP_COUNTRIES if c in COUNTRIES), "languages": sorted(l for l in CLIP_LANGUAGES if l in LANGUAGES)}


def _doc_id(uid) -> str:
    return f"clipping:{uid}"


def _is_owner(uid) -> bool:
    try:
        from app.models import User, oid
        u = User.find_one(id=oid(str(uid)))
        return bool(u and u.get("role") == "owner")
    except Exception:
        return False


def _uid(uid=None) -> Optional[str]:
    return str(uid) if uid else (os.environ.get("CLIPSTUDIO_USER_ID") or None)


def get(uid=None) -> Dict:
    """What this person has chosen: {"countries": "all" | [codes], "languages": "all" | [codes], "custom": {"countries": bool, "languages": bool}}."""
    explicit = bool(uid)                          # a web request names the person; only a run (CLIPSTUDIO_USER_ID) may use the per-process memory
    uid = _uid(uid)
    if not explicit and uid in _cache:            # (the web server has several processes: remembering a choice there would show a stale answer)
        return _cache[uid]
    doc = {}
    if uid:
        try:
            from app.models import Setting
            doc = Setting.find_one(id=_doc_id(uid)) or {}
        except Exception:
            doc = {}
    dflt = {"countries": "all", "languages": "all"} if (uid and _is_owner(uid)) else server_default()
    out, custom = {}, {}
    for key, cat in (("countries", COUNTRIES), ("languages", LANGUAGES)):
        v = doc.get("aud_" + key)
        if v == "all" or (isinstance(v, list) and v and all(isinstance(x, str) for x in v)):
            out[key] = "all" if v == "all" else [x for x in v if x in cat] or dflt[key]
            custom[key] = True
        else:
            out[key], custom[key] = dflt[key], False
    out["custom"] = custom
    if uid and not explicit:
        _cache[uid] = out
    return out


def clear(uid=None) -> None:
    _cache.pop(_uid(uid) or "", None)


def countries(uid=None) -> Optional[Set[str]]:
    """The allowed country codes, or None when every country is allowed."""
    v = get(uid)["countries"]
    return None if v == "all" else {c.upper() for c in v}


def languages(uid=None) -> Optional[Set[str]]:
    v = get(uid)["languages"]
    return None if v == "all" else {l.lower() for l in v}


def country_names(uid=None) -> Optional[Set[str]]:
    """The allowed countries by name (lower case), as a YouTube channel's About page spells them. None = every country."""
    codes = countries(uid)
    if codes is None:
        return None
    names: Set[str] = set()
    for c in codes:
        n, alt = COUNTRIES.get(c, (None, []))
        if n:
            names |= {x.lower() for x in [n] + list(alt)}
    return names


def language_ok(lang: str, uid=None, allow_unknown: bool = False) -> bool:
    langs = languages(uid)
    if langs is None:
        return True
    code = (lang or "").lower().split("-")[0]
    return (allow_unknown and not code) or code in langs


def country_ok(code: str, uid=None) -> bool:
    cs = countries(uid)
    return cs is None or not code or code.upper() in cs


def save(uid, data: Dict) -> Dict:
    """Save one person's choice. data: {"countries": "all" | [codes], "languages": "all" | [codes]}, or {"reset": true} to go back to the default."""
    from app.models import Setting
    if data.get("reset"):
        Setting.set_fields(_doc_id(uid), {}, unset=("aud_countries", "aud_languages"), upsert=True)
        clear(uid)
        return get(uid)
    upd = {}
    for key, cat, noun in (("countries", COUNTRIES, "country"), ("languages", LANGUAGES, "language")):
        if key not in data:
            continue
        v = data[key]
        if v == "all":
            upd["aud_" + key] = "all"
            continue
        if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
            raise ValueError(f"Choose {noun} names from the list, or choose All.")
        codes = list(dict.fromkeys(x.strip().upper() if key == "countries" else x.strip().lower() for x in v))
        if not codes:
            raise ValueError(f"Choose at least one {noun}, or choose All.")
        bad = [x for x in codes if x not in cat]
        if bad:
            raise ValueError(f"Unknown {noun}: {', '.join(bad[:3])}.")
        upd["aud_" + key] = codes
    if upd:
        Setting.set_fields(_doc_id(uid), upd, upsert=True)
    clear(uid)
    return get(uid)


def catalog() -> Dict:
    return {"countries": [{"code": c, "name": n} for c, (n, _) in COUNTRIES.items()], "languages": [{"code": c, "name": n} for c, n in LANGUAGES.items()],
            "presets": {"default": server_default(), "english": PRESET_ENGLISH}}
