"""CSV export -> lossless all-varchar Parquet (permits_raw), hive-partitioned by year."""

from __future__ import annotations

import re
import shutil

import polars as pl

from plancheck.acquire.socrata import DATASET as SOCRATA_DATASET
from plancheck.acquire.socrata import filename_for
from plancheck.ahj.base import AHJ, SourceSpec
from plancheck.ingest.schema import to_date
from plancheck.paths import PARQUET_DIR, RAW_DIR


def norm_header(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def raw_dir(ahj: AHJ, spec: SourceSpec):
    return PARQUET_DIR / "permits_raw" / f"ahj={ahj.slug}" / f"source={spec.slug}"


def read_export_csv(path) -> pl.DataFrame:
    df = pl.read_csv(
        path,
        infer_schema=False,
        quote_char='"',
        encoding="utf8-lossy",
        truncate_ragged_lines=False,
    )
    return df.rename({c: norm_header(c) for c in df.columns})


def ingest_source(ahj: AHJ, spec: SourceSpec) -> int:
    src = RAW_DIR / SOCRATA_DATASET / filename_for(spec)
    if not src.exists():
        print(f"  skip {spec.slug}: {src} not downloaded")
        return 0
    df = read_export_csv(src)
    date_col = norm_header(spec.partition_date)
    if date_col not in df.columns:
        raise RuntimeError(f"{spec.slug}: partition column {date_col!r} not in {df.columns}")
    df = df.with_columns(to_date(date_col).dt.year().fill_null(0).cast(pl.Int32).alias("year"))
    out = raw_dir(ahj, spec)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for (year,), part in df.partition_by("year", as_dict=True).items():
        d = out / f"year={year}"
        d.mkdir()
        part.drop("year").write_parquet(d / "data.parquet", compression="zstd")
    print(
        f"  {spec.slug}: {df.height:,} rows, {len(df.columns)} cols, years "
        f"{df['year'].min()}–{df['year'].max()}"
    )
    return df.height
