"""Administrative and covariate layers (GeoJSONL) -> ref parquet (id, name, props, wkb).

Attribute-only tables (`geometry: false`) are stored the same way without wkb. A layer with
a `dissolve` block is additionally merged by each named key into derived polygon layers
(LAUSD MP25 -> elementary / middle / high attendance areas), named from the matching codes
table (widest grade span wins; ties break on the lowest CDS code).
"""

from __future__ import annotations

import json
import shutil

import polars as pl
from shapely import coverage_union_all, from_wkb, union_all
from shapely.errors import GEOSException
from shapely.geometry import shape

from plancheck.ahj.base import AHJ
from plancheck.paths import PARQUET_DIR, RAW_DIR

SCHEMA = {"id": pl.Utf8, "name": pl.Utf8, "props": pl.Utf8, "geom_type": pl.Utf8, "wkb": pl.Binary}


def _load(path, id_field: str, name_field: str, geometry: bool = True) -> pl.DataFrame:
    rows = []
    with path.open() as f:
        for line in f:
            feat = json.loads(line)
            props = feat.get("properties") or {}
            geom = feat.get("geometry")
            if geometry:
                if not geom:
                    continue
                shp = shape(geom)
                if shp.is_empty:
                    continue
                gt, wkb = shp.geom_type, shp.wkb
            else:
                gt, wkb = None, None
            rows.append(
                {
                    "id": str(props.get(id_field)),
                    "name": None if props.get(name_field) is None else str(props.get(name_field)),
                    "props": json.dumps(props, default=str),
                    "geom_type": gt,
                    "wkb": wkb,
                }
            )
    return pl.DataFrame(rows, schema=SCHEMA)


def _write(out_root, name: str, df: pl.DataFrame) -> None:
    d = out_root / f"layer={name}"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    df.write_parquet(d / "data.parquet", compression="zstd")


def _best_names(codes: pl.DataFrame, key_field: str) -> dict[str, str]:
    """key -> school name, preferring the widest grade span then the lowest CDS."""
    rows = []
    for r in codes.iter_rows(named=True):
        p = json.loads(r["props"])
        key = p.get(key_field)
        if key is None or not p.get("NAME"):
            continue
        span = (p.get("HI_GRD") or 0) - (p.get("LO_GRD") or 0)
        rows.append((str(int(key)), -span, str(p.get("CDS") or ""), p["NAME"].strip()))
    rows.sort()
    out: dict[str, str] = {}
    for key, _, _, name in rows:
        out.setdefault(key, name)
    return out


def dissolve(base: pl.DataFrame, key_field: str, names: dict[str, str]) -> pl.DataFrame:
    by_key: dict[str, list] = {}
    for r in base.iter_rows(named=True):
        key = json.loads(r["props"]).get(key_field)
        if key is None:
            continue
        by_key.setdefault(str(int(key)), []).append(from_wkb(r["wkb"]))
    rows = []
    for key in sorted(by_key):
        parts = by_key[key]
        if len(parts) == 1:
            geom = parts[0]
        else:
            try:
                geom = coverage_union_all(parts)
            except GEOSException:  # slivers/overlaps in the source partition
                geom = union_all(parts)
        rows.append(
            {
                "id": key,
                "name": names.get(key, key),
                "props": json.dumps({"key": key, "n_parts": len(parts), "school": names.get(key)}),
                "geom_type": geom.geom_type,
                "wkb": geom.wkb,
            }
        )
    return pl.DataFrame(rows, schema=SCHEMA)


def ingest_layers(ahj: AHJ) -> None:
    out_root = PARQUET_DIR / "ref" / f"ahj={ahj.slug}"
    loaded: dict[str, pl.DataFrame] = {}
    for dataset, layers in (("reference", ahj.reference), ("covariates", ahj.covariates)):
        for name, spec in layers.items():
            if name == "assessor":
                continue  # the roll has its own ingester (ingest/assessor.py)
            path = RAW_DIR / f"{ahj.slug}_{dataset}" / f"{name}.geojsonl"
            if not path.exists():
                print(f"  skip {name}: {path} not downloaded")
                continue
            df = _load(path, spec["id_field"], spec["name_field"], spec.get("geometry", True))
            loaded[name] = df
            _write(out_root, name, df)
            print(f"  {name}: {df.height:,} features")
    for name, spec in ahj.reference.items():
        for derived, d in (spec.get("dissolve") or {}).items():
            if name not in loaded:
                continue
            codes = loaded.get(d["codes"])
            key_field = d["key_field"]
            names = (
                _best_names(
                    codes, {"E_KEY": "EKEY_5S", "M_KEY": "MKEY_5S", "H_KEY": "HKEY_5S"}[key_field]
                )
                if codes is not None
                else {}
            )
            df = dissolve(loaded[name], key_field, names)
            _write(out_root, derived, df)
            print(f"  {derived}: {df.height:,} areas dissolved from {name} ({len(names)} named)")
