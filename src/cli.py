from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from src.agents.reflect import reflect
from src.config import ROOT, load_sample_edition, load_user_md
from src.deliver.smtp import send_pdf
from src.log import close, error, info, ok, path as log_path, start_run, step, warn
from src.models import Edition, StoriesOut
from src.pipeline import build_edition_live
from src.render.edition import stories_to_edition
from src.render.pdf import compile_pdf, open_preview
from src.render.tex import render_tex
from src.seen import remember
from src.taste import db as taste_db
from src.taste.trends import summarize


def archive_dir(date: str) -> Path:
    path = ROOT / "editions" / date
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_stories(stories: StoriesOut) -> Path:
    out_dir = archive_dir(stories.date)
    path = out_dir / "stories.json"
    path.write_text(json.dumps(stories.model_dump(mode="json"), indent=2) + "\n")
    info(f"stories {path}")
    return path


def write_edition(edition: Edition, *, preview: bool = True) -> Path:
    out_dir = archive_dir(edition.date)
    step("render", str(out_dir))
    (out_dir / f"{edition.date}.json").write_text(
        json.dumps(edition.model_dump(mode="json"), indent=2) + "\n"
    )
    tex_path = render_tex(edition, out_dir)
    info(f"tex {tex_path.name}")
    pdf_path = compile_pdf(tex_path)
    ok(f"pdf {pdf_path}")
    if preview:
        open_preview(pdf_path)
        info("opened PDF")
    return pdf_path


def record_taste(edition: Edition) -> None:
    """Log what was printed for the taste tracker. Never fatal: a broken taste
    log must not cost the morning paper."""
    try:
        count = taste_db.record_edition(edition)
        info(f"taste: logged {count} stories")
    except Exception as exc:
        warn(f"taste log failed: {exc}")


async def _reflect() -> None:
    summary = summarize(taste_db.stories_with_votes(), topics=taste_db.topics())
    info(f"taste: {summary['stories']} stories, {summary['votes']} votes")
    async with httpx.AsyncClient() as client:
        report = await reflect(client, summary, load_user_md())
    taste_db.save_report(report.model_dump(mode="json"))
    ok(f"report: {report.summary}")


def _send(edition: Edition, pdf_path: Path) -> None:
    step("send", pdf_path.name)
    send_pdf(edition, pdf_path)
    remember([(a.source_url, a.headline) for a in edition.articles if a.source_url])
    ok("sent")


def main() -> None:
    parser = argparse.ArgumentParser(prog="rameen-times")
    sub = parser.add_subparsers(dest="cmd", required=True)
    preview = sub.add_parser("preview", help="write A4 PDF and open Preview")
    preview.add_argument(
        "--sample",
        action="store_true",
        help="render config/sample-edition.json",
    )
    sub.add_parser("send", help="compose, write PDF, SMTP the attachment")
    sub.add_parser("serve", help="run the local taste server (votes, trends)")
    taste = sub.add_parser("taste", help="taste tracker maintenance")
    taste.add_argument("action", choices=["backfill", "reflect"])
    args = parser.parse_args()
    if args.cmd == "serve":
        from src.web.app import serve

        serve()
        return
    if args.cmd == "taste" and args.action == "backfill":
        count = taste_db.backfill()
        print(f"taste: loaded {count} stories from editions/")
        return
    label = "preview-sample" if args.cmd == "preview" and args.sample else args.cmd
    if args.cmd == "taste":
        label = f"taste-{args.action}"
    run_log = start_run(label)
    try:
        if args.cmd == "preview" and args.sample:
            edition = load_sample_edition()
            info("using sample edition")
            write_edition(edition)
        elif args.cmd == "taste":
            asyncio.run(_reflect())
        else:
            stories = asyncio.run(build_edition_live())
            json_path = write_stories(stories)
            ok(f"json {json_path}")
            headline = stories.headline.title if stories.headline else "(none)"
            ok(f"headline: {headline}")
            info(f"topics: {len(stories.topics)}  meetings: {len(stories.meetings)}  tasks: {len(stories.tasks)}")
            edition = stories_to_edition(stories)
            preview_flag = args.cmd == "preview"
            pdf_path = write_edition(edition, preview=preview_flag)
            record_taste(edition)
            if args.cmd == "send":
                _send(edition, pdf_path)
        saved = log_path() or run_log
        ok(f"log file: {saved}")
    except Exception as exc:
        error(str(exc))
        saved = log_path() or run_log
        warn(f"log file: {saved}")
        raise
    finally:
        close()


if __name__ == "__main__":
    main()
