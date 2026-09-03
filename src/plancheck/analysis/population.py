"""Population and housing units per geography, from 2020 census blocks.

Block internal points are assigned to each geography's polygons (or to tracts by GEOID
prefix, and to H3 cells directly), and P.L. 94-171 counts are summed. This is the
denominator for per-capita and per-housing-unit rates on every area type, including ones
that contain large unpopulated land such as parks.
"""

from __future__ import annotations

import polars as pl

from plancheck.analysis.export import GEOGRAPHIES
from plancheck.config import analysis_config
from plancheck.geocode.spatial import load_layer, point_in_polygon
from plancheck.paths import PARQUET_DIR


def population_by_geography(ahj_slug: str = "la_city") -> dict[str, pl.DataFrame]:
    path = PARQUET_DIR / "blocks" / "data.parquet"
    if not path.exists():
        return {}
    blocks = pl.read_parquet(path).filter(pl.col("lat").is_not_null())
    lat, lon = blocks["lat"].to_numpy(), blocks["lon"].to_numpy()
    out: dict[str, pl.DataFrame] = {}

    def agg(ids: list, name: str) -> None:
        df = (
            blocks.with_columns(pl.Series("geo_id", ids, dtype=pl.Utf8))
            .filter(pl.col("geo_id").is_not_null())
            .group_by("geo_id")
            .agg(
                pl.col("pop").sum().alias("pop"),
                pl.col("housing_units").sum().alias("housing_units"),
                pl.len().alias("n_blocks"),
            )
        )
        out[f"population_{name}"] = df

    agg(blocks["tract_geoid"].to_list(), "tract")
    for slug, (_stem, layer, _label, _tol) in GEOGRAPHIES.items():
        if layer is None:
            continue
        ref = load_layer(ahj_slug, layer)
        if ref is None:
            continue
        agg(point_in_polygon(lat, lon, ref, "id"), slug)
    try:
        import h3

        res = analysis_config()["hexes"]["resolutions"][0]
        agg(
            [h3.latlng_to_cell(float(a), float(o), res) for a, o in zip(lat, lon, strict=True)],
            "hex_r8",
        )
    except ImportError:  # pragma: no cover
        pass
    return out
