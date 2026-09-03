"""Ingest orchestration."""

from __future__ import annotations

from plancheck.ahj.base import list_ahjs, select_sources


def run_ingest(ahj: str = "all", source: str = "all", family: str = "all") -> None:
    from plancheck.ingest import db

    for a in list_ahjs(ahj):
        if family in ("all", "permits"):
            from plancheck.ingest.csv_raw import ingest_source
            from plancheck.ingest.permits import normalize_source

            for spec in select_sources(a, source):
                print(f"{a.slug}/{spec.slug}")
                if ingest_source(a, spec):
                    normalize_source(a, spec)
        if family in ("all", "geometries"):
            from plancheck.ingest.geometries import ingest_geometries

            ingest_geometries(a)
        if family in ("all", "reference"):
            from plancheck.ingest.reference import ingest_layers

            ingest_layers(a)
    if family in ("all", "census"):
        from plancheck.ingest.census import ingest_acs, ingest_tracts

        ingest_tracts()
        ingest_acs()
    db.build()
