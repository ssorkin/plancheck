"""Exports for the map pages: one GeoJSON per geography (tracts, neighborhoods, council
districts, ZIP codes, LAUSD attendance areas, H3 hexes) carrying per-class, per-year metrics
in the same property shape, plus outline layers, citywide series and a config echo."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

import polars as pl
from shapely import from_wkb
from shapely.geometry import mapping

from plancheck.config import analysis_config
from plancheck.paths import EXPORT_DIR, PARQUET_DIR, REPO_ROOT

METRICS = [
    "n_permits",
    "n_new_building",
    "n_additions",
    "n_demolitions",
    "n_adu",
    "n_solar",
    "n_ev",
    "valuation_sum",
    "du_net",
]
CLASSES = ("building", "electrical", "mechanical", "right_of_way")

# geography slug -> (intensity parquet stem, ref layer, page label, simplify tolerance)
GEOGRAPHIES = {
    "tract": ("intensity_tract", None, "Census tracts", 0.0004),
    "neighborhood": ("intensity_neighborhood", "neighborhoods", "Neighborhoods", 0.0006),
    "council_district": (
        "intensity_council_district",
        "council_districts",
        "Council districts",
        0.0006,
    ),
    "zip": ("intensity_zip", "zip_codes", "ZIP codes", 0.0006),
    "lausd_elementary": (
        "intensity_lausd_elementary",
        "lausd_elementary",
        "Elementary attendance areas",
        0.0005,
    ),
    "lausd_middle": (
        "intensity_lausd_middle",
        "lausd_middle",
        "Middle school attendance areas",
        0.0006,
    ),
    "lausd_high": ("intensity_lausd_high", "lausd_high", "High school attendance areas", 0.0006),
}


def _round(x):
    return None if x is None else (round(x, 6) if isinstance(x, float) else x)


def _feature(geom, props: dict) -> dict:
    return {"type": "Feature", "geometry": mapping(geom), "properties": props}


def _simplify(geom, tol: float):
    g = geom.simplify(tol, preserve_topology=True)
    return g if not g.is_empty else geom


def area_km2(geom) -> float:
    """Planar area of a WGS84 polygon scaled to km² at its own latitude (≈1% accuracy)."""
    lat = geom.centroid.y
    return geom.area * (111.32**2) * math.cos(math.radians(lat))


def _metrics_by_geo(intensity: pl.DataFrame, permit_class: str, years) -> dict[str, dict]:
    d = intensity.filter(
        (pl.col("permit_class") == permit_class) & pl.col("year").is_between(*years)
    )
    out: dict[str, dict] = {}
    for row in d.iter_rows(named=True):
        g = out.setdefault(str(row["geo_id"]), {})
        y = g.setdefault(str(row["year"]), {})
        for m in METRICS:
            v = row.get(m)
            if v is not None:
                y[m] = (
                    int(v)
                    if isinstance(v, int) or (isinstance(v, float) and v.is_integer())
                    else round(v, 2)
                )
    return out


def _write_fc(name: str, feats: list[dict]) -> int:
    (EXPORT_DIR / f"{name}.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))
    )
    return len(feats)


def export_geography(slug: str, ahj_slug: str, years, acs: pl.DataFrame | None) -> int:
    stem, layer, _label, tol = GEOGRAPHIES[slug]
    ip = PARQUET_DIR / "analysis" / f"{stem}.parquet"
    if not ip.exists():
        return 0
    intensity = pl.read_parquet(ip)
    by_geo = {cls: _metrics_by_geo(intensity, cls, years) for cls in CLASSES}
    if layer is None:
        ref = pl.read_parquet(PARQUET_DIR / "tracts" / "data.parquet").select(
            pl.col("geoid").alias("id"),
            (pl.col("geoid").str.slice(5, 4) + "." + pl.col("geoid").str.slice(9)).alias("name"),
            (pl.col("arealand_m2") / 1e6).alias("area_km2"),
            "wkb",
        )
    else:
        p = PARQUET_DIR / "ref" / f"ahj={ahj_slug}" / f"layer={layer}" / "data.parquet"
        if not p.exists():
            return 0
        ref = (
            pl.read_parquet(p)
            .select("id", "name", "wkb")
            .with_columns(pl.lit(None, dtype=pl.Float64).alias("area_km2"))
        )
    acs_map = (
        {r["geoid"]: r for r in acs.iter_rows(named=True)}
        if (acs is not None and layer is None)
        else {}
    )
    pp = PARQUET_DIR / "analysis" / f"population_{slug}.parquet"
    pop_map = (
        {r["geo_id"]: r for r in pl.read_parquet(pp).iter_rows(named=True)} if pp.exists() else {}
    )
    # Display names: never empty, never numeric-only, unique within the layer.
    raw_names = [r["name"] for r in ref.iter_rows(named=True)]
    counts: dict[str, int] = {}
    for n in raw_names:
        if n:
            counts[n] = counts.get(n, 0) + 1
    feats = []
    for r in ref.iter_rows(named=True):
        gid = r["id"]
        geom = from_wkb(r["wkb"])
        name = r["name"]
        if not name:
            name = "Unnamed area" if gid in ("None", "") else f"Unnamed area {gid}"
        elif name.isdigit() and layer is not None and slug != "zip":
            name = f"Area {name}"
        elif counts.get(name, 0) > 1 and layer is not None:
            name = f"{name} ({gid})"
        props = {
            "id": gid,
            "name": name,
            "area_km2": round(r["area_km2"] if r["area_km2"] is not None else area_km2(geom), 4),
        }
        if gid in pop_map:
            props["pop"] = int(pop_map[gid]["pop"])
            props["housing_units"] = int(pop_map[gid]["housing_units"])
        has_any = False
        for cls, m in by_geo.items():
            if gid in m:
                props[cls] = m[gid]
                has_any = True
        if not has_any:
            continue
        a = acs_map.get(gid)
        if a:
            props["acs"] = {
                k: _round(a[k])
                for k in (
                    "pop",
                    "median_hh_income",
                    "renter_share",
                    "pop_density_km2",
                    "median_year_built",
                    "housing_units",
                    "share_single_family",
                )
                if a.get(k) is not None
            }
        feats.append(_feature(_simplify(geom, tol), props))
    return _write_fc(f"geo_{slug}", feats)


def export_hex(intensity_h3: pl.DataFrame, years) -> int:
    import h3
    from shapely.geometry import Polygon

    by_geo = {cls: _metrics_by_geo(intensity_h3, cls, years) for cls in CLASSES}
    cells = set().union(*(m.keys() for m in by_geo.values()))
    pp = PARQUET_DIR / "analysis" / "population_hex_r8.parquet"
    pop_map = (
        {r["geo_id"]: r for r in pl.read_parquet(pp).iter_rows(named=True)} if pp.exists() else {}
    )
    feats = []
    for cell in sorted(cells):
        ring = [(round(lon, 5), round(lat, 5)) for lat, lon in h3.cell_to_boundary(cell)]
        props = {"id": cell, "name": cell, "area_km2": 0.737}
        if cell in pop_map:
            props["pop"] = int(pop_map[cell]["pop"])
            props["housing_units"] = int(pop_map[cell]["housing_units"])
        for cls, m in by_geo.items():
            if cell in m:
                props[cls] = m[cell]
        feats.append(_feature(Polygon(ring), props))
    return _write_fc("geo_hex_r8", feats)


def export_outlines(ahj_slug: str, tol=0.0006) -> int:
    n = 0
    for layer in ("council_districts", "community_plan_areas", "city_boundary"):
        p = PARQUET_DIR / "ref" / f"ahj={ahj_slug}" / f"layer={layer}" / "data.parquet"
        if not p.exists():
            continue
        df = pl.read_parquet(p)
        feats = [
            _feature(_simplify(from_wkb(r["wkb"]), tol), {"id": r["id"], "name": r["name"]})
            for r in df.iter_rows(named=True)
        ]
        n += _write_fc(layer, feats)
    return n


def run_export(inline: bool = False, ahj_slug: str = "la_city") -> None:
    from plancheck.analysis.acs import tract_covariates
    from plancheck.analysis.leaflet import write_map_html

    cfg = analysis_config()
    years = (cfg["years"]["start"], cfg["years"]["end"])
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    a = PARQUET_DIR / "analysis"
    acs = tract_covariates()
    geographies = {}
    for slug, (_stem, _layer, label, _tol) in GEOGRAPHIES.items():
        n = export_geography(slug, ahj_slug, years, acs)
        if n:
            geographies[slug] = {"label": label, "features": n, "file": f"geo_{slug}.geojson"}
            print(f"  geo_{slug}.geojson: {n:,} areas")
    h3p = a / "intensity_h3_r8.parquet"
    if h3p.exists():
        n = export_hex(pl.read_parquet(h3p), years)
        geographies["hex_r8"] = {
            "label": "Hex cells (H3 r8)",
            "features": n,
            "file": "geo_hex_r8.geojson",
        }
        print(f"  geo_hex_r8.geojson: {n:,} cells")
    # Back-compatible alias for the tract layer.
    (EXPORT_DIR / "tracts.geojson").write_bytes((EXPORT_DIR / "geo_tract.geojson").read_bytes())
    print(f"  outline layers: {export_outlines(ahj_slug):,} features")
    series = pl.read_parquet(a / "series_class.parquet")
    (EXPORT_DIR / "series.json").write_text(json.dumps(series.to_dicts(), separators=(",", ":")))
    cov = pl.read_parquet(a / "geocode_coverage.parquet")
    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": cfg,
        "geocode_coverage": cov.to_dicts(),
        "metrics": METRICS,
        "geographies": geographies,
    }
    (EXPORT_DIR / "meta.json").write_text(json.dumps(meta, separators=(",", ":"), default=str))
    print(f"  wrote {EXPORT_DIR.relative_to(REPO_ROOT)}/geo_*.geojson, series.json, meta.json")
    out = write_map_html(inline=inline)
    print(
        f"  wrote {out.relative_to(REPO_ROOT)}"
        + (f" ({out.stat().st_size / 1e6:.1f} MB)" if inline else "")
    )
