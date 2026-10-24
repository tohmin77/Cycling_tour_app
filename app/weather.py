import datetime as dt
from dataclasses import dataclass

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_HORIZON_DAYS = 15
TYPICAL_YEARS = 3
DAILY = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
HOURLY = "temperature_2m,precipitation,wind_speed_10m"
DAY_START_HOUR = 6
DAY_END_HOUR = 22  # inclusive: the 22:00 reading
WET_PROB = 50
WET_MM = 2


@dataclass
class Weather:
    date: dt.date
    tmin: float
    tmax: float
    precip_prob: float | None
    precip_mm: float
    wind_kmh: float
    typical: bool

    @property
    def wet(self) -> bool:
        return (self.precip_prob or 0) >= WET_PROB or self.precip_mm >= WET_MM


@dataclass
class PeriodWeather:
    start: dt.date
    end: dt.date
    days: list[Weather]
    point: tuple[float, float] | None = None

    @property
    def tmin(self) -> float:
        return min(d.tmin for d in self.days)

    @property
    def tmax(self) -> float:
        return max(d.tmax for d in self.days)

    @property
    def avg_tmin(self) -> float:
        return _mean([d.tmin for d in self.days])

    @property
    def avg_tmax(self) -> float:
        return _mean([d.tmax for d in self.days])

    @property
    def wet_days(self) -> int:
        return sum(d.wet for d in self.days)

    @property
    def total_mm(self) -> float:
        return sum(d.precip_mm for d in self.days)

    @property
    def wind_max(self) -> float:
        return max(d.wind_kmh for d in self.days)

    @property
    def n_forecast(self) -> int:
        return sum(not d.typical for d in self.days)

    @property
    def n_typical(self) -> int:
        return sum(d.typical for d in self.days)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _same_day_in(date: dt.date, year: int) -> dt.date:
    try:
        return date.replace(year=year)
    except ValueError:
        return date.replace(year=year, day=28)


def _runs(dates: list[dt.date]) -> list[tuple[dt.date, dt.date]]:
    runs: list[tuple[dt.date, dt.date]] = []
    for d in dates:
        if runs and d - runs[-1][1] == dt.timedelta(days=1):
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


def _get(client: httpx.Client, url: str, point, start: dt.date, end: dt.date, extra_hourly: str = "") -> dict:
    resp = client.get(url, params={
        "latitude": point[0], "longitude": point[1], "daily": DAILY + (",precipitation_probability_max" if extra_hourly else ""),
        "hourly": HOURLY + (("," + extra_hourly) if extra_hourly else ""),
        "start_date": start.isoformat(), "end_date": end.isoformat(), "timezone": "auto",
    })
    resp.raise_for_status()
    return resp.json()


def _daytime(data: dict) -> dict[dt.date, dict]:
    """Per-date stats over 06:00-22:00 local time, from the hourly series (empty if absent)."""
    hourly = data.get("hourly") or {}
    times = hourly.get("time") or []
    by_date: dict[dt.date, dict[str, list[float]]] = {}
    for i, stamp in enumerate(times):
        day, _, hh = stamp.partition("T")
        if not DAY_START_HOUR <= int(hh[:2]) <= DAY_END_HOUR:
            continue
        bucket = by_date.setdefault(dt.date.fromisoformat(day), {"t": [], "mm": [], "wind": [], "prob": []})
        for key, col in (("t", "temperature_2m"), ("mm", "precipitation"), ("wind", "wind_speed_10m"),
                         ("prob", "precipitation_probability")):
            series = hourly.get(col) or []
            if i < len(series) and series[i] is not None:
                bucket[key].append(series[i])
    return {
        d: {"tmin": min(b["t"]), "tmax": max(b["t"]), "mm": sum(b["mm"]),
            "wind": max(b["wind"]) if b["wind"] else 0.0, "prob": max(b["prob"]) if b["prob"] else None}
        for d, b in by_date.items() if b["t"]
    }


def _forecast_range(client, point, start: dt.date, end: dt.date) -> list[Weather]:
    data = _get(client, FORECAST_URL, point, start, end, "precipitation_probability")
    daily = data.get("daily", {})
    day = _daytime(data)
    rows = []
    for i, tmin in enumerate(daily.get("temperature_2m_min") or []):
        tmax = daily["temperature_2m_max"][i]
        if tmin is None or tmax is None:
            continue
        date = start + dt.timedelta(days=i)
        probs = daily.get("precipitation_probability_max") or []
        w = Weather(
            date, tmin, tmax,
            probs[i] if i < len(probs) else None,
            (daily.get("precipitation_sum") or [0.0] * (i + 1))[i] or 0.0,
            (daily.get("wind_speed_10m_max") or [0.0] * (i + 1))[i] or 0.0,
            typical=False,
        )
        if date in day:
            h = day[date]
            w.tmin, w.tmax, w.precip_mm, w.wind_kmh = h["tmin"], h["tmax"], h["mm"], h["wind"]
            w.precip_prob = h["prob"] if h["prob"] is not None else w.precip_prob
        rows.append(w)
    return rows


def _typical_range(client, point, start: dt.date, end: dt.date) -> list[Weather]:
    n = (end - start).days + 1
    years = []
    for back in range(1, TYPICAL_YEARS + 1):
        data = _get(client, ARCHIVE_URL, point,
                    _same_day_in(start, start.year - back), _same_day_in(end, end.year - back))
        daily = data.get("daily", {})
        cols = [daily.get(k) or [] for k in
                ("temperature_2m_min", "temperature_2m_max", "precipitation_sum", "wind_speed_10m_max")]
        if not all(len(c) == n for c in cols):
            continue
        day = _daytime(data)
        first = _same_day_in(start, start.year - back)
        for i in range(n):
            h = day.get(first + dt.timedelta(days=i))
            if h:
                cols[0][i], cols[1][i], cols[2][i], cols[3][i] = h["tmin"], h["tmax"], h["mm"], h["wind"]
        years.append(cols)
    rows = []
    for i in range(n):
        obs = [(y[0][i], y[1][i], y[2][i] or 0.0, y[3][i] or 0.0) for y in years
               if y[0][i] is not None and y[1][i] is not None]
        if obs:
            rows.append(Weather(
                start + dt.timedelta(days=i),
                _mean([o[0] for o in obs]), _mean([o[1] for o in obs]),
                100 * sum(o[2] >= 1 for o in obs) / len(obs),
                _mean([o[2] for o in obs]), _mean([o[3] for o in obs]),
                typical=True,
            ))
    return rows


def period_weather(
    point, start: dt.date, end: dt.date, today: dt.date | None = None, client: httpx.Client | None = None
) -> PeriodWeather | None:
    """Forecast for days within the forecast horizon, 3-year typical conditions for the rest."""
    today = today or dt.date.today()
    dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    horizon = today + dt.timedelta(days=FORECAST_HORIZON_DAYS)
    own = client is None
    client = client or httpx.Client(timeout=20)
    try:
        rows: list[Weather] = []
        for run_start, run_end in _runs(dates):
            in_horizon = today <= run_start and run_end <= horizon
            if today <= run_start <= horizon < run_end:  # run straddles the horizon: split it
                rows += _forecast_range(client, point, run_start, horizon)
                rows += _typical_range(client, point, horizon + dt.timedelta(days=1), run_end)
            elif in_horizon:
                rows += _forecast_range(client, point, run_start, run_end)
            else:
                rows += _typical_range(client, point, run_start, run_end)
    finally:
        if own:
            client.close()
    rows.sort(key=lambda w: w.date)
    return PeriodWeather(start, end, rows, (point[0], point[1])) if rows else None
