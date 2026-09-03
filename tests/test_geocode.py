import polars as pl

from plancheck.ahj.base import BBox
from plancheck.geocode import cache
from plancheck.geocode.address import parse_location
from plancheck.geocode.base import GeocodeResult, accept
from plancheck.geocode.strategy import Context, SourceCoordsTier, run_chain

BBOX = BBox(33.70, 34.35, -118.70, -118.10)


def _res(status="M", lat=34.05, lon=-118.25, score=95.0, mt="StreetAddress"):
    return GeocodeResult("k", "cams", status, lat, lon, score, mt, "x", "2026-01-01T00:00:00")


def test_accept_rules():
    addr = parse_location("1200 N STATE ST")
    inter = parse_location("TEXAS AVE AND OHIO AVE")
    assert accept(addr, _res(), BBOX, 90)[0]
    assert accept(addr, _res(score=85), BBOX, 90) == (False, "low_score")
    assert accept(addr, _res(status="U", lat=None, lon=None), BBOX, 90) == (False, "unmatched")
    assert accept(addr, _res(lat=33.71, lon=-117.79), BBOX, 90) == (False, "out_of_bbox")
    # "118TH PLACE and BROADWAY AVE" matched as an address -> must be rejected.
    assert accept(inter, _res(mt="StreetAddress"), BBOX, 90) == (False, "type_mismatch")
    assert accept(inter, _res(mt="StreetInt"), BBOX, 90)[0]
    assert accept(addr, _res(mt="StreetInt"), BBOX, 90) == (False, "type_mismatch")
    assert accept(addr, _res(mt="StreetName"), BBOX, 90) == (False, "type_mismatch")
    assert accept(addr, _res(status="E"), BBOX, 90) == (False, "error")


def test_cache_append_and_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "PARQUET_DIR", tmp_path)
    r1 = GeocodeResult("k1", "t", "U", None, None, 0.0, None, None, "2026-01-01T00:00:00")
    r2 = GeocodeResult("k1", "t", "M", 34.0, -118.2, 99.0, "StreetAddress", "a", "2026-01-02T00:00:00")
    r3 = GeocodeResult("k2", "t", "M", 34.1, -118.3, 91.0, "StreetInt", "b", "2026-01-01T00:00:00")
    cache.append("t", [r1, r3])
    cache.append("t", [r2])
    df = cache.load("t")
    assert df.height == 2
    assert df.filter(pl.col("key") == "k1")["status"].item() == "M"
    assert cache.compact("t") == 2
    assert cache.load("t").height == 2


def _permits():
    return pl.DataFrame(
        {
            "permit_id": ["a", "b", "c", "d", "e"],
            "source_dataset": ["s"] * 5,
            "source_family": ["ladbs_building_issued"] * 5,
            "permit_ref": [None] * 5,
            "address_raw": ["1 A ST", "2 B ST", "3 C ST", "4 D ST", "5 E ST"],
            "zip": [None] * 5,
            "lat_src": [34.05, 0.0, 34.05, -118.3, None],
            "lon_src": [-118.25, 0.0, -117.0, 34.05, None],
            "latlon_type_src": ["ADDRESS", "ADDRESS", "ADDRESS", "PIN", None],
            "geocode_key": ["k1", "k2", "k3", "k4", "k5"],
        }
    )


class _Ahj:
    slug = "t"
    bbox = BBOX


def test_source_coords_tier_and_chain():
    permits = _permits()
    ctx = Context(ahj=_Ahj(), queries={})
    out, counts = run_chain([SourceCoordsTier(BBOX)], permits, ctx)
    assert counts == {"source_coords": 1, "none": 4}
    assert out.height == 5
    by = {r["permit_id"]: r for r in out.iter_rows(named=True)}
    assert by["a"]["geocode_method"] == "source" and by["a"]["lat"] == 34.05
    assert by["b"]["geocode_reason"] == "zero_coords"
    assert by["c"]["geocode_reason"] == "out_of_bbox"
    assert by["d"]["geocode_reason"] == "swapped_axes"
    assert by["e"]["geocode_reason"] == "unmatched" and by["e"]["geocode_method"] == "none"
