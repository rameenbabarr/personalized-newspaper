from __future__ import annotations

from pathlib import Path

import httpx

from src.agents.llm import complete_json
from src.config import ROOT
from src.log import info
from src.models import StoriesOut, TexFile

TEMPLATE_PATH = ROOT / "inspo" / "template.tex"
LAYOUT_MODEL = "claude-opus-5"
LAYOUT_TOKENS = 32000
LAYOUT_TIMEOUT = 300.0

LAYOUT_SYSTEM = """You fill The Rameen Times LaTeX template with today's JSON.

Return one complete .tex file in tex.
- Copy the template preamble, macros, page grid, minipages, and \\fetchimg / \\photobox structure. Do not add packages, pages, or new environments.
- Delete every \\lipsum[...].
- Map JSON to pages: A1 headline + meetings + tasks + weather + reader_note; A2 palestine; A3 art-crafts; A4 space; A5 tech-ai; A6 islamabad-folk.
- Fill titles, authors, bodies, bylines, and \\fetchimg{image_url}{same local filename} from JSON.
- You may write kickers, datelines, photo captions, INSIDE teasers, weather table cells from the raw weather blob, and pull-quote / craft / around-town boxes only if grounded in the JSON. No new facts.
- If a lead, brief, or image is missing, omit or leave that box empty. Never keep template sample stories.
- Escape TeX specials in filled text: & % $ # _ { }
"""


def load_template() -> str:
    return TEMPLATE_PATH.read_text()


def edition_tex_path(date: str) -> Path:
    out_dir = ROOT / "editions" / date
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{date}.tex"


def _payload(stories: StoriesOut) -> str:
    return f"TEMPLATE\n{load_template()}\n\nJSON\n{stories.model_dump_json(indent=2)}\n"


async def compose_tex(client: httpx.AsyncClient, stories: StoriesOut) -> str:
    draft = await complete_json(
        client,
        LAYOUT_SYSTEM,
        _payload(stories),
        TexFile,
        agent="layout",
        model=LAYOUT_MODEL,
        max_tokens=LAYOUT_TOKENS,
        timeout=LAYOUT_TIMEOUT,
    )
    tex = draft.tex.strip()
    if not tex:
        raise RuntimeError("layout returned empty tex")
    return tex


async def write_tex(client: httpx.AsyncClient, stories: StoriesOut) -> Path:
    tex = await compose_tex(client, stories)
    path = edition_tex_path(stories.date)
    path.write_text(tex + "\n")
    info(f"tex {path}")
    return path
