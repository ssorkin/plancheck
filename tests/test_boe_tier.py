import polars as pl

from plancheck.ahj.la_city.boe import BoeGeometryTier
from plancheck.geocode.strategy import Context


class _Ahj:
    slug = "t"


def test_boe_geometry_tier_prefers_points_then_lines(tmp_path, monkeypatch):
    from plancheck import paths

    monkeypatch.setattr(paths, "PARQUET_DIR", tmp_path)
    d = tmp_path / "boe_geom" / "ahj=t" / "layer=01"
    d.mkdir(parents=True)
    pl.DataFrame(
        {
            "refno": [1, 1, 2, 2, 3],
            "geotype": ["pt", "pt", "ln", "pg", "pg"],
            "lat": [34.0, 34.2, 34.5, 34.6, 34.7],
            "lon": [-118.0, -118.2, -118.5, -118.6, -118.7],
        }
    ).write_parquet(d / "data.parquet")
    pending = pl.DataFrame(
        {
            "permit_id": ["U1", "U2", "U3", "U4", "L1"],
            "source_dataset": ["boe_permits"] * 4 + ["ladbs"],
            "source_family": ["boe_permits"] * 4 + ["ladbs_building_issued"],
            "permit_ref": ["1", "2", "3", "9", "1"],
        }
    )
    out = BoeGeometryTier(_Ahj()).resolve(pending, Context(ahj=_Ahj(), queries={}))
    by = {r["permit_id"]: r for r in out.iter_rows(named=True)}
    assert set(by) == {"U1", "U2", "U3"}
    assert by["U1"]["geocode_method"] == "boe_point" and by["U1"]["n_geoms"] == 2
    assert abs(by["U1"]["lat"] - 34.1) < 1e-9
    assert by["U2"]["geocode_method"] == "boe_line_centroid" and by["U2"]["n_geoms"] == 1
    assert by["U3"]["geocode_method"] == "boe_polygon_centroid"
