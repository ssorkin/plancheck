"""Geocoder interface, result type, and the acceptance rule shared by every locator tier."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from plancheck.ahj.base import BBox

ADDRESS_MATCH_TYPES = frozenset(
    {"PointAddress", "StreetAddress", "Subaddress", "StreetAddressExt", "BuildingName"}
)
INTERSECTION_MATCH_TYPES = frozenset({"StreetInt"})


@dataclass(frozen=True)
class AddressQuery:
    """A parsed location string. `key` is the cache key (normalized, geocoder-agnostic)."""

    key: str
    kind: str  # address | intersection | unparsed
    raw: str = ""
    number: str | None = None
    street: str | None = None
    street2: str | None = None  # second street of an intersection
    cross_street: str | None = None  # "<number> <street> AND <cross>" — informational
    zip: str | None = None
    city: str | None = None
    number_alt: tuple[str, ...] = field(default_factory=tuple)  # extra numbers in a range/list
    relation: str | None = None  # stripped prefix such as "S/W CORNER OF", "REAR OF"
    reason: str | None = None  # why kind == unparsed

    @property
    def display(self) -> str:
        if self.kind == "address":
            return f"{self.number} {self.street}"
        if self.kind == "intersection":
            return f"{self.street} & {self.street2}"
        return self.raw


@dataclass(frozen=True)
class GeocodeResult:
    key: str
    geocoder: str
    status: str  # M (matched) | T (tied) | U (unmatched) | E (error)
    lat: float | None
    lon: float | None
    score: float | None
    match_type: str | None
    matched_address: str | None
    geocoded_at: str


class Geocoder(Protocol):
    name: str
    batch_size: int
    supports_intersections: bool

    def geocode(self, queries: list[AddressQuery]) -> list[GeocodeResult]: ...


def accept(
    q: AddressQuery,
    r: GeocodeResult,
    bbox: BBox,
    min_score: float,
    address_types: frozenset[str] = ADDRESS_MATCH_TYPES,
    intersection_types: frozenset[str] = INTERSECTION_MATCH_TYPES,
) -> tuple[bool, str]:
    """Decide whether a locator result is trustworthy for the query. Returns (ok, reason)."""
    if r.status == "E":
        return False, "error"
    if r.status not in ("M", "T") or r.lat is None or r.lon is None:
        return False, "unmatched"
    if r.score is None or r.score < min_score:
        return False, "low_score"
    if not bbox.contains(r.lat, r.lon):
        return False, "out_of_bbox"
    mt = r.match_type or ""
    if q.kind == "intersection" and mt not in intersection_types:
        return False, "type_mismatch"
    if q.kind == "address" and mt not in address_types:
        return False, "type_mismatch"
    return True, "ok"
