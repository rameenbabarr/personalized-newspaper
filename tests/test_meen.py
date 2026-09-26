from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, SystemMessage

from src.chat import meen


class FakeModel:
    """Replays scripted AIMessages and remembers what it was shown."""

    def __init__(self, *replies: AIMessage) -> None:
        self.replies = list(replies)
        self.seen: list[list] = []

    def invoke(self, messages):
        self.seen.append(messages)
        return self.replies.pop(0)


@pytest.fixture
def user_md(tmp_path, monkeypatch):
    path = tmp_path / "user.md"
    path.write_text("# User\n\n## Space\n\nMissions and sky events.\n")
    monkeypatch.setattr(meen, "USER_MD_PATH", path)
    return path


def test_reply_sees_page_and_remembers_the_session(user_md) -> None:
    model = FakeModel(AIMessage("Hi!"), AIMessage("You said hello."))
    app = meen.build_graph(model)
    first = list(meen.chat("thread-0001", "hello", "Nothing is being shown.", app=app))
    assert first == [{"type": "reply", "text": "Hi!", "reload": False}]
    system = model.seen[0][0]
    assert isinstance(system, SystemMessage)
    assert "Nothing is being shown." in system.content
    assert "Missions and sky events." in system.content

    list(meen.chat("thread-0001", "what did I say?", "page two", app=app))
    second = model.seen[1]
    assert "page two" in second[0].content  # prompt rebuilt from the new page
    assert [m.content for m in second[1:]] == ["hello", "Hi!", "what did I say?"]
    assert meen.history("thread-0001", app=app)[-1] == {"role": "meen", "text": "You said hello."}
    assert meen.history("other-thread", app=app) == []


def test_generate_streams_generating_then_reload(user_md, monkeypatch) -> None:
    import src.cli

    edition = SimpleNamespace(date="2026-09-26", articles=[SimpleNamespace(role="lead", headline="Comet")])
    calls = []
    monkeypatch.setattr(src.cli, "generate_edition", lambda **kw: calls.append(kw) or edition)
    monkeypatch.setattr(meen, "start_run", lambda label: None)
    monkeypatch.setattr(meen, "close", lambda: None)
    model = FakeModel(
        AIMessage("", tool_calls=[{"name": "generate_newspaper", "args": {}, "id": "c1"}]),
        AIMessage("Fresh paper, still warm."),
    )
    events = list(meen.chat("thread-0002", "make me a paper", "", app=meen.build_graph(model)))
    assert events == [
        {"type": "generating"},
        {"type": "reply", "text": "Fresh paper, still warm.", "reload": True},
    ]
    assert calls == [{"open_pdf": False}]
    assert "Comet" in model.seen[1][-1].content  # tool result went back to the model


def test_edit_interests_replaces_once_or_appends(user_md) -> None:
    assert meen.edit_interests.invoke({"find": "Missions", "replace": "Rockets"}) == "Interests updated."
    assert "Rockets and sky events." in user_md.read_text()
    assert "No change" in meen.edit_interests.invoke({"find": "nope", "replace": "x"})
    meen.edit_interests.invoke({"find": "", "replace": "## Poetry\n\nUrdu ghazals."})
    assert user_md.read_text().endswith("sky events.\n\n## Poetry\n\nUrdu ghazals.\n")
