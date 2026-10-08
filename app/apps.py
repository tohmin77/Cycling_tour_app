import json
from pathlib import Path

from app.llm import tool_json

DATA = Path(__file__).parent / "data" / "country_apps.json"

_ITEMS = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"name": {"type": "string"}, "use": {"type": "string"}},
        "required": ["name", "use"],
    },
}
SCHEMA = {
    "type": "object",
    "properties": {"transport": _ITEMS, "navigation": _ITEMS, "payment": _ITEMS},
    "required": ["transport", "navigation", "payment"],
}


def _curated(country: str) -> dict | None:
    data = json.loads(DATA.read_text())
    key = country.strip().lower()
    key = data["_aliases"].get(key, key)
    return data.get(key) if key != "_aliases" else None


def apps_for(country: str) -> tuple[dict, bool]:
    """Return (apps by category, curated). Unknown countries are filled in by Claude and flagged."""
    curated = _curated(country)
    if curated:
        return curated, True
    data = tool_json(
        "You advise cycling tourists. Recommend 3-5 apps per category that work for foreign visitors "
        "in the given country: local public transport/ticketing and taxi apps, navigation and cycling "
        "apps, and payment options. Be honest about limits for foreign cards.",
        f"Country: {country}",
        "record_apps",
        SCHEMA,
        max_tokens=2000,
    )
    return {k: data[k] for k in ("transport", "navigation", "payment")}, False
