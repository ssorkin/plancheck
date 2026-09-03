import json

import polars as pl

from plancheck.ingest.geometries import _rep_point, ingest_geometries
from plancheck.ingest.reference import _load


class _Ahj:
    slug = "t"
    geometries = {"g": {"kind": "arcgis_mapserver", "key_field": "RefNo"}}  # noqa: RUF012


def test_rep_point_kinds():
    from shapely.geometry import LineString, Point, Polygon

    assert _rep_point(Point(-118.2, 34.1)) == (34.1, -118.2)
    lat, lon = _rep_point(LineString([(-118.2, 34.0), (-118.2, 34.2)]))
    assert abs(lat - 34.1) < 1e-9 and abs(lon + 118.2) < 1e-9
    lat, lon = _rep_point(Polygon([(-118.3, 34.0), (-118.1, 34.0), (-118.1, 34.2), (-118.3, 34.2)]))
    assert 34.0 < lat < 34.2 and -118.3 < lon < -118.1


def test_ingest_geometries_and_reference(tmp_path, monkeypatch):
    import plancheck.ingest.geometries as g
    import plancheck.ingest.reference as r

    monkeypatch.setattr(g, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(g, "PARQUET_DIR", tmp_path / "pq")
    monkeypatch.setattr(r, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(r, "PARQUET_DIR", tmp_path / "pq")
    d = tmp_path / "raw" / "t_g"
    d.mkdir(parents=True)
    feats = [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-118.2, 34.1]},
         "properties": {"RefNo": 42.0, "PermitNo": "p", "PermitType": "U", "Active": 1}},
        {"type": "Feature", "geometry": {"type": "LineString",
                                          "coordinates": [[-118.2, 34.0], [-118.2, 34.2]]},
         "properties": {"RefNo": 43.0, "PermitNo": "q", "PermitType": "U", "Active": 0}},
        {"type": "Feature", "geometry": None, "properties": {"RefNo": 44.0}},
    ]
    (d / "layer_59_u_points.geojsonl").write_text("\n".join(json.dumps(f) for f in feats) + "\n")
    ingest_geometries(_Ahj())
    out = pl.read_parquet(tmp_path / "pq" / "boe_geom" / "ahj=t" / "layer=59" / "data.parquet")
    assert out.height == 2 and out["refno"].to_list() == [42, 43]
    assert out["geotype"].to_list() == ["pt", "ln"]

    poly = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-118.3, 34.0],
            [-118.1, 34.0], [-118.1, 34.2], [-118.3, 34.2], [-118.3, 34.0]]]},
            "properties": {"District": 5, "District_Name": "Five"}}
    p = tmp_path / "ref.geojsonl"
    p.write_text(json.dumps(poly) + "\n")
    df = _load(p, "District", "District_Name")
    assert df["id"].to_list() == ["5"] and df["name"].to_list() == ["Five"]
