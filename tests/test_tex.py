from datetime import datetime

from PIL import Image

from src.config import TZ
from src.models import Article, Desk, Edition
from src.render import tex
from src.render.tex import crop_to_ratio, tex_escape


def test_tex_escape_specials() -> None:
    assert tex_escape("Aid & food_aid 50%") == r"Aid \& food\_aid 50\%"
    assert tex_escape("Cost $4#") == r"Cost \$4\#"
    assert tex_escape("a^b~c") == r"a\textasciicircum{}b\textasciitilde{}c"


def test_tex_escape_none_is_empty() -> None:
    assert tex_escape(None) == ""


def test_tex_escape_drops_characters_pdflatex_cannot_set() -> None:
    # A writer put an emoji in the reader note and killed the whole edition:
    # pdfTeX raises a hard error on an unmapped codepoint, it does not skip it.
    assert tex_escape("Morning! ☀️ warm") == "Morning!  warm"
    assert tex_escape("Arabic القدس") == "Arabic "
    assert tex_escape("CJK 中文") == "CJK "
    # Named LATIN but genuinely uncompilable under T1.
    assert tex_escape("schwa ə") == "schwa "


def test_tex_escape_keeps_latin_and_converts_typography() -> None:
    assert tex_escape("Señor Gałązka Čech ḥamza") == "Señor Gałązka Čech ḥamza"
    assert tex_escape("“q” — – …") == "``q'' --- -- \\ldots{}"
    assert tex_escape("31°C") == "31\\textdegree{}C"
    # Folds to a faithful ASCII equivalent rather than vanishing.
    assert tex_escape("Ștefan") == "Stefan"


def test_crop_to_ratio_center_crops_wide_jpeg(tmp_path) -> None:
    source = tmp_path / "wide.jpg"
    Image.new("RGB", (1200, 600), color=(20, 40, 80)).save(source, "JPEG")
    cropped = crop_to_ratio(source, 16 / 9)
    assert cropped is not None
    with Image.open(cropped) as image:
        width, height = image.size
    assert abs((width / height) - (16 / 9)) < 0.02


SVG_ICON = b'<svg id="email-icon" xmlns="http://www.w3.org/2000/svg" width="16"></svg>'


class _Response:
    """Minimal stand-in for an httpx response."""

    def __init__(self, content: bytes, content_type: str = "image/jpeg") -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"content-type": content_type}


def _png_bytes(size=(800, 600)) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", size, (30, 60, 90)).save(buffer, "PNG")
    return buffer.getvalue()


def test_svg_served_as_jpeg_is_rejected(tmp_path, monkeypatch) -> None:
    # A real run died here: turkmenistan.gov.tm returned a 631-byte SVG email
    # icon with a JPEG content type, and pdflatex found no JPEG header.
    monkeypatch.setattr(tex.httpx, "get", lambda *a, **k: _Response(SVG_ICON))
    assert tex.cache_image("https://example.com/icon.jpg", tmp_path) is None
    assert list(tmp_path.iterdir()) == []


def test_png_saved_under_a_jpg_name_is_renamed(tmp_path, monkeypatch) -> None:
    # pdflatex chooses its driver from the extension, so a PNG called .jpg fails.
    monkeypatch.setattr(tex.httpx, "get", lambda *a, **k: _Response(_png_bytes()))
    path = tex.cache_image("https://example.com/photo.jpg", tmp_path)
    assert path is not None and path.suffix == ".png"


def test_icon_sized_images_are_dropped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tex.httpx, "get", lambda *a, **k: _Response(_png_bytes((64, 64))))
    assert tex.cache_image("https://example.com/logo.jpg", tmp_path) is None


def test_webp_is_converted_for_pdflatex(tmp_path, monkeypatch) -> None:
    from io import BytesIO

    buffer = BytesIO()
    Image.new("RGB", (900, 600), (10, 10, 10)).save(buffer, "WEBP")
    monkeypatch.setattr(tex.httpx, "get", lambda *a, **k: _Response(buffer.getvalue(), "image/webp"))
    path = tex.cache_image("https://example.com/photo.webp", tmp_path)
    assert path is not None and path.suffix == ".jpg"


def test_a_story_whose_photo_cannot_be_cropped_prints_without_one(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tex, "cache_image", lambda url, d: tmp_path / "broken.jpg")
    monkeypatch.setattr(tex, "crop_to_ratio", lambda path, ratio: None)
    edition = Edition(
        paper_name="The Rameen Times", date="2026-09-23", volume="Vol. I",
        generated_at=datetime(2026, 9, 23, tzinfo=TZ), timezone="Asia/Karachi",
        diary=[], desk=Desk(pending=[], in_progress=[]),
        articles=[Article(id="space-1", headline="h", section="Space", body=["b"], role="lead",
                          source_url="", source_name="E", image_url="https://example.com/x.jpg")],
    )
    context = tex.prepare_edition(edition, tmp_path)
    assert context["lead_image"] is None
