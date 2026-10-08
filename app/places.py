from dataclasses import dataclass, field
from urllib.parse import urlencode

from app.geo import Point, haversine_m, thin
from app.maps import OsmServices

CORRIDOR_M = 3000
MEAL_RADIUS_M = {"breakfast": 1500, "lunch": 2000, "dinner": 1500}
MAX_CORRIDOR_POINTS = 40


@dataclass
class Listing:
    name: str
    address: str | None
    url: str
    lat: float
    lng: float
    ref: dict = field(default_factory=dict)
    local_name: str | None = None
    name_note: str | None = None
    photo: str | None = None
    photo_page: str | None = None


def _score(tags: dict) -> float:
    score = 0.0
    if "wikidata" in tags or "wikipedia" in tags:
        score += 3
    if tags.get("website") or tags.get("contact:website"):
        score += 1
    if "opening_hours" in tags:
        score += 1
    if "name:en" in tags:
        score += 1
    if "cuisine" in tags:
        score += 0.5
    if tags.get("tourism") in ("attraction", "museum"):
        score += 1
    return score


def _address(tags: dict) -> str | None:
    if tags.get("addr:full"):
        return tags["addr:full"]
    street = " ".join(filter(None, (tags.get("addr:street"), tags.get("addr:housenumber"))))
    parts = [street, tags.get("addr:city") or tags.get("addr:district")]
    return ", ".join(p for p in parts if p) or None


def _listings(elements: list[dict], area: str) -> list[tuple[float, Listing]]:
    seen, out = set(), []
    for el in elements:
        tags = el.get("tags", {})
        local = tags.get("name")
        name = tags.get("name:en") or local
        pos = el if "lat" in el else el.get("center")
        if not name or not pos or name in seen:
            continue
        seen.add(name)
        address = _address(tags)
        url = "https://www.google.com/maps/search/?" + urlencode(
            {"api": 1, "query": f"{local or name}, {address or area}"}
        )
        ref = {k: v for k, v in (("wikipedia", tags.get("wikipedia")), ("wikidata", tags.get("wikidata")),
                                 ("commons", tags.get("wikimedia_commons"))) if v}
        listing = Listing(name, address, url, pos["lat"], pos["lon"], ref,
                          local_name=local if local and local != name else None)
        out.append((_score(tags), listing))
    return out


def recommend_meal(osm: OsmServices, meal: str, near: Point, area: str, top: int = 3) -> list[Listing]:
    around = f"around:{MEAL_RADIUS_M[meal]},{near[0]:.5f},{near[1]:.5f}"
    parts = [f'nwr["amenity"~"^(restaurant|cafe)$"]["name"]({around});']
    if meal == "breakfast":
        parts.append(f'nwr["shop"="bakery"]["name"]({around});')
    query = "[out:json][timeout:30];(" + "".join(parts) + ");out center 120;"
    scored = _listings(osm.overpass(query), area)
    scored.sort(key=lambda s: (-s[0], haversine_m(near, (s[1].lat, s[1].lng))))
    return [listing for _, listing in scored[:top]]


def pois_along(osm: OsmServices, route_points: list[Point], area: str, top: int = 12) -> list[Listing]:
    line = ",".join(f"{lat:.5f},{lng:.5f}" for lat, lng in thin(route_points, MAX_CORRIDOR_POINTS))
    around = f"around:{CORRIDOR_M},{line}"
    parts = [
        f'nwr["tourism"~"^(attraction|museum|viewpoint|gallery)$"]["name"]({around});',
        f'nwr["historic"]["name"]({around});',
        f'nwr["leisure"="park"]["name"]({around});',
        f'nwr["natural"="beach"]["name"]({around});',
    ]
    query = "[out:json][timeout:60];(" + "".join(parts) + ");out center 400;"
    scored = _listings(osm.overpass(query), area)
    scored.sort(key=lambda s: (-s[0], s[1].name))
    return [listing for _, listing in scored[:top]]
