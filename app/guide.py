from dataclasses import dataclass, field

import httpx

from app import names, photos, places
from app.geo import Point, point_at
from app.maps import OsmServices
from app.places import Listing
from app.models import Day, Itinerary
from app.routes import DayRoute, build_day_route

AVG_SPEED_KMH = 15.0
DEFAULT_START_HOUR = 9.0
LUNCH_HOUR = 12.0


@dataclass
class DayGuide:
    day: Day
    route: DayRoute | None = None
    lunch_point: Point | None = None
    breakfast: list[Listing] = field(default_factory=list)
    lunch: list[Listing] = field(default_factory=list)
    dinner: list[Listing] = field(default_factory=list)
    pois: list[Listing] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def map_data(self) -> dict:
        return {
            "path": [{"lat": a, "lng": b} for a, b in (self.route.points if self.route else [])],
            "stops": [{"name": s.name, "lat": s.point[0], "lng": s.point[1]} for s in (self.route.stops if self.route else [])],
        }


def start_hour(day: Day) -> float:
    try:
        hh, mm = day.start_time.split(":")
        return int(hh) + int(mm) / 60
    except (AttributeError, ValueError):
        return DEFAULT_START_HOUR


def lunch_point(route_points: list[Point], hour: float) -> Point:
    ridden_m = max(0.0, LUNCH_HOUR - hour) * AVG_SPEED_KMH * 1000
    return point_at(route_points, ridden_m)


def build_day_guide(
    trip: Itinerary,
    day: Day,
    osm: OsmServices,
    section: str = "all",
) -> DayGuide:
    """section: 'route' (map, sights), 'food' (meals) or 'all'."""
    g = DayGuide(day=day)
    area = f"{day.city}, {trip.country}"

    def attempt(label, fn, default=None):
        try:
            return fn()
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            g.warnings.append(f"{label} unavailable ({type(exc).__name__})")
            return default

    g.route = attempt("Route", lambda: build_day_route(osm, day, trip.country))
    if day.is_ride and g.route is None:
        g.warnings.append("Could not build a route from the itinerary stops")
    if g.route:
        located = {s.name for s in g.route.stops}
        missing = [s.name for s in day.stops if s.name not in located]
        if missing:
            g.warnings.append("Could not locate on the map (skipped): " + "; ".join(missing))
    if g.route and g.route.mode != "BICYCLE":
        g.warnings.append("Routing service unavailable; the line joins the stops directly and is indicative only.")

    def locate(query: str) -> Point | None:
        return osm.geocode(query)

    city_pt = attempt("Location", lambda: locate(f"{day.city}, {trip.country}"))
    hotel_pt = (attempt("Hotel location", lambda: locate(f"{day.hotel}, {day.city}, {trip.country}"))
                if day.hotel else None) or city_pt
    start_pt = g.route.points[0] if g.route else (hotel_pt or city_pt)
    end_pt = hotel_pt or (g.route.points[-1] if g.route else None)

    if g.route:
        g.lunch_point = lunch_point(g.route.points, start_hour(day))
    lunch_anchor = g.lunch_point or hotel_pt or city_pt

    meals = (("breakfast", start_pt or hotel_pt), ("lunch", lunch_anchor), ("dinner", end_pt))
    for meal, anchor in meals if section in ("food", "all") else ():
        if anchor:
            setattr(g, meal, attempt(f"{meal.title()} suggestions",
                                     lambda: places.recommend_meal(osm, meal, anchor, area), []))

    if section == "food":
        return g

    if g.route:
        g.pois = attempt("Points of interest", lambda: places.pois_along(osm, g.route.points, area), [])
        names.add_english_names(osm, g.pois, area)
        photos.attach_photos(osm, g.pois)

    return g
