"""The common permits schema every AHJ mapper produces.

Normalization is additive: the all-varchar raw table is kept alongside (permits_raw), so
nothing a source publishes is lost. Columns that a source cannot fill are null.
"""

from __future__ import annotations

import polars as pl

PERMITS_SCHEMA: dict[str, pl.DataType] = {
    "ahj": pl.Utf8,
    "source_dataset": pl.Utf8,
    "source_family": pl.Utf8,
    "record_kind": pl.Utf8,  # issued | submitted
    "permit_id": pl.Utf8,  # unique within (ahj, source_dataset)
    "permit_ref": pl.Utf8,  # secondary key (BOE refno; LADBS PIN)
    "permit_class": pl.Utf8,  # building | electrical | mechanical | right_of_way
    "permit_type": pl.Utf8,
    "permit_subtype": pl.Utf8,
    "permit_group": pl.Utf8,
    "use_code": pl.Utf8,
    "use_desc": pl.Utf8,
    "status": pl.Utf8,
    "status_date": pl.Date,
    "submitted_date": pl.Date,
    "issue_date": pl.Date,
    "final_date": pl.Date,
    "year": pl.Int32,
    "address_raw": pl.Utf8,
    "zip": pl.Utf8,
    "apn": pl.Utf8,
    "council_district_src": pl.Utf8,
    "tract_src": pl.Utf8,  # 6-digit tract code as published by the source
    "cpa_src": pl.Utf8,
    "nc_src": pl.Utf8,
    "apc_src": pl.Utf8,
    "zone_src": pl.Utf8,
    "hillside": pl.Boolean,
    "valuation": pl.Float64,
    "dwelling_units_change": pl.Int32,
    "adu_changed": pl.Boolean,
    "junior_adu": pl.Boolean,
    "solar": pl.Boolean,
    "ev": pl.Boolean,
    "sqft": pl.Float64,
    "height": pl.Float64,
    "construction": pl.Utf8,
    "work_desc": pl.Utf8,
    "business_unit": pl.Utf8,
    "lat_src": pl.Float64,
    "lon_src": pl.Float64,
    "latlon_type_src": pl.Utf8,
    "source_url": pl.Utf8,
    "refresh_time": pl.Datetime("us"),
}

DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d")


def to_date(col: str) -> pl.Expr:
    """Parse a text date in any of the portal's formats (CSV export uses MM/DD/YYYY)."""
    s = pl.col(col).str.strip_chars()
    expr = pl.lit(None, dtype=pl.Date)
    for fmt in reversed(DATE_FORMATS):
        expr = s.str.strptime(pl.Date, fmt, strict=False).fill_null(expr)
    return expr.alias(col)


def to_datetime(col: str) -> pl.Expr:
    s = pl.col(col).str.strip_chars()
    a = s.str.strptime(pl.Datetime("us"), "%m/%d/%Y", strict=False)
    b = s.str.strptime(pl.Datetime("us"), "%Y-%m-%dT%H:%M:%S%.f", strict=False)
    return a.fill_null(b).alias(col)


def to_money(col: str) -> pl.Expr:
    return pl.col(col).str.replace_all(r"[$,\s]", "").cast(pl.Float64, strict=False)


def to_float(col: str) -> pl.Expr:
    return pl.col(col).str.strip_chars().cast(pl.Float64, strict=False)


def to_int(col: str) -> pl.Expr:
    return pl.col(col).str.strip_chars().cast(pl.Float64, strict=False).cast(pl.Int32)


def to_bool(col: str) -> pl.Expr:
    u = pl.col(col).str.strip_chars().str.to_uppercase()
    return (
        pl.when(u.is_in(["Y", "YES", "T", "TRUE", "1"]))
        .then(pl.lit(True))
        .when(u.is_in(["N", "NO", "F", "FALSE", "0"]))
        .then(pl.lit(False))
        .otherwise(pl.lit(None, dtype=pl.Boolean))
        .alias(col)
    )


def norm_tract(col: str) -> pl.Expr:
    """'1173.01' -> '117301'; '2679' -> '267900'."""
    s = pl.col(col).str.strip_chars()
    whole = s.str.extract(r"^(\d+)", 1).str.zfill(4)
    frac = s.str.extract(r"\.(\d+)$", 1).fill_null("00").str.pad_end(2, "0").str.slice(0, 2)
    return (
        pl.when(s.is_null() | (s == ""))
        .then(pl.lit(None, dtype=pl.Utf8))
        .otherwise(whole + frac)
        .alias(col)
    )


def clean_text(col: str) -> pl.Expr:
    s = pl.col(col).str.strip_chars()
    return pl.when(s == "").then(pl.lit(None, dtype=pl.Utf8)).otherwise(s).alias(col)


def conform(lf: pl.LazyFrame) -> pl.LazyFrame:
    """Select every schema column in order, adding nulls for missing ones, and cast."""
    have = set(lf.collect_schema().names())
    exprs = []
    for name, dtype in PERMITS_SCHEMA.items():
        if name in have:
            exprs.append(pl.col(name).cast(dtype, strict=True).alias(name))
        else:
            exprs.append(pl.lit(None, dtype=dtype).alias(name))
    return lf.select(exprs)
