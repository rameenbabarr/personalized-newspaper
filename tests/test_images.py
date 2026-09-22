from src.gather.images import ensure_image, first_web_image, image_query, is_unusable_image


def test_image_query_prefers_article_text() -> None:
    assert image_query("The pulsar feeds on a stellar wind. " * 20, "A pulsar")[:20] == "The pulsar feeds on "
    assert image_query("", "A pulsar") == "A pulsar"
    assert image_query(None, "A pulsar") == "A pulsar"


def test_ensure_image_keeps_existing() -> None:
    assert ensure_image("https://img.example/x.jpg", "long article", "Title") == "https://img.example/x.jpg"


def test_instagram_and_facebook_urls_are_unusable() -> None:
    assert is_unusable_image(None)
    assert is_unusable_image("")
    assert is_unusable_image("https://scontent-atl3-1.cdninstagram.com/v/t51.2885-19/x.jpg")
    assert is_unusable_image("https://www.instagram.com/p/abc/media")
    assert is_unusable_image("https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id=1")
    assert is_unusable_image("https://scontent-gru2-1.xx.fbcdn.net/v/t39.30808-6/x.jpg")
    assert is_unusable_image("https://www.facebook.com/photo.php?fbid=1")
    assert not is_unusable_image("https://img.example/x.jpg")


def test_ensure_image_searches_when_facebook(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.gather.images.first_web_image",
        lambda query: "https://ddg.example/nomad.jpg",
    )
    url = "https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id=1"
    assert ensure_image(url, "Nomad Gallery crafts weekend", "Nomad") == "https://ddg.example/nomad.jpg"


def test_ensure_image_searches_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.gather.images.first_web_image",
        lambda query: f"https://ddg.example/{query[:8]}",
    )
    assert ensure_image(None, "article text about a nebula", "Nebula") == "https://ddg.example/article "


def test_first_web_image_uses_first_result(monkeypatch) -> None:
    import sys
    import types

    class FakeDDGS:
        def images(self, query, max_results=1):
            assert query == "a nebula over chile"
            assert max_results == 5
            return [
                {"image": "https://scontent.cdninstagram.com/bad.jpg"},
                {"image": "https://lookaside.fbsbx.com/lookaside/crawler/media/?media_id=1"},
                {"image": "https://ddg.example/first.jpg", "thumbnail": "https://ddg.example/t.jpg"},
            ]

    fake = types.ModuleType("ddgs")
    fake.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", fake)
    assert first_web_image("a nebula over chile") == "https://ddg.example/first.jpg"
