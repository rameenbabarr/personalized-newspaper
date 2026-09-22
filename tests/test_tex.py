from PIL import Image

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
