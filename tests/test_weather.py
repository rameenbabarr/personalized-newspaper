from src.gather.weather import SCRIPT, fetch_weather


def test_fetch_weather_returns_script_payload(monkeypatch) -> None:
    import src.gather.weather as weather

    class Fake:
        @staticmethod
        def get_weather():
            return {"latitude": 33.6844, "daily": {"time": ["2026-09-20"]}}

    class FakeSpec:
        loader = type("L", (), {"exec_module": staticmethod(lambda mod: None)})()

    monkeypatch.setattr(weather.importlib.util, "spec_from_file_location", lambda name, path: FakeSpec())
    monkeypatch.setattr(weather.importlib.util, "module_from_spec", lambda spec: Fake())
    assert SCRIPT.name == "islamabad_weather.py"
    assert fetch_weather() == {"latitude": 33.6844, "daily": {"time": ["2026-09-20"]}}
