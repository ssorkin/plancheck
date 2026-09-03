"""2020 census tracts for the AHJ's county from TIGERweb (Census Bureau ArcGIS REST).

Layer IDs on TIGERweb shift between releases, so the layer name is asserted before any
data is trusted. Geometry is requested in EPSG:4326 at precision 6.
"""

from __future__ import annotations

from plancheck.acquire.arcgis import fetch_layer_jsonl, layer_info
from plancheck.config import analysis_config

DATASET = "tiger"
SERVICE = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer"
)
OUT_FIELDS = "GEOID,NAME,BASENAME,AREALAND,AREAWATER,CENTLAT,CENTLON"


def find_layer(name_contains: str) -> str:
    from plancheck.acquire.base import get_json, retrying

    info = retrying(lambda: get_json(SERVICE, {"f": "json"}), label="tigerweb service")
    for lyr in info.get("layers", []):
        if lyr["name"] == name_contains or name_contains == lyr["name"].strip():
            return f"{SERVICE}/{lyr['id']}"
    for lyr in info.get("layers", []):
        if name_contains.lower() in lyr["name"].lower():
            return f"{SERVICE}/{lyr['id']}"
    raise RuntimeError(f"TIGERweb layer containing {name_contains!r} not found in {SERVICE}")


def acquire(refresh: bool = False, force: bool = False) -> None:
    cfg = analysis_config()["census"]
    state, county = cfg["state_fips"], cfg["county_fips"]
    layer_url = find_layer("Census Tracts")
    info = layer_info(layer_url)
    assert "Tract" in info.get("name", ""), info.get("name")
    print(f"tiger tracts 2020 ({layer_url}): county {state}{county}")
    fetch_layer_jsonl(
        DATASET,
        f"tracts_2020_{state}{county}",
        layer_url,
        out_fields=OUT_FIELDS,
        where=f"STATE='{state}' AND COUNTY='{county}'",
        order_by="OBJECTID",
        refresh=refresh,
        force=force,
        note=f"2020 census tracts, county {state}{county}, TIGERweb {info.get('name')!r}",
    )
