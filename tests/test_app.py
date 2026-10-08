import datetime as dt

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app import config, main, maps, parser, photos
from app.models import Itinerary


ITIN = {
    "title": "Test Tour", "country": "South Korea",
    "days": [{"number": 1, "date": "2026-10-26", "title": "Ride", "is_ride": True, "city": "Busan",
              "hotel": "Hotel X",
              "stops": [{"name": "A, Busan", "kind": "start"}, {"name": "B, Busan", "kind": "end"}]}],
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TRIPS_DIR", tmp_path / "trips")
    monkeypatch.setattr(config, "CACHE_PATH", tmp_path / "cache.sqlite")
    monkeypatch.setattr(main, "parse_itinerary", lambda text: Itinerary.model_validate(ITIN))
    monkeypatch.setattr(main, "region_banner", lambda osm, trip: None)
    monkeypatch.setattr(maps, "NOMINATIM_INTERVAL_S", 0)
    monkeypatch.setattr(maps, "OVERPASS_INTERVAL_S", 0)
    return TestClient(main.app, follow_redirects=False)


def test_parse_itinerary_validates_model_output(monkeypatch):
    monkeypatch.setattr(parser, "tool_json", lambda *a, **k: ITIN)
    assert parser.parse_itinerary("text").days[0].city == "Busan"


def test_parse_itinerary_rejects_bad_output(monkeypatch):
    monkeypatch.setattr(parser, "tool_json", lambda *a, **k: {"title": "x"})
    with pytest.raises(Exception):
        parser.parse_itinerary("text")


def test_upload_rejects_non_pdf(client):
    r = client.post("/upload", files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 400 and "PDF" in r.text


def test_upload_text_then_tabs_and_edit(client):
    r = client.post("/upload", data={"text": "Day 1 ride"})
    assert r.status_code == 303
    trip_url = r.headers["location"]
    assert client.get(trip_url).headers["location"] == trip_url + "/day/1"

    route = client.get(trip_url + "/day/1")
    assert route.status_code == 200 and 'name="viewport"' in route.text
    assert 'data-src="' + trip_url + '/day/1/route.part"' in route.text
    food = client.get(trip_url + "/day/1/food")
    assert food.status_code == 200 and "/food.part" in food.text

    apps = client.get(trip_url + "/apps?d=1")
    assert "Apps for South Korea" in apps.text and "KORAIL Talk" in apps.text
    assert client.get(trip_url + "/apps?d=99").status_code == 200

    assert client.get(trip_url + "/edit").status_code == 200
    assert client.post(trip_url + "/edit", data={"body": "{}"}).status_code == 400


def test_trip_id_must_be_hex(client):
    assert client.get("/trip/..%2Fetc/day/1").status_code == 404
    assert client.get("/trip/" + "0" * 32).status_code == 404


def test_import_json_and_sample(client):
    r = client.post("/upload", data={"itinerary_json": __import__("json").dumps(ITIN)})
    assert r.status_code == 303
    bad = client.post("/upload", data={"itinerary_json": "{}"})
    assert bad.status_code == 400
    sample = client.get("/sample")
    assert sample.status_code == 303 and client.get(sample.headers["location"] + "/apps").status_code == 200


def test_text_upload_without_api_key_explains_json_import(client, monkeypatch):
    monkeypatch.undo()
    monkeypatch.setattr(config, "TRIPS_DIR", config.TRIPS_DIR)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = client.post("/upload", data={"text": "Day 1"})
    assert r.status_code == 400 and "JSON" in r.text


def geocode_ok(request):
    return httpx.Response(200, json=[{"lat": "35.1", "lon": "129.0"}])


def mock_services():
    respx.get(maps.NOMINATIM_URL).mock(side_effect=geocode_ok)
    respx.get(maps.BROUTER_URL).mock(return_value=httpx.Response(200, json={"features": [{
        "geometry": {"coordinates": [[129.0, 35.1, 5], [129.1, 35.2, 9]]},
        "properties": {"track-length": "14000"}}]}))
    respx.post(maps.OVERPASS_URL).mock(return_value=httpx.Response(200, json={"elements": [
        {"type": "node", "id": 1, "lat": 35.1, "lon": 129.0, "tags": {"name": "Good Cafe", "amenity": "cafe"}}]}))
    respx.get("https://en.wikipedia.org/w/api.php").mock(return_value=httpx.Response(200, json={"query": {"pages": {
        "1": {"title": "Good Cafe", "index": 1, "thumbnail": {"source": "https://upload.wikimedia.org/cafe.jpg"},
              "fullurl": "https://en.wikipedia.org/wiki/Good_Cafe"}}}}))
    respx.get("https://archive-api.open-meteo.com/v1/archive").mock(return_value=httpx.Response(200, json={
        "daily": {"temperature_2m_min": [14.0], "temperature_2m_max": [21.0], "precipitation_sum": [0.0],
                  "wind_speed_10m_max": [12.0]}}))


@respx.mock
def test_route_part_has_map_weather_and_sights(client):
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    mock_services()
    r = client.get(trip_url + "/day/1/route.part")
    assert r.status_code == 200
    assert "About 14.0 km" in r.text and 'id="map-data"' in r.text and "Open in Google Maps" in r.text
    assert "Good Cafe" in r.text and "Typical" not in r.text and "What to wear" not in r.text
    assert 'src="https://upload.wikimedia.org/cafe.jpg"' in r.text and "Photo: Wikimedia" in r.text
    assert "Breakfast" not in r.text


@respx.mock
def test_food_part_lists_meals_with_map_links(client):
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    mock_services()
    r = client.get(trip_url + "/day/1/food.part")
    assert r.status_code == 200
    for meal in ("Breakfast", "Lunch", "Dinner"):
        assert meal in r.text
    assert "Good Cafe" in r.text and "google.com/maps/search" in r.text
    assert "<img" not in r.text


@respx.mock
def test_weather_part_is_one_period_summary_with_packing_advice(client):
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    respx.get(maps.NOMINATIM_URL).mock(side_effect=geocode_ok)
    respx.get("https://archive-api.open-meteo.com/v1/archive").mock(return_value=httpx.Response(200, json={
        "daily": {"temperature_2m_min": [9.0], "temperature_2m_max": [18.0], "precipitation_sum": [3.0],
                  "wind_speed_10m_max": [25.0]}}))
    r = client.get(trip_url + "/weather.part")
    assert r.status_code == 200
    assert "9–18°C" in r.text and "Rain likely on about 1 of 1 days" in r.text
    assert "What to pack" in r.text and "last 3 years" in r.text


@respx.mock
def test_weather_part_survives_service_failure(client):
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    respx.get(maps.NOMINATIM_URL).mock(return_value=httpx.Response(503))
    r = client.get(trip_url + "/weather.part")
    assert r.status_code == 200 and "unavailable" in r.text


@respx.mock
def test_banner_picks_wide_photo_and_tabs_include_weather(client, monkeypatch):
    monkeypatch.setattr(main, "region_banner", photos.region_banner)
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    respx.get("https://en.wikipedia.org/w/api.php").mock(return_value=httpx.Response(200, json={"query": {"pages": {
        "1": {"title": "Busan", "pageimage": "Busan skyline.jpg",
              "thumbnail": {"source": "https://upload.wikimedia.org/busan.jpg", "width": 1000, "height": 500}}}}}))
    r = client.get(trip_url + "/weather?d=1")
    assert 'class="banner"' in r.text and 'src="https://upload.wikimedia.org/busan.jpg"' in r.text
    assert "File:Busan_skyline.jpg" in r.text and "/weather?d=1" in r.text and "data-src" in r.text


@respx.mock
def test_banner_rejects_square_images_and_falls_back_to_plain_banner(client, monkeypatch):
    monkeypatch.setattr(main, "region_banner", photos.region_banner)
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    respx.get("https://en.wikipedia.org/w/api.php").mock(return_value=httpx.Response(200, json={"query": {"pages": {
        "1": {"title": "Busan", "thumbnail": {"source": "https://x/seal.png", "width": 500, "height": 500}}}}}))
    r = client.get(trip_url + "/apps")
    assert r.status_code == 200 and 'class="banner"' in r.text and "seal.png" not in r.text


def test_unknown_day_or_section_is_404(client):
    trip_url = client.post("/upload", data={"text": "x"}).headers["location"]
    assert client.get(trip_url + "/day/9").status_code == 404
    assert client.get(trip_url + "/day/9/food").status_code == 404
    assert client.get(trip_url + "/day/1/other.part").status_code == 404


@respx.mock
def test_route_falls_back_to_straight_lines_when_brouter_fails(tmp_path):
    from app.cache import Cache
    respx.get(maps.BROUTER_URL).mock(return_value=httpx.Response(500))
    route = maps.OsmServices(Cache(tmp_path / "c.sqlite")).route([(35.0, 129.0), (35.1, 129.0)])
    assert route.mode == "STRAIGHT" and route.distance_m == pytest.approx(11119, rel=0.01)


@respx.mock
def test_geocode_retries_with_shorter_name(tmp_path):
    from app.cache import Cache
    calls = []

    def handler(request):
        q = request.url.params["q"]
        calls.append(q)
        return httpx.Response(200, json=[{"lat": "1", "lon": "2"}] if q == "Eulsukdo, Busan" else [])

    respx.get(maps.NOMINATIM_URL).mock(side_effect=handler)
    osm = maps.OsmServices(Cache(tmp_path / "c.sqlite"))
    monkey_interval = maps.NOMINATIM_INTERVAL_S
    maps.NOMINATIM_INTERVAL_S = 0
    try:
        assert osm.geocode("Eulsukdo Eco Park, Busan") == (1.0, 2.0)
    finally:
        maps.NOMINATIM_INTERVAL_S = monkey_interval
    assert calls == ["Eulsukdo Eco Park, Busan", "Eulsukdo Eco, Busan", "Eulsukdo, Busan"]
