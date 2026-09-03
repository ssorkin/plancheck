"""Static figures for the writeup (matplotlib, headless). Each function returns the PNG path.

Form choices: choropleths and hex maps use one sequential hue (magnitude); net dwelling
units uses the diverging blue–red ramp with a neutral midpoint (polarity); time series
use the fixed categorical order with direct labels; scatter plots report Spearman rank
correlation and say "correlated with", never more.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from scipy import stats

from plancheck.analysis.geo_plot import (
    CATEGORICAL,
    CMAP_DIV,
    CMAP_SEQ,
    INK2,
    MUTED,
    RCPARAMS,
    outline,
    poly_collection,
    set_geo_axes,
)
from plancheck.config import analysis_config
from plancheck.paths import FIG_DIR, PARQUET_DIR

plt.rcParams.update(RCPARAMS)

CLASS_ORDER = ["building", "electrical", "mechanical", "right_of_way"]
CLASS_LABEL = {
    "building": "Building",
    "electrical": "Electrical",
    "mechanical": "Mechanical",
    "right_of_way": "Right-of-way (BOE)",
}


def _save(fig, name: str) -> Path:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = FIG_DIR / f"{name}.png"
    fig.savefig(out, dpi=analysis_config()["figures"]["dpi"], bbox_inches="tight")
    plt.close(fig)
    return out


def _city_wkbs(ahj_slug: str) -> list:
    p = PARQUET_DIR / "ref" / f"ahj={ahj_slug}" / "layer=city_boundary" / "data.parquet"
    return pl.read_parquet(p)["wkb"].to_list() if p.exists() else []


def _city_bounds(ahj_slug: str, fallback=(-118.70, 33.70, -118.10, 34.35)):
    from shapely import from_wkb

    wkbs = _city_wkbs(ahj_slug)
    if not wkbs:
        return fallback
    b = np.array([from_wkb(w).bounds for w in wkbs])
    return (b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max())


def _tract_frame(
    intensity: pl.DataFrame, years: tuple[int, int], permit_class: str | None, metric: str
) -> pl.DataFrame:
    tracts = pl.read_parquet(PARQUET_DIR / "tracts" / "data.parquet").select(
        "geoid", "wkb", "arealand_m2"
    )
    d = intensity.filter(pl.col("year").is_between(years[0], years[1]))
    if permit_class:
        d = d.filter(pl.col("permit_class") == permit_class)
    agg = d.group_by("geo_id").agg(pl.col(metric).sum().alias(metric))
    return tracts.join(agg, left_on="geoid", right_on="geo_id", how="left")


def fig_tract_choropleth(
    ahj_slug: str,
    intensity: pl.DataFrame,
    metric: str,
    title: str,
    years: tuple[int, int],
    permit_class: str | None = "building",
    per_km2: bool = True,
    name: str | None = None,
    diverging: bool = False,
) -> Path:
    df = _tract_frame(intensity, years, permit_class, metric)
    vals = df[metric].to_numpy().astype(float)
    if per_km2:  # per acre (the option name predates the unit change)
        vals = vals / (df["arealand_m2"].to_numpy() / 4046.86)
    vals[~np.isfinite(vals)] = np.nan
    vals_plot = vals.copy()
    if diverging:
        lim = np.nanpercentile(np.abs(vals), 98) or 1.0
        vmin, vmax, cmap = -lim, lim, CMAP_DIV
    else:
        vmin, vmax, cmap = 0, np.nanpercentile(vals, 98) or 1.0, CMAP_SEQ
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.add_collection(
        poly_collection(df["wkb"].to_list(), vals_plot.tolist(), cmap=cmap, vmin=vmin, vmax=vmax)
    )
    outline(ax, _city_wkbs(ahj_slug))
    set_geo_axes(ax, _city_bounds(ahj_slug))
    cb = fig.colorbar(ax.collections[0], ax=ax, shrink=0.5, pad=0.01)
    cb.set_label(("per acre" if per_km2 else "total") + f", {years[0]}–{years[1]}", color=INK2)
    cb.outline.set_visible(False)
    ax.set_title(title, fontsize=13, loc="left")
    ax.text(
        0,
        -0.01,
        "Census tracts (2020). Tracts outside the city boundary are blank.",
        transform=ax.transAxes,
        fontsize=8,
        color=MUTED,
        va="top",
    )
    return _save(fig, name or f"tract_{metric}_{permit_class or 'all'}")


def fig_hex_density(
    ahj_slug: str,
    intensity_h3: pl.DataFrame,
    metric: str,
    title: str,
    years: tuple[int, int],
    permit_class: str | None = "building",
    name: str | None = None,
) -> Path:
    import h3
    from shapely.geometry import Polygon

    d = intensity_h3.filter(pl.col("year").is_between(years[0], years[1]))
    if permit_class:
        d = d.filter(pl.col("permit_class") == permit_class)
    agg = d.group_by("geo_id").agg(pl.col(metric).sum().alias(metric))
    wkbs, vals = [], []
    for cell, v in agg.iter_rows():
        ring = [(lon, lat) for lat, lon in h3.cell_to_boundary(cell)]
        wkbs.append(Polygon(ring).wkb)
        vals.append(float(v))
    vals_arr = np.array(vals)
    fig, ax = plt.subplots(figsize=(9, 9))
    vmax = np.percentile(vals_arr, 98) if len(vals_arr) else 1.0
    ax.add_collection(poly_collection(wkbs, vals, cmap=CMAP_SEQ, vmin=0, vmax=vmax, linewidths=0))
    outline(ax, _city_wkbs(ahj_slug))
    set_geo_axes(ax, _city_bounds(ahj_slug))
    cb = fig.colorbar(ax.collections[0], ax=ax, shrink=0.5, pad=0.01)
    cb.set_label(f"per H3 r8 cell (~182 acres), {years[0]}–{years[1]}", color=INK2)
    cb.outline.set_visible(False)
    ax.set_title(title, fontsize=13, loc="left")
    return _save(fig, name or f"hex_{metric}_{permit_class or 'all'}")


def fig_small_multiples(
    ahj_slug: str,
    intensity: pl.DataFrame,
    metric: str,
    title: str,
    years: list[int],
    permit_class: str = "building",
    name: str | None = None,
) -> Path:
    tracts = pl.read_parquet(PARQUET_DIR / "tracts" / "data.parquet").select(
        "geoid", "wkb", "arealand_m2"
    )
    d = intensity.filter(pl.col("permit_class") == permit_class)
    n = len(years)
    cols = min(4, n)
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(4.2 * cols, 4.2 * rows))
    axes = np.atleast_1d(axes).ravel()
    allv = d.filter(pl.col("year").is_in(years))[metric].to_numpy()
    per = (
        d.filter(pl.col("year").is_in(years))
        .join(tracts, left_on="geo_id", right_on="geoid")
        .with_columns((pl.col(metric) / (pl.col("arealand_m2") / 1e6)).alias("v"))["v"]
        .to_numpy()
    )
    vmax = np.nanpercentile(per, 98) if len(allv) else 1.0
    bounds = _city_bounds(ahj_slug)
    city = _city_wkbs(ahj_slug)
    for ax, year in zip(axes, years, strict=False):
        agg = d.filter(pl.col("year") == year).group_by("geo_id").agg(pl.col(metric).sum())
        df = tracts.join(agg, left_on="geoid", right_on="geo_id", how="left")
        vals = df[metric].to_numpy().astype(float) / (df["arealand_m2"].to_numpy() / 4046.86)
        vals[~np.isfinite(vals)] = np.nan
        ax.add_collection(
            poly_collection(df["wkb"].to_list(), vals.tolist(), cmap=CMAP_SEQ, vmin=0, vmax=vmax)
        )
        outline(ax, city, lw=0.4)
        set_geo_axes(ax, bounds)
        ax.set_title(str(year), fontsize=11, loc="left")
    for ax in axes[n:]:
        ax.set_visible(False)
    fig.suptitle(title, fontsize=13, x=0.01, ha="left")
    return _save(fig, name or f"years_{metric}_{permit_class}")


def fig_timeseries_by_class(series: pl.DataFrame, ahj_slug: str) -> Path:
    d = series.filter(pl.col("ahj") == ahj_slug)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for i, cls in enumerate(CLASS_ORDER):
        s = d.filter(pl.col("permit_class") == cls).sort("year")
        if s.is_empty():
            continue
        x, y = s["year"].to_numpy(), s["n_permits"].to_numpy() / 1000
        ax.plot(x, y, color=CATEGORICAL[i], lw=2, label=CLASS_LABEL[cls])
        ax.text(x[-1] + 0.15, y[-1], CLASS_LABEL[cls], color=INK2, fontsize=9, va="center")
    ax.set_ylabel("Permits issued (thousands)")
    ax.set_xlabel("")
    ax.set_ylim(bottom=0)
    ax.set_title("Permits issued per year, by class", fontsize=13, loc="left")
    ax.legend(loc="upper left", fontsize=9)
    ax.text(0, -0.12, "The final year is partial.", transform=ax.transAxes, fontsize=8, color=MUTED)
    return _save(fig, "series_by_class")


def fig_scatter_vs_covariate(
    joined: pl.DataFrame,
    x: str,
    y: str,
    xlabel: str,
    ylabel: str,
    name: str,
    logx: bool = False,
    logy: bool = True,
    weight: str | None = None,
) -> Path:
    d = joined.filter(pl.col(x).is_not_null() & pl.col(y).is_not_null())
    if logx:
        d = d.filter(pl.col(x) > 0)
    if logy:
        d = d.filter(pl.col(y) > 0)
    if d.height < 10:
        fig, ax = plt.subplots(figsize=(6, 4.5))
        ax.text(0.5, 0.5, "not enough tracts with data", ha="center", transform=ax.transAxes)
        return _save(fig, name)
    xv, yv = d[x].to_numpy(), d[y].to_numpy()
    rho, _p = stats.spearmanr(xv, yv)
    fig, ax = plt.subplots(figsize=(6.5, 5))
    s = 8 if weight is None else np.clip(d[weight].to_numpy() / 200, 4, 60)
    ax.scatter(xv, yv, s=s, alpha=0.35, color=CATEGORICAL[0], edgecolors="none", rasterized=True)
    if logx:
        ax.set_xscale("log")
    if logy:
        ax.set_yscale("log")
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(
        f"{ylabel} is correlated with {xlabel.lower()} (Spearman ρ = {rho:+.2f})",
        fontsize=11,
        loc="left",
    )
    ax.text(
        0,
        -0.16,
        f"Each dot is a census tract (n = {d.height:,}). Association, not cause.",
        transform=ax.transAxes,
        fontsize=8,
        color=MUTED,
    )
    return _save(fig, name)


def fig_geocode_coverage(coverage: pl.DataFrame, ahj_slug: str, min_year: int = 1990) -> Path:
    d = coverage.filter((pl.col("ahj") == ahj_slug) & (pl.col("year") >= min_year))
    fams = sorted(d["source_family"].unique().to_list())
    fig, axes = plt.subplots(len(fams), 1, figsize=(9, 2.2 * len(fams)), sharex=True)
    axes = np.atleast_1d(axes)
    methods = [
        "source",
        "boe_point",
        "boe_line_centroid",
        "boe_polygon_centroid",
        "cams",
        "centerline",
        "none",
    ]
    colors = dict(zip(methods, [*CATEGORICAL[:6], "#c3c2b7"], strict=True))
    for ax, fam in zip(axes, fams, strict=True):
        f = d.filter(pl.col("source_family") == fam)
        years = sorted(f["year"].unique().to_list())
        totals = {y: f.filter(pl.col("year") == y)["n"].sum() for y in years}
        bottom = np.zeros(len(years))
        for m in methods:
            share = np.array(
                [
                    (f.filter((pl.col("year") == y) & (pl.col("method") == m))["n"].sum() or 0)
                    / max(totals[y], 1)
                    for y in years
                ]
            )
            if share.sum() == 0:
                continue
            ax.bar(years, share, bottom=bottom, color=colors[m], width=0.8, label=m, linewidth=0)
            bottom += share
        ax.set_ylim(0, 1)
        ax.set_ylabel(fam.replace("ladbs_", "").replace("_issued", ""), fontsize=8)
        ax.grid(False)
    axes[0].legend(ncol=4, fontsize=8, loc="lower left")
    axes[0].set_title(
        "How each permit was located, by year and source family", fontsize=12, loc="left"
    )
    return _save(fig, "geocode_coverage")
