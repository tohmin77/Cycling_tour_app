# Cycling Tour Companion

Load a tour itinerary and get, per day: an indicative cycling route on a map, breakfast/lunch/dinner suggestions (near the start, the noon point on the route, and the hotel), sights within 3 km of the route, weather with clothing advice, and recommended transport/navigation/payment apps for the country. Restaurants and sights are listed with addresses and Google Maps links.

No API keys are needed. Data comes from OpenStreetMap services (Nominatim geocoding, BRouter cycling routes, Overpass places) and Open-Meteo weather.

## Setup and run
```
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000 and either click "Load the Busan 2026 sample" or paste itinerary JSON (format: `samples/busan_2026.json`).

Uploading a PDF or pasting itinerary text additionally needs `ANTHROPIC_API_KEY` (copy `.env.example` to `.env`). Without it, use the JSON import.

## Tests
```
python -m pytest
```

## Notes
- The first load of each day takes 1-2 minutes (public servers, rate-limited to be polite); results are cached in `var/cache.sqlite`, so repeat loads are instant.
- Stops that cannot be geocoded are skipped and listed as a warning; edit the itinerary JSON to use better names.
- If BRouter is unavailable, the route line joins the stops directly.
- Open-Meteo forecasts reach 15 days ahead. Further out, the app shows typical conditions averaged over the last 3 years.
- OpenStreetMap has no ratings, so suggestions are ranked by how well-documented a place is (website, opening hours, Wikipedia entry) and by distance.
