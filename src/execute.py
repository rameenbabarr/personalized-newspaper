from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx

from src.agents.layout import write_tex
from src.cli import write_stories
from src.log import close, error, ok, path as log_path, start_run, warn
from src.models import StoriesOut
from src.pipeline import build_edition_live
from src.render.pdf import compile_pdf


async def finish_edition(stories: StoriesOut) -> tuple[Path, Path]:
    json_path = write_stories(stories)
    async with httpx.AsyncClient() as client:
        tex_path = await write_tex(client, stories)
    pdf_path = compile_pdf(tex_path)
    return json_path, pdf_path


async def run() -> tuple[Path, Path]:
    stories = await build_edition_live()
    return await finish_edition(stories)


def main() -> None:
    run_log = start_run("execute")
    json_path = None
    pdf_path = None
    try:
        json_path, pdf_path = asyncio.run(run())
        saved = log_path() or run_log
        ok(f"json {json_path}")
        ok(f"pdf {pdf_path}")
        ok(f"log file: {saved}")
    except Exception as exc:
        error(str(exc))
        saved = log_path() or run_log
        warn(f"log file: {saved}")
        print(f"log {saved}", file=sys.stderr)
        raise
    finally:
        close()
    if json_path is not None:
        saved = log_path() or run_log
        print(f"json {json_path}")
        print(f"pdf {pdf_path}")
        print(f"log {saved}")


if __name__ == "__main__":
    main()
