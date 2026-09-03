"""Bureau of Engineering right-of-way permits -> common schema, plus the geometry tier.

The Socrata table carries only a free-text `location`; the authoritative geometry for
most permits is published by the city's own "BOE Permits Geocoder" map service, keyed by
`refno`. BoeGeometryTier joins that before any locator is consulted.
"""

from __future__ import annotations

import polars as pl

from plancheck.ahj.base import SourceSpec
from plancheck.ingest.schema import clean_text, to_date

PERMIT_NAMES = {
    "U": "Excavation (U) Permit",
    "SFC": "Sewer Facility Charge Certificate",
    "A": "Class (A) Permit",
    "S": "Sewer Permit",
    "B": "Class (B) Permit",
    "H": "Highway Dedication",
    "E": "Excavation (E) Permit",
    "PCRF": "Planning Case Referral Form",
    "CFR": "Claim for Refund",
    "R": "Revocable Permit",
    "DT": "Dye Test Certificate",
    "STD": "Storm Drain Permit",
    "W": "Watercourse Permit",
}

REQUIRED = ["id", "refno", "permitno", "permitname", "permittype", "location", "permitissuedate"]


def map_boe(lf: pl.LazyFrame, spec: SourceSpec) -> pl.LazyFrame:
    have = set(lf.collect_schema().names())
    missing = [c for c in REQUIRED if c not in have]
    if missing:
        raise RuntimeError(f"{spec.slug}: raw table lacks columns {missing}")
    url_col = "permiturl" if "permiturl" in have else None
    return lf.select(
        pl.lit("la_city").alias("ahj"),
        pl.lit(spec.slug).alias("source_dataset"),
        pl.lit(spec.family).alias("source_family"),
        pl.lit(spec.record_kind).alias("record_kind"),
        clean_text("id").alias("permit_id"),
        pl.col("refno").str.strip_chars().str.replace(r"\.0$", "").alias("permit_ref"),
        pl.lit(spec.permit_class).alias("permit_class"),
        clean_text("permittype").alias("permit_type"),
        clean_text("permitname").alias("permit_subtype"),
        clean_text("permitsubtype").alias("permit_group")
        if "permitsubtype" in have
        else pl.lit(None, dtype=pl.Utf8).alias("permit_group"),
        to_date("permitissuedate").alias("issue_date"),
        clean_text("location").alias("address_raw"),
        (clean_text(url_col) if url_col else pl.lit(None, dtype=pl.Utf8)).alias("source_url"),
    )


class BoeGeometryTier:
    """Resolve BOE permits from the city's own geometry service by refno.

    Preference per refno: points (centroid of all points when several), then the midpoint
    of lines, then the representative point of polygons. `n_geoms` records how many
    features the refno matched so multi-site permits are visible downstream.
    """

    name = "boe_geometry"
    method_prefix = "boe"

    def __init__(self, ahj) -> None:
        self.ahj = ahj

    def resolve(self, pending: pl.DataFrame, ctx) -> pl.DataFrame:
        from plancheck.paths import PARQUET_DIR

        geom_dir = PARQUET_DIR / "boe_geom" / f"ahj={self.ahj.slug}"
        if not geom_dir.exists():
            print(
                "  boe_geometry: no boe_geom parquet (run `pc acquire --family geometries` "
                "and `pc ingest --family geometries`)"
            )
            return ctx.empty()
        mine = pending.filter(pl.col("source_family") == "boe_permits")
        if mine.is_empty():
            return ctx.empty()
        geoms = pl.read_parquet(geom_dir / "**" / "*.parquet").filter(
            pl.col("refno").is_not_null() & pl.col("lat").is_not_null()
        )
        rank = pl.col("geotype").replace_strict({"pt": 0, "ln": 1, "pg": 2}, default=3)
        best = (
            geoms.with_columns(rank.alias("_rank"))
            .with_columns(pl.col("_rank").min().over("refno").alias("_best"))
            .filter(pl.col("_rank") == pl.col("_best"))
            .group_by("refno")
            .agg(
                pl.col("lat").mean().alias("lat"),
                pl.col("lon").mean().alias("lon"),
                pl.col("geotype").first().alias("geotype"),
                pl.len().alias("n_geoms"),
            )
            .with_columns(pl.col("refno").cast(pl.Utf8))
        )
        joined = mine.select("permit_id", "source_dataset", "permit_ref").join(
            best, left_on="permit_ref", right_on="refno", how="inner"
        )
        method = pl.col("geotype").replace_strict(
            {"pt": "boe_point", "ln": "boe_line_centroid", "pg": "boe_polygon_centroid"},
            default="boe_other",
        )
        return joined.select(
            "permit_id",
            "source_dataset",
            pl.col("lat").cast(pl.Float64),
            pl.col("lon").cast(pl.Float64),
            method.alias("geocode_method"),
            pl.lit(None, dtype=pl.Float64).alias("geocode_score"),
            pl.col("geotype").alias("geocode_match_type"),
            pl.lit(None, dtype=pl.Utf8).alias("geocode_key"),
            pl.lit(None, dtype=pl.Utf8).alias("geocode_reason"),
            pl.col("geotype").alias("geom_type"),
            pl.col("n_geoms").cast(pl.Int32),
        )
