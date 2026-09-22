from __future__ import annotations

import os
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from src.log import agent_fail, agent_in, agent_out

MODEL = "claude-sonnet-5"
URL = "https://api.anthropic.com/v1/messages"
TOOL_NAME = "submit"
T = TypeVar("T", bound=BaseModel)


def _schema(out_type: type[BaseModel]) -> dict:
    schema = out_type.model_json_schema()
    schema.pop("$schema", None)
    return schema


def _tool_use(data: dict) -> dict:
    for block in data.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return block
    raise KeyError("no tool_use input")


def _tool_input(data: dict) -> dict:
    payload = _tool_use(data).get("input")
    if isinstance(payload, dict):
        return payload
    raise KeyError("no tool_use input")


async def complete_json(
    client: httpx.AsyncClient,
    system: str,
    user: str,
    out_type: type[T],
    *,
    agent: str = "llm",
    model: str | None = None,
    max_tokens: int = 4000,
    timeout: float = 120.0,
) -> T:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    agent_in(agent, system, user)
    started = time.monotonic()
    messages: list[dict] = [{"role": "user", "content": user}]
    last_error: Exception | None = None
    for attempt in range(2):
        response = await client.post(
            URL,
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": model or MODEL,
                "max_tokens": max_tokens,
                "thinking": {"type": "disabled"},
                "system": system,
                "tools": [
                    {
                        "name": TOOL_NAME,
                        "description": "Submit one JSON object that matches the schema.",
                        "input_schema": _schema(out_type),
                    }
                ],
                "tool_choice": {"type": "tool", "name": TOOL_NAME},
                "messages": messages,
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            exc = RuntimeError(f"Anthropic {response.status_code}: {response.text[:2000]}")
            agent_fail(agent, exc, elapsed=time.monotonic() - started)
            raise exc
        data = response.json()
        try:
            parsed = out_type.model_validate(_tool_input(data))
            agent_out(agent, parsed, elapsed=time.monotonic() - started)
            return parsed
        except (ValidationError, KeyError, TypeError) as exc:
            last_error = exc
            if attempt == 0:
                agent_fail(agent, exc)
            messages.append({"role": "assistant", "content": data.get("content") or []})
            try:
                tool_id = _tool_use(data).get("id")
            except KeyError:
                tool_id = None
            if not tool_id:
                agent_fail(agent, last_error, elapsed=time.monotonic() - started)
                raise RuntimeError(f"Anthropic JSON failed: {last_error}") from exc
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "is_error": True,
                            "content": f"Invalid for the required schema: {exc}. Call submit again with one valid object.",
                        }
                    ],
                }
            )
    agent_fail(agent, last_error or RuntimeError("unknown"), elapsed=time.monotonic() - started)
    raise RuntimeError(f"Anthropic JSON failed: {last_error}")
