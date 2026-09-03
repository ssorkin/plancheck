import numpy as np
import polars as pl
from shapely.geometry import Point, box

from plancheck.geocode.spatial import haversine_m, nearest_distance_m, point_in_polygon


def test_point_in_polygon_first_hit_and_none():
    polys = pl.DataFrame(
        {"id": ["west", "east", "overlap"],
         "wkb": [box(-118.5, 34.0, -118.3, 34.2).wkb, box(-118.3, 34.0, -118.1, 34.2).wkb,
                 box(-118.4, 34.0, -118.2, 34.2).wkb]}
    )
    lat = np.array([34.1, 34.1, 34.1, 35.0])
    lon = np.array([-118.45, -118.15, -118.25, -118.3])
    out = point_in_polygon(lat, lon, polys, "id")
    assert out == ["west", "east", "east", None]  # overlap: first containing polygon wins


def test_nearest_distance():
    targets = pl.DataFrame({"wkb": [Point(-118.25, 34.05).wkb, Point(-118.45, 34.15).wkb]})
    d = nearest_distance_m(np.array([34.05, 34.15]), np.array([-118.26, -118.45]), targets)
    assert 800 < d[0] < 1000 and d[1] < 1
    assert abs(haversine_m(34.0, -118.0, 34.0, -118.0)) < 1e-6
