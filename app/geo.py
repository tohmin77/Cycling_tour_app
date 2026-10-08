import math

Point = tuple[float, float]
EARTH_R = 6371000.0


def haversine_m(a: Point, b: Point) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(h))


def decode_polyline(encoded: str) -> list[Point]:
    points, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        for axis in (0, 1):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if axis == 0:
                lat += delta
            else:
                lng += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


def total_m(points: list[Point]) -> float:
    return sum(haversine_m(a, b) for a, b in zip(points, points[1:]))


def point_at(points: list[Point], distance_m: float) -> Point:
    if distance_m <= 0:
        return points[0]
    walked = 0.0
    for a, b in zip(points, points[1:]):
        seg = haversine_m(a, b)
        if walked + seg >= distance_m and seg > 0:
            t = (distance_m - walked) / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        walked += seg
    return points[-1]


def thin(points: list[Point], max_n: int) -> list[Point]:
    if len(points) <= max_n:
        return points
    stride = math.ceil(len(points) / max_n)
    out = points[::stride]
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out
