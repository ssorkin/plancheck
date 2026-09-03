"""Shared download machinery: HTTP client, streaming downloads, provenance manifests.

Every downloaded file gets a manifest entry (manifests/<dataset>.json) recording the exact
URL, size, SHA-256, timestamps and validators (ETag / Last-Modified), so any published
number can be traced back to a byte-identical source file. Downloads are idempotent: a
file whose manifest entry and on-disk size match is skipped unless `refresh` (conditional
re-fetch: one 304 when upstream is unchanged) or `force`.
"""

from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from plancheck.paths import MANIFEST_DIR, RAW_DIR

USER_AGENT = (
    "plancheck/0.1 (open-source permits data project; "
    "https://github.com/ssorkin/plancheck; ssorkin@gmail.com)"
)

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(30.0, read=600.0),
            follow_redirects=True,
        )
    return _client


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class ManifestEntry:
    dataset: str
    filename: str
    url: str
    sha256: str
    size: int
    downloaded_at: str
    etag: str = ""
    last_modified: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)


def _manifest_path(dataset: str) -> Path:
    return MANIFEST_DIR / f"{dataset}.json"


def load_manifest(dataset: str) -> dict[str, dict]:
    path = _manifest_path(dataset)
    return json.loads(path.read_text()) if path.exists() else {}


def save_manifest(dataset: str, manifest: dict[str, dict]) -> None:
    """Atomic write (tmp + rename) of the dataset's manifest."""
    path = _manifest_path(dataset)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(dict(sorted(manifest.items())), indent=2) + "\n")
    tmp.replace(path)


def record(dataset: str, entry: ManifestEntry) -> None:
    manifest = load_manifest(dataset)
    manifest[entry.filename] = entry.__dict__
    save_manifest(dataset, manifest)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def is_cached(dataset: str, filename: str) -> bool:
    entry = load_manifest(dataset).get(filename)
    dest = RAW_DIR / dataset / filename
    return bool(entry) and dest.exists() and dest.stat().st_size == entry["size"]


class NotData(RuntimeError):
    """The server answered 200 with something that is not the requested data."""


def retrying(fn, attempts: int = 5, base: float = 2.0, label: str = ""):
    """Call fn() with exponential backoff on HTTP/network errors (5xx and timeouts)."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except (httpx.HTTPError, RuntimeError) as exc:
            last = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            delay = base * (2**attempt) + random.uniform(0, 1)
            print(f"  retry {attempt + 1}/{attempts} {label}: {exc} (sleep {delay:.0f}s)")
            time.sleep(delay)
    assert last is not None
    raise last


def download(
    dataset: str,
    url: str,
    filename: str,
    note: str = "",
    headers: dict | None = None,
    throttle_seconds: float = 1.0,
    force: bool = False,
    refresh: bool = False,
    sniff=None,
    extra: dict | None = None,
) -> tuple[Path | None, str]:
    """Stream-download url into data/raw/<dataset>/<filename> and record a manifest entry.

    Returns (path, status) where status is one of "cached", "not_modified", "downloaded",
    "failed". `refresh` sends If-None-Match / If-Modified-Since from the manifest.
    `sniff(first_bytes)` may raise NotData to reject block/error pages served with 200.
    The previous file and manifest entry are left untouched on failure.
    """
    dest_dir = RAW_DIR / dataset
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename

    manifest = load_manifest(dataset)
    entry = manifest.get(filename)
    cached = bool(entry) and dest.exists() and dest.stat().st_size == entry["size"]
    if cached and not force and not refresh:
        return dest, "cached"

    req_headers = dict(headers or {})
    if cached and refresh and not force:
        if entry.get("etag"):
            req_headers["If-None-Match"] = entry["etag"]
        if entry.get("last_modified"):
            req_headers["If-Modified-Since"] = entry["last_modified"]

    tmp = dest.with_suffix(dest.suffix + ".part")
    last_error: Exception | None = None
    etag = last_modified = ""
    started = time.time()
    for attempt in range(3):
        h = hashlib.sha256()
        first = b""
        try:
            with client().stream("GET", url, headers=req_headers) as resp:
                if resp.status_code == 304:
                    print(f"  unchanged {filename} (304)")
                    return dest, "not_modified"
                resp.raise_for_status()
                etag = resp.headers.get("etag", "")
                last_modified = resp.headers.get("last-modified", "")
                with tmp.open("wb") as f:
                    for chunk in resp.iter_bytes(1 << 20):
                        if not first:
                            first = chunk[:4096]
                            if sniff is not None:
                                sniff(first)
                        h.update(chunk)
                        f.write(chunk)
            last_error = None
            break
        except NotData as exc:
            tmp.unlink(missing_ok=True)
            print(f"  FAILED {url}: {exc}")
            return None, "failed"
        except httpx.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            last_error = exc
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500 and status != 429:
                break
            time.sleep(5 * (attempt + 1))
    if last_error is not None:
        print(f"  FAILED {url}: {last_error}")
        return None, "failed"

    tmp.replace(dest)
    size = dest.stat().st_size
    record(
        dataset,
        ManifestEntry(
            dataset=dataset,
            filename=filename,
            url=url,
            sha256=h.hexdigest(),
            size=size,
            downloaded_at=now_iso(),
            etag=etag,
            last_modified=last_modified,
            note=note,
            extra=dict(extra or {}),
        ),
    )
    elapsed = time.time() - started
    print(f"  ok {filename} ({size:,} bytes, {elapsed:.0f}s)", flush=True)
    if throttle_seconds:
        time.sleep(throttle_seconds)
    return dest, "downloaded"


def update_extra(dataset: str, filename: str, **values) -> None:
    """Merge values into a manifest entry's `extra` dict (e.g. a post-download row count)."""
    manifest = load_manifest(dataset)
    if filename in manifest:
        manifest[filename].setdefault("extra", {}).update(values)
        save_manifest(dataset, manifest)


def get_json(url: str, params: dict | None = None, timeout: float = 120.0) -> dict:
    """GET a JSON endpoint; ArcGIS reports errors inside a 200 body, so unwrap those."""
    resp = client().get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        code = err.get("code") if isinstance(err, dict) else None
        exc = RuntimeError(f"ArcGIS error {code} for {url}: {err}")
        if isinstance(code, int) and code >= 500:
            raise exc
        raise exc
    return data
