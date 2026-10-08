from dataclasses import dataclass, field

import datetime as dt

from app.weather import PeriodWeather, Weather


@dataclass
class Advice:
    attire: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    off_bike: list[str] = field(default_factory=list)


def advise(w: Weather) -> Advice:
    a = Advice()
    if w.tmax >= 28:
        a.attire += ["Light short-sleeve jersey", "Padded shorts or bib shorts", "Light socks"]
        a.extras += ["Sunscreen and lip balm", "Extra water bottle / electrolytes"]
    elif w.tmax >= 20:
        a.attire += ["Short-sleeve jersey", "Padded shorts or bib shorts"]
    elif w.tmax >= 12:
        a.attire += ["Long-sleeve jersey or short sleeves with arm warmers", "Padded shorts with knee warmers or tights",
                     "Light full-finger gloves"]
    elif w.tmax >= 5:
        a.attire += ["Thermal base layer", "Long-sleeve thermal jersey", "Thermal tights", "Warm gloves",
                     "Ear band or cap under helmet", "Shoe covers"]
    else:
        a.attire += ["Thermal base layer", "Insulated winter jacket", "Thermal tights", "Winter gloves",
                     "Neck warmer and ear cover", "Overshoes"]

    if w.tmin < 8 and 12 <= w.tmax < 20:
        a.extras.append("Thermal base layer and warm gloves for the coldest mornings")
    if w.tmin < 12 and w.tmax >= 20:
        a.extras.append("Arm warmers or a packable gilet for the cold morning start")
    if w.tmax >= 20:
        a.extras.append("Sunglasses")
    if (w.precip_prob or 0) >= 50 or w.precip_mm >= 2:
        a.extras += ["Waterproof packable jacket", "Waterproof shoe covers", "Clear or tinted glasses for spray",
                     "Be careful on wet metal, paint and leaves; brake early"]
    elif (w.precip_prob or 0) >= 25:
        a.extras.append("Packable rain jacket in the bag")
    if w.wind_kmh >= 30:
        a.extras.append("Windproof layer; expect strong crosswinds on exposed coast and river paths")
    a.off_bike += ["Comfortable shoes for walking sites", "Light jacket or fleece for the evening"
                   if w.tmin < 15 else "Light layer for air-conditioned venues"]
    return a


def advise_period(pw: PeriodWeather) -> Advice:
    """Packing advice covering the whole period: average daytime highs, coldest morning, wettest outlook."""
    n = len(pw.days)
    return advise(Weather(
        pw.start, pw.tmin, pw.avg_tmax, 100 * pw.wet_days / n, pw.total_mm / n, pw.wind_max,
        typical=pw.n_forecast == 0,
    ))
