"""Administrative and covariate polygon layers (GeoJSONL) -> ref parquet (id, name, wkb)."""

from __future__ import annotations

import json
import shutil

import polars as pl
from shapely.geometry import shape

from plancheck.ahj.base import AHJ
from plancheck.paths import PARQUET_DIR, RAW_DIR


def _load(path, id_field: str, name_field: str) -> pl.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            feat = json.loads(line)
            geom = feat.get("geometry")
            if not geom:
                continue
            shp = shape(geom)
            if shp.is_empty:
                continue
            props = feat.get("properties") or {}
            rows.append(
                {
                    "id": str(props.get(id_field)),
                    "name": None if props.get(name_field) is None else str(props.get(name_field)),
                    "props": json.dumps(props, default=str),
                    "geom_type": shp.geom_type,
                    "wkb": shp.wkb,
                }
            )
    return pl.DataFrame(
        rows,
        schema={"id": pl.Utf8, "name": pl.Utf8, "props": pl.Utf8, "geom_type": pl.Utf8,
                "wkb": pl.Binary},
    )


def ingest_layers(ahj: AHJ) -> None:
    out_root = PARQUET_DIR / "ref" / f"ahj={ahj.slug}"
    for dataset, layers in (("reference", ahj.reference), ("covariates", ahj.covariates)):
        for name, spec in layers.items():
            path = RAW_DIR / f"{ahj.slug}_{dataset}" / f"{name}.geojsonl"
            if not path.exists():
                print(f"  skip {name}: {path} not downloaded")
                continue
            df = _load(path, spec["id_field"], spec["name_field"])
            d = out_root / f"layer={name}"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            df.write_parquet(d / "data.parquet", compression="zstd")
            print(f"  {name}: {df.height:,} features")
