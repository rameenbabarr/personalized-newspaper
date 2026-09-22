from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from src.log import warn

PDFLATEX_CANDIDATES = (
    "pdflatex",
    # Linux: TeX Live from the distro, then a manual install.
    "/usr/bin/pdflatex",
    "/usr/local/bin/pdflatex",
    "/usr/local/texlive/2025/bin/x86_64-linux/pdflatex",
    # macOS: MacTeX/BasicTeX, which are not on PATH for non-login shells.
    "/Library/TeX/texbin/pdflatex",
    "/usr/local/texlive/2026/bin/universal-darwin/pdflatex",
)

INSTALL_HINT = {
    "linux": (
        "Install TeX Live: sudo apt install texlive-latex-recommended "
        "texlive-latex-extra texlive-fonts-recommended."
    ),
    "darwin": "Install MacTeX or BasicTeX.",
}


def find_pdflatex() -> str:
    for candidate in PDFLATEX_CANDIDATES:
        path = shutil.which(candidate) if os.path.basename(candidate) == candidate else candidate
        if path and Path(path).exists():
            return path
    hint = INSTALL_HINT.get(sys.platform, "Install a TeX distribution that provides pdflatex.")
    raise FileNotFoundError(f"pdflatex is not installed. {hint}")


def compile_pdf(tex_path: Path) -> Path:
    engine = find_pdflatex()
    workdir = tex_path.parent
    cmd = [
        engine,
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-shell-escape",
        tex_path.name,
    ]
    for _ in range(2):
        result = subprocess.run(
            cmd,
            cwd=workdir,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            log = workdir / tex_path.with_suffix(".log").name
            detail = result.stdout[-2000:] if result.stdout else result.stderr
            if log.exists():
                detail = log.read_text(errors="replace")[-2000:]
            raise RuntimeError(f"pdflatex failed:\n{detail}")
    pdf = tex_path.with_suffix(".pdf")
    if not pdf.exists():
        raise RuntimeError("pdflatex finished without writing a PDF")
    return pdf


def open_preview(pdf_path: Path) -> None:
    """Show the finished PDF. Never fatal: a headless box or a bare SSH session
    has no viewer, and the paper is the artifact, not the window."""
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", "Preview", str(pdf_path)], check=False)
        return
    opener = shutil.which("xdg-open")
    if not opener:
        warn(f"no PDF viewer found; the paper is at {pdf_path}")
        return
    # xdg-open hands off to the desktop's handler and can be noisy when there is
    # no session to hand off to, so its output stays out of the run log.
    subprocess.run(
        [opener, str(pdf_path)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
