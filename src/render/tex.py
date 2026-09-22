from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader
from PIL import Image

from src.config import ROOT, VOTE_BASE
from src.log import warn
from src.models import Article, Edition, TaskItem

TEMPLATES = ROOT / "templates"
UA = "RameenTimes/1.0 (personal morning paper)"
_SPECIALS = {
    "\\": r"\textbackslash{}",
    "{": r"\{",
    "}": r"\}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# Typography the writers produce that reads better as a real TeX command than as
# a raw codepoint.
_UNICODE = {
    "‘": "`",
    "’": "'",
    "“": "``",
    "”": "''",
    "–": "--",
    "—": "---",
    "…": r"\ldots{}",
    "−": "-",
    "′": "'",
    "″": "''",
    " ": "~",
    "°": r"\textdegree{}",
    "•": r"\textbullet{}",
    "×": r"$\times$",
    "€": r"\texteuro{}",
    "½": r"$\frac{1}{2}$",
    # Zero-width and emoji-presentation joiners carry no text.
    "­": "",
    "​": "",
    "‌": "",
    "‍": "",
    "️": "",
    "﻿": "",
}

_DROPPED: set[str] = set()

# Blocks T1 + inputenc can set, confirmed against pdflatex rather than assumed.
# The Unicode name is not a safe test: U+0259 SCHWA and U+01C0 DENTAL CLICK are
# both named LATIN and both fail to compile.
_SAFE_RANGES = (
    (0x00C0, 0x00FF),  # Latin-1 letters: é ñ ü ß ÷
    (0x0100, 0x017F),  # Latin Extended-A: ā ł č œ
    (0x1E00, 0x1EFF),  # Latin Extended Additional: ḥ
    (0xFB00, 0xFB06),  # ﬁ ﬂ ligatures
)


def _unicode_char(ch: str) -> str:
    """Render one non-ASCII character in a way pdfTeX can actually typeset.

    pdfTeX is not a Unicode engine: inputenc covers Latin scripts and common
    punctuation, and anything else is a hard compile error, not a bad glyph. A
    model that drops an emoji into the copy must not be able to kill the paper.
    """
    mapped = _UNICODE.get(ch)
    if mapped is not None:
        return mapped
    code = ord(ch)
    if any(low <= code <= high for low, high in _SAFE_RANGES):
        return ch
    # Fold to ASCII where there is a faithful equivalent (Ș -> S).
    folded = unicodedata.normalize("NFKD", ch)
    ascii_only = "".join(c for c in folded if ord(c) < 128)
    if ascii_only.strip():
        return ascii_only
    # Emoji, Arabic, CJK: no ASCII equivalent and no pdfTeX glyph.
    _DROPPED.add(ch)
    return ""


def tex_escape(value: object) -> str:
    text = "" if value is None else str(value)
    out: list[str] = []
    for ch in text:
        special = _SPECIALS.get(ch)
        if special is not None:
            out.append(special)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            out.append(_unicode_char(ch))
    return "".join(out)


def report_dropped() -> None:
    """Say what was removed, so silently losing a name is visible in the log."""
    if not _DROPPED:
        return
    shown = " ".join(f"U+{ord(ch):04X}" for ch in sorted(_DROPPED))
    warn(f"dropped {len(_DROPPED)} character(s) pdflatex cannot set: {shown}")
    _DROPPED.clear()


_VOTE_ID = re.compile(r"^[A-Za-z0-9-]+$")


def vote_links(story_id: str) -> str:
    """The more/less links after a story's source line. Only for ids that are
    safe verbatim inside \\href; anything else prints no links at all."""
    if not _VOTE_ID.match(story_id or ""):
        return ""
    return rf"\hfill\votelinks{{{story_id}}}"


def trial_links(story_id: str) -> str:
    """The trial box's links: same votes, worded as the topic decision they are."""
    if not _VOTE_ID.match(story_id or ""):
        return ""
    return rf"\triallinks{{{story_id}}}"


def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
        variable_start_string="((",
        variable_end_string="))",
        block_start_string="((*",
        block_end_string="*))",
        comment_start_string="((#",
        comment_end_string="#))",
    )
    env.filters["tex"] = tex_escape
    env.filters["vote_links"] = vote_links
    env.filters["trial_links"] = trial_links
    return env


def _ext_for(content_type: str, url: str) -> str:
    lowered = content_type.lower()
    if "png" in lowered:
        return ".png"
    if "gif" in lowered:
        return ".gif"
    if "webp" in lowered:
        return ".webp"
    if "jpeg" in lowered or "jpg" in lowered:
        return ".jpg"
    path = url.split("?", 1)[0].lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".jpg"


# pdflatex picks its image driver from the file extension and reads only these.
_TEX_FORMATS = {"JPEG": ".jpg", "PNG": ".png"}
# Below this, a "photo" is a logo, an icon or a tracking pixel. Blown up to
# column width it looks broken, so the story runs without a picture instead.
MIN_IMAGE_SIDE = 200


def usable_image(path: Path) -> Path | None:
    """Make a downloaded file safe for pdflatex, or delete it and give up.

    A server sending an SVG icon or an HTML error page under a JPEG content
    type once killed a whole run: the bytes were saved as .jpg, pdflatex found
    no JPEG header, and no PDF was produced. So the file is opened for real,
    rejected if it is not an image or is icon-sized, and rewritten as JPEG when
    it is a format pdflatex cannot read (webp, gif) -- or simply renamed when
    the extension lies about the contents (a PNG saved as .jpg fails too).
    """
    try:
        with Image.open(path) as image:
            image.verify()  # cheap header check; invalidates the handle
        with Image.open(path) as image:
            fmt, (width, height) = image.format, image.size
            if min(width, height) < MIN_IMAGE_SIDE:
                path.unlink(missing_ok=True)
                return None
            wanted = _TEX_FORMATS.get(fmt or "")
            if wanted is None:
                jpg = path.with_suffix(".jpg")
                image.convert("RGB").save(jpg, "JPEG", quality=90)
            elif path.suffix.lower() not in {wanted, ".jpeg"}:
                jpg = path.with_suffix(wanted)
                path.replace(jpg)
            else:
                return path
    except (OSError, ValueError, Image.DecompressionBombError):
        path.unlink(missing_ok=True)
        return None
    if not jpg.exists() or jpg.stat().st_size == 0:
        return None
    if path != jpg:
        path.unlink(missing_ok=True)
    return jpg


def cache_image(url: str, dest_dir: Path) -> Path | None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    existing = next((p for p in dest_dir.glob(f"{digest}.*") if "_r" not in p.stem), None)
    if existing and existing.stat().st_size > 0:
        return usable_image(existing)
    try:
        response = httpx.get(
            url,
            headers={"User-Agent": UA},
            follow_redirects=True,
            timeout=12.0,
        )
        if response.status_code >= 400 or not response.content:
            return None
        ext = _ext_for(response.headers.get("content-type", ""), url)
        path = dest_dir / f"{digest}{ext}"
        path.write_bytes(response.content)
        return usable_image(path)
    except httpx.HTTPError:
        return None


def _image_size(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as image:
            width, height = image.size
    except OSError:
        return None
    if width and height:
        return width, height
    return None


def crop_to_ratio(path: Path, ratio: float) -> Path | None:
    """Center-crop an image to a width/height ratio so it fills its box edge to
    edge in the template, instead of leaving whitespace next to a mismatched
    photo (keepaspectratio otherwise shrinks the image to whichever dimension
    is tighter)."""
    label = f"r{round(ratio * 1000)}"
    cropped = path.with_name(f"{path.stem}_{label}{path.suffix}")
    if cropped.exists() and cropped.stat().st_size > 0:
        return cropped
    try:
        with Image.open(path) as image:
            width, height = image.size
            if not width or not height:
                return None
            current_ratio = width / height
            if current_ratio > ratio:
                new_width, new_height = round(height * ratio), height
            else:
                new_width, new_height = width, round(width / ratio)
            new_width, new_height = max(new_width, 1), max(new_height, 1)
            left = max((width - new_width) // 2, 0)
            top = max((height - new_height) // 2, 0)
            box = (left, top, left + new_width, top + new_height)
            out = image.crop(box)
            if cropped.suffix.lower() in {".jpg", ".jpeg"}:
                out = out.convert("RGB")
                out.save(cropped, "JPEG", quality=90)
            else:
                out.save(cropped)
    except OSError:
        return None
    if not cropped.exists() or cropped.stat().st_size == 0:
        return None
    return cropped


# WMO weather codes, condensed to the bands a reader actually needs.
WMO_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Rain showers",
    82: "Violent showers",
    95: "Thunderstorm",
    96: "Thunderstorm, hail",
    99: "Thunderstorm, hail",
}


def describe_weather(code: object) -> str:
    try:
        return WMO_CODES.get(int(code), "—")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"


def _num(value: object) -> float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _clock(value: object) -> str:
    """Open-Meteo returns '2026-09-20T05:54'; the paper prints '05:54'."""
    text = str(value or "")
    return text.split("T")[-1][:5] if "T" in text else ""


def weather_summary(blob: dict | None) -> dict | None:
    """Reduce the raw Open-Meteo payload to the handful of values the rail
    prints. Returns None when the fetch failed, so the box simply drops."""
    if not isinstance(blob, dict):
        return None
    current = blob.get("current") if isinstance(blob.get("current"), dict) else {}
    daily = blob.get("daily") if isinstance(blob.get("daily"), dict) else {}

    def day(key: str, index: int = 0) -> object:
        rows = daily.get(key)
        if isinstance(rows, list) and len(rows) > index:
            return rows[index]
        return None

    temp = _num(current.get("temperature_2m"))
    if temp is None and day("temperature_2m_max") is None:
        return None

    days: list[dict] = []
    times = daily.get("time") if isinstance(daily.get("time"), list) else []
    for index in range(min(3, len(times))):
        high, low = _num(day("temperature_2m_max", index)), _num(day("temperature_2m_min", index))
        days.append(
            {
                "date": str(times[index])[5:],  # MM-DD
                "high": f"{high:.0f}" if high is not None else "—",
                "low": f"{low:.0f}" if low is not None else "—",
                "summary": describe_weather(day("weather_code", index)),
            }
        )

    feels = _num(current.get("apparent_temperature"))
    humidity = _num(current.get("relative_humidity_2m"))
    wind = _num(current.get("wind_speed_10m"))
    high_today, low_today = _num(day("temperature_2m_max")), _num(day("temperature_2m_min"))
    return {
        "temp": f"{temp:.0f}" if temp is not None else "—",
        "feels": f"{feels:.0f}" if feels is not None else None,
        "summary": describe_weather(current.get("weather_code")),
        "humidity": f"{humidity:.0f}" if humidity is not None else None,
        "wind": f"{wind:.0f}" if wind is not None else None,
        "high": f"{high_today:.0f}" if high_today is not None else None,
        "low": f"{low_today:.0f}" if low_today is not None else None,
        "sunrise": _clock(day("sunrise")),
        "sunset": _clock(day("sunset")),
        "days": days,
    }


# The rail sits beside the lead in a fixed row, and a row taller than the space
# under the masthead gets pushed to the next page whole, leaving page one empty.
# The note is the one rail box with no natural ceiling, so it gets one here.
NOTE_LIMIT = 330


def clip_sentences(text: str | None, limit: int) -> str:
    """Trim to whole sentences within `limit`, rather than mid-word."""
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit]
    for stop in (". ", "! ", "? "):
        found = cut.rfind(stop)
        if found > limit // 2:
            return cut[: found + 1]
    return cut.rsplit(" ", 1)[0] + "..."


def _split_lead(text: str) -> tuple[str, str]:
    stripped = text.lstrip()
    if not stripped:
        return "", ""
    return stripped[0], stripped[1:]


HERO_RATIO = 16 / 9   # full-width lead photo: wide hero crop
TRIAL_RATIO = 4 / 3   # trial photo sits beside its text in a narrow column
SIDE_RATIO = 2 / 1    # secondary photo at column width: a shallow crop keeps the
                      # unbreakable head+photo block short enough to fit a
                      # column tail, instead of jumping and leaving a hole


def prepare_edition(edition: Edition, image_dir: Path) -> dict:
    articles = list(edition.articles)
    lead = next((a for a in articles if a.role == "lead"), None)
    rest = [a for a in articles if a is not lead]
    trial = next((a for a in rest if a.trial), None)
    secondaries = [a for a in rest if a.role == "secondary" and a is not trial]
    briefs = [a for a in rest if a.role == "brief"]

    def local_image(article: Article, ratio: float) -> str | None:
        if not article.image_url:
            return None
        path = cache_image(article.image_url, image_dir)
        if path is None:
            return None
        # Crop to the slot's aspect ratio so the photo fills its box edge to
        # edge. Without this, keepaspectratio shrinks a mismatched photo to
        # a fraction of the column width and leaves the rest blank.
        cropped = crop_to_ratio(path, ratio)
        if cropped is None:
            # The file downloaded but Pillow cannot work with it. Falling back
            # to the uncropped original would hand pdflatex the same bad file.
            warn(f"unusable photo, running without it: {article.image_url}")
            return None
        return f"images/{cropped.name}"

    lead_drop = ("", "")
    if lead and lead.body:
        lead_drop = _split_lead(lead.body[0])

    by_id = {task.id: task for task in [*edition.desk.pending, *edition.desk.in_progress]}
    ranked: list[TaskItem] = []
    for task_id in edition.desk.ranked_ids:
        task = by_id.pop(task_id, None)
        if task:
            ranked.append(task)
    ranked.extend(by_id.values())

    return {
        "edition": edition,
        "lead": lead,
        "lead_image": local_image(lead, HERO_RATIO) if lead else None,
        "lead_drop": lead_drop,
        "secondaries": secondaries,
        "story_images": {
            article.id: path
            for article in secondaries
            if (path := local_image(article, SIDE_RATIO))
        },
        "briefs": briefs,
        "trial": trial,
        "trial_image": local_image(trial, TRIAL_RATIO) if trial else None,
        "ranked_tasks": ranked,
        "in_progress": [t for t in ranked if t.status == "in-progress"],
        "pending": [t for t in ranked if t.status == "pending"],
        "weather": weather_summary(edition.weather),
        "reader_note": clip_sentences(edition.reader_note, NOTE_LIMIT),
        "thin": edition.page_mode == "thin",
        "vote_base": VOTE_BASE,
    }


def render_tex(edition: Edition, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    image_dir = out_dir / "images"
    context = prepare_edition(edition, image_dir)
    tex = _env().get_template("edition.tex.j2").render(**context)
    report_dropped()
    # Trailing spaces on a line become a real inter-word space in TeX, so the
    # template's indentation leaks into the set text as stray gaps.
    tex = re.sub(r"[ \t]+$", "", tex, flags=re.MULTILINE)
    tex = re.sub(r"\n{3,}", "\n\n", tex)
    tex = tex.rstrip() + "\n"
    path = out_dir / f"{edition.date}.tex"
    path.write_text(tex)
    return path
