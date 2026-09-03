"""Assessor roll (attribute-only ArcGIS table, GeoJSONL with null geometry) -> parquet."""

from __future__ import annotations

import json

import polars as pl

from plancheck.ahj.base import AHJ
from plancheck.paths import PARQUET_DIR, RAW_DIR

NUMERIC = (
    "YearBuilt",
    "EffectiveYearBuilt",
    "SQFTmain",
    "Units",
    "Bedrooms",
    "Bathrooms",
    "Roll_LandValue",
    "Roll_ImpValue",
    "Roll_TotalValue",
    "Roll_LandBaseYear",
    "Roll_ImpBaseYear",
    "CENTER_LAT",
    "CENTER_LON",
)


def ingest_assessor(ahj: AHJ) -> None:
    spec = ahj.covariates.get("assessor")
    if not spec:
        return
    path = RAW_DIR / f"{ahj.slug}_covariates" / "assessor.geojsonl"
    if not path.exists():
        print(f"  skip assessor: {path} not downloaded")
        return
    rows = []
    with path.open() as f:
        for line in f:
            rows.append(json.loads(line).get("properties") or {})
    df = pl.DataFrame(rows, infer_schema_length=None)
    df = df.with_columns(
        [pl.col(c).cast(pl.Float64, strict=False) for c in NUMERIC if c in df.columns]
    ).rename({c: c.lower() for c in df.columns})
    df = df.with_columns(
        pl.when(pl.col("yearbuilt") < 1800)
        .then(None)
        .otherwise(pl.col("yearbuilt"))
        .alias("yearbuilt"),
        pl.lit(ahj.slug).alias("ahj"),
    )
    out = PARQUET_DIR / "assessor"
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / f"{ahj.slug}.parquet", compression="zstd")
    print(f"  assessor: {df.height:,} parcels")
