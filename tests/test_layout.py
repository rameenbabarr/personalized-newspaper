import asyncio

import httpx

from src.agents.layout import LAYOUT_SYSTEM, compose_tex, write_tex
from src.models import LongPiece, StoriesOut, TexFile, TopicCopy


def _stories() -> StoriesOut:
    headline = LongPiece(
        id="palestine-1",
        title="West Bank Palestinians Forgive Millions in Debt",
        author="Qassam Muaddi",
        body="A solidarity drive spread across the West Bank.",
        source_name="Mondoweiss",
        source_url="https://mondoweiss.net/x",
        image_url="https://img.example/headline.jpg",
    )
    return StoriesOut(
        date="2026-09-20",
        headline=headline,
        topics={
            "space": TopicCopy(lead=None, briefs=[]),
        },
        reader_note="Good morning, Rameen.",
    )


def test_layout_prompt_fills_text_and_drops_missing() -> None:
    lowered = LAYOUT_SYSTEM.lower()
    assert "lipsum" in lowered
    assert "omit" in lowered or "missing" in lowered
    assert "sample" in lowered
    assert "do not add packages" in lowered


def test_compose_tex_sends_json_and_template(monkeypatch) -> None:
    captured: dict = {}

    async def fake_complete(client, system, user, out_type, **kwargs):
        captured["system"] = system
        captured["user"] = user
        captured["model"] = kwargs.get("model")
        captured["max_tokens"] = kwargs.get("max_tokens")
        captured["timeout"] = kwargs.get("timeout")
        assert out_type is TexFile
        return TexFile(
            tex=(
                "\\documentclass{article}\n"
                "\\fetchimg{https://img.example/headline.jpg}{front-hero.jpg}\n"
                "West Bank Palestinians Forgive Millions in Debt\n"
            )
        )

    monkeypatch.setattr("src.agents.layout.complete_json", fake_complete)
    monkeypatch.setattr(
        "src.agents.layout.load_template",
        lambda: "% sample\nAid Convoys Expand Deliveries\n\\lipsum[2]\n",
    )
    tex = asyncio.run(compose_tex(httpx.AsyncClient(), _stories()))
    assert "West Bank Palestinians Forgive Millions in Debt" in captured["user"]
    assert "Aid Convoys Expand Deliveries" in captured["user"]
    assert "\\lipsum[2]" in captured["user"]
    assert captured["model"] == "claude-opus-5"
    assert captured["max_tokens"] == 32000
    assert captured["timeout"] == 300.0
    assert "https://img.example/headline.jpg" in tex
    assert "\\fetchimg{https://img.example/headline.jpg}{front-hero.jpg}" in tex
    assert "Aid Convoys Expand Deliveries" not in tex


def test_write_tex_saves_opus_output(monkeypatch, tmp_path) -> None:
    async def fake_compose(client, stories):
        return (
            "\\documentclass{article}\n"
            "\\fetchimg{https://img.example/headline.jpg}{front-hero.jpg}\n"
            "West Bank Palestinians Forgive Millions in Debt\n"
        )

    monkeypatch.setattr("src.agents.layout.compose_tex", fake_compose)
    monkeypatch.setattr("src.agents.layout.edition_tex_path", lambda date: tmp_path / f"{date}.tex")
    path = asyncio.run(write_tex(httpx.AsyncClient(), _stories()))
    text = path.read_text()
    assert path.name == "2026-09-20.tex"
    assert "https://img.example/headline.jpg" in text
    assert "Aid Convoys Expand Deliveries" not in text
