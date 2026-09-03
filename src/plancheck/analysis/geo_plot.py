"""Matplotlib helpers for shapely geometry (no geopandas): polygon collections, a city
outline, and colour ramps from the reference dataviz palette."""

from __future__ import annotations

import math

import numpy as np
from matplotlib.collections import PolyCollection
from matplotlib.colors import LinearSegmentedColormap, ListedColormap
from shapely import from_wkb

# Reference palette (dataviz skill, light mode).
BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
MAGENTA = "#e87ba4"
GREEN = "#008300"
VIOLET = "#4a3aa7"
RED = "#e34948"
CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"
NEUTRAL_MID = "#f0efec"
SEQ_BLUE = [
    "#cde2fb",
    "#b7d3f6",
    "#9ec5f4",
    "#86b6ef",
    "#6da7ec",
    "#5598e7",
    "#3987e5",
    "#2a78d6",
    "#256abf",
    "#1c5cab",
    "#184f95",
    "#104281",
    "#0d366b",
]
SEQ_ORANGE = ["#fbe3d8", "#f7c5ae", "#f3a684", "#ef875a", "#eb6834", "#c9532a", "#a54321"]
DIV_BLUE_RED = [
    "#0d366b",
    "#256abf",
    "#6da7ec",
    "#cde2fb",
    NEUTRAL_MID,
    "#f5b8b8",
    "#ee8080",
    "#e34948",
    "#8f1f1f",
]

CMAP_SEQ = LinearSegmentedColormap.from_list("pc_blue", SEQ_BLUE)
CMAP_SEQ_ORANGE = LinearSegmentedColormap.from_list("pc_orange", SEQ_ORANGE)
CMAP_DIV = LinearSegmentedColormap.from_list("pc_div", DIV_BLUE_RED)
CMAP_CAT = ListedColormap(CATEGORICAL)

RCPARAMS = {
    "figure.facecolor": SURFACE,
    "axes.facecolor": SURFACE,
    "axes.edgecolor": "#c3c2b7",
    "axes.labelcolor": INK2,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.6,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "text.color": INK,
    "font.family": "sans-serif",
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titlecolor": INK,
    "legend.frameon": False,
}


def rings(geom) -> list[np.ndarray]:
    """Exterior rings of a (Multi)Polygon as Nx2 arrays (holes are ignored for fill)."""
    if geom.geom_type == "Polygon":
        return [np.asarray(geom.exterior.coords)]
    if geom.geom_type == "MultiPolygon":
        return [np.asarray(g.exterior.coords) for g in geom.geoms]
    return []


def poly_collection(wkbs, values=None, cmap=CMAP_SEQ, vmin=None, vmax=None, **kw) -> PolyCollection:
    verts, vals = [], []
    for wkb, v in zip(wkbs, values if values is not None else [None] * len(wkbs), strict=True):
        for ring in rings(from_wkb(wkb)):
            verts.append(ring)
            vals.append(v)
    pc = PolyCollection(verts, **{"linewidths": 0.15, "edgecolors": "#ffffff", **kw})
    if values is not None:
        arr = np.array([np.nan if v is None else v for v in vals], dtype=float)
        pc.set_array(arr)
        pc.set_cmap(cmap)
        pc.set_clim(vmin, vmax)
    return pc


def set_geo_axes(ax, bounds, lat0: float = 34.05) -> None:
    """Equal-ish aspect in degrees at this latitude; hide ticks and grid."""
    xmin, ymin, xmax, ymax = bounds
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(ymin, ymax)
    ax.set_aspect(1 / math.cos(math.radians(lat0)))
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_visible(False)


def outline(ax, wkbs, color=INK2, lw=0.6) -> None:
    for wkb in wkbs:
        for ring in rings(from_wkb(wkb)):
            ax.plot(ring[:, 0], ring[:, 1], color=color, lw=lw, zorder=3)
