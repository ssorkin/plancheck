"""AHJ permit geometries (GeoJSONL) -> boe_geom parquet with a representative lat/lon.

Points keep their coordinates; lines take the point halfway along their length (so the
representative point lies on the trench, not beside a curve); polygons take shapely's
representative_point (guaranteed inside). WKB is kept for anyone who needs the shape.
"""

from __future__ import annotations

import json
import shutil

import polars as pl
from shapely.geometry import shape

from plancheck.ahj.base import AHJ
from plancheck.paths import PARQUET_DIR, RAW_DIR

GEOTYPES = {"Point": "pt", "MultiPoint": "pt", "LineString": "ln", "MultiLineString": "ln",
            "Polygon": "pg", "MultiPolygon": "pg"}


def _rep_point(geom) -> tuple[float, float]:
    gt = geom.geom_type
    if gt in ("Point",):
        return geom.y, geom.x
    if gt == "MultiPoint":
        c = geom.centroid
        return c.y, c.x
    if gt in ("LineString", "MultiLineString"):
        p = geom.interpolate(0.5, normalized=True)
        return p.y, p.x
    p = geom.representative_point()
    return p.y, p.x


def ingest_geometries(ahj: AHJ) -> None:
    for gname, g in ahj.geometries.items():
        raw = RAW_DIR / f"{ahj.slug}_{gname}"
        if not raw.exists():
            print(f"  skip {gname}: {raw} not downloaded")
            continue
        out_root = PARQUET_DIR / "boe_geom" / f"ahj={ahj.slug}"
        if out_root.exists():
            shutil.rmtree(out_root)
        key = g.get("key_field", "RefNo")
        total = 0
        for path in sorted(raw.glob("layer_*.geojsonl")):
            layer_id = int(path.name.split("_")[1])
            rows = []
            with path.open() as f:
                for line in f:
                    feat = json.loads(line)
                    props = feat.get("properties") or {}
                    geom = feat.get("geometry")
                    if not geom or not geom.get("coordinates"):
                        continue
                    shp = shape(geom)
                    if shp.is_empty:
                        continue
                    lat, lon = _rep_point(shp)
                    ref = props.get(key)
                    rows.append(
                        {
                            "layer_id": layer_id,
                            "layer": path.stem,
                            "refno": int(ref) if ref is not None else None,
                            "permitno": props.get("PermitNo"),
                            "permittype": props.get("PermitType"),
                            "permitsubtype": props.get("PermitSubType"),
                            "location": props.get("Location"),
                            "geotype": GEOTYPES.get(shp.geom_type, "other"),
                            "active": props.get("Active"),
                            "enter_date": props.get("EnterDate"),
                            "lat": lat,
                            "lon": lon,
                            "wkb": shp.wkb,
                        }
                    )
            if not rows:
                continue
            df = pl.DataFrame(
                rows,
                schema={
                    "layer_id": pl.Int32, "layer": pl.Utf8, "refno": pl.Int64,
                    "permitno": pl.Utf8, "permittype": pl.Utf8, "permitsubtype": pl.Utf8,
                    "location": pl.Utf8, "geotype": pl.Utf8, "active": pl.Int32,
                    "enter_date": pl.Int64, "lat": pl.Float64, "lon": pl.Float64,
                    "wkb": pl.Binary,
                },
            )
            d = out_root / f"layer={layer_id:02d}"
            d.mkdir(parents=True, exist_ok=True)
            df.write_parquet(d / "data.parquet", compression="zstd")
            total += df.height
        print(f"  {gname}: {total:,} geometries -> {out_root}")
