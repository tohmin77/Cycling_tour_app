import pytest

from app import geo


def test_decode_polyline_reference_example():
    pts = geo.decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert pts == pytest.approx([(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)])


def test_haversine_one_degree_latitude():
    assert geo.haversine_m((0, 0), (1, 0)) == pytest.approx(111195, rel=1e-3)


LINE = [(0.0, 0.0), (0.0, 0.1)]  # ~11.1 km east along the equator


def test_point_at_midpoint_and_clamping():
    mid = geo.point_at(LINE, geo.total_m(LINE) / 2)
    assert mid == pytest.approx((0.0, 0.05), abs=1e-6)
    assert geo.point_at(LINE, 1e9) == LINE[-1]
    assert geo.point_at(LINE, -5) == LINE[0]


def test_thin_keeps_endpoints():
    pts = [(i * 0.001, 0.0) for i in range(1000)]
    out = geo.thin(pts, 100)
    assert len(out) <= 101 and out[0] == pts[0] and out[-1] == pts[-1]
