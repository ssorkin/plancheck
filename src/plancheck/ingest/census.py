"""TIGER tracts and ACS tables -> parquet (tracts, census_acs long format)."""

from __future__ import annotations

import json

import polars as pl
from shapely.geometry import shape

from plancheck.config import analysis_config
from plancheck.paths import PARQUET_DIR, RAW_DIR


def ingest_tracts() -> None:
    cfg = analysis_config()["census"]
    path = RAW_DIR / "tiger" / f"tracts_2020_{cfg['state_fips']}{cfg['county_fips']}.geojsonl"
    if not path.exists():
        print(f"  skip tracts: {path} not downloaded")
        return
    rows = []
    with path.open() as f:
        for line in f:
            feat = json.loads(line)
            p = feat["properties"]
            shp = shape(feat["geometry"])
            rows.append(
                {
                    "geoid": p["GEOID"],
                    "tract": p["GEOID"][5:],
                    "name": p.get("NAME"),
                    "arealand_m2": float(p.get("AREALAND") or 0),
                    "areawater_m2": float(p.get("AREAWATER") or 0),
                    "centlat": float(p["CENTLAT"]) if p.get("CENTLAT") else None,
                    "centlon": float(p["CENTLON"]) if p.get("CENTLON") else None,
                    "wkb": shp.wkb,
                }
            )
    df = pl.DataFrame(rows)
    out = PARQUET_DIR / "tracts"
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / "data.parquet", compression="zstd")
    print(f"  tracts: {df.height:,}")


def ingest_blocks() -> None:
    cfg = analysis_config()["census"]
    path = RAW_DIR / "tiger" / f"blocks_2020_{cfg['state_fips']}{cfg['county_fips']}.geojsonl"
    if not path.exists():
        print(f"  skip blocks: {path} not downloaded")
        return
    rows = []
    with path.open() as f:
        for line in f:
            p = json.loads(line)["properties"]
            rows.append(
                {
                    "geoid": p["GEOID"],
                    "tract_geoid": p["GEOID"][:11],
                    "pop": int(p.get("POP100") or 0),
                    "housing_units": int(p.get("HU100") or 0),
                    "arealand_m2": float(p.get("AREALAND") or 0),
                    "lat": float(p["INTPTLAT"]) if p.get("INTPTLAT") else None,
                    "lon": float(p["INTPTLON"]) if p.get("INTPTLON") else None,
                }
            )
    df = pl.DataFrame(rows)
    out = PARQUET_DIR / "blocks"
    out.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out / "data.parquet", compression="zstd")
    print(
        f"  blocks: {df.height:,} (pop {df['pop'].sum():,}, housing units {df['housing_units'].sum():,})"
    )


def ingest_acs() -> None:
    cfg = analysis_config()["census"]
    vintage, state, county = cfg["acs_vintage"], cfg["state_fips"], cfg["county_fips"]
    raw = RAW_DIR / "census"
    out = PARQUET_DIR / "census_acs"
    out.mkdir(parents=True, exist_ok=True)
    n_tables = 0
    for table in cfg["tables"]:
        t = table.lower()
        data_path = raw / f"acs5_{vintage}_{t}_tract_{state}{county}.json"
        meta_path = raw / f"acs5_{vintage}_groups_{t}.json"
        if not data_path.exists() or not meta_path.exists():
            print(f"  skip {table}: not downloaded")
            continue
        labels = {
            k: v.get("label", "") for k, v in json.load(meta_path.open())["variables"].items()
        }
        data = json.load(data_path.open())
        header, body = data[0], data[1:]
        # The API repeats NAME (once from `get=NAME`, once inside group()); keep first.
        keep = [i for i, h in enumerate(header) if h not in header[:i]]
        header = [header[i] for i in keep]
        body = [[row[i] for i in keep] for row in body]
        wide = pl.DataFrame(body, schema=header, orient="row")
        id_cols = [c for c in ("NAME", "state", "county", "tract") if c in header]
        value_cols = [c for c in header if c.startswith(table) and c.endswith("E")]
        long = (
            wide.unpivot(index=id_cols, on=value_cols, variable_name="variable", value_name="value")
            .with_columns(
                (pl.col("state") + pl.col("county") + pl.col("tract")).alias("geoid"),
                pl.col("value").cast(pl.Float64, strict=False),
                pl.col("variable").replace_strict(labels, default=None).alias("label"),
                pl.lit(table).alias("table"),
                pl.lit(vintage).cast(pl.Int32).alias("vintage"),
            )
            .select("geoid", "table", "variable", "label", "value", "vintage")
        )
        # The API encodes suppressed/unavailable values as large negatives.
        long = long.with_columns(
            pl.when(pl.col("value") <= -222222222)
            .then(None)
            .otherwise(pl.col("value"))
            .alias("value")
        )
        long.write_parquet(out / f"{t}.parquet", compression="zstd")
        n_tables += 1
    print(f"  census_acs: {n_tables} tables")
