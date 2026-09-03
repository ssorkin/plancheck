"""Development-intensity aggregates: permits by geography × year × class.

Issued records only (submitted tables describe the same permits earlier in life and would
double count). Within a family the era datasets can overlap on permit_id; the latest
refresh wins. Every metric is a plain count or sum over the deduplicated permits view.
"""

from __future__ import annotations

import duckdb
import polars as pl

from plancheck.config import analysis_config
from plancheck.ingest.db import connect
from plancheck.paths import PARQUET_DIR

GEOGRAPHIES = {
    "tract": "tract_geoid",
    "council_district": "council_district",
    "cpa": "cpa_id",
    "nc": "nc_id",
    "h3_r8": "h3_r8",
    "zoning_category": "zoning_category",
    "neighborhood": "neighborhoods_id",
    "zip": "zip_codes_id",
    "lausd_elementary": "lausd_elementary_id",
    "lausd_middle": "lausd_middle_id",
    "lausd_high": "lausd_high_id",
}


def _list(values: list[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def dedup_issued_sql() -> str:
    cfg = analysis_config()
    return f"""
    WITH ranked AS (
        SELECT p.*, row_number() OVER (
            PARTITION BY ahj, permit_id ORDER BY refresh_time DESC NULLS LAST, source_dataset DESC
        ) AS rn
        FROM permits p
        WHERE record_kind = 'issued' AND year BETWEEN {cfg["years"]["start"]} AND {cfg["years"]["end"]}
    )
    SELECT * EXCLUDE (rn) FROM ranked WHERE rn = 1
    """


def metrics_sql(geo_col: str) -> str:
    cfg = analysis_config()["intensity"]
    return f"""
    SELECT ahj, {geo_col} AS geo_id, year, permit_class,
           count(*)::BIGINT AS n_permits,
           sum(CASE WHEN permit_type IN ({_list(cfg["new_building_types"])}) THEN 1 ELSE 0 END)::BIGINT
               AS n_new_building,
           sum(CASE WHEN permit_type IN ({_list(cfg["addition_types"])}) THEN 1 ELSE 0 END)::BIGINT
               AS n_additions,
           sum(CASE WHEN permit_type IN ({_list(cfg["demolition_types"])}) THEN 1 ELSE 0 END)::BIGINT
               AS n_demolitions,
           sum(CASE WHEN adu_changed THEN 1 ELSE 0 END)::BIGINT AS n_adu,
           sum(CASE WHEN solar THEN 1 ELSE 0 END)::BIGINT AS n_solar,
           sum(CASE WHEN ev THEN 1 ELSE 0 END)::BIGINT AS n_ev,
           sum(valuation)::DOUBLE AS valuation_sum,
           median(valuation)::DOUBLE AS valuation_median,
           sum(dwelling_units_change)::BIGINT AS du_net,
           sum(sqft)::DOUBLE AS sqft_sum,
           sum(CASE WHEN lat IS NULL THEN 1 ELSE 0 END)::BIGINT AS n_unlocated
    FROM issued
    WHERE {geo_col} IS NOT NULL
    GROUP BY 1, 2, 3, 4
    """


def compute(con: duckdb.DuckDBPyConnection | None = None) -> dict[str, pl.DataFrame]:
    own = con is None
    con = con or connect(read_only=True)
    con.execute(f"CREATE OR REPLACE TEMP VIEW issued AS {dedup_issued_sql()}")
    out: dict[str, pl.DataFrame] = {}
    for name, col in GEOGRAPHIES.items():
        try:
            df = con.execute(metrics_sql(col)).pl()
        except duckdb.BinderException:
            continue  # geography column absent (layer not acquired)
        out[f"intensity_{name}"] = df
    # Citywide series by class and by BOE subtype.
    out["series_class"] = con.execute(
        "SELECT ahj, year, permit_class, count(*)::BIGINT AS n_permits, sum(valuation)::DOUBLE AS valuation_sum, "
        "sum(dwelling_units_change) AS du_net FROM issued GROUP BY 1, 2, 3 ORDER BY 1, 2, 3"
    ).pl()
    out["series_type"] = con.execute(
        "SELECT ahj, year, permit_class, permit_type, count(*) AS n_permits "
        "FROM issued GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 5 DESC"
    ).pl()
    out["geocode_coverage"] = con.execute(
        "SELECT ahj, source_family, year, coalesce(geocode_method, 'none') AS method, count(*) AS n "
        "FROM permits WHERE record_kind='issued' GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4"
    ).pl()
    if own:
        con.close()
    return out


def _plain(df: pl.DataFrame) -> pl.DataFrame:
    """DuckDB returns DECIMAL for integer sums; keep the store to plain Int64/Float64."""
    casts = []
    for name, dtype in df.schema.items():
        if isinstance(dtype, pl.Decimal):
            casts.append(pl.col(name).cast(pl.Int64 if (dtype.scale or 0) == 0 else pl.Float64))
    return df.with_columns(casts) if casts else df


def write(frames: dict[str, pl.DataFrame]) -> None:
    d = PARQUET_DIR / "analysis"
    d.mkdir(parents=True, exist_ok=True)
    for name, df in frames.items():
        df = _plain(df)
        frames[name] = df
        df.write_parquet(d / f"{name}.parquet", compression="zstd")
        print(f"  {name}: {df.height:,} rows")
