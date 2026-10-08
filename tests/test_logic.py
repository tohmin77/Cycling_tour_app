import datetime as dt

import httpx
import pytest
import respx

from app import weather
from app.advice import advise, advise_period
from app.guide import lunch_point, start_hour
from app import places
from app.models import Day
from app.routes import ResolvedStop, maps_url

LINE = [(0.0, 0.0), (0.0, 0.5)]  # ~55.6 km


def make_day(**kw):
    base = dict(number=1, date=dt.date(2026, 10, 26), title="t", is_ride=True, city="Busan")
    return Day(**{**base, **kw})


def test_lunch_point_three_hours_in_at_15kmh():
    p = lunch_point(LINE, 9.0)
    assert p[1] == pytest.approx(45 / 111.195, rel=0.01)


def test_lunch_point_clamps_to_end_when_ride_is_short():
    short = [(0.0, 0.0), (0.0, 0.05)]
    assert lunch_point(short, 9.0) == short[-1]


def test_lunch_point_after_noon_start_is_route_start():
    assert lunch_point(LINE, 13.0) == LINE[0]


def test_start_hour_parsing():
    assert start_hour(make_day(start_time="08:30")) == 8.5
    assert start_hour(make_day(start_time="garbage")) == 9.0
    assert start_hour(make_day()) == 9.0


class FakeOsm:
    def __init__(self, elements):
        self.elements, self.queries = elements, []

    def overpass(self, query):
        self.queries.append(query)
        return self.elements


def el(i, name, lat, lon, **tags):
    return {"type": "node", "id": i, "lat": lat, "lon": lon, "tags": {"name": name, **tags}}


def test_meals_rank_by_tag_richness_then_distance_and_link_to_google():
    osm = FakeOsm([
        el(1, "Far Plain", 0.02, 0.0),
        el(2, "Near Plain", 0.001, 0.0),
        el(3, "Rich", 0.01, 0.0, wikidata="Q1", website="x", opening_hours="24/7",
           **{"addr:street": "Main St", "addr:housenumber": "5", "addr:city": "Busan"}),
        el(4, "Near Plain", 0.001, 0.0),
    ])
    out = places.recommend_meal(osm, "lunch", (0.0, 0.0), "Busan, South Korea")
    assert [x.name for x in out] == ["Rich", "Near Plain", "Far Plain"]
    assert out[0].address == "Main St 5, Busan"
    assert out[1].url.startswith("https://www.google.com/maps/search/?api=1&query=Near+Plain")
    assert "bakery" not in osm.queries[0]


def test_breakfast_includes_bakeries_and_prefers_english_name():
    osm = FakeOsm([el(1, "한글", 0, 0, **{"name:en": "English Name"})])
    out = places.recommend_meal(osm, "breakfast", (0.0, 0.0), "Busan")
    assert out[0].name == "English Name" and "bakery" in osm.queries[0]


def test_pois_query_uses_corridor_around_thinned_route():
    osm = FakeOsm([el(1, "Temple", 0, 0, historic="temple", wikidata="Q2")])
    route = [(0.0, i * 0.001) for i in range(1000)]
    out = places.pois_along(osm, route, "Busan")
    assert out[0].name == "Temple"
    clause = osm.queries[0].split("(around:")[1].split(")")[0]
    clause = "around:" + clause
    assert clause.startswith("around:3000,") and len(clause.split(",")) <= 1 + 2 * places.MAX_CORRIDOR_POINTS + 2


def test_maps_url_limits_waypoints():
    stops = [ResolvedStop(f"s{i}", "checkpoint", (i, i)) for i in range(15)]
    url = maps_url(stops)
    assert "origin=0%2C0" in url and "destination=14%2C14" in url
    assert url.split("waypoints=")[1].count("%7C") == 8


def wx(tmin, tmax, prob=0, mm=0, wind=10):
    return weather.Weather(dt.date(2026, 10, 27), tmin, tmax, prob, mm, wind, False)


def test_advice_cold_wet_windy():
    a = advise(wx(2, 8, prob=80, mm=5, wind=40))
    text = " ".join(a.attire + a.extras)
    assert "Thermal" in text and "Waterproof packable jacket" in text and "Windproof" in text


def test_advice_hot_and_cool_morning():
    a = advise(wx(10, 30))
    assert any("Sunscreen" in x for x in a.extras) and any("Arm warmers" in x for x in a.extras)


def daily(n, tmin, tmax, mm=0.0, wind=10.0, prob=None):
    d = {"temperature_2m_min": [tmin] * n, "temperature_2m_max": [tmax] * n,
         "precipitation_sum": [mm] * n, "wind_speed_10m_max": [wind] * n}
    if prob is not None:
        d["precipitation_probability_max"] = [prob] * n
    return {"daily": d}


@respx.mock
def test_period_inside_horizon_uses_one_forecast_call():
    route = respx.get(weather.FORECAST_URL).mock(return_value=httpx.Response(200, json=daily(3, 12, 19, prob=10)))
    pw = weather.period_weather((35, 129), dt.date(2026, 10, 12), dt.date(2026, 10, 14), today=dt.date(2026, 10, 8))
    assert route.call_count == 1 and pw.n_forecast == 3 and pw.n_typical == 0
    assert (pw.tmin, pw.tmax, pw.wet_days) == (12, 19, 0)


@respx.mock
def test_period_outside_horizon_averages_three_prior_years():
    route = respx.get(weather.ARCHIVE_URL).mock(return_value=httpx.Response(200, json=daily(7, 10, 20, mm=2.0, wind=20)))
    pw = weather.period_weather((35, 129), dt.date(2026, 10, 26), dt.date(2026, 11, 1), today=dt.date(2026, 10, 8))
    assert route.call_count == 3 and pw.n_typical == 7 and len(pw.days) == 7
    assert pw.wet_days == 7 and pw.total_mm == pytest.approx(14.0) and pw.avg_tmax == 20


@respx.mock
def test_period_straddling_horizon_mixes_forecast_and_typical():
    respx.get(weather.FORECAST_URL).mock(return_value=httpx.Response(200, json=daily(2, 8, 15, prob=70)))
    respx.get(weather.ARCHIVE_URL).mock(return_value=httpx.Response(200, json=daily(3, 10, 20)))
    pw = weather.period_weather((35, 129), dt.date(2026, 10, 22), dt.date(2026, 10, 26), today=dt.date(2026, 10, 8))
    assert pw.n_forecast == 2 and pw.n_typical == 3
    assert [d.date.day for d in pw.days] == [22, 23, 24, 25, 26]


@respx.mock
def test_period_skips_prior_year_with_wrong_length():
    respx.get(weather.ARCHIVE_URL).mock(return_value=httpx.Response(200, json=daily(3, 10, 20)))
    pw = weather.period_weather((35, 129), dt.date(2026, 10, 26), dt.date(2026, 10, 27), today=dt.date(2026, 10, 8))
    assert pw is None


def test_advise_period_uses_average_highs_and_coldest_morning():
    days = [wx(3, 12), wx(8, 22), wx(6, 14, prob=60)]
    pw = weather.PeriodWeather(dt.date(2026, 10, 26), dt.date(2026, 10, 28), days)
    a = advise_period(pw)
    assert any("coldest mornings" in x for x in a.extras)
    assert any("rain" in x.lower() for x in a.extras)


def test_same_day_in_leap_year_edge():
    assert weather._same_day_in(dt.date(2028, 2, 29), 2027) == dt.date(2027, 2, 28)


from app import photos
from app.cache import Cache
from app.maps import OsmServices
from app.places import Listing


def make_osm(tmp_path):
    return OsmServices(Cache(tmp_path / "c.sqlite"))


@respx.mock
def test_photo_from_wikipedia_tag(tmp_path):
    respx.get("https://en.wikipedia.org/api/rest_v1/page/summary/Cheomseongdae").mock(
        return_value=httpx.Response(200, json={
            "thumbnail": {"source": "https://upload.wikimedia.org/x.jpg"},
            "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Cheomseongdae"}}}))
    item = Listing("Cheomseongdae", None, "u", 0, 0, {"wikipedia": "en:Cheomseongdae"})
    photos.attach_photos(make_osm(tmp_path), [item])
    assert item.photo == "https://upload.wikimedia.org/x.jpg" and "wikipedia.org/wiki" in item.photo_page


@respx.mock
def test_photo_from_wikidata_when_wikipedia_has_none(tmp_path):
    respx.get(photos.WIKIDATA_API).mock(return_value=httpx.Response(200, json={"claims": {"P18": [
        {"mainsnak": {"datavalue": {"value": "Bulguksa Temple.jpg"}}}]}}))
    item = Listing("Bulguksa", None, "u", 0, 0, {"wikidata": "Q123"})
    photos.attach_photos(make_osm(tmp_path), [item])
    assert item.photo.endswith("Special:FilePath/Bulguksa%20Temple.jpg?width=480")
    assert item.photo_page.endswith("File:Bulguksa_Temple.jpg")


@respx.mock
def test_geosearch_fallback_requires_similar_name(tmp_path):
    respx.get(photos.EN_WIKIPEDIA_API).mock(return_value=httpx.Response(200, json={"query": {"pages": {
        "1": {"title": "Unrelated Mall", "index": 1, "thumbnail": {"source": "https://x/mall.jpg"}},
        "2": {"title": "Gyerim Forest", "index": 2, "thumbnail": {"source": "https://x/forest.jpg"},
              "fullurl": "https://en.wikipedia.org/wiki/Gyerim"}}}}))
    item = Listing("Gyerim Forest", None, "u", 35.8, 129.2)
    photos.attach_photos(make_osm(tmp_path), [item])
    assert item.photo == "https://x/forest.jpg"
    other = Listing("Totally Different Place", None, "u", 35.8, 129.2)
    photos.attach_photos(make_osm(tmp_path), [other])
    assert other.photo is None


@respx.mock
def test_bad_wikipedia_language_and_qid_are_ignored(tmp_path):
    route = respx.route().mock(return_value=httpx.Response(500))
    item = Listing("Name", None, "u", 0, 0, {"wikipedia": "evil.com/x:Page", "wikidata": "Q1;drop"})
    photos.attach_photos(make_osm(tmp_path), [item])
    assert item.photo is None
    assert all("evil.com" not in str(c.request.url) for c in route.calls)


def test_similar_rejects_shared_city_word_only():
    assert not photos._similar("Busan City Art Museum", "Busan Exhibition and Convention Center")
    assert photos._similar("Gyerim Forest", "Gyerim")
    assert photos._similar("Cheomseongdae", "Cheomseongdae")
    assert not photos._similar("Totally Different Place", "Gyerim Forest")
    assert not photos._similar("국립부산과학관", "National Science Museum")
