"""Geocode stage: parse -> tier chain -> spatial enrichment -> permits_geo parquet."""

from __future__ import annotations

import shutil

import polars as pl

from plancheck.ahj.base import list_ahjs, select_sources
from plancheck.config import analysis_config
from plancheck.geocode.address import parse_location
from plancheck.geocode.strategy import Context, run_chain
from plancheck.paths import PARQUET_DIR


def _load_permits(ahj, specs) -> pl.DataFrame:
    frames = []
    for spec in specs:
        d = PARQUET_DIR / "permits" / f"ahj={ahj.slug}" / f"source={spec.slug}"
        if not d.exists():
            continue
        frames.append(
            pl.scan_parquet(d / "**" / "*.parquet", hive_partitioning=True)
            .select(
                "permit_id",
                "source_dataset",
                "source_family",
                "permit_ref",
                "address_raw",
                "zip",
                "lat_src",
                "lon_src",
                "latlon_type_src",
                "council_district_src",
                "tract_src",
                "cpa_src",
                "nc_src",
            )
            .collect()
        )
    if not frames:
        return pl.DataFrame()
    return pl.concat(frames, how="vertical_relaxed")


def _parse_all(permits: pl.DataFrame, default_city: str | None):
    raws = permits.select("address_raw", "zip").unique()
    queries = {}
    keys = {}
    for raw, zip_code in raws.iter_rows():
        q = parse_location(raw, default_zip=zip_code, default_city=default_city)
        queries[q.key] = q
        keys[(raw, zip_code)] = q.key
    key_series = [keys[(r, z)] for r, z in zip(permits["address_raw"], permits["zip"], strict=True)]
    return permits.with_columns(pl.Series("geocode_key", key_series, dtype=pl.Utf8)), queries


def run_geocode(
    ahj: str = "all",
    source: str = "all",
    limit: int | None = None,
    no_network: bool = False,
    dry_run: bool = False,
    compact: bool = False,
) -> None:
    cfg = analysis_config()["geocode"]
    for a in list_ahjs(ahj):
        if compact:
            from plancheck.geocode import cache

            for name in a.geocoders:
                print(f"  compacted {name}: {cache.compact(name):,} keys")
        specs = select_sources(a, source)
        permits = _load_permits(a, specs)
        if permits.is_empty():
            print(f"{a.slug}: nothing ingested for {source}")
            continue
        default_city = next(
            (g.get("default_city") for g in a.geocoders.values() if g.get("default_city")), None
        )
        permits, queries = _parse_all(permits, default_city)
        kinds = pl.Series([queries[k].kind for k in permits["geocode_key"]]).value_counts()
        print(
            f"{a.slug}: {permits.height:,} permits; parsed kinds: "
            + ", ".join(f"{r[0]}={r[1]:,}" for r in kinds.iter_rows())
        )
        ctx = Context(
            ahj=a,
            queries=queries,
            limit=limit,
            no_network=no_network,
            dry_run=dry_run,
            min_score=float(cfg["min_score"]),
            throttle_seconds=float(cfg["throttle_seconds"]),
        )
        resolved, counts = run_chain(a.build_tiers(), permits, ctx)
        total = permits.height
        print("  coverage: " + ", ".join(f"{k}={v:,} ({v / total:.1%})" for k, v in counts.items()))
        if dry_run:
            continue

        from plancheck.geocode.spatial import enrich

        print("  spatial joins …")
        geo = enrich(resolved, a)
        # Disagreement flags vs the source's own admin fields.
        src = permits.select(
            "permit_id",
            "source_dataset",
            "council_district_src",
            "tract_src",
            "cpa_src",
            "nc_src",
        )
        geo = geo.join(src, on=["permit_id", "source_dataset"], how="left")
        flags = []
        if "tract_geoid" in geo.columns:
            flags.append(
                (
                    pl.col("tract_geoid").is_not_null()
                    & pl.col("tract_src").is_not_null()
                    & (pl.col("tract_geoid").str.slice(5) != pl.col("tract_src"))
                ).alias("tract_disagrees")
            )
        if "council_district" in geo.columns:
            flags.append(
                (
                    pl.col("council_district").is_not_null()
                    & pl.col("council_district_src").is_not_null()
                    & (pl.col("council_district") != pl.col("council_district_src"))
                ).alias("cd_disagrees")
            )
        if flags:
            geo = geo.with_columns(flags)
        geo = geo.drop("council_district_src", "tract_src", "cpa_src", "nc_src")

        for spec in specs:
            part = geo.filter(pl.col("source_dataset") == spec.slug)
            if part.is_empty():
                continue
            d = PARQUET_DIR / "permits_geo" / f"ahj={a.slug}" / f"source={spec.slug}"
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True)
            part.write_parquet(d / "data.parquet", compression="zstd")
        print(f"  wrote permits_geo for {len(specs)} source(s)")
    from plancheck.ingest import db

    db.build()


def geocode_one(text: str, ahj: str = "la_city", geocoder: str = "") -> None:
    from plancheck.ahj.base import load_ahj
    from plancheck.geocode.arcgis_locator import ArcgisLocator
    from plancheck.geocode.base import accept

    a = load_ahj(ahj)
    default_city = next(
        (g.get("default_city") for g in a.geocoders.values() if g.get("default_city")), None
    )
    q = parse_location(text, default_city=default_city)
    print(
        f"parsed: kind={q.kind} number={q.number} street={q.street!r} street2={q.street2!r} "
        f"cross={q.cross_street!r} alts={q.number_alt} zip={q.zip} relation={q.relation!r} "
        f"reason={q.reason}\n  key={q.key}"
    )
    if q.kind == "unparsed":
        return
    cfg = analysis_config()["geocode"]
    for name, gcfg in a.geocoders.items():
        if geocoder and name != geocoder:
            continue
        loc = ArcgisLocator.from_config(name, gcfg)
        r = loc.geocode([q])[0]
        ok, reason = accept(q, r, a.bbox, float(gcfg.get("min_score", cfg["min_score"])))
        print(
            f"{name}: status={r.status} score={r.score} type={r.match_type} "
            f"lat={r.lat} lon={r.lon} -> {'ACCEPT' if ok else 'REJECT ' + reason}\n"
            f"  matched: {r.matched_address}"
        )
