"""Data-quality checks over the store. Each returns Finding rows; nothing is patched."""

from __future__ import annotations

from dataclasses import dataclass, field

import duckdb

from plancheck.acquire.base import load_manifest, sha256_file
from plancheck.ahj.base import list_ahjs
from plancheck.paths import DUCKDB_PATH, PARQUET_DIR, RAW_DIR


@dataclass
class Finding:
    check: str
    severity: str  # info | warning | anomaly
    scope: str | None
    message: str
    details: dict = field(default_factory=dict)


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(DUCKDB_PATH), read_only=True)


def _has_view(con, name: str) -> bool:
    return bool(
        con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]
        ).fetchone()[0]
    )


def check_manifest_hashes(verify: bool = False) -> list[Finding]:
    out: list[Finding] = []
    for path in sorted((RAW_DIR.parent.parent / "manifests").glob("*.json")):
        dataset = path.stem
        for filename, entry in load_manifest(dataset).items():
            f = RAW_DIR / dataset / filename
            if not f.exists():
                out.append(Finding("manifest", "warning", dataset, f"{filename}: file missing"))
                continue
            if f.stat().st_size != entry["size"]:
                out.append(
                    Finding(
                        "manifest",
                        "anomaly",
                        dataset,
                        f"{filename}: size {f.stat().st_size:,} != manifest {entry['size']:,}",
                    )
                )
            elif verify and sha256_file(f) != entry["sha256"]:
                out.append(Finding("manifest", "anomaly", dataset, f"{filename}: sha256 mismatch"))
    if not out:
        out.append(Finding("manifest", "info", None, "all manifest entries present and sized"))
    return out


def check_row_counts() -> list[Finding]:
    """Ingested rows per source vs the portal's own count(*) at download time."""
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits_raw"):
        return [Finding("row_counts", "warning", None, "permits_raw view missing")]
    counts = dict(con.execute("SELECT source, count(*) FROM permits_raw GROUP BY 1").fetchall())
    manifest = load_manifest("socrata")
    for a in list_ahjs():
        for spec in a.sources.values():
            entry = manifest.get(f"{spec.slug}.csv")
            n = counts.get(spec.slug)
            if n is None:
                continue
            portal = (entry or {}).get("extra", {}).get("soda_count")
            if portal is None:
                out.append(
                    Finding("row_counts", "info", spec.slug, f"{n:,} rows (no portal count)")
                )
            elif portal != n:
                out.append(
                    Finding(
                        "row_counts",
                        "anomaly",
                        spec.slug,
                        f"{n:,} ingested rows vs {portal:,} reported by the portal",
                    )
                )
            else:
                out.append(Finding("row_counts", "info", spec.slug, f"{n:,} rows = portal count"))
    con.close()
    return out


def check_permit_id_unique() -> list[Finding]:
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits_norm"):
        return out
    rows = con.execute(
        "SELECT source_dataset, count(*) - count(DISTINCT permit_id) AS dup "
        "FROM permits_norm GROUP BY 1 HAVING dup > 0"
    ).fetchall()
    for src, dup in rows:
        out.append(Finding("permit_id_unique", "warning", src, f"{dup:,} duplicate permit_id rows"))
    overlap = con.execute(
        """
        SELECT source_family, count(*) FROM (
          SELECT source_family, permit_id FROM permits_norm
          GROUP BY 1, 2 HAVING count(DISTINCT source_dataset) > 1)
        GROUP BY 1
        """
    ).fetchall()
    for fam, n in overlap:
        out.append(
            Finding(
                "permit_id_unique",
                "info",
                fam,
                f"{n:,} permit_ids appear in more than one era dataset of this family",
            )
        )
    if not out:
        out.append(
            Finding("permit_id_unique", "info", None, "permit_id unique within every source")
        )
    con.close()
    return out


def check_coord_coverage() -> list[Finding]:
    """Share of permits without source coordinates, per source and year (>5% flagged,
    one warning per source listing the affected years)."""
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits_norm"):
        return out
    rows = con.execute(
        """
        SELECT source_dataset, year, count(*) AS n,
               sum(CASE WHEN lat_src IS NULL THEN 1 ELSE 0 END) AS missing
        FROM permits_norm WHERE source_family <> 'boe_permits' AND year > 0
        GROUP BY 1, 2 HAVING n >= 500 ORDER BY 1, 2
        """
    ).fetchall()
    by_src: dict[str, list[tuple[int, float]]] = {}
    for src, year, n, missing in rows:
        if missing / n > 0.05:
            by_src.setdefault(src, []).append((year, missing / n))
    for src, years in by_src.items():
        out.append(
            Finding(
                "coord_coverage",
                "warning",
                src,
                f">5% of permits lack source coordinates in {len(years)} year(s) "
                f"{years[0][0]}–{years[-1][0]} (max {max(s for _, s in years):.0%}); "
                "these rows go through the locator chain",
            )
        )
    if not out:
        out.append(
            Finding(
                "coord_coverage",
                "info",
                None,
                "no source-year with >5% missing source coordinates",
            )
        )
    con.close()
    return out


def check_geocode_rates() -> list[Finding]:
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits_geo"):
        return [Finding("geocode_rates", "info", None, "not geocoded yet (run `pc geocode`)")]
    rows = con.execute(
        """
        SELECT source_dataset, geocode_method, count(*) FROM permits_geo GROUP BY 1, 2 ORDER BY 1, 3 DESC
        """
    ).fetchall()
    by_src: dict[str, dict[str, int]] = {}
    for src, method, n in rows:
        by_src.setdefault(src, {})[method] = n
    for src, methods in by_src.items():
        total = sum(methods.values())
        none = methods.get("none", 0)
        sev = "warning" if none / total > 0.05 else "info"
        out.append(
            Finding(
                "geocode_rates",
                sev,
                src,
                f"{1 - none / total:.1%} located: "
                + ", ".join(f"{m}={n:,}" for m, n in methods.items()),
            )
        )
    reasons = con.execute(
        "SELECT geocode_reason, count(*) FROM permits_geo WHERE geocode_method='none' "
        "GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    if reasons:
        out.append(
            Finding(
                "geocode_rates",
                "info",
                None,
                "unlocated by reason: " + ", ".join(f"{r}={n:,}" for r, n in reasons),
            )
        )
    con.close()
    return out


def check_admin_disagreement() -> list[Finding]:
    """Spatial join vs the source's own tract / council-district field, by year.

    Old records carry the tract and district vintage in force when they were processed, so
    disagreement is expected to step down at each redistricting (2012, 2022) and at the
    2020 tract release; it is reported as one warning per field listing the years above
    10%, plus the full series as info."""
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits"):
        return out
    cols = {r[1] for r in con.execute("PRAGMA table_info('permits')").fetchall()}
    for flag, label in (("tract_disagrees", "census tract"), ("cd_disagrees", "council district")):
        if flag not in cols:
            continue
        rows = con.execute(
            f"""
            SELECT year, count(*) AS n, sum(CASE WHEN {flag} THEN 1 ELSE 0 END) AS d
            FROM permits WHERE {flag} IS NOT NULL AND lat IS NOT NULL
              AND source_family <> 'boe_permits' AND year > 0
            GROUP BY 1 HAVING n >= 1000 ORDER BY 1
            """
        ).fetchall()
        if not rows:
            continue
        high = [(y, d / n) for y, n, d in rows if d / n > 0.10]
        if high:
            out.append(
                Finding(
                    "admin_disagreement",
                    "warning",
                    label,
                    f"spatial join disagrees with the source field on >10% of located permits "
                    f"in {len(high)} year(s): {high[0][0]}–{high[-1][0]} "
                    f"(max {max(s for _, s in high):.0%}); expected where the source vintage "
                    "predates the current boundaries — see known_issues",
                )
            )
        series = ", ".join(f"{y}: {d / n:.1%}" for y, n, d in rows[-8:])
        out.append(Finding("admin_disagreement", "info", label, f"recent years — {series}"))
    con.close()
    return out


def check_date_sanity() -> list[Finding]:
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits_norm"):
        return out
    n_future = con.execute(
        "SELECT count(*) FROM permits_norm WHERE issue_date > current_date + INTERVAL 7 DAY"
    ).fetchone()[0]
    if n_future:
        out.append(
            Finding("date_sanity", "warning", None, f"{n_future:,} issue dates in the future")
        )
    n_order = con.execute(
        "SELECT count(*) FROM permits_norm WHERE issue_date < submitted_date"
    ).fetchone()[0]
    if n_order:
        out.append(
            Finding(
                "date_sanity",
                "info",
                None,
                f"{n_order:,} permits issued before their submitted date",
            )
        )
    n_year0 = con.execute("SELECT count(*) FROM permits_norm WHERE year = 0").fetchone()[0]
    if n_year0:
        out.append(
            Finding(
                "date_sanity", "info", None, f"{n_year0:,} permits have no partition date (year=0)"
            )
        )
    con.close()
    return out


def check_valuation_outliers() -> list[Finding]:
    out: list[Finding] = []
    con = _con()
    if not _has_view(con, "permits_norm"):
        return out
    rows = con.execute(
        "SELECT permit_id, source_dataset, valuation, address_raw FROM permits_norm "
        "WHERE valuation IS NOT NULL ORDER BY valuation DESC LIMIT 5"
    ).fetchall()
    if rows:
        out.append(
            Finding(
                "valuation_outliers",
                "info",
                None,
                "largest declared valuations (kept as published)",
                {"examples": [f"{v:,.0f} — {p} ({s}) {a}" for p, s, v, a in rows]},
            )
        )
    con.close()
    return out


ALL_CHECKS = [
    check_row_counts,
    check_permit_id_unique,
    check_coord_coverage,
    check_geocode_rates,
    check_admin_disagreement,
    check_date_sanity,
    check_valuation_outliers,
]

__all__ = ["ALL_CHECKS", "PARQUET_DIR", "Finding", "check_manifest_hashes"]
