import asyncio
from pathlib import Path

from src.execute import finish_edition, run
from src.models import LongPiece, StoriesOut


def _stories() -> StoriesOut:
    return StoriesOut(
        date="2026-09-20",
        headline=LongPiece(
            id="palestine-1",
            title="A headline",
            author="A. Writer",
            body="Body.",
            source_name="Example",
            source_url="https://example.com/x",
            image_url="https://img.example/h.jpg",
        ),
    )


def test_finish_edition_returns_json_and_pdf(monkeypatch, tmp_path) -> None:
    json_path = tmp_path / "stories.json"
    tex_path = tmp_path / "2026-09-20.tex"
    pdf_path = tmp_path / "2026-09-20.pdf"
    json_path.write_text("{}\n")
    tex_path.write_text("tex\n")
    pdf_path.write_bytes(b"%PDF")

    monkeypatch.setattr("src.execute.write_stories", lambda stories: json_path)

    async def fake_write_tex(client, stories):
        return tex_path

    monkeypatch.setattr("src.execute.write_tex", fake_write_tex)
    monkeypatch.setattr("src.execute.compile_pdf", lambda path: pdf_path)
    got_json, got_pdf = asyncio.run(finish_edition(_stories()))
    assert got_json == json_path
    assert got_pdf == pdf_path


def test_run_returns_pdf_path(monkeypatch, tmp_path) -> None:
    json_path = tmp_path / "stories.json"
    pdf_path = tmp_path / "out.pdf"

    async def fake_live():
        return _stories()

    async def fake_finish(stories):
        return json_path, pdf_path

    monkeypatch.setattr("src.execute.build_edition_live", fake_live)
    monkeypatch.setattr("src.execute.finish_edition", fake_finish)
    got_json, got_pdf = asyncio.run(run())
    assert got_json == json_path
    assert got_pdf == pdf_path
