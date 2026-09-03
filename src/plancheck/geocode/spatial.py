"""Spatial joins for located permits: point-in-polygon against reference layers, nearest
station distance, and H3 cells. Pure shapely + numpy (no geopandas)."""

from __future__ import annotations

import math

import numpy as np
import polars as pl
from shapely import STRtree, from_wkb, points

from plancheck.paths import PARQUET_DIR


def load_layer(ahj_slug: str, layer: str) -> pl.DataFrame | None:
    path = PARQUET_DIR / "ref" / f"ahj={ahj_slug}" / f"layer={layer}" / "data.parquet"
    return pl.read_parquet(path) if path.exists() else None


def load_tracts() -> pl.DataFrame | None:
    path = PARQUET_DIR / "tracts" / "data.parquet"
    return pl.read_parquet(path) if path.exists() else None


def point_in_polygon(lat: np.ndarray, lon: np.ndarray, polys: pl.DataFrame, id_col: str) -> list:
    """For each (lat, lon) return the id of the containing polygon (first hit) or None."""
    pts = points(lon, lat)
    tree = STRtree(pts)
    geoms = from_wkb(polys["wkb"].to_list())
    ids = polys[id_col].to_list()
    out: list = [None] * len(pts)
    for gi, geom in enumerate(geoms):
        hits = tree.query(geom, predicate="contains")
        for h in hits:
            if out[h] is None:
                out[h] = ids[gi]
    return out


def nearest_distance_m(lat: np.ndarray, lon: np.ndarray, targets: pl.DataFrame) -> np.ndarray:
    """Great-circle distance (m) from each point to the nearest target point."""
    tg = from_wkb(targets["wkb"].to_list())
    tpts = [g if g.geom_type == "Point" else g.centroid for g in tg]
    if not tpts:
        return np.full(len(lat), np.nan)
    cos_lat = math.cos(math.radians(float(np.nanmean(lat))))
    # Planar nearest in a locally scaled frame, then haversine for the reported distance.
    scaled_targets = points([p.x * cos_lat for p in tpts], [p.y for p in tpts])
    tree = STRtree(scaled_targets)
    q = points(lon * cos_lat, lat)
    idx = tree.nearest(q)
    tlat = np.array([tpts[i].y for i in idx])
    tlon = np.array([tpts[i].x for i in idx])
    return haversine_m(lat, lon, tlat, tlon)


def haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray:
    r = 6_371_000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def h3_cells(lat: np.ndarray, lon: np.ndarray, res: int) -> list[str | None]:
    try:
        import h3
    except ImportError:  # pragma: no cover
        return [None] * len(lat)
    return [
        h3.latlng_to_cell(float(a), float(o), res) if not (np.isnan(a) or np.isnan(o)) else None
        for a, o in zip(lat, lon, strict=True)
    ]


def enrich(located: pl.DataFrame, ahj) -> pl.DataFrame:
    """Add tract_geoid, council_district, cpa_id, nc_id, in_city, zoning, hpoz, rail
    distance and H3 cells to a frame with lat/lon (nulls pass through)."""
    from plancheck.config import analysis_config

    has = located.filter(pl.col("lat").is_not_null() & pl.col("lon").is_not_null())
    lat = has["lat"].to_numpy()
    lon = has["lon"].to_numpy()
    cols: dict[str, list] = {}

    tracts = load_tracts()
    if tracts is not None:
        cols["tract_geoid"] = point_in_polygon(lat, lon, tracts, "geoid")
    for layer, col in (
        ("council_districts", "council_district"),
        ("community_plan_areas", "cpa_id"),
        ("neighborhood_councils", "nc_id"),
    ):
        ref = load_layer(ahj.slug, layer)
        if ref is not None:
            cols[col] = point_in_polygon(lat, lon, ref, "id")
            names = dict(zip(ref["id"].to_list(), ref["name"].to_list(), strict=True))
            cols[col + "_name"] = [names.get(x) if x is not None else None for x in cols[col]]
    # Any other polygon reference layer (neighborhoods, zip codes, LAUSD attendance areas …)
    # joins generically as <layer>_id; derived dissolve layers are declared in the source's
    # `dissolve` block.
    handled = {
        "council_districts",
        "community_plan_areas",
        "neighborhood_councils",
        "city_boundary",
    }
    generic = []
    for name, spec in ahj.reference.items():
        if spec.get("geometry", True) is False or spec.get("dissolve"):
            generic += list(spec.get("dissolve") or {})
            continue
        if name not in handled:
            generic.append(name)
    for name in generic:
        ref = load_layer(ahj.slug, name)
        if ref is not None:
            cols[f"{name}_id"] = point_in_polygon(lat, lon, ref, "id")
    city = load_layer(ahj.slug, "city_boundary")
    if city is not None:
        cols["in_city"] = [x is not None for x in point_in_polygon(lat, lon, city, "id")]
    zoning = load_layer(ahj.slug, "zoning")
    if zoning is not None:
        zid = point_in_polygon(lat, lon, zoning, "id")
        import json

        props = {r["id"]: json.loads(r["props"]) for r in zoning.iter_rows(named=True)}
        cols["zoning"] = [props[z].get("Zoning") if z is not None else None for z in zid]
        cols["zoning_category"] = [props[z].get("CATEGORY") if z is not None else None for z in zid]
    hpoz = load_layer(ahj.slug, "hpoz")
    if hpoz is not None:
        cols["hpoz"] = [x is not None for x in point_in_polygon(lat, lon, hpoz, "id")]
    rail = load_layer(ahj.slug, "rail_stations")
    if rail is not None:
        cols["dist_rail_m"] = nearest_distance_m(lat, lon, rail).tolist()
    for res in analysis_config()["hexes"]["resolutions"]:
        cols[f"h3_r{res}"] = h3_cells(lat, lon, res)

    enriched = has.with_columns([pl.Series(name, vals) for name, vals in cols.items()])
    rest = located.filter(pl.col("lat").is_null() | pl.col("lon").is_null())
    return pl.concat([enriched, rest], how="diagonal_relaxed")
