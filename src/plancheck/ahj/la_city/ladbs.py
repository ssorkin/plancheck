"""LADBS permit tables -> common schema.

Building datasets carry 38 columns; electrical and mechanical ("trade") datasets carry the
same core minus dwelling-unit, valuation, square-footage, construction and height fields.
Column names are the export headers lowercased (see ingest.csv_raw.norm_header).
"""

from __future__ import annotations

import polars as pl

from plancheck.ahj.base import SourceSpec
from plancheck.ingest.schema import (
    clean_text,
    norm_tract,
    to_bool,
    to_date,
    to_datetime,
    to_float,
    to_int,
    to_money,
)

REQUIRED_TRADE = [
    "permit_nbr",
    "primary_address",
    "zip_code",
    "cd",
    "pin_nbr",
    "apn",
    "zone",
    "apc",
    "cpa",
    "cnc",
    "hl",
    "ct",
    "permit_group",
    "permit_type",
    "permit_sub_type",
    "use_code",
    "use_desc",
    "submitted_date",
    "issue_date",
    "cofo_date",
    "status_desc",
    "status_date",
    "type_lat_lon",
    "lat",
    "lon",
    "work_desc",
    "ev",
    "solar",
    "business_unit",
    "refresh_time",
]
REQUIRED_BUILDING = REQUIRED_TRADE + (
    [
        "du_changed",
        "adu_changed",
        "junior_adu",
        "square_footage",
        "valuation",
        "construction",
        "height",
    ]
)


def _require(lf: pl.LazyFrame, cols: list[str], spec: SourceSpec) -> None:
    have = set(lf.collect_schema().names())
    missing = [c for c in cols if c not in have]
    if missing:
        raise RuntimeError(f"{spec.slug}: raw table lacks columns {missing}")


def _common(spec: SourceSpec) -> list[pl.Expr]:
    return [
        pl.lit("la_city").alias("ahj"),
        pl.lit(spec.slug).alias("source_dataset"),
        pl.lit(spec.family).alias("source_family"),
        pl.lit(spec.record_kind).alias("record_kind"),
        clean_text("permit_nbr").alias("permit_id"),
        clean_text("pin_nbr").alias("permit_ref"),
        pl.lit(spec.permit_class).alias("permit_class"),
        clean_text("permit_type").alias("permit_type"),
        clean_text("permit_sub_type").alias("permit_subtype"),
        clean_text("permit_group").alias("permit_group"),
        clean_text("use_code").alias("use_code"),
        clean_text("use_desc").alias("use_desc"),
        clean_text("status_desc").alias("status"),
        to_date("status_date").alias("status_date"),
        to_date("submitted_date").alias("submitted_date"),
        to_date("issue_date").alias("issue_date"),
        to_date("cofo_date").alias("final_date"),
        clean_text("primary_address").alias("address_raw"),
        pl.col("zip_code").str.extract(r"(\d{5})", 1).alias("zip"),
        clean_text("apn").alias("apn"),
        pl.col("cd").str.strip_chars().str.replace(r"\.0$", "").alias("council_district_src"),
        norm_tract("ct").alias("tract_src"),
        clean_text("cpa").alias("cpa_src"),
        clean_text("cnc").alias("nc_src"),
        clean_text("apc").alias("apc_src"),
        clean_text("zone").alias("zone_src"),
        to_bool("hl").alias("hillside"),
        to_bool("solar").alias("solar"),
        to_bool("ev").alias("ev"),
        clean_text("work_desc").alias("work_desc"),
        clean_text("business_unit").alias("business_unit"),
        to_float("lat").alias("lat_src"),
        to_float("lon").alias("lon_src"),
        clean_text("type_lat_lon").alias("latlon_type_src"),
        to_datetime("refresh_time").alias("refresh_time"),
    ]


def map_ladbs_trade(lf: pl.LazyFrame, spec: SourceSpec) -> pl.LazyFrame:
    _require(lf, REQUIRED_TRADE, spec)
    return lf.select(_common(spec))


def map_ladbs_building(lf: pl.LazyFrame, spec: SourceSpec) -> pl.LazyFrame:
    _require(lf, REQUIRED_BUILDING, spec)
    extras = [
        to_money("valuation").alias("valuation"),
        to_int("du_changed").alias("dwelling_units_change"),
        to_int("adu_changed").alias("adu_units_change"),
        to_int("junior_adu").alias("jadu_units_change"),
        to_float("square_footage").alias("sqft"),
        to_float("height").alias("height"),
        clean_text("construction").alias("construction"),
    ]
    return lf.select([*_common(spec), *extras])
