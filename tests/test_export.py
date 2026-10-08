import datetime as dt
import json
import re

import httpx
import pytest
import respx

from app import export, maps
from app.cache import Cache
from app.maps import OsmServices
from app.models import Itinerary

ITIN = {
    "title": "Test Tour", "country": "South Korea",
    "days": [
        {"number": 1, "date": "2026-10-26", "title": "Ride", "is_ride": True, "city": "Busan", "hotel": "Hotel X",
         "stops": [{"name": "A, Busan", "kind": "start"}, {"name": "B, Busan", "kind": "end"}]},
        {"number": 2, "date": "2026-10-27", "title": "Fly home", "is_ride": False, "city": "Busan", "stops": []},
    ],
}


def trip():
    return Itinerary.model_validate(ITIN)


def test_slug_uses_main_city_and_start_date():
    assert export.slug_for(trip()) == "busan-2026-10-26"


def test_slug_falls_back_for_non_latin_city_and_undated_trip():
    data = json.loads(json.dumps(ITIN))
    for d in data["days"]:
        d["city"] = "부산"
    assert export.slug_for(Itinerary.model_validate(data)) == "south-korea-2026-10-26"
    assert export.slug_for(Itinerary(title="t", country="", days=[])) == "tour-undated"


def mock_services():
    respx.get(maps.NOMINATIM_URL).mock(return_value=httpx.Response(200, json=[{"lat": "35.1", "lon": "129.0"}]))
    respx.get(maps.BROUTER_URL).mock(return_value=httpx.Response(200, json={"features": [{
        "geometry": {"coordinates": [[129.0, 35.1, 5], [129.1, 35.2, 9]]},
        "properties": {"track-length": "14000"}}]}))
    respx.post(maps.OVERPASS_URL).mock(return_value=httpx.Response(200, json={"elements": [
        {"type": "node", "id": 1, "lat": 35.1, "lon": 129.0, "tags": {"name": "Good Cafe", "amenity": "cafe"}}]}))
    respx.get("https://en.wikipedia.org/w/api.php").mock(return_value=httpx.Response(200, json={"query": {"pages": {
        "1": {"title": "Busan", "pageimage": "Busan.jpg",
              "thumbnail": {"source": "https://upload.wikimedia.org/busan.jpg", "width": 1000, "height": 500}}}}}))
    respx.get("https://archive-api.open-meteo.com/v1/archive").mock(return_value=httpx.Response(200, json={
        "daily": {"temperature_2m_min": [9.0, 9.0], "temperature_2m_max": [18.0, 18.0],
                  "precipitation_sum": [0.0, 0.0], "wind_speed_10m_max": [12.0, 12.0]}}))


@pytest.fixture
def osm(tmp_path, monkeypatch):
    monkeypatch.setattr(maps, "NOMINATIM_INTERVAL_S", 0)
    monkeypatch.setattr(maps, "OVERPASS_INTERVAL_S", 0)
    return OsmServices(Cache(tmp_path / "c.sqlite"))


@respx.mock
def test_build_site_writes_self_contained_relative_pages(osm, tmp_path):
    mock_services()
    out = tmp_path / "site"
    out.mkdir()
    (out / "stale.html").write_text("old")
    warnings = export.build_site(trip(), osm, out, today=dt.date(2026, 10, 8))

    names = {p.name for p in out.iterdir()}
    assert {"index.html", "route-1.html", "food-1.html", "weather-1.html", "apps-1.html",
            "route-2.html", "food-2.html", "weather-2.html", "apps-2.html", "static"} <= names
    assert "stale.html" not in names
    assert {p.name for p in (out / "static").iterdir()} == {"style.css", "app.js", "map.js"}
    assert not any("banner" in w or "Weather" in w for w in warnings)

    route = (out / "route-1.html").read_text()
    assert (out / "index.html").read_text() == route
    assert 'id="map-data"' in route and "About 14.0 km" in route and "Good Cafe" in route
    assert 'href="static/style.css"' in route and 'src="static/map.js"' in route
    assert 'src="https://upload.wikimedia.org/busan.jpg"' in route
    assert 'href="food-1.html"' in route and 'href="weather-1.html"' in route and 'href="route-2.html"' in route
    assert "data-src" not in route
    assert 'class="hotel"' in route and "query=Hotel+X%2C+Busan%2C+South+Korea" in route
    assert 'class="hotel"' not in (out / "route-2.html").read_text()  # no hotel on departure day


@respx.mock
def test_pages_have_no_absolute_local_links_or_server_dependencies(osm, tmp_path):
    mock_services()
    out = tmp_path / "site"
    export.build_site(trip(), osm, out, today=dt.date(2026, 10, 8))
    for page in out.glob("*.html"):
        html = page.read_text()
        assert not re.search(r'(?:href|src)="/(?!/)', html), page.name
        assert "/trip/" not in html and "data-src" not in html, page.name
    weather = (out / "weather-2.html").read_text()
    assert "9–18°C" in weather and "Snapshot taken on 8 Oct 2026" in weather
    apps = (out / "apps-1.html").read_text()
    assert "Apps for South Korea" in apps and "Guide generated on 8 Oct 2026" in apps and "Edit parsed" not in apps
    assert "No cycling planned today" in (out / "route-2.html").read_text()


@respx.mock
def test_cli_creates_tour_folder_and_copies_itinerary(tmp_path, monkeypatch):
    mock_services()
    monkeypatch.setattr(maps, "NOMINATIM_INTERVAL_S", 0)
    monkeypatch.setattr(maps, "OVERPASS_INTERVAL_S", 0)
    monkeypatch.setattr(export.config, "CACHE_PATH", tmp_path / "cache.sqlite")
    src = tmp_path / "my.json"
    src.write_text(json.dumps(ITIN))
    tours = tmp_path / "tours"

    assert export.main([str(src), "--tours-dir", str(tours)]) == 0
    folder = tours / "busan-2026-10-26"
    assert (folder / "itinerary.json").exists() and (folder / "site" / "index.html").exists()

    assert export.main([str(folder), "--tours-dir", str(tours)]) == 0  # rebuild from the folder itself
    assert not (tours / "busan-2026-10-26" / "busan-2026-10-26").exists()
