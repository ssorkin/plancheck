"""ACS tract covariates, selected by variable label (never by hardcoded variable id)."""

from __future__ import annotations

import polars as pl

from plancheck.paths import PARQUET_DIR


def _pick(acs: pl.DataFrame, table: str, label_parts: list[str], name: str) -> pl.DataFrame:
    t = acs.filter(pl.col("table") == table)
    for part in label_parts:
        t = t.filter(pl.col("label").str.contains(part, literal=True))
    if t.select("variable").n_unique() != 1:
        vars_ = t["variable"].unique().to_list()
        raise RuntimeError(f"{table} {label_parts}: expected one variable, got {vars_}")
    return t.select("geoid", pl.col("value").alias(name))


def tract_covariates() -> pl.DataFrame | None:
    d = PARQUET_DIR / "census_acs"
    if not d.exists() or not any(d.glob("*.parquet")):
        return None
    acs = pl.read_parquet(d / "*.parquet")
    frames = [
        _pick(acs, "B01003", ["Estimate!!Total"], "pop"),
        _pick(acs, "B19013", ["Estimate!!Median household income"], "median_hh_income"),
        _pick(acs, "B25003", ["Estimate!!Total:"], "occ_units"),
        _pick(acs, "B25003", ["Renter occupied"], "renter_units"),
        _pick(acs, "B25035", ["Estimate!!Median year structure built"], "median_year_built"),
        _pick(acs, "B25001", ["Estimate!!Total"], "housing_units"),
        _pick(acs, "B25024", ["Estimate!!Total:!!1, detached"], "units_1_detached"),
        _pick(acs, "B03002", ["Estimate!!Total:!!Hispanic or Latino"], "pop_hispanic"),
        _pick(acs, "B03002", ["Not Hispanic or Latino:!!White alone"], "pop_white_nh"),
        _pick(
            acs,
            "B03002",
            ["Not Hispanic or Latino:!!Black or African American alone"],
            "pop_black_nh",
        ),
        _pick(acs, "B03002", ["Not Hispanic or Latino:!!Asian alone"], "pop_asian_nh"),
    ]
    out = frames[0]
    for f in frames[1:]:
        out = out.join(f, on="geoid", how="full", coalesce=True)
    tracts = pl.read_parquet(PARQUET_DIR / "tracts" / "data.parquet").select("geoid", "arealand_m2")
    out = out.join(tracts, on="geoid", how="left").with_columns(
        (pl.col("renter_units") / pl.col("occ_units")).alias("renter_share"),
        (pl.col("pop") / (pl.col("arealand_m2") / 1e6)).alias("pop_density_km2"),
        (pl.col("units_1_detached") / pl.col("housing_units")).alias("share_single_family"),
        (pl.col("pop_hispanic") / pl.col("pop")).alias("share_hispanic"),
        (pl.col("pop_white_nh") / pl.col("pop")).alias("share_white_nh"),
    )
    # Median year built uses a large negative sentinel when not computable.
    return out.with_columns(
        pl.when(pl.col("median_year_built") < 1800)
        .then(None)
        .otherwise(pl.col("median_year_built"))
        .alias("median_year_built")
    )
