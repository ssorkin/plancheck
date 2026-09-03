"""Persistent geocode cache: append-only parquet parts under geocode_cache/geocoder=<name>/.

Each locator run appends one part file (crash-safe, never rewrites); readers dedupe by key
keeping the latest `geocoded_at`. `pc geocode --compact` merges the parts.
"""

from __future__ import annotations

import shutil
from datetime import UTC, datetime

import polars as pl

from plancheck.geocode.base import GeocodeResult
from plancheck.paths import PARQUET_DIR

SCHEMA = {
    "key": pl.Utf8, "geocoder": pl.Utf8, "status": pl.Utf8, "lat": pl.Float64,
    "lon": pl.Float64, "score": pl.Float64, "match_type": pl.Utf8,
    "matched_address": pl.Utf8, "geocoded_at": pl.Utf8,
}


def cache_dir(geocoder: str):
    return PARQUET_DIR / "geocode_cache" / f"geocoder={geocoder}"


def load(geocoder: str) -> pl.DataFrame:
    d = cache_dir(geocoder)
    parts = sorted(d.glob("*.parquet")) if d.exists() else []
    if not parts:
        return pl.DataFrame(schema=SCHEMA)
    df = pl.concat([pl.read_parquet(p) for p in parts], how="vertical_relaxed")
    return (
        df.sort("geocoded_at")
        .unique(subset=["key"], keep="last", maintain_order=True)
        .select(list(SCHEMA))
    )


def append(geocoder: str, results: list[GeocodeResult]) -> None:
    if not results:
        return
    d = cache_dir(geocoder)
    d.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame([r.__dict__ for r in results], schema=SCHEMA)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f")
    df.write_parquet(d / f"part-{stamp}.parquet", compression="zstd")


def compact(geocoder: str) -> int:
    df = load(geocoder)
    d = cache_dir(geocoder)
    if d.exists():
        shutil.rmtree(d)
    if df.is_empty():
        return 0
    d.mkdir(parents=True)
    df.write_parquet(d / "part-compacted.parquet", compression="zstd")
    return df.height
