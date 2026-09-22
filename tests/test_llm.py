import asyncio

from pydantic import BaseModel

from src.agents.llm import complete_json


class _Out(BaseModel):
    kicker: str


class _Response:
    status_code = 200

    def json(self) -> dict:
        return {
            "content": [
                {"type": "tool_use", "name": "submit", "input": {"kicker": "Clear morning."}}
            ]
        }


class _Client:
    def __init__(self) -> None:
        self.payloads: list[dict] = []
        self.timeouts: list[float | None] = []

    async def post(self, *args, **kwargs):
        self.payloads.append(kwargs.get("json") or {})
        self.timeouts.append(kwargs.get("timeout"))
        return _Response()


def test_complete_json_reads_tool_use(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = _Client()
    out = asyncio.run(complete_json(client, "system", "user", _Out))
    assert out.kicker == "Clear morning."
    assert client.payloads[0]["model"] == "claude-sonnet-5"
    assert client.payloads[0]["max_tokens"] == 4000
    assert client.timeouts[0] == 120.0


def test_complete_json_passes_model(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = _Client()
    asyncio.run(
        complete_json(
            client,
            "system",
            "user",
            _Out,
            model="claude-opus-5",
            max_tokens=8000,
            timeout=300.0,
        )
    )
    assert client.payloads[0]["model"] == "claude-opus-5"
    assert client.payloads[0]["max_tokens"] == 8000
    assert client.timeouts[0] == 300.0
