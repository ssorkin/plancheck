"""Socrata (data.lacity.org and other SODA portals) full-table exports.

The permit tables are republished wholesale on each refresh (every row carries the same
refresh timestamp), so incremental pulls buy nothing: each source is a single streamed
CSV export, validated afterwards against the portal's own `count(*)`. The export endpoint
honours ETag / Last-Modified, so `--refresh` costs one 304 when nothing changed.

Optional: set SOCRATA_APP_TOKEN (env or .env) to lift the anonymous throttle.
"""

from __future__ import annotations

import os
from pathlib import Path

from plancheck.acquire.base import NotData, download, get_json, retrying, update_extra
from plancheck.ahj.base import AHJ, SourceSpec

DATASET = "socrata"


def app_token() -> str | None:
    tok = os.environ.get("SOCRATA_APP_TOKEN", "").strip()
    if not tok:
        env_file = Path(__file__).resolve().parents[3] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "SOCRATA_APP_TOKEN":
                    tok = value.strip().strip("'\"")
    return tok or None


def _headers() -> dict:
    tok = app_token()
    return {"X-App-Token": tok} if tok else {}


def export_url(domain: str, dataset_id: str) -> str:
    return f"https://{domain}/api/views/{dataset_id}/rows.csv?accessType=DOWNLOAD"


def soda_count(domain: str, dataset_id: str, where: str | None = None) -> int:
    params = {"$select": "count(*)"}
    if where:
        params["$where"] = where
    data = retrying(
        lambda: get_json(f"https://{domain}/resource/{dataset_id}.json", params=params),
        label=f"count {dataset_id}",
    )
    return int(data[0]["count"])


def soda_metadata(domain: str, dataset_id: str) -> dict:
    d = get_json(f"https://{domain}/api/views/{dataset_id}.json")
    return {
        "name": d.get("name"),
        "rowsUpdatedAt": d.get("rowsUpdatedAt"),
        "viewLastModified": d.get("viewLastModified"),
        "attribution": d.get("attribution"),
    }


def _sniff_csv(first: bytes) -> None:
    head = first.lstrip()[:64].lower()
    if head.startswith((b"<html", b"<!doctype")):
        raise NotData("HTML served instead of CSV")
    if b"," not in first[:4096] and b"\n" not in first[:4096]:
        raise NotData("response does not look like CSV")


def filename_for(spec: SourceSpec) -> str:
    return f"{spec.slug}.csv"


def acquire_source(
    ahj: AHJ, spec: SourceSpec, refresh: bool = False, force: bool = False
) -> Path | None:
    assert spec.kind == "socrata" and spec.dataset_id and ahj.socrata_domain
    domain, did = ahj.socrata_domain, spec.dataset_id
    filename = filename_for(spec)
    print(f"{ahj.slug}/{spec.slug} ({did}): {spec.title}")
    path, status = download(
        DATASET,
        export_url(domain, did),
        filename,
        note=f"{ahj.slug} {spec.slug}: {spec.title}",
        headers=_headers(),
        throttle_seconds=2.0,
        force=force,
        refresh=refresh,
        sniff=_sniff_csv,
        extra={"ahj": ahj.slug, "source": spec.slug, "dataset_id": did},
    )
    if status == "downloaded":
        try:
            n = soda_count(domain, did)
            meta = soda_metadata(domain, did)
            update_extra(DATASET, filename, soda_count=n, soda_meta=meta)
            print(f"  portal reports {n:,} rows")
        except Exception as exc:  # noqa: BLE001 — verification is best-effort
            print(f"  WARNING could not fetch portal row count: {exc}")
    return path
