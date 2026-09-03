"""ACS 5-year tract tables for the AHJ's county via api.census.gov.

Variable metadata (`groups/<table>.json`) is snapshotted alongside each table so analysis
selects variables by label rather than hardcoded IDs. The API key is required
(CENSUS_API_KEY in the environment or a git-ignored .env) and is redacted from manifests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

from plancheck.acquire.base import ManifestEntry, client, is_cached, now_iso, record, sha256_file
from plancheck.config import analysis_config
from plancheck.paths import RAW_DIR

DATASET = "census"
ACS_BASE = "https://api.census.gov/data"


def api_key() -> str:
    key = os.environ.get("CENSUS_API_KEY", "").strip()
    if not key:
        env_file = Path(__file__).resolve().parents[3] / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "CENSUS_API_KEY":
                    key = value.strip().strip("'\"")
    if not key:
        raise RuntimeError(
            "CENSUS_API_KEY is not set. Sign up (free) at "
            "https://api.census.gov/data/key_signup.html, then export CENSUS_API_KEY or put "
            "CENSUS_API_KEY=<key> in a .env file at the repo root."
        )
    return key


def _fetch_json(filename: str, url: str, note: str, key: str | None = None) -> Path | None:
    dest_dir = RAW_DIR / DATASET
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    if is_cached(DATASET, filename):
        return dest
    request_url = f"{url}&key={key}" if key else url
    try:
        resp = client().get(request_url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"  FAILED {url}: {exc}")
        return None
    body = resp.text
    try:
        json.loads(body)
    except ValueError:
        print(f"  FAILED {url}: response is not JSON (missing/invalid API key?)")
        return None
    dest.write_text(body)
    record(
        DATASET,
        ManifestEntry(
            dataset=DATASET,
            filename=filename,
            url=url,
            sha256=sha256_file(dest),
            size=dest.stat().st_size,
            downloaded_at=now_iso(),
            note=note,
        ),
    )
    print(f"  ok {filename} ({dest.stat().st_size:,} bytes)")
    return dest


def acquire() -> None:
    cfg = analysis_config()["census"]
    vintage, state, county = cfg["acs_vintage"], cfg["state_fips"], cfg["county_fips"]
    key = api_key()
    base = f"{ACS_BASE}/{vintage}/acs/acs5"
    for table, desc in cfg["tables"].items():
        t = table.lower()
        _fetch_json(
            f"acs5_{vintage}_groups_{t}.json",
            f"{base}/groups/{table}.json",
            note=f"ACS5 {vintage} variable metadata for {table} ({desc})",
        )
        _fetch_json(
            f"acs5_{vintage}_{t}_tract_{state}{county}.json",
            f"{base}?get=NAME,group({table})&for=tract:*&in=state:{state}%20county:{county}",
            note=f"ACS5 {vintage} {table} ({desc}), tracts, county {state}{county}",
            key=key,
        )
