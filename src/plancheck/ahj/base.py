"""AHJ (authority having jurisdiction) abstraction.

An AHJ is a YAML block in config/sources.yaml plus a Python package under
plancheck.ahj.<slug> exporting:

- ``MAPPERS``: dict[str, Mapper] — each maps one raw source frame (all-varchar columns,
  lowercased headers) into the common permits schema (see plancheck.ingest.schema).
- ``build_tiers(ahj) -> list[Tier]``: the geocoding chain named in the YAML ``chain``.

Every pipeline stage loops over ``list_ahjs()`` and never special-cases a slug.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any

import polars as pl

from plancheck.config import sources_config


@dataclass(frozen=True)
class BBox:
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.lat_min <= lat <= self.lat_max and self.lon_min <= lon <= self.lon_max


@dataclass(frozen=True)
class SourceSpec:
    slug: str
    family: str
    kind: str  # socrata | arcgis_layer | file
    permit_class: str  # building | electrical | mechanical | right_of_way | ...
    record_kind: str  # issued | submitted
    mapper: str
    partition_date: str
    dataset_id: str | None = None
    url: str | None = None
    title: str = ""
    note: str = ""


Mapper = Callable[[pl.LazyFrame, SourceSpec], pl.LazyFrame]


@dataclass(frozen=True)
class AHJ:
    slug: str
    name: str
    bbox: BBox
    sources: dict[str, SourceSpec]
    geometries: dict[str, dict[str, Any]] = field(default_factory=dict)
    reference: dict[str, dict[str, Any]] = field(default_factory=dict)
    covariates: dict[str, dict[str, Any]] = field(default_factory=dict)
    geocoders: dict[str, dict[str, Any]] = field(default_factory=dict)
    chain: tuple[str, ...] = ()
    socrata_domain: str | None = None

    @property
    def module(self):
        return importlib.import_module(f"plancheck.ahj.{self.slug}")

    @property
    def mappers(self) -> dict[str, Mapper]:
        return self.module.MAPPERS

    def mapper(self, spec: SourceSpec) -> Mapper:
        try:
            return self.mappers[spec.mapper]
        except KeyError as exc:
            raise KeyError(
                f"AHJ {self.slug!r} has no mapper {spec.mapper!r} (source {spec.slug})"
            ) from exc

    def build_tiers(self) -> list:
        return self.module.build_tiers(self)

    def families(self) -> dict[str, list[SourceSpec]]:
        out: dict[str, list[SourceSpec]] = {}
        for spec in self.sources.values():
            out.setdefault(spec.family, []).append(spec)
        return out


def _parse(slug: str, raw: dict) -> AHJ:
    sources = {
        s: SourceSpec(slug=s, **{k: v for k, v in spec.items()})
        for s, spec in (raw.get("sources") or {}).items()
    }
    return AHJ(
        slug=slug,
        name=raw["name"],
        bbox=BBox(**raw["bbox"]),
        sources=sources,
        geometries=raw.get("geometries") or {},
        reference=raw.get("reference") or {},
        covariates=raw.get("covariates") or {},
        geocoders=raw.get("geocoders") or {},
        chain=tuple(raw.get("chain") or ()),
        socrata_domain=raw.get("socrata_domain"),
    )


@cache
def load_ahj(slug: str) -> AHJ:
    cfg = sources_config()["ahjs"]
    if slug not in cfg:
        raise KeyError(f"unknown AHJ {slug!r}; known: {', '.join(sorted(cfg))}")
    return _parse(slug, cfg[slug])


def list_ahjs(selector: str = "all") -> list[AHJ]:
    cfg = sources_config()["ahjs"]
    slugs = sorted(cfg) if selector in ("all", "", None) else [selector]
    return [load_ahj(s) for s in slugs]


def select_sources(ahj: AHJ, source: str = "all") -> list[SourceSpec]:
    """Sources matching a slug, a family name, or 'all'."""
    if source in ("all", "", None):
        return list(ahj.sources.values())
    if source in ahj.sources:
        return [ahj.sources[source]]
    fam = [s for s in ahj.sources.values() if s.family == source]
    if fam:
        return fam
    raise KeyError(f"AHJ {ahj.slug!r} has no source or family {source!r}")
