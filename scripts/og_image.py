"""Render the atlas's social card (1200×630, dark) from the tract aggregates."""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import polars as pl
from matplotlib.colors import LinearSegmentedColormap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from plancheck.analysis.geo_plot import outline, poly_collection, set_geo_axes
from plancheck.config import analysis_config
from plancheck.paths import PARQUET_DIR

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/site/og/atlas.png")
GROUND, INK, INK2 = "#131619", "#eef0f3", "#aab1bb"
RAMP = ["#1d2b3f", "#1c3f6e", "#1c5cab", "#2a78d6", "#3987e5", "#6da7ec", "#9ec5f4", "#cde2fb"]
CMAP = LinearSegmentedColormap.from_list("dark_blue", RAMP)


def main() -> None:
    cfg = analysis_config()
    y0, y1 = cfg["years"]["start"], cfg["years"]["end"]
    tr = pl.read_parquet(PARQUET_DIR / "analysis" / "intensity_tract.parquet")
    tracts = pl.read_parquet(PARQUET_DIR / "tracts" / "data.parquet").select(
        "geoid", "wkb", "arealand_m2"
    )
    agg = (
        tr.filter((pl.col("permit_class") == "building") & pl.col("year").is_between(y0, y1))
        .group_by("geo_id")
        .agg(pl.col("n_permits").sum())
    )
    df = tracts.join(agg, left_on="geoid", right_on="geo_id", how="inner")
    vals = df["n_permits"].to_numpy() / (df["arealand_m2"].to_numpy() / 1e6)
    vals[~np.isfinite(vals)] = np.nan
    city = PARQUET_DIR / "ref" / "ahj=la_city" / "layer=city_boundary" / "data.parquet"
    wkbs = pl.read_parquet(city)["wkb"].to_list() if city.exists() else []

    fig = plt.figure(figsize=(12, 6.3), dpi=100, facecolor=GROUND)
    ax = fig.add_axes([0.42, 0.02, 0.58, 0.96], facecolor=GROUND)
    ax.add_collection(
        poly_collection(
            df["wkb"].to_list(),
            vals.tolist(),
            cmap=CMAP,
            vmin=0,
            vmax=np.nanpercentile(vals, 97),
            linewidths=0.2,
            edgecolors=GROUND,
        )
    )
    outline(ax, wkbs, color="#5b6270", lw=0.8)
    set_geo_axes(ax, (-118.70, 33.70, -118.10, 34.35))
    fig.text(
        0.05,
        0.80,
        "LA Permit Atlas",
        color=INK,
        fontsize=44,
        fontweight="bold",
        family="sans-serif",
        va="top",
    )
    fig.text(
        0.05,
        0.60,
        "Every building, trade and right-of-way permit\nthe City of Los Angeles "
        "publishes, located and\nsummed by tract, school area, neighborhood,\ncouncil district or ZIP.",
        color=INK2,
        fontsize=17,
        va="top",
        linespacing=1.4,
    )
    fig.text(
        0.05,
        0.16,
        f"Building permits per km², {y0}–{y1}  ·  plancheck.sorkinlabs.com",
        color="#737b86",
        fontsize=12,
        va="top",
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=100, facecolor=GROUND)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
