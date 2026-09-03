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
           sum(dwelling_units_change)::BIGINT AS du_permitted,
           sum(sqft)::DOUBLE AS sqft_sum,
           sum(CASE WHEN lat IS NULL THEN 1 ELSE 0 END)::BIGINT AS n_unlocated
    FROM issued
    WHERE {geo_col} IS NOT NULL
    GROUP BY 1, 2, 3, 4
    """


def completions_sql() -> str:
    """Permits whose dwelling-unit change actually happened: a certificate of occupancy was
    issued (final_date) or a demolition was finaled. `year` is the completion year."""
    cfg = analysis_config()
    demo = _list(cfg["intensity"]["demolition_types"])
    return f"""
    WITH ranked AS (
        SELECT p.*, row_number() OVER (
            PARTITION BY ahj, permit_id ORDER BY refresh_time DESC NULLS LAST, source_dataset DESC
        ) AS rn
        FROM permits p
        WHERE record_kind = 'issued' AND permit_class = 'building'
          AND dwelling_units_change IS NOT NULL AND dwelling_units_change <> 0
    ),
    done AS (
        SELECT *,
               CASE WHEN final_date IS NOT NULL THEN final_date
                    WHEN permit_type IN ({demo}) AND status = 'Permit Finaled' THEN status_date
               END AS completed_date
        FROM ranked WHERE rn = 1
    )
    SELECT * EXCLUDE (rn, year), year(completed_date)::INTEGER AS year
    FROM done
    WHERE completed_date IS NOT NULL
      AND year(completed_date) BETWEEN {cfg["years"]["start"]} AND {cfg["years"]["end"]}
    """


def du_net_sql(geo_col: str) -> str:
    return f"""
    SELECT ahj, {geo_col} AS geo_id, year, permit_class,
           sum(dwelling_units_change)::BIGINT AS du_net,
           count(*)::BIGINT AS n_du_completed
    FROM completions WHERE {geo_col} IS NOT NULL
    GROUP BY 1, 2, 3, 4
    """


def compute(con: duckdb.DuckDBPyConnection | None = None) -> dict[str, pl.DataFrame]:
    own = con is None
    con = con or connect(read_only=True)
    con.execute(f"CREATE OR REPLACE TEMP VIEW issued AS {dedup_issued_sql()}")
    con.execute(f"CREATE OR REPLACE TEMP VIEW completions AS {completions_sql()}")
    out: dict[str, pl.DataFrame] = {}
    for name, col in GEOGRAPHIES.items():
        try:
            df = con.execute(metrics_sql(col)).pl()
            du = con.execute(du_net_sql(col)).pl()
        except duckdb.BinderException:
            continue  # geography column absent (layer not acquired)
        df = df.join(du, on=["ahj", "geo_id", "year", "permit_class"], how="full", coalesce=True)
        out[f"intensity_{name}"] = df
    # Citywide series by class and by BOE subtype.
    out["series_class"] = con.execute(
        "SELECT ahj, year, permit_class, count(*)::BIGINT AS n_permits, "
        "sum(valuation)::DOUBLE AS valuation_sum, "
        "sum(dwelling_units_change)::BIGINT AS du_permitted FROM issued GROUP BY 1, 2, 3 "
        "ORDER BY 1, 2, 3"
    ).pl()
    out["series_du_net"] = con.execute(
        "SELECT ahj, year, sum(dwelling_units_change)::BIGINT AS du_net, count(*)::BIGINT AS n "
        "FROM completions GROUP BY 1, 2 ORDER BY 1, 2"
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
