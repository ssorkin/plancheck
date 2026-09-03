"""Tract-level covariates beyond ACS: zoning mix, HPOZ share and rail proximity seen by
the permits themselves, and the assessor roll (building age, value, units) aggregated by
parcel centroid. Also a permit-level APN join to the roll."""

from __future__ import annotations

import numpy as np
import polars as pl

from plancheck.ingest.db import connect
from plancheck.paths import PARQUET_DIR


def tract_context() -> pl.DataFrame:
    """Per tract: dominant zoning category, share of permits inside an HPOZ, share within
    800 m of rail — computed over located issued permits since 2013 (the permits are the
    sampling frame, so this describes where activity happens, not the tract's land)."""
    con = connect(read_only=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info('permits')").fetchall()}
    sel = ["tract_geoid", "count(*)::BIGINT AS n"]
    if "zoning_category" in cols:
        sel.append("mode(zoning_category) AS zoning_mode")
    if "hpoz" in cols:
        sel.append("avg(CASE WHEN hpoz THEN 1.0 ELSE 0.0 END) AS hpoz_share")
    if "dist_rail_m" in cols:
        sel.append("avg(CASE WHEN dist_rail_m <= 800 THEN 1.0 ELSE 0.0 END) AS near_rail_share")
        sel.append("median(dist_rail_m)::DOUBLE AS dist_rail_median_m")
    df = con.execute(
        f"SELECT {', '.join(sel)} FROM permits WHERE record_kind='issued' "
        "AND tract_geoid IS NOT NULL AND year >= 2013 GROUP BY 1"
    ).pl()
    con.close()
    return df


def assessor_by_tract() -> pl.DataFrame | None:
    """Assessor roll aggregated to 2020 tracts by parcel centroid: parcels, median year
    built, median improvement value per sqft, single-family share, assessed units."""
    from plancheck.geocode.spatial import load_tracts, point_in_polygon

    d = PARQUET_DIR / "assessor"
    tracts = load_tracts()
    if not d.exists() or tracts is None or not any(d.glob("*.parquet")):
        return None
    roll = pl.read_parquet(d / "*.parquet").filter(
        pl.col("center_lat").is_not_null() & pl.col("center_lon").is_not_null()
    )
    lat = roll["center_lat"].to_numpy()
    lon = roll["center_lon"].to_numpy()
    roll = roll.with_columns(pl.Series("tract_geoid", point_in_polygon(lat, lon, tracts, "geoid")))
    res = roll.filter(pl.col("usetype").is_in(["SFR", "CND", "R-I"]))
    return (
        roll.filter(pl.col("tract_geoid").is_not_null())
        .group_by("tract_geoid")
        .agg(
            pl.len().alias("parcels"),
            pl.col("yearbuilt").median().alias("assessor_median_year_built"),
            (pl.col("roll_impvalue") / pl.col("sqftmain"))
            .filter((pl.col("sqftmain") > 200) & (pl.col("roll_impvalue") > 0))
            .median()
            .alias("assessor_imp_value_per_sqft"),
            pl.col("roll_totalvalue").median().alias("assessor_median_total_value"),
            pl.col("units").sum().alias("assessor_units"),
            (pl.col("usetype") == "SFR").mean().alias("assessor_sfr_share"),
        )
        .join(
            res.filter(pl.col("tract_geoid").is_not_null())
            .group_by("tract_geoid")
            .agg(pl.col("roll_impbaseyear").median().alias("assessor_median_imp_base_year")),
            on="tract_geoid",
            how="left",
        )
    )


def permit_parcel_join() -> pl.DataFrame | None:
    """Permit -> assessor parcel by APN (LADBS APN == assessor AIN): year built and value
    of the parcel each permit was pulled on."""
    d = PARQUET_DIR / "assessor"
    if not d.exists() or not any(d.glob("*.parquet")):
        return None
    roll = (
        pl.read_parquet(d / "*.parquet")
        .select(
            pl.col("ain").alias("apn"),
            pl.col("yearbuilt").alias("parcel_year_built"),
            pl.col("roll_totalvalue").alias("parcel_total_value"),
            pl.col("units").alias("parcel_units"),
            pl.col("usetype").alias("parcel_use_type"),
        )
        .unique(subset=["apn"], keep="first")
    )
    con = connect(read_only=True)
    permits = con.execute(
        "SELECT ahj, source_dataset, permit_id, apn FROM permits_norm "
        "WHERE apn IS NOT NULL AND record_kind='issued'"
    ).pl()
    con.close()
    joined = permits.join(roll, on="apn", how="inner")
    print(
        f"  apn join: {joined.height:,} of {permits.height:,} issued permits with an APN "
        f"matched a 2025 city parcel"
    )
    return joined


__all__ = ["assessor_by_tract", "np", "permit_parcel_join", "tract_context"]
