"""Tiered location resolution.

Each Tier sees only the permits still unresolved, returns rows in RESULT_SCHEMA for the
ones it could place, and the chain moves on. Provenance (`geocode_method`, score, match
type, key, reason) travels with every row so coverage can be reported by method.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import polars as pl

from plancheck.ahj.base import AHJ, BBox
from plancheck.geocode.base import AddressQuery, accept

RESULT_SCHEMA: dict[str, pl.DataType] = {
    "permit_id": pl.Utf8,
    "source_dataset": pl.Utf8,
    "lat": pl.Float64,
    "lon": pl.Float64,
    "geocode_method": pl.Utf8,
    "geocode_score": pl.Float64,
    "geocode_match_type": pl.Utf8,
    "geocode_key": pl.Utf8,
    "geocode_reason": pl.Utf8,
    "geom_type": pl.Utf8,
    "n_geoms": pl.Int32,
}


@dataclass
class Context:
    ahj: AHJ
    queries: dict[str, AddressQuery]  # permit key -> parsed query (by geocode_key)
    limit: int | None = None
    no_network: bool = False
    dry_run: bool = False
    min_score: float = 90.0
    throttle_seconds: float = 0.5

    def empty(self) -> pl.DataFrame:
        return pl.DataFrame(schema=RESULT_SCHEMA)


class Tier(Protocol):
    name: str

    def resolve(self, pending: pl.DataFrame, ctx: Context) -> pl.DataFrame: ...


def conform_results(df: pl.DataFrame) -> pl.DataFrame:
    have = set(df.columns)
    return df.select(
        [
            pl.col(c).cast(t) if c in have else pl.lit(None, dtype=t).alias(c)
            for c, t in RESULT_SCHEMA.items()
        ]
    )


class SourceCoordsTier:
    """Trust the source's own coordinates when they are present and inside the AHJ bbox.

    Zero coordinates and out-of-bbox points are recorded with a reason and left for later
    tiers. A lat/lon swap that would land inside the bbox is flagged, never auto-fixed.
    """

    name = "source_coords"

    def __init__(self, bbox: BBox) -> None:
        self.bbox = bbox

    def resolve(self, pending: pl.DataFrame, ctx: Context) -> pl.DataFrame:
        b = self.bbox
        lat, lon = pl.col("lat_src"), pl.col("lon_src")
        has = lat.is_not_null() & lon.is_not_null()
        zero = has & (lat == 0) & (lon == 0)
        inside = (
            has & (lat >= b.lat_min) & (lat <= b.lat_max) & (lon >= b.lon_min) & (lon <= b.lon_max)
        )
        swapped = (
            has
            & ~inside
            & (lon >= b.lat_min)
            & (lon <= b.lat_max)
            & (lat >= b.lon_min)
            & (lat <= b.lon_max)
        )
        reason = (
            pl.when(zero)
            .then(pl.lit("zero_coords"))
            .when(swapped)
            .then(pl.lit("swapped_axes"))
            .when(has & ~inside)
            .then(pl.lit("out_of_bbox"))
            .otherwise(pl.lit(None, dtype=pl.Utf8))
        )
        ok = pending.filter(inside & ~zero)
        rejected = pending.filter(has & ~(inside & ~zero)).select(
            "permit_id", "source_dataset", reason.alias("geocode_reason")
        )
        ctx.rejections = rejected  # type: ignore[attr-defined]
        return conform_results(
            ok.select(
                "permit_id",
                "source_dataset",
                lat.alias("lat"),
                lon.alias("lon"),
                pl.lit("source").alias("geocode_method"),
                pl.col("latlon_type_src").alias("geocode_match_type"),
            )
        )


class LocatorTier:
    """Query a batch geocoder for the parsed address/intersection of each pending permit.

    Unique keys are looked up in the cache first; only misses hit the network (unless
    `no_network`). Acceptance applies the score floor, bbox and match-type rules.
    """

    def __init__(self, geocoder, min_score: float | None = None) -> None:
        self.geocoder = geocoder
        self.name = geocoder.name
        self.min_score = min_score

    @classmethod
    def from_config(cls, name: str, ahj: AHJ) -> LocatorTier:
        from plancheck.geocode.arcgis_locator import ArcgisLocator

        cfg = ahj.geocoders[name]
        if cfg["kind"] != "arcgis_locator":
            raise KeyError(f"geocoder {name}: unsupported kind {cfg['kind']}")
        return cls(ArcgisLocator.from_config(name, cfg), min_score=cfg.get("min_score"))

    def resolve(self, pending: pl.DataFrame, ctx: Context) -> pl.DataFrame:
        from plancheck.geocode import cache

        min_score = self.min_score if self.min_score is not None else ctx.min_score
        keys = pending.filter(pl.col("geocode_key").is_not_null())["geocode_key"].unique()
        queries = [ctx.queries[k] for k in keys if k in ctx.queries]
        askable = [q for q in queries if q.kind in ("address", "intersection")]
        cached = cache.load(self.name)
        have = set(cached["key"].to_list())
        misses = [q for q in askable if q.key not in have]
        print(
            f"  {self.name}: {len(keys):,} unique keys, {len(askable):,} parseable, "
            f"{len(misses):,} not cached"
        )
        if misses and not ctx.no_network and not ctx.dry_run:
            if ctx.limit is not None:
                misses = misses[: ctx.limit]
            self.geocoder.throttle = ctx.throttle_seconds
            done = 0
            for start in range(0, len(misses), self.geocoder.batch_size):
                chunk = misses[start : start + self.geocoder.batch_size]
                results = self.geocoder.geocode(chunk)
                cache.append(self.name, results)
                done += len(chunk)
                if done % (self.geocoder.batch_size * 10) == 0 or done == len(misses):
                    print(f"    {self.name}: geocoded {done:,}/{len(misses):,}", flush=True)
            cached = cache.load(self.name)
        if cached.is_empty():
            return ctx.empty()

        # Apply acceptance per key.
        rows = []
        by_key = {r["key"]: r for r in cached.iter_rows(named=True)}
        for q in askable:
            r = by_key.get(q.key)
            if r is None:
                continue
            from plancheck.geocode.base import GeocodeResult

            res = GeocodeResult(**r)
            ok, reason = accept(q, res, ctx.ahj.bbox, min_score)
            rows.append(
                {
                    "geocode_key": q.key,
                    "lat": res.lat if ok else None,
                    "lon": res.lon if ok else None,
                    "geocode_score": res.score,
                    "geocode_match_type": res.match_type,
                    "geocode_reason": None if ok else reason,
                    "_ok": ok,
                }
            )
        if not rows:
            return ctx.empty()
        verdicts = pl.DataFrame(rows)
        joined = pending.select("permit_id", "source_dataset", "geocode_key").join(
            verdicts, on="geocode_key", how="inner"
        )
        ctx.rejections = joined.filter(~pl.col("_ok")).select(  # type: ignore[attr-defined]
            "permit_id", "source_dataset", "geocode_reason"
        )
        return conform_results(
            joined.filter(pl.col("_ok")).with_columns(pl.lit(self.name).alias("geocode_method"))
        )


def run_chain(tiers: list, permits: pl.DataFrame, ctx: Context) -> tuple[pl.DataFrame, dict]:
    """Walk the tiers; return (resolved rows for every permit, per-tier counts)."""
    key_cols = ["permit_id", "source_dataset"]
    pending = permits
    resolved: list[pl.DataFrame] = []
    last_reason = pl.DataFrame(schema={**{c: pl.Utf8 for c in key_cols}, "geocode_reason": pl.Utf8})
    counts: dict[str, int] = {}
    for tier in tiers:
        ctx.rejections = None  # type: ignore[attr-defined]
        got = tier.resolve(pending, ctx)
        counts[tier.name] = got.height
        print(f"  {tier.name}: located {got.height:,} of {pending.height:,} pending")
        rej = getattr(ctx, "rejections", None)
        if rej is not None and not rej.is_empty():
            last_reason = pl.concat(
                [last_reason.join(rej.select(key_cols), on=key_cols, how="anti"), rej],
                how="vertical_relaxed",
            )
        if not got.is_empty():
            resolved.append(got)
            pending = pending.join(got.select(key_cols), on=key_cols, how="anti")
        if pending.is_empty():
            break
    unresolved = pending.select(key_cols).join(last_reason, on=key_cols, how="left")
    unresolved = conform_results(
        unresolved.with_columns(
            pl.lit("none").alias("geocode_method"),
            pl.col("geocode_reason").fill_null("unmatched"),
        ).join(permits.select(*key_cols, "geocode_key"), on=key_cols, how="left")
    )
    counts["none"] = unresolved.height
    out = pl.concat([*resolved, unresolved], how="vertical_relaxed") if resolved else unresolved
    return out, counts
