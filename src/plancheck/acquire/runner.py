"""Acquisition orchestration across AHJs and source families."""

from __future__ import annotations

from plancheck.ahj.base import AHJ, list_ahjs, select_sources


def show_sources(ahj: str = "all") -> None:
    from plancheck.acquire.base import load_manifest
    from plancheck.acquire.socrata import DATASET, filename_for
    from plancheck.paths import PARQUET_DIR

    manifest = load_manifest(DATASET)
    for a in list_ahjs(ahj):
        print(f"{a.slug}: {a.name}  (chain: {' → '.join(a.chain)})")
        for spec in a.sources.values():
            entry = manifest.get(filename_for(spec)) if spec.kind == "socrata" else None
            raw = "raw " + entry["downloaded_at"][:10] if entry else "raw -"
            n = (entry or {}).get("extra", {}).get("soda_count")
            pq = PARQUET_DIR / "permits" / f"ahj={a.slug}" / f"source={spec.slug}"
            ing = "parquet ✓" if pq.exists() else "parquet -"
            print(f"  {spec.slug:38s} {spec.kind:8s} {raw:16s} {ing}  {n or ''}")


def acquire_permits(a: AHJ, source: str, refresh: bool, force: bool) -> None:
    from plancheck.acquire.socrata import acquire_source

    for spec in select_sources(a, source):
        if spec.kind == "socrata":
            acquire_source(a, spec, refresh=refresh, force=force)
        else:
            print(f"  skip {spec.slug}: unsupported kind {spec.kind}")


def acquire_geometries(a: AHJ, refresh: bool, force: bool) -> None:
    from plancheck.acquire.arcgis import fetch_layer_jsonl, mapserver_sublayers, slugify

    for gname, g in a.geometries.items():
        dataset = f"{a.slug}_{gname}"
        print(f"{a.slug}/{gname}: {g['url']}")
        if g["kind"] != "arcgis_mapserver":
            print(f"  skip: unsupported kind {g['kind']}")
            continue
        failed = []
        for layer_id, layer_name in mapserver_sublayers(g["url"], g["layer_name_regex"]):
            try:
                fetch_layer_jsonl(
                    dataset,
                    f"layer_{layer_id:02d}_{slugify(layer_name)}",
                    f"{g['url']}/{layer_id}",
                    out_fields=g.get("out_fields", "*"),
                    order_by=g.get("order_by"),
                    refresh=refresh,
                    force=force,
                )
            except Exception as exc:  # noqa: BLE001 — one bad sublayer must not stop the rest
                print(f"  FAILED layer {layer_id} {layer_name!r}: {exc}")
                failed.append(layer_id)
        if failed:
            print(f"  {gname}: {len(failed)} layer(s) failed: {failed} (rerun to retry)")


def _acquire_layers(a: AHJ, layers: dict, dataset: str, refresh: bool, force: bool) -> None:
    from plancheck.acquire.arcgis import fetch_layer_jsonl

    for name, spec in layers.items():
        print(f"{a.slug}/{dataset}/{name}: {spec['url']}")
        try:
            fetch_layer_jsonl(
                f"{a.slug}_{dataset}",
                name,
                spec["url"],
                out_fields=spec.get("out_fields", "*"),
                where=spec.get("where", "1=1"),
                order_by=spec.get("order_by"),
                return_geometry=spec.get("geometry", True),
                refresh=refresh,
                force=force,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {name}: {exc}")


def run_acquire(
    ahj: str = "all",
    source: str = "all",
    family: str = "all",
    refresh: bool = False,
    force: bool = False,
) -> None:
    fam = family
    for a in list_ahjs(ahj):
        if fam in ("all", "permits"):
            acquire_permits(a, source, refresh, force)
        if fam in ("all", "geometries"):
            acquire_geometries(a, refresh, force)
        if fam in ("all", "reference"):
            _acquire_layers(a, a.reference, "reference", refresh, force)
        if fam in ("all", "covariates"):
            _acquire_layers(a, a.covariates, "covariates", refresh, force)
    if fam in ("all", "tiger"):
        from plancheck.acquire.tiger import acquire as acquire_tiger

        acquire_tiger(refresh=refresh, force=force)
    if fam in ("all", "census"):
        from plancheck.acquire.census import acquire as acquire_census

        acquire_census()
