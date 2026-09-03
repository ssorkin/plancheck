import json

import polars as pl
from shapely.geometry import box

from plancheck.ingest.reference import SCHEMA, _best_names, dissolve


def _row(id_, props, geom=None):
    return {"id": id_, "name": id_, "props": json.dumps(props), "geom_type": geom.geom_type if geom else None,
            "wkb": geom.wkb if geom else None}


def test_dissolve_merges_parts_by_key_and_names_them():
    base = pl.DataFrame(
        [
            _row("a", {"P_KEY": "10001200013000", "E_KEY": 10001}, box(0, 0, 1, 1)),
            _row("b", {"P_KEY": "10001200023000", "E_KEY": 10001}, box(1, 0, 2, 1)),
            _row("c", {"P_KEY": "10002200013000", "E_KEY": 10002}, box(0, 1, 1, 2)),
        ],
        schema=SCHEMA,
    )
    codes = pl.DataFrame(
        [
            _row("10001", {"EKEY_5S": 10001, "NAME": "Wide El", "LO_GRD": 0, "HI_GRD": 6, "CDS": "2"}),
            _row("10001", {"EKEY_5S": 10001, "NAME": "Narrow PC", "LO_GRD": 0, "HI_GRD": 2, "CDS": "1"}),
        ],
        schema=SCHEMA,
    )
    names = _best_names(codes, "EKEY_5S")
    assert names == {"10001": "Wide El"}
    out = dissolve(base, "E_KEY", names)
    assert out["id"].to_list() == ["10001", "10002"]
    assert out["name"].to_list() == ["Wide El", "10002"]
    from shapely import from_wkb

    assert abs(from_wkb(out["wkb"][0]).area - 2.0) < 1e-9
    assert json.loads(out["props"][0])["n_parts"] == 2
