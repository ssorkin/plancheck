"""Permit detail store for the map's click-through pages.

One Parquet file (data/export/detail/permits.parquet) with every issued permit from the
configured start year, sorted by H3 r9 cell so nearby permits share row groups, plus one
index per geography (detail/index_<geo>.json: area id -> row-group numbers). A browser
fetches the index, then only those row groups via HTTP range requests, and filters by the
area id column; the file itself is never downloaded whole.
"""

from __future__ import annotations

import json

import duckdb

from plancheck.analysis.export import GEOGRAPHIES
from plancheck.analysis.intensity import GEOGRAPHIES as GEO_COLS
from plancheck.analysis.intensity import completions_sql, dedup_issued_sql
from plancheck.config import analysis_config
from plancheck.ingest.db import connect
from plancheck.paths import EXPORT_DIR

ROW_GROUP = 8192
WORK_DESC_MAX = 200
GEO_SLUGS = list(GEOGRAPHIES) + ["hex_r8"]
COL_KEY = {"hex_r8": "h3_r8"}  # export slug -> intensity geography key


def detail_sql() -> str:
    cfg = analysis_config()["intensity"]
    new = ", ".join(f"'{t}'" for t in cfg["new_building_types"])
    add = ", ".join(f"'{t}'" for t in cfg["addition_types"])
    demo = ", ".join(f"'{t}'" for t in cfg["demolition_types"])
    geo_cols = ", ".join(f"i.{GEO_COLS[COL_KEY.get(s, s)]} AS g_{s}" for s in GEO_SLUGS)
    return f"""
    SELECT {geo_cols},
           i.permit_id, i.permit_class, i.permit_type, i.permit_subtype, i.status,
           i.issue_date, i.final_date, i.year, c.year AS completed_year,
           i.address_raw AS address, i.valuation,
           i.dwelling_units_change AS du,
           left(i.work_desc, {WORK_DESC_MAX}) AS work_desc,
           round(i.lat, 5) AS lat, round(i.lon, 5) AS lon, i.source_url,
           (i.permit_type IN ({new})) AS is_new_building,
           (i.permit_type IN ({add})) AS is_addition,
           (i.permit_type IN ({demo})) AS is_demolition,
           coalesce(i.adu_changed, false) AS is_adu,
           coalesce(i.solar, false) AS is_solar,
           coalesce(i.ev, false) AS is_ev,
           (c.permit_id IS NOT NULL) AS is_completed
    FROM issued i
    LEFT JOIN completions c ON c.ahj = i.ahj AND c.permit_id = i.permit_id
    WHERE i.lat IS NOT NULL
    ORDER BY i.h3_r9, i.issue_date
    """


def export_detail(con: duckdb.DuckDBPyConnection | None = None) -> dict[str, int]:
    own = con is None
    con = con or connect(read_only=True)
    con.execute(f"CREATE OR REPLACE TEMP VIEW issued AS {dedup_issued_sql()}")
    con.execute(f"CREATE OR REPLACE TEMP VIEW completions AS {completions_sql()}")
    out_dir = EXPORT_DIR / "detail"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "permits.parquet"
    con.execute(
        f"COPY ({detail_sql()}) TO '{path}' "
        f"(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {ROW_GROUP})"
    )
    n = con.execute(f"SELECT count(*) FROM read_parquet('{path}')").fetchone()[0]
    print(f"  detail/permits.parquet: {n:,} permits, {path.stat().st_size / 1e6:.1f} MB")
    # Row-group membership per geography, from the parquet metadata (row groups are
    # written in order, so group k covers rows [k*ROW_GROUP, (k+1)*ROW_GROUP)).
    counts: dict[str, int] = {"permits": n}
    for slug in GEO_SLUGS:
        rows = con.execute(
            f"""
            SELECT g_{slug} AS id, list_sort(list_distinct(list(rg))) AS groups, count(*) AS n
            FROM (SELECT g_{slug}, (row_number() OVER () - 1) // {ROW_GROUP} AS rg
                  FROM read_parquet('{path}'))
            WHERE g_{slug} IS NOT NULL GROUP BY 1
            """
        ).fetchall()
        index = {str(i): [int(g) for g in groups] for i, groups, _n in rows}
        (out_dir / f"index_{slug}.json").write_text(json.dumps(index, separators=(",", ":")))
        avg = sum(len(v) for v in index.values()) / max(len(index), 1)
        counts[slug] = len(index)
        print(f"  index_{slug}.json: {len(index):,} areas, {avg:.1f} row groups each on average")
    (out_dir / "meta.json").write_text(
        json.dumps({"row_group": ROW_GROUP, "rows": n, "geographies": GEO_SLUGS})
    )
    if own:
        con.close()
    return counts
