import re
from collections import Counter
from urllib.parse import quote

import httpx

from app.maps import OsmServices
from app.places import Listing

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
EN_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
THUMB_W = 480
LANG = re.compile(r"^[a-z]{2,3}(-[a-z]+)?$")
QID = re.compile(r"^Q\d+$")
GENERIC_WORDS = {"park", "temple", "museum", "beach", "lake", "site", "bridge", "hall", "palace", "tomb",
                 "gallery", "village", "river", "mountain", "station"}
ERRORS = (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError)

Photo = tuple[str, str | None]  # (image url, page crediting the photo)


def _commons(filename: str) -> Photo | None:
    name = filename.removeprefix("File:").strip()
    if not name:
        return None
    return (
        f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(name)}?width={THUMB_W}",
        f"https://commons.wikimedia.org/wiki/File:{quote(name.replace(' ', '_'))}",
    )


def _from_wikipedia_tag(osm: OsmServices, tag: str) -> Photo | None:
    lang, _, title = tag.partition(":")
    if not LANG.match(lang) or not title:
        return None
    data = osm.fetch_json(
        f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title.replace(' ', '_'), safe='')}", {}
    )
    thumb = (data.get("thumbnail") or {}).get("source")
    page = (data.get("content_urls") or {}).get("desktop", {}).get("page")
    return (_https(thumb), _https(page)) if thumb else None


def _from_wikidata(osm: OsmServices, qid: str) -> Photo | None:
    if not QID.match(qid):
        return None
    data = osm.fetch_json(
        WIKIDATA_API, {"action": "wbgetclaims", "entity": qid, "property": "P18", "format": "json"}
    )
    claims = data.get("claims", {}).get("P18") or []
    return _commons(claims[0]["mainsnak"]["datavalue"]["value"]) if claims else None


def _distinctive(text: str) -> set[str]:
    return {w for w in re.findall(r"\w{3,}", text.lower()) if w not in GENERIC_WORDS}


def _similar(name: str, title: str) -> bool:
    """Same place only if one name's distinctive words are all contained in the other's."""
    a, b = _distinctive(name), _distinctive(title)
    return bool(a and b) and (a <= b or b <= a)


def _https(url: str | None) -> str | None:
    return "https:" + url if url and url.startswith("//") else url


def _from_geosearch(osm: OsmServices, listing: Listing) -> Photo | None:
    data = osm.fetch_json(EN_WIKIPEDIA_API, {
        "action": "query", "generator": "geosearch", "ggscoord": f"{listing.lat:.5f}|{listing.lng:.5f}",
        "ggsradius": 600, "ggslimit": 5, "prop": "pageimages|info", "piprop": "thumbnail",
        "pithumbsize": THUMB_W, "inprop": "url", "format": "json",
    })
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for page in pages:
        thumb = (page.get("thumbnail") or {}).get("source")
        if thumb and _similar(listing.name, page.get("title", "")):
            return _https(thumb), _https(page.get("fullurl"))
    return None


def attach_photos(osm: OsmServices, listings: list[Listing]) -> None:
    """Best-effort: set photo/photo_page from Wikimedia sources. Failures just leave a listing without one."""
    for listing in listings:
        ref = listing.ref
        steps = [
            lambda: _from_wikipedia_tag(osm, ref["wikipedia"]) if "wikipedia" in ref else None,
            lambda: _from_wikidata(osm, ref["wikidata"]) if "wikidata" in ref else None,
            lambda: _commons(ref["commons"]) if ref.get("commons", "").startswith("File:") else None,
            lambda: _from_geosearch(osm, listing),
        ]
        for step in steps:
            try:
                found = step()
            except ERRORS:
                continue
            if found:
                listing.photo, listing.photo_page = found
                break


BANNER_W = 1000
MIN_BANNER_ASPECT = 1.3


def region_banner(osm: OsmServices, trip) -> Photo | None:
    """A wide Wikimedia photo of the tour's main city (falling back to its other cities, then the country)."""
    cities = [c for c, _ in Counter(d.city for d in trip.days if d.city).most_common()]
    for title in [*cities, trip.country][:4]:
        try:
            data = osm.fetch_json(EN_WIKIPEDIA_API, {
                "action": "query", "titles": title, "redirects": 1, "prop": "pageimages",
                "piprop": "thumbnail|name", "pithumbsize": BANNER_W, "format": "json",
            })
            for page in data.get("query", {}).get("pages", {}).values():
                thumb = page.get("thumbnail") or {}
                if thumb.get("source") and thumb["width"] >= MIN_BANNER_ASPECT * thumb["height"]:
                    credit = _commons(page["pageimage"])[1] if page.get("pageimage") else None
                    return _https(thumb["source"]), credit
        except ERRORS:
            continue
    return None
