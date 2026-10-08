"""Export a tour as a self-contained static site (one folder per tour, deployable on its own).

    python -m app.export tours/busan-2026-10-26/itinerary.json
    python -m app.export my-itinerary.json        # creates tours/<slug>/ and copies the JSON in
"""
import argparse
import datetime as dt
import re
import shutil
import sys
import unicodedata
from pathlib import Path

import httpx
from jinja2 import Environment, FileSystemLoader

from app import config
from app.advice import advise_period
from app.apps import apps_for
from app.cache import Cache
from app.guide import build_day_guide
from app.maps import OsmServices
from app.models import Itinerary
from app.photos import region_banner
from app.urls import StaticUrls
from app.weather import period_weather

HERE = Path(__file__).parent
ASSETS = ("style.css", "app.js", "map.js")


def slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def slug_for(trip: Itinerary) -> str:
    place = slugify(trip.main_city or "") or slugify(trip.country) or "tour"
    return f"{place}-{trip.start.isoformat() if trip.start else 'undated'}"


def build_site(trip: Itinerary, osm: OsmServices, out: Path, today: dt.date | None = None) -> list[str]:
    """Render every page into `out` (replacing it). Returns human-readable warnings."""
    today = today or dt.date.today()
    env = Environment(loader=FileSystemLoader(HERE / "templates"), autoescape=True)
    warnings: list[str] = []

    try:
        banner = region_banner(osm, trip)
    except Exception:
        banner = None
    if banner is None:
        warnings.append("No region banner photo found")

    pw = advice = None
    region = trip.main_city
    if trip.days and region:
        try:
            point = osm.geocode(f"{region}, {trip.country}")
            pw = period_weather(point, trip.start, trip.end, today) if point else None
            advice = advise_period(pw) if pw else None
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    if pw is None:
        warnings.append("Weather unavailable")

    try:
        apps, curated = apps_for(trip.country)
    except Exception:
        apps, curated = None, False
        warnings.append("App suggestions unavailable")

    pages: dict[str, str] = {}
    for day in trip.days:
        base = dict(trip=trip, day=day, banner=banner, u=StaticUrls(), static=True, inline=True,
                    generated=today.strftime("%-d %b %Y"))

        def page(name: str, tab: str, **ctx) -> str:
            return env.get_template(name).render(**base, tab=tab, **ctx)

        for section in ("route", "food"):
            guide = build_day_guide(trip, day, osm, section=section)
            # the food pass repeats the route warnings; keep only what is specific to it
            own = [w for w in guide.warnings if section == "route" or "suggestions" in w]
            warnings += [f"Day {day.number}: {w}" for w in own]
            pages[f"{section}-{day.number}.html"] = page(f"{section}.html", section, g=guide)
        pages[f"weather-{day.number}.html"] = page("weather.html", "weather", pw=pw, advice=advice, region=region)
        pages[f"apps-{day.number}.html"] = page("apps.html", "apps", apps=apps, curated=curated)

    if trip.days:
        pages["index.html"] = pages[f"route-{trip.days[0].number}.html"]

    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    for name in ASSETS:
        shutil.copy(HERE / "static" / name, out / "static" / name)
    for name, html in pages.items():
        (out / name).write_text(html, encoding="utf-8")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=Path, help="itinerary JSON file, or a tour folder containing itinerary.json")
    parser.add_argument("--tours-dir", type=Path, default=config.TOURS_DIR)
    args = parser.parse_args(argv)

    json_path = args.source / "itinerary.json" if args.source.is_dir() else args.source
    trip = Itinerary.model_validate_json(json_path.read_text())
    folder = args.tours_dir / slug_for(trip)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "itinerary.json"
    if json_path.resolve() != target.resolve():
        shutil.copy(json_path, target)

    warnings = build_site(trip, OsmServices(Cache(config.CACHE_PATH)), folder / "site")
    print(f"Built {folder / 'site'}")
    for w in warnings:
        print(f"  warning: {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
