"""Analysis orchestration: aggregates -> parquet -> figures."""

from __future__ import annotations

import polars as pl

from plancheck.ahj.base import list_ahjs
from plancheck.config import analysis_config
from plancheck.ingest import db
from plancheck.paths import PARQUET_DIR


def run_analysis(ahj: str = "all", figures: bool = True) -> None:
    from plancheck.analysis import intensity
    from plancheck.analysis.acs import tract_covariates
    from plancheck.analysis.covariates import assessor_by_tract, permit_parcel_join, tract_context

    print("aggregating …")
    frames = intensity.compute()
    acs = tract_covariates()
    if acs is not None:
        frames["acs_tract"] = acs
    try:
        frames["tract_context"] = tract_context()
    except Exception as exc:  # noqa: BLE001
        print(f"  tract_context skipped: {exc}")
    for name, fn in (("assessor_tract", assessor_by_tract), ("permit_parcel", permit_parcel_join)):
        try:
            out = fn()
            if out is not None:
                frames[name] = out
        except Exception as exc:  # noqa: BLE001
            print(f"  {name} skipped: {exc}")
    intensity.write(frames)
    db.build()
    if not figures:
        return
    from plancheck.analysis import figures as F

    cfg = analysis_config()
    y0, y1 = cfg["years"]["start"], cfg["years"]["end"]
    recent = (max(y0, y1 - 5), y1)
    for a in list_ahjs(ahj):
        print(f"figures for {a.slug} …")
        tr = frames.get("intensity_tract")
        if tr is None or tr.is_empty():
            print("  no tract aggregates; skipping maps")
            continue
        outs = [
            F.fig_tract_choropleth(
                a.slug, tr, "n_permits", "Building permits issued per km²", (y0, y1), "building"
            ),
            F.fig_tract_choropleth(
                a.slug, tr, "n_new_building", "New-building permits per km²", (y0, y1), "building"
            ),
            F.fig_tract_choropleth(
                a.slug,
                tr,
                "du_net",
                "Net dwelling units permitted",
                (y0, y1),
                "building",
                per_km2=False,
                diverging=True,
            ),
            F.fig_tract_choropleth(
                a.slug, tr, "n_adu", "ADU permits per km²", (2017, y1), "building"
            ),
            F.fig_tract_choropleth(
                a.slug,
                tr,
                "n_permits",
                "Right-of-way (BOE) permits per km²",
                (y0, y1),
                "right_of_way",
            ),
            F.fig_tract_choropleth(
                a.slug,
                tr,
                "n_solar",
                "Solar permits per km²",
                (y0, y1),
                "electrical",
                name="tract_n_solar_electrical",
            ),
            F.fig_timeseries_by_class(frames["series_class"], a.slug),
            F.fig_geocode_coverage(frames["geocode_coverage"], a.slug),
        ]
        h3 = frames.get("intensity_h3_r8")
        if h3 is not None and not h3.is_empty():
            outs.append(
                F.fig_hex_density(
                    a.slug, h3, "n_permits", "Building permits per hex cell", recent, "building"
                )
            )
            outs.append(
                F.fig_hex_density(
                    a.slug,
                    h3,
                    "n_permits",
                    "Right-of-way permits per hex cell",
                    recent,
                    "right_of_way",
                )
            )
        years = [y for y in range(y0, y1 + 1) if (y - y0) % 2 == 0][:8]
        outs.append(
            F.fig_small_multiples(
                a.slug, tr, "n_permits", "Building permits per km², by year", years
            )
        )
        if acs is not None:
            tot = (
                tr.filter(
                    (pl.col("permit_class") == "building") & pl.col("year").is_between(y0, y1)
                )
                .group_by("geo_id")
                .agg(
                    pl.col("n_permits").sum(),
                    pl.col("n_new_building").sum(),
                    pl.col("n_adu").sum(),
                    pl.col("valuation_sum").sum(),
                )
                .join(acs, left_on="geo_id", right_on="geoid")
                .with_columns(
                    (pl.col("n_permits") / pl.col("housing_units") * 1000).alias(
                        "permits_per_1k_units"
                    ),
                    (pl.col("n_adu") / pl.col("housing_units") * 1000).alias("adu_per_1k_units"),
                )
                .filter(pl.col("housing_units") > 100)
            )
            outs += [
                F.fig_scatter_vs_covariate(
                    tot,
                    "median_hh_income",
                    "permits_per_1k_units",
                    "Median household income",
                    "Building permits per 1,000 units",
                    "scatter_income_permits",
                    logx=True,
                    weight="housing_units",
                ),
                F.fig_scatter_vs_covariate(
                    tot,
                    "renter_share",
                    "permits_per_1k_units",
                    "Renter share",
                    "Building permits per 1,000 units",
                    "scatter_renter_permits",
                    weight="housing_units",
                ),
                F.fig_scatter_vs_covariate(
                    tot,
                    "median_year_built",
                    "adu_per_1k_units",
                    "Median year built",
                    "ADU permits per 1,000 units",
                    "scatter_yearbuilt_adu",
                    weight="housing_units",
                ),
                F.fig_scatter_vs_covariate(
                    tot,
                    "share_single_family",
                    "adu_per_1k_units",
                    "Share single-family detached",
                    "ADU permits per 1,000 units",
                    "scatter_sfd_adu",
                    weight="housing_units",
                ),
                F.fig_scatter_vs_covariate(
                    tot,
                    "pop_density_km2",
                    "permits_per_1k_units",
                    "Population density (per km²)",
                    "Building permits per 1,000 units",
                    "scatter_density_permits",
                    logx=True,
                    weight="housing_units",
                ),
            ]
            at = frames.get("assessor_tract")
            if at is not None:
                tot3 = tot.join(at, left_on="geo_id", right_on="tract_geoid")
                outs += [
                    F.fig_scatter_vs_covariate(
                        tot3,
                        "assessor_median_year_built",
                        "adu_per_1k_units",
                        "Assessor median year built",
                        "ADU permits per 1,000 units",
                        "scatter_assessor_yearbuilt_adu",
                        weight="housing_units",
                    ),
                    F.fig_scatter_vs_covariate(
                        tot3,
                        "assessor_imp_value_per_sqft",
                        "permits_per_1k_units",
                        "Assessed improvement value per sq ft",
                        "Building permits per 1,000 units",
                        "scatter_assessor_value_permits",
                        logx=True,
                        weight="housing_units",
                    ),
                ]
            ctx = frames.get("tract_context")
            if ctx is not None and "dist_rail_median_m" in ctx.columns:
                tot2 = tot.join(ctx, left_on="geo_id", right_on="tract_geoid")
                outs.append(
                    F.fig_scatter_vs_covariate(
                        tot2,
                        "dist_rail_median_m",
                        "permits_per_1k_units",
                        "Median distance to rail (m)",
                        "Building permits per 1,000 units",
                        "scatter_rail_permits",
                        logx=True,
                        weight="housing_units",
                    )
                )
        for o in outs:
            print(f"  {o.relative_to(PARQUET_DIR.parents[1])}")
