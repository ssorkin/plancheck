from pathlib import Path

import polars as pl

from plancheck.ahj import load_ahj
from plancheck.ingest.csv_raw import norm_header, read_export_csv
from plancheck.ingest.schema import PERMITS_SCHEMA, conform

FIX = Path(__file__).parent / "fixtures"


def _map(fixture: str, source: str) -> pl.DataFrame:
    ahj = load_ahj("la_city")
    spec = ahj.sources[source]
    raw = read_export_csv(FIX / fixture)
    date_col = norm_header(spec.partition_date)
    assert date_col in raw.columns
    mapped = ahj.mapper(spec)(raw.lazy(), spec)
    return conform(mapped).collect()


def test_ladbs_building_mapper():
    df = _map("ladbs_building_sample.csv", "ladbs_building_issued_2020")
    assert df.columns == list(PERMITS_SCHEMA)
    assert df.height == 3
    r = df.row(1, named=True)
    assert r["permit_id"] == "22016-10000-31693"
    assert r["valuation"] == 8500.0
    assert r["adu_changed"] is True and r["hillside"] is True and r["solar"] is True
    assert str(r["issue_date"]) == "2023-03-17" and str(r["final_date"]) == "2024-08-15"
    assert r["tract_src"] == "191500" and r["council_district_src"] == "13"
    assert r["lat_src"] == 34.08693 and r["latlon_type_src"] == "ADDRESS"
    r0 = df.row(0, named=True)
    assert "embedded newline" in r0["work_desc"]
    r2 = df.row(2, named=True)
    assert r2["valuation"] == 1_500_000.0 and r2["dwelling_units_change"] == 12
    assert r2["lat_src"] is None and r2["apn"] is None and r2["tract_src"] == "207300"


def test_boe_mapper():
    df = _map("boe_sample.csv", "boe_permits")
    assert df.columns == list(PERMITS_SCHEMA)
    r = df.row(0, named=True)
    assert r["permit_id"] == "U2015008392" and r["permit_ref"] == "2015008392"
    assert r["permit_class"] == "right_of_way" and r["permit_type"] == "U"
    assert r["address_raw"] == "19150 Harnett St. and Vanalden Ave."
    assert str(r["issue_date"]) == "2015-08-18"
    assert df.row(2, named=True)["address_raw"] is None


def test_registry_lists_all_sources():
    ahj = load_ahj("la_city")
    assert len(ahj.sources) == 19
    assert {s.mapper for s in ahj.sources.values()} <= set(ahj.mappers)
    assert ahj.chain == ("source_coords", "boe_geometry", "cams", "centerline")
