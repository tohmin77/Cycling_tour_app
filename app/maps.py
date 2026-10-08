import hashlib
import json
import threading
import time
from dataclasses import dataclass

import httpx

from app.cache import Cache
from app.geo import Point, haversine_m

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
BROUTER_URL = "https://brouter.de/brouter"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "cycling-tour-app/0.1 (personal trip planner)"
NOMINATIM_INTERVAL_S = 1.1
MAX_GEOCODE_TRIES = 3
OVERPASS_INTERVAL_S = 1.5
OVERPASS_RETRIES = 2
OVERPASS_RETRY_STATUS = {429, 502, 503, 504}


@dataclass
class Route:
    points: list[Point]
    distance_m: float
    mode: str  # "BICYCLE" (BRouter) or "STRAIGHT" (stops joined by straight lines)


class OsmServices:
    """Keyless mapping services: Nominatim (geocoding), BRouter (cycling routes), Overpass (places)."""

    def __init__(self, cache: Cache, client: httpx.Client | None = None):
        self.cache = cache
        self.client = client or httpx.Client(timeout=45, headers={"User-Agent": USER_AGENT})
        self._last_geocode = 0.0
        self._last_overpass = 0.0
        self._lock = threading.Lock()

    def _cached(self, kind: str, payload, send):
        key = hashlib.sha256(json.dumps([kind, payload], sort_keys=True).encode()).hexdigest()
        hit = self.cache.get(key)
        if hit is not None:
            return json.loads(hit)
        resp = send()
        resp.raise_for_status()
        data = resp.json()
        self.cache.set(key, json.dumps(data))
        return data

    def _geocode_once(self, query: str) -> Point | None:
        params = {"q": query, "format": "json", "limit": 1}

        def send():
            with self._lock:  # Nominatim's usage policy allows at most 1 request per second
                wait = NOMINATIM_INTERVAL_S - (time.monotonic() - self._last_geocode)
                if wait > 0:
                    time.sleep(wait)
                try:
                    return self.client.get(NOMINATIM_URL, params=params)
                finally:
                    self._last_geocode = time.monotonic()

        data = self._cached("geocode", params, send)
        return (float(data[0]["lat"]), float(data[0]["lon"])) if data else None

    def geocode(self, query: str) -> Point | None:
        """Try the full query, then progressively shorter place names ('Eulsukdo Eco Park' -> 'Eulsukdo')."""
        place, _, rest = query.partition(",")
        words = place.split()
        tries = 0
        for n in range(len(words), 0, -1):
            if tries >= MAX_GEOCODE_TRIES:
                break
            tries += 1
            found = self._geocode_once(f"{' '.join(words[:n])},{rest}" if rest else " ".join(words[:n]))
            if found:
                return found
        return None

    def route(self, stops: list[Point]) -> Route:
        """Cycling route through the stops; falls back to straight lines if BRouter can't help."""
        lonlats = "|".join(f"{lng:.6f},{lat:.6f}" for lat, lng in stops)
        params = {"lonlats": lonlats, "profile": "trekking", "alternativeidx": 0, "format": "geojson"}
        try:
            data = self._cached("route", params, lambda: self.client.get(BROUTER_URL, params=params))
            feature = data["features"][0]
            points = [(c[1], c[0]) for c in feature["geometry"]["coordinates"]]
            return Route(points, float(feature["properties"]["track-length"]), "BICYCLE")
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError):
            length = sum(haversine_m(a, b) for a, b in zip(stops, stops[1:]))
            return Route(list(stops), length, "STRAIGHT")

    def _overpass_post(self, query: str) -> httpx.Response:
        for attempt in range(OVERPASS_RETRIES + 1):
            with self._lock:  # the public server rate-limits bursts of requests
                wait = OVERPASS_INTERVAL_S - (time.monotonic() - self._last_overpass)
                if wait > 0:
                    time.sleep(wait)
                try:
                    resp = self.client.post(OVERPASS_URL, data={"data": query}, timeout=90)
                finally:
                    self._last_overpass = time.monotonic()
            if resp.status_code not in OVERPASS_RETRY_STATUS or attempt == OVERPASS_RETRIES:
                return resp
            time.sleep(5 * (attempt + 1))
        return resp

    def fetch_json(self, url: str, params: dict) -> dict:
        return self._cached("json", [url, params], lambda: self.client.get(url, params=params))

    def overpass(self, query: str) -> list[dict]:
        data = self._cached("overpass", query, lambda: self._overpass_post(query))
        return data.get("elements", [])
