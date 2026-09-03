"""Batch client for Esri GeocodeServer `geocodeAddresses`.

The LA County CAMS and LA City centerline locators do not accept single-line input; each
query is sent in the locator's own address fields (mapped from config). Intersections go
in the street field joined by `intersection_joiner` ("A & B").
"""

from __future__ import annotations

import json
import math
import time

import httpx

from plancheck.acquire.base import client, now_iso, retrying
from plancheck.geocode.base import AddressQuery, GeocodeResult


class ArcgisLocator:
    def __init__(
        self,
        name: str,
        url: str,
        fields: dict[str, str],
        batch_size: int = 1000,
        default_city: str | None = None,
        default_state: str | None = None,
        intersection_joiner: str = " & ",
        throttle_seconds: float = 0.5,
    ) -> None:
        self.name = name
        self.url = url.rstrip("/")
        self.fields = fields
        self.batch_size = int(batch_size)
        self.default_city = default_city
        self.default_state = default_state
        self.joiner = intersection_joiner
        self.throttle = throttle_seconds
        self.supports_intersections = True

    @classmethod
    def from_config(cls, name: str, cfg: dict, throttle_seconds: float = 0.5) -> ArcgisLocator:
        return cls(
            name=name,
            url=cfg["url"],
            fields=cfg["fields"],
            batch_size=cfg.get("batch_size", 1000),
            default_city=cfg.get("default_city"),
            default_state=cfg.get("default_state"),
            intersection_joiner=cfg.get("intersection_joiner", " & "),
            throttle_seconds=throttle_seconds,
        )

    def _record(self, i: int, q: AddressQuery) -> dict:
        if q.kind == "intersection":
            street = f"{q.street}{self.joiner}{q.street2}"
        else:
            street = q.display
        attrs = {"OBJECTID": i, self.fields["street"]: street[:100]}
        if "city" in self.fields and (q.city or self.default_city):
            attrs[self.fields["city"]] = q.city or self.default_city
        if "state" in self.fields and self.default_state:
            attrs[self.fields["state"]] = self.default_state
        if "zip" in self.fields and q.zip:
            attrs[self.fields["zip"]] = q.zip
        return {"attributes": attrs}

    def geocode(self, queries: list[AddressQuery]) -> list[GeocodeResult]:
        out: list[GeocodeResult] = []
        for start in range(0, len(queries), self.batch_size):
            chunk = queries[start : start + self.batch_size]
            out.extend(self._batch(chunk))
            if self.throttle:
                time.sleep(self.throttle)
        return out

    def _batch(self, chunk: list[AddressQuery]) -> list[GeocodeResult]:
        payload = {"records": [self._record(i, q) for i, q in enumerate(chunk)]}
        data = {
            "addresses": json.dumps(payload),
            "f": "json",
            "outSR": "4326",
            "outFields": "Addr_type,Score,Match_addr,Status",
        }
        stamp = now_iso()

        def call() -> dict:
            resp = client().post(f"{self.url}/geocodeAddresses", data=data, timeout=180.0)
            resp.raise_for_status()
            body = resp.json()
            if "error" in body:
                raise RuntimeError(f"{self.name}: {body['error']}")
            return body

        try:
            body = retrying(call, label=f"{self.name} batch of {len(chunk)}")
        except (httpx.HTTPError, RuntimeError) as exc:
            print(f"  {self.name}: batch failed: {exc}")
            return [
                GeocodeResult(q.key, self.name, "E", None, None, None, None, None, stamp)
                for q in chunk
            ]
        by_id: dict[int, dict] = {}
        for loc in body.get("locations", []):
            a = loc.get("attributes") or {}
            by_id[int(a.get("ResultID", -1))] = loc
        results = []
        for i, q in enumerate(chunk):
            loc = by_id.get(i)
            if loc is None:
                results.append(
                    GeocodeResult(q.key, self.name, "U", None, None, None, None, None, stamp)
                )
                continue
            a = loc.get("attributes") or {}
            status = a.get("Status") or ("M" if loc.get("score") else "U")
            xy = loc.get("location") or {}
            try:
                lon, lat = float(xy.get("x")), float(xy.get("y"))
                if math.isnan(lon) or math.isnan(lat):
                    lon = lat = None
            except (TypeError, ValueError):
                lon = lat = None
            score = a.get("Score", loc.get("score"))
            results.append(
                GeocodeResult(
                    key=q.key,
                    geocoder=self.name,
                    status=status,
                    lat=lat,
                    lon=lon,
                    score=float(score) if score is not None else None,
                    match_type=a.get("Addr_type") or None,
                    matched_address=a.get("Match_addr") or loc.get("address") or None,
                    geocoded_at=stamp,
                )
            )
        return results
