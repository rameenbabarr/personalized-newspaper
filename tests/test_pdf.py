from src.render.pdf import compile_pdf


def test_compile_pdf_uses_shell_escape_twice(monkeypatch, tmp_path) -> None:
    tex = tmp_path / "2026-09-20.tex"
    tex.write_text("\\documentclass{article}\\begin{document}Hi\\end{document}\n")
    (tmp_path / "2026-09-20.pdf").write_bytes(b"%PDF")
    calls: list[list[str]] = []
    cwds: list[object] = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        cwds.append(kwargs.get("cwd"))
        return Result()

    monkeypatch.setattr("src.render.pdf.subprocess.run", fake_run)
    monkeypatch.setattr("src.render.pdf.find_pdflatex", lambda: "pdflatex")
    pdf = compile_pdf(tex)
    assert pdf == tmp_path / "2026-09-20.pdf"
    assert len(calls) == 2
    assert calls[0] == calls[1]
    assert "-shell-escape" in calls[0]
    assert calls[0][-1] == "2026-09-20.tex"
    assert cwds == [tmp_path, tmp_path]
