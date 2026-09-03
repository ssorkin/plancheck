import polars as pl

from plancheck.ingest.schema import norm_tract, to_bool, to_date, to_money


def test_to_date_handles_export_and_iso():
    df = pl.DataFrame({"d": ["12/22/2022", "2023-04-06T00:00:00.000", "", None, "bogus"]})
    out = df.select(to_date("d").alias("d"))["d"].to_list()
    assert [str(x) if x else None for x in out] == ["2022-12-22", "2023-04-06", None, None, None]


def test_to_money_strips_symbols():
    df = pl.DataFrame({"v": ["5000", "8,500", "$1500000", "", None, "n/a"]})
    assert df.select(to_money("v"))["v"].to_list() == [5000.0, 8500.0, 1500000.0, None, None, None]


def test_to_bool():
    df = pl.DataFrame({"b": ["Y", "N", "", None, "yes", "0"]})
    assert df.select(to_bool("b"))["b"].to_list() == [True, False, None, None, True, False]


def test_norm_tract():
    df = pl.DataFrame({"ct": ["1173.01", "1915.00", "2073", "", None, "980.1"]})
    assert df.select(norm_tract("ct"))["ct"].to_list() == [
        "117301",
        "191500",
        "207300",
        None,
        None,
        "098010",
    ]
