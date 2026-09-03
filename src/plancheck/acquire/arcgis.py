"""Paginated ArcGIS REST layer downloads to newline-delimited GeoJSON (GeoJSONL).

Used for the AHJ's own permit geometries (hundreds of thousands of features across
dozens of MapServer sublayers), administrative boundaries and covariate layers. Pages are
ordered by the layer's OID field (unordered resultOffset paging can skip or repeat
features), written page-by-page to a .part file with a progress sidecar so an
interrupted run resumes, and the final line count must equal the server's own count
before anything is recorded in the manifest. 5xx and timeouts are retried with backoff;
maps.lacity.org answers 502 now and then.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from plancheck.acquire.base import (
    ManifestEntry,
    get_json,
    is_cached,
    load_manifest,
    now_iso,
    record,
    retrying,
    sha256_file,
)
from plancheck.paths import RAW_DIR


def layer_info(layer_url: str) -> dict:
    return retrying(lambda: get_json(layer_url, {"f": "json"}), label=f"meta {layer_url}")


def layer_count(layer_url: str, where: str = "1=1") -> int:
    data = retrying(
        lambda: get_json(
            f"{layer_url}/query", {"where": where, "returnCountOnly": "true", "f": "json"}
        ),
        label=f"count {layer_url}",
    )
    return int(data["count"])


def oid_field(info: dict) -> str:
    for f in info.get("fields") or []:
        if f.get("type") == "esriFieldTypeOID":
            return f["name"]
    return info.get("objectIdField") or "OBJECTID"


def assert_fields(info: dict, names: list[str], layer_url: str) -> None:
    have = {f["name"] for f in info.get("fields") or []}
    missing = [n for n in names if n and n != "*" and n not in have]
    if missing:
        raise RuntimeError(
            f"layer {layer_url} lacks field(s) {missing}; have {sorted(have)}. "
            "Update config/sources.yaml (the upstream schema changed)."
        )


def fetch_layer_jsonl(
    dataset: str,
    name: str,
    layer_url: str,
    out_fields: str = "*",
    where: str = "1=1",
    order_by: str | None = None,
    page_size: int | None = None,
    return_geometry: bool = True,
    geometry_precision: int = 6,
    force: bool = False,
    refresh: bool = False,
    note: str = "",
) -> Path | None:
    """Download one layer as data/raw/<dataset>/<name>.geojsonl (+ <name>_meta.json).

    `refresh` re-downloads only when the server's feature count differs from the
    manifest's recorded count (ArcGIS layers carry no ETag).
    """
    dest_dir = RAW_DIR / dataset
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.geojsonl"
    tmp = dest.with_suffix(".geojsonl.part")
    progress = dest.with_suffix(".progress.json")

    info = layer_info(layer_url)
    if "error" in info:
        raise RuntimeError(f"{layer_url}: {info['error']}")
    (dest_dir / f"{name}_meta.json").write_text(json.dumps(info, indent=1))
    page_size = page_size or min(int(info.get("maxRecordCount") or 1000), 2000)
    order_by = order_by or oid_field(info)
    fields = [f.strip() for f in out_fields.split(",")] if out_fields != "*" else []
    assert_fields(info, [*fields, order_by], layer_url)

    expected = layer_count(layer_url, where)
    cached = is_cached(dataset, dest.name)
    if cached and not force:
        prev = load_manifest(dataset)[dest.name].get("extra", {}).get("count")
        if not refresh or prev == expected:
            if refresh:
                print(f"  unchanged {dest.name} ({expected:,} features)")
            return dest
        print(f"  {dest.name}: server count {expected:,} != cached {prev:,}; re-downloading")

    params = {
        "where": where,
        "outFields": out_fields,
        "orderByFields": order_by,
        "returnGeometry": "true" if return_geometry else "false",
        "f": "geojson",
        "outSR": 4326,
        "geometryPrecision": geometry_precision,
        "resultRecordCount": page_size,
    }

    offset, written = 0, 0
    if progress.exists() and tmp.exists() and not force:
        state = json.loads(progress.read_text())
        if state.get("expected") == expected and state.get("page_size") == page_size:
            offset, written = state["offset"], state["written"]
            print(f"  resuming {dest.name} at offset {offset:,}")
    if offset == 0:
        tmp.unlink(missing_ok=True)

    with tmp.open("a") as f:
        while True:
            page = retrying(
                lambda o=offset: get_json(f"{layer_url}/query", {**params, "resultOffset": o}),
                label=f"{name} offset {offset}",
            )
            feats = page.get("features", [])
            for feat in feats:
                f.write(json.dumps(feat, separators=(",", ":")) + "\n")
            written += len(feats)
            offset += len(feats)
            f.flush()
            progress.write_text(
                json.dumps(
                    {
                        "offset": offset,
                        "written": written,
                        "expected": expected,
                        "page_size": page_size,
                    }
                )
            )
            more = page.get("exceededTransferLimit") or (page.get("properties") or {}).get(
                "exceededTransferLimit"
            )
            if not feats or (len(feats) < page_size and not more):
                break
            if written % (page_size * 25) == 0:
                print(f"    {name}: {written:,}/{expected:,}", flush=True)

    if written != expected:
        print(
            f"  FAILED {dest.name}: wrote {written:,} features but server reports {expected:,}"
            " (left .part in place; rerun to resume)"
        )
        return None
    tmp.replace(dest)
    progress.unlink(missing_ok=True)
    record(
        dataset,
        ManifestEntry(
            dataset=dataset,
            filename=dest.name,
            url=f"{layer_url}/query",
            sha256=sha256_file(dest),
            size=dest.stat().st_size,
            downloaded_at=now_iso(),
            note=note or f"{written} features, layer {info.get('name')!r}",
            extra={
                "count": written,
                "layer_name": info.get("name"),
                "where": where,
                "out_fields": out_fields,
            },
        ),
    )
    print(f"  ok {dest.name} ({written:,} features, {dest.stat().st_size:,} bytes)")
    return dest


def mapserver_sublayers(service_url: str, name_regex: str) -> list[tuple[int, str]]:
    info = retrying(lambda: get_json(service_url, {"f": "json"}), label="service meta")
    pat = re.compile(name_regex)
    return [(lyr["id"], lyr["name"]) for lyr in info.get("layers", []) if pat.search(lyr["name"])]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
