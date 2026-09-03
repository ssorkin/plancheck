"""City of Los Angeles: LADBS (building / electrical / mechanical) and BOE (right-of-way).

Exports MAPPERS (raw -> common permits schema) and build_tiers (the geocoding chain).
"""

from __future__ import annotations

from plancheck.ahj.la_city.boe import map_boe
from plancheck.ahj.la_city.ladbs import map_ladbs_building, map_ladbs_trade

MAPPERS = {
    "ladbs_building": map_ladbs_building,
    "ladbs_trade": map_ladbs_trade,
    "boe": map_boe,
}


def build_tiers(ahj) -> list:
    from plancheck.ahj.la_city.boe import BoeGeometryTier
    from plancheck.geocode.strategy import LocatorTier, SourceCoordsTier

    tiers = []
    for name in ahj.chain:
        if name == "source_coords":
            tiers.append(SourceCoordsTier(ahj.bbox))
        elif name == "boe_geometry":
            tiers.append(BoeGeometryTier(ahj))
        elif name in ahj.geocoders:
            tiers.append(LocatorTier.from_config(name, ahj))
        else:
            raise KeyError(f"la_city chain: unknown tier {name!r}")
    return tiers
