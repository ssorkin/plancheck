"""permits_raw -> normalized permits parquet via the AHJ's mapper."""

from __future__ import annotations

import shutil

import polars as pl

from plancheck.ahj.base import AHJ, SourceSpec
from plancheck.ingest.csv_raw import norm_header, raw_dir
from plancheck.ingest.schema import conform
from plancheck.paths import PARQUET_DIR


def permits_dir(ahj: AHJ, spec: SourceSpec):
    return PARQUET_DIR / "permits" / f"ahj={ahj.slug}" / f"source={spec.slug}"


def normalize_source(ahj: AHJ, spec: SourceSpec) -> int:
    src = raw_dir(ahj, spec)
    if not src.exists():
        print(f"  skip {spec.slug}: no permits_raw")
        return 0
    lf = pl.scan_parquet(src / "**" / "*.parquet", hive_partitioning=True)
    mapper = ahj.mapper(spec)
    mapped = mapper(lf, spec)
    date_col = norm_header(spec.partition_date)
    # Reattach the partition year from the raw table (same row order).
    year = lf.select(pl.col("year").cast(pl.Int32)).collect()["year"]
    df = conform(mapped).collect().with_columns(year)
    dup = df.height - df.select("permit_id").n_unique()
    if dup:
        print(f"  WARNING {spec.slug}: {dup:,} duplicate permit_id rows (kept)")
    out = permits_dir(ahj, spec)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for (year_val,), part in df.partition_by("year", as_dict=True).items():
        d = out / f"year={year_val}"
        d.mkdir()
        part.drop("year").write_parquet(d / "data.parquet", compression="zstd")
    n_loc = df.filter(pl.col("lat_src").is_not_null()).height
    print(
        f"  {spec.slug}: {df.height:,} permits ({date_col}); "
        f"source coords on {n_loc / max(df.height, 1):.1%}"
    )
    return df.height
