"""Exports for the map page: simplified tract GeoJSON with per-year metrics, hex GeoJSON,
district GeoJSON, citywide series and a config echo. Also the self-contained map.html."""

from __future__ import annotations

import json
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


def _round(x):
    return None if x is None else (round(x, 6) if isinstance(x, float) else x)


def _feature(geom, props: dict) -> dict:
    return {"type": "Feature", "geometry": mapping(geom), "properties": props}


def _simplify(geom, tol: float):
    g = geom.simplify(tol, preserve_topology=True)
    return g if not g.is_empty else geom


def _metrics_by_geo(intensity: pl.DataFrame, permit_class: str, years) -> dict[str, dict]:
    d = intensity.filter(
        (pl.col("permit_class") == permit_class) & pl.col("year").is_between(*years)
    )
    out: dict[str, dict] = {}
    for row in d.iter_rows(named=True):
        g = out.setdefault(row["geo_id"], {})
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


def export_tracts(intensity: pl.DataFrame, acs: pl.DataFrame | None, years, tol=0.0004) -> int:
    tracts = pl.read_parquet(PARQUET_DIR / "tracts" / "data.parquet")
    by_geo = {
        cls: _metrics_by_geo(intensity, cls, years)
        for cls in ("building", "electrical", "mechanical", "right_of_way")
    }
    acs_map = {r["geoid"]: r for r in acs.iter_rows(named=True)} if acs is not None else {}
    feats = []
    for r in tracts.iter_rows(named=True):
        gid = r["geoid"]
        props = {"geoid": gid, "arealand_km2": round(r["arealand_m2"] / 1e6, 4)}
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
        feats.append(_feature(_simplify(from_wkb(r["wkb"]), tol), props))
    (EXPORT_DIR / "tracts.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))
    )
    return len(feats)


def export_hex(intensity_h3: pl.DataFrame, years) -> int:
    import h3
    from shapely.geometry import Polygon

    by_geo = {
        cls: _metrics_by_geo(intensity_h3, cls, years) for cls in ("building", "right_of_way")
    }
    cells = set().union(*(m.keys() for m in by_geo.values()))
    feats = []
    for cell in sorted(cells):
        ring = [(round(lon, 5), round(lat, 5)) for lat, lon in h3.cell_to_boundary(cell)]
        props = {"h3": cell}
        for cls, m in by_geo.items():
            if cell in m:
                props[cls] = m[cell]
        feats.append(_feature(Polygon(ring), props))
    (EXPORT_DIR / "hex_r8.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))
    )
    return len(feats)


def export_districts(ahj_slug: str, tol=0.0006) -> int:
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
        (EXPORT_DIR / f"{layer}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"))
        )
        n += len(feats)
    return n


def run_export(inline: bool = False) -> None:
    from plancheck.analysis.acs import tract_covariates
    from plancheck.analysis.leaflet import write_map_html

    cfg = analysis_config()
    years = (cfg["years"]["start"], cfg["years"]["end"])
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    a = PARQUET_DIR / "analysis"
    intensity = pl.read_parquet(a / "intensity_tract.parquet")
    n = export_tracts(intensity, tract_covariates(), years)
    print(f"  tracts.geojson: {n:,} tracts")
    h3p = a / "intensity_h3_r8.parquet"
    if h3p.exists():
        print(f"  hex_r8.geojson: {export_hex(pl.read_parquet(h3p), years):,} cells")
    print(f"  district layers: {export_districts('la_city'):,} features")
    series = pl.read_parquet(a / "series_class.parquet")
    (EXPORT_DIR / "series.json").write_text(json.dumps(series.to_dicts(), separators=(",", ":")))
    cov = pl.read_parquet(a / "geocode_coverage.parquet")
    meta = {
        "generated": datetime.now(UTC).isoformat(timespec="seconds"),
        "config": cfg,
        "geocode_coverage": cov.to_dicts(),
        "metrics": METRICS,
    }
    (EXPORT_DIR / "meta.json").write_text(json.dumps(meta, separators=(",", ":"), default=str))
    print(
        f"  wrote {EXPORT_DIR.relative_to(REPO_ROOT)}/{{tracts,hex_r8,*}}.geojson, series.json, meta.json"
    )
    if inline:
        out = write_map_html(inline=True)
        print(f"  wrote {out.relative_to(REPO_ROOT)} ({out.stat().st_size / 1e6:.1f} MB)")
    else:
        out = write_map_html(inline=False)
        print(f"  wrote {out.relative_to(REPO_ROOT)} (loads ../data/export/*.geojson)")
