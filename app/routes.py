from dataclasses import dataclass
from urllib.parse import urlencode

from app.geo import Point
from app.maps import OsmServices
from app.models import Day


@dataclass
class ResolvedStop:
    name: str
    kind: str
    point: Point


@dataclass
class DayRoute:
    points: list[Point]
    distance_m: float
    mode: str
    stops: list[ResolvedStop]
    maps_url: str


def resolve_stops(maps: OsmServices, day: Day, country: str) -> list[ResolvedStop]:
    out = []
    for stop in day.stops:
        if stop.lat is not None and stop.lng is not None:
            point = (stop.lat, stop.lng)
        else:
            point = maps.geocode(f"{stop.name}, {country}")
        if point:
            out.append(ResolvedStop(stop.name, stop.kind, point))
    return out


def maps_url(stops: list[ResolvedStop]) -> str:
    fmt = lambda s: f"{s.point[0]},{s.point[1]}"
    params = {
        "api": 1,
        "origin": fmt(stops[0]),
        "destination": fmt(stops[-1]),
        "travelmode": "bicycling",
    }
    waypoints = [fmt(s) for s in stops[1:-1]][:9]
    if waypoints:
        params["waypoints"] = "|".join(waypoints)
    return "https://www.google.com/maps/dir/?" + urlencode(params)


def build_day_route(maps: OsmServices, day: Day, country: str) -> DayRoute | None:
    if not day.is_ride:
        return None
    stops = resolve_stops(maps, day, country)
    if len(stops) < 2:
        return None
    route = maps.route([s.point for s in stops])
    return DayRoute(route.points, route.distance_m, route.mode, stops, maps_url(stops))
