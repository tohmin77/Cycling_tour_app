class LiveUrls:
    """Links for the running web app."""

    def __init__(self, trip_id: str):
        self.base = f"/trip/{trip_id}"

    def route(self, n: int) -> str:
        return f"{self.base}/day/{n}"

    def food(self, n: int) -> str:
        return f"{self.base}/day/{n}/food"

    def weather(self, n: int) -> str:
        return f"{self.base}/weather?d={n}"

    def apps(self, n: int) -> str:
        return f"{self.base}/apps?d={n}"

    def part(self, section: str, n: int) -> str:
        return f"{self.base}/weather.part" if section == "weather" else f"{self.base}/day/{n}/{section}.part"

    def static(self, name: str) -> str:
        return f"/static/{name}"


class StaticUrls:
    """Relative links for an exported site, so it works from any folder or sub-path."""

    def route(self, n: int) -> str:
        return f"route-{n}.html"

    def food(self, n: int) -> str:
        return f"food-{n}.html"

    def weather(self, n: int) -> str:
        return f"weather-{n}.html"

    def apps(self, n: int) -> str:
        return f"apps-{n}.html"

    def static(self, name: str) -> str:
        return f"static/{name}"
