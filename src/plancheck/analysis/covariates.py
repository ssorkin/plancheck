"""Tract-level covariates derived from the permits themselves and the joined layers:
zoning mix, HPOZ share, rail proximity, and (when present) the assessor roll."""

from __future__ import annotations

import polars as pl

from plancheck.ingest.db import connect


def tract_context() -> pl.DataFrame:
    """Per tract: dominant zoning category, share of permits inside an HPOZ, share within
    800 m of rail — computed over located issued permits since 2013 (the permits are the
    sampling frame, so this describes where activity happens, not the tract's land)."""
    con = connect(read_only=True)
    cols = {r[1] for r in con.execute("PRAGMA table_info('permits')").fetchall()}
    sel = ["tract_geoid", "count(*) AS n"]
    if "zoning_category" in cols:
        sel.append("mode(zoning_category) AS zoning_mode")
    if "hpoz" in cols:
        sel.append("avg(CASE WHEN hpoz THEN 1.0 ELSE 0.0 END) AS hpoz_share")
    if "dist_rail_m" in cols:
        sel.append("avg(CASE WHEN dist_rail_m <= 800 THEN 1.0 ELSE 0.0 END) AS near_rail_share")
        sel.append("median(dist_rail_m) AS dist_rail_median_m")
    df = con.execute(
        f"SELECT {', '.join(sel)} FROM permits WHERE record_kind='issued' AND tract_geoid IS NOT NULL "
        "AND year >= 2013 GROUP BY 1"
    ).pl()
    con.close()
    return df
