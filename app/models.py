import datetime as dt
from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field


class Stop(BaseModel):
    name: str = Field(description="Geocodable place name including the city, e.g. 'Eulsukdo Eco Park, Busan'")
    kind: Literal["start", "checkpoint", "lunch", "end"]
    lat: float | None = None
    lng: float | None = None


class Day(BaseModel):
    number: int
    date: dt.date
    title: str
    is_ride: bool = Field(description="True if the day includes cycling")
    distance_km: float | None = None
    start_time: str | None = Field(default=None, description="Ride start as HH:MM 24h, if stated")
    stops: list[Stop] = Field(default_factory=list, description="Ordered: start, checkpoints/lunch, end")
    hotel: str | None = None
    city: str
    notes: str | None = Field(default=None, description="Transfers, support vehicle, other logistics")


class Itinerary(BaseModel):
    title: str
    country: str
    days: list[Day]

    @property
    def main_city(self) -> str | None:
        cities = Counter(d.city for d in self.days if d.city)
        return cities.most_common(1)[0][0] if cities else None

    @property
    def start(self) -> dt.date | None:
        return min((d.date for d in self.days), default=None)

    @property
    def end(self) -> dt.date | None:
        return max((d.date for d in self.days), default=None)
