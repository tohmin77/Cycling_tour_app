import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx
from pydantic import ValidationError

from app import config
from app.apps import apps_for
from app.cache import Cache
from app.advice import advise_period
from app.guide import build_day_guide
from app.maps import OsmServices
from app.models import Itinerary
from app.parser import extract_text, parse_itinerary
from app.photos import region_banner
from app.routes import hotel_links
from app.urls import LiveUrls
from app.weather import period_weather

HERE = Path(__file__).parent
MAX_UPLOAD = 10 * 1024 * 1024
TRIP_ID = re.compile(r"^[0-9a-f]{32}$")

app = FastAPI(title="Cycling Tour Companion")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.globals["hotel_links"] = hotel_links


def get_osm() -> OsmServices:
    return OsmServices(Cache(config.CACHE_PATH))


def trip_path(trip_id: str) -> Path:
    if not TRIP_ID.match(trip_id):
        raise HTTPException(404, "Trip not found")
    return config.TRIPS_DIR / f"{trip_id}.json"


def load_trip(trip_id: str) -> Itinerary:
    path = trip_path(trip_id)
    if not path.exists():
        raise HTTPException(404, "Trip not found")
    return Itinerary.model_validate_json(path.read_text())


def save_trip(trip_id: str, trip: Itinerary) -> None:
    config.TRIPS_DIR.mkdir(parents=True, exist_ok=True)
    trip_path(trip_id).write_text(trip.model_dump_json(indent=2))


def render(request: Request, name: str, status: int = 200, **ctx):
    return templates.TemplateResponse(request, name, ctx, status_code=status)


def tab_page(request: Request, name: str, trip_id: str, trip: Itinerary, tab: str, day, **ctx):
    try:
        banner = region_banner(get_osm(), trip)
    except Exception:
        banner = None
    return render(request, name, tab=tab, trip=trip, trip_id=trip_id, day=day, banner=banner,
                  u=LiveUrls(trip_id), **ctx)


def day_or_first(trip: Itinerary, number: int):
    return next((x for x in trip.days if x.number == number), trip.days[0] if trip.days else None)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return render(request, "index.html", error=None)


@app.post("/upload")
async def upload(
    request: Request,
    file: UploadFile | None = File(None),
    text: str = Form(""),
    itinerary_json: str = Form(""),
):
    def fail(msg: str):
        return render(request, "index.html", status=400, error=msg)

    try:
        if itinerary_json.strip():
            trip = Itinerary.model_validate_json(itinerary_json)
        elif file and file.filename:
            data = await file.read(MAX_UPLOAD + 1)
            if len(data) > MAX_UPLOAD:
                return fail("File is larger than 10 MB")
            if not data.startswith(b"%PDF"):
                return fail("Please upload a PDF file")
            trip = parse_itinerary(extract_text(data))
        elif text.strip():
            trip = parse_itinerary(text)
        else:
            return fail("Upload a PDF, paste the itinerary text, or paste itinerary JSON")
    except (ValueError, ValidationError) as exc:
        return fail(f"Could not read the itinerary: {exc}")
    except Exception:
        return fail("Could not process the itinerary (unreadable PDF, or the parser failed).")
    trip_id = uuid.uuid4().hex
    save_trip(trip_id, trip)
    return RedirectResponse(f"/trip/{trip_id}", status_code=303)


@app.get("/sample")
def sample():
    found = sorted(config.TOURS_DIR.glob("*/itinerary.json"))
    if not found:
        raise HTTPException(404, "No tours found in the tours folder")
    trip = Itinerary.model_validate_json(found[0].read_text())
    trip_id = uuid.uuid4().hex
    save_trip(trip_id, trip)
    return RedirectResponse(f"/trip/{trip_id}", status_code=303)


def find_day(trip: Itinerary, number: int):
    day = next((d for d in trip.days if d.number == number), None)
    if day is None:
        raise HTTPException(404, "Day not found")
    return day


@app.get("/trip/{trip_id}")
def trip_view(trip_id: str):
    trip = load_trip(trip_id)
    first = trip.days[0].number if trip.days else 1
    return RedirectResponse(f"/trip/{trip_id}/day/{first}", status_code=303)


@app.get("/trip/{trip_id}/apps", response_class=HTMLResponse)
def apps_tab(request: Request, trip_id: str, d: int = 1):
    trip = load_trip(trip_id)
    try:
        apps, curated = apps_for(trip.country)
    except Exception:
        apps, curated = None, False
    return tab_page(request, "apps.html", trip_id, trip, "apps", day_or_first(trip, d),
                    apps=apps, curated=curated)


@app.get("/trip/{trip_id}/weather", response_class=HTMLResponse)
def weather_tab(request: Request, trip_id: str, d: int = 1):
    trip = load_trip(trip_id)
    return tab_page(request, "weather.html", trip_id, trip, "weather", day_or_first(trip, d))


@app.get("/trip/{trip_id}/weather.part", response_class=HTMLResponse)
def weather_part(request: Request, trip_id: str):
    trip = load_trip(trip_id)
    pw = advice = None
    region = trip.main_city
    if trip.days and region:
        try:
            point = get_osm().geocode(f"{region}, {trip.country}")
            if point:
                pw = period_weather(point, trip.start, trip.end)
                advice = advise_period(pw) if pw else None
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    return render(request, "weather_part.html", pw=pw, advice=advice, region=region)


@app.get("/trip/{trip_id}/edit", response_class=HTMLResponse)
def edit_form(request: Request, trip_id: str):
    trip = load_trip(trip_id)
    return render(request, "edit.html", trip_id=trip_id, body=trip.model_dump_json(indent=2), error=None)


@app.post("/trip/{trip_id}/edit")
def edit_save(request: Request, trip_id: str, body: str = Form(...)):
    load_trip(trip_id)
    try:
        trip = Itinerary.model_validate_json(body)
    except ValidationError as exc:
        return render(request, "edit.html", status=400, trip_id=trip_id, body=body, error=str(exc))
    save_trip(trip_id, trip)
    return RedirectResponse(f"/trip/{trip_id}", status_code=303)


@app.get("/trip/{trip_id}/day/{number}", response_class=HTMLResponse)
def route_tab(request: Request, trip_id: str, number: int):
    trip = load_trip(trip_id)
    return tab_page(request, "route.html", trip_id, trip, "route", find_day(trip, number))


@app.get("/trip/{trip_id}/day/{number}/food", response_class=HTMLResponse)
def food_tab(request: Request, trip_id: str, number: int):
    trip = load_trip(trip_id)
    return tab_page(request, "food.html", trip_id, trip, "food", find_day(trip, number))


@app.get("/trip/{trip_id}/day/{number}/{section}.part", response_class=HTMLResponse)
def day_part(request: Request, trip_id: str, number: int, section: str):
    if section not in ("route", "food"):
        raise HTTPException(404, "Not found")
    trip = load_trip(trip_id)
    guide = build_day_guide(trip, find_day(trip, number), get_osm(), section=section)
    return render(request, f"{section}_part.html", g=guide)
