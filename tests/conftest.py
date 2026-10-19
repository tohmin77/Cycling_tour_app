import datetime as dt

import pytest

from app import export, main, weather

TEST_TODAY = dt.date(2026, 1, 1)  # far from the sample tour dates, so weather tests never depend on the real clock


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    real = weather.period_weather
    monkeypatch.setattr(main, "period_weather", lambda *a, **kw: real(*a[:3], today=TEST_TODAY, **kw))
    monkeypatch.setattr(export, "period_weather", lambda *a, **kw: real(*a[:3], today=TEST_TODAY, **kw))
