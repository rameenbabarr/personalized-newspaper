import asyncio

import httpx

from src.gather.trello import _board_id, _list_status


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeClient:
    pass


def test_board_id_falls_back_when_configured_board_is_unauthorized(monkeypatch) -> None:
    async def fake_get(client, path, creds):
        if path.startswith("/boards/locked"):
            raise httpx.HTTPStatusError(
                "no",
                request=httpx.Request("GET", "https://api.trello.com/1/boards/locked"),
                response=FakeResponse(401),  # type: ignore[arg-type]
            )
        if path == "/members/me/boards":
            return [
                {"id": "open-1", "name": "My Trello Board", "closed": False},
                {"id": "other", "name": "Other", "closed": False},
            ]
        raise AssertionError(path)

    monkeypatch.setattr("src.gather.trello._get", fake_get)
    board_id = asyncio.run(
        _board_id(
            FakeClient(),  # type: ignore[arg-type]
            ("key", "token"),
            {"boardId": "locked", "boardName": "My Trello Board"},
        )
    )
    assert board_id == "open-1"


def test_list_status_maps_rameen_board_names() -> None:
    pending = ["this week", "later"]
    doing = ["today", "in-progress"]
    # Matching is case-folded, so the board's "This Week" hits "this week".
    assert _list_status("This Week", pending, doing) == "pending"
    assert _list_status("later", pending, doing) == "pending"
    assert _list_status("today", pending, doing) == "in-progress"
    # A list that is on neither side is not a task source.
    assert _list_status("Inbox", pending, doing) is None
