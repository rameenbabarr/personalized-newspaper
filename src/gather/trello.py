from __future__ import annotations

import os
from datetime import datetime

import httpx

from src.config import load_paper
from src.models import TaskItem

API = "https://api.trello.com/1"


def _creds() -> tuple[str, str] | None:
    key = os.environ.get("TRELLO_API_KEY")
    token = os.environ.get("TRELLO_TOKEN")
    if not key or not token:
        return None
    return key, token


async def _get(client: httpx.AsyncClient, path: str, creds: tuple[str, str]) -> object:
    key, token = creds
    response = await client.get(f"{API}{path}", params={"key": key, "token": token}, timeout=12.0)
    response.raise_for_status()
    return response.json()


DEFAULT_PENDING = ("this week", "later", "to-do", "todo", "pending")
DEFAULT_DOING = ("today", "in-progress", "in progress", "doing", "wip")


def _list_names(cfg: dict, plural: str, singular: str, defaults: tuple[str, ...]) -> list[str]:
    raw = cfg.get(plural)
    if raw is None:
        raw = cfg.get(singular)
    if raw is None:
        raw = list(defaults)
    if isinstance(raw, str):
        raw = [raw]
    return [str(name).casefold() for name in raw if str(name).strip()]


def _list_status(name: str, pending_names: list[str], doing_names: list[str]) -> str | None:
    folded = name.casefold()
    if folded in doing_names:
        return "in-progress"
    if folded in pending_names:
        return "pending"
    return None


def _cards_to_tasks(cards: list[dict], status: str, list_name: str) -> list[TaskItem]:
    items: list[TaskItem] = []
    for card in cards:
        if card.get("closed"):
            continue
        due = card.get("due")
        due_dt = None
        if due:
            try:
                due_dt = datetime.fromisoformat(str(due).replace("Z", "+00:00"))
            except ValueError:
                due_dt = None
        items.append(
            TaskItem(
                id=str(card["id"]),
                title=str(card.get("name") or "(untitled)"),
                status=status,  # type: ignore[arg-type]
                due=due_dt,
                url=card.get("url"),
                list_name=list_name,
            )
        )
    return items


async def _board_id(client: httpx.AsyncClient, creds: tuple[str, str], cfg: dict) -> str:
    configured = cfg.get("boardId")
    if configured:
        try:
            await _get(client, f"/boards/{configured}", creds)
            return str(configured)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in {401, 403, 404}:
                raise
    boards = await _get(client, "/members/me/boards", creds)
    name = str(cfg.get("boardName") or "My Trello Board").casefold()
    open_boards = [
        board
        for board in boards
        if isinstance(board, dict) and not board.get("closed")
    ]
    matches = [
        board
        for board in open_boards
        if str(board.get("name", "")).casefold() == name
    ]
    if matches:
        return str(matches[0]["id"])
    if open_boards:
        return str(open_boards[0]["id"])
    raise RuntimeError(f'Trello board "{cfg.get("boardName")}" not found.')


async def gather_trello(paper: dict | None = None) -> tuple[list[TaskItem], str | None]:
    creds = _creds()
    if not creds:
        return [], "Trello not connected."
    cfg = (paper or load_paper()).get("trello") or {}
    try:
        async with httpx.AsyncClient() as client:
            board_id = await _board_id(client, creds, cfg)
            lists = await _get(client, f"/boards/{board_id}/lists", creds)
            pending_names = _list_names(cfg, "pendingLists", "pendingList", DEFAULT_PENDING)
            doing_names = _list_names(cfg, "inProgressLists", "inProgressList", DEFAULT_DOING)
            tasks: list[TaskItem] = []
            matched = 0
            for lst in lists:
                if not isinstance(lst, dict) or lst.get("closed"):
                    continue
                list_name = str(lst.get("name") or "")
                status = _list_status(list_name, pending_names, doing_names)
                if status is None:
                    continue
                matched += 1
                cards = await _get(client, f"/lists/{lst['id']}/cards", creds)
                tasks.extend(_cards_to_tasks(cards, status, list_name))
            if not matched:
                for lst in lists:
                    if not isinstance(lst, dict) or lst.get("closed"):
                        continue
                    list_name = str(lst.get("name") or "")
                    cards = await _get(client, f"/lists/{lst['id']}/cards", creds)
                    tasks.extend(_cards_to_tasks(cards, "pending", list_name))
        if not tasks:
            return [], "Trello is connected, but the matched lists are empty."
        return tasks, None
    except Exception as exc:
        return [], str(exc)
