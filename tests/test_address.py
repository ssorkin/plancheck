import pytest

from plancheck.geocode.address import normalize_street, parse_location

CASES = [
    # raw, kind, number, street, street2/cross, alts
    ("5249 N VANALDEN AVE", "address", "5249", "N VANALDEN AVE", None, ()),
    ("19150 Harnett St. and Vanalden Ave.", "address", "19150", "HARNETT ST", "VANALDEN AVE", ()),
    ("Texas Ave and Ohio Ave", "intersection", None, "OHIO AVE", "TEXAS AVE", ()),
    ("228TH ST & LOCKNESS AVE", "intersection", None, "228TH ST", "LOCKNESS AVE", ()),
    (
        "S/W CORNER OF VIRGINA AVE  and AND ST ANDREWS PL",
        "intersection",
        None,
        "ST ANDREWS PL",
        "VIRGINA AVE",
        (),
    ),
    ("F 6615 FRANKLIN AVE", "address", "6615", "FRANKLIN AVE", None, ()),
    (
        "619,621,623 TOWNE AVE. and E. 6TH ST",
        "address",
        "619",
        "TOWNE AVE",
        "E 6TH ST",
        ("621", "623"),
    ),
    (
        "1016-20 1/2 W. 23RD ST. and TOBERMAN ST.",
        "address",
        "1016",
        "W 23RD ST",
        "TOBERMAN ST",
        ("1020",),
    ),
    ("118TH PLACE and BROADWAY AVE", "intersection", None, "118TH PL", "BROADWAY AVE", ()),
    ("434 n martel  and rosewood ave", "address", "434", "N MARTEL", "ROSEWOOD AVE", ()),
    ("N/E corner Noble & lassen and Noble/Lassen", "intersection", None, "LASSEN", "NOBLE", ()),
    ("REAR OF 55 ELM AVENUE", "address", "55", "ELM AVE", None, ()),
    ("972-980 E.ELKLAND PL.,", "address", "972", "E ELKLAND PL", None, ("980",)),
    ("123 MAIN ST, LOS ANGELES 90012", "address", "123", "MAIN ST", None, ()),
    ("10201 W PICO BLVD B103, L5", "address", "10201", "W PICO BLVD", None, ()),
    ("922 N NORMANDIE AVE 1-11", "address", "922", "N NORMANDIE AVE", None, ()),
    ("VANALDEN AV and SCHOENBORN ST", "intersection", None, "SCHOENBORN ST", "VANALDEN AVE", ()),
]


@pytest.mark.parametrize("raw,kind,number,street,other,alts", CASES)
def test_parse_location(raw, kind, number, street, other, alts):
    q = parse_location(raw)
    assert q.kind == kind, q
    assert q.number == number, q
    assert q.street == street, q
    if kind == "intersection":
        assert q.street2 == other, q
    else:
        assert q.cross_street == other, q
    assert q.number_alt == alts, q


def test_zip_and_city_stripped():
    q = parse_location("123 MAIN ST, LOS ANGELES 90012")
    assert q.zip == "90012" and q.key == "address|123|MAIN ST|90012"


def test_intersection_key_is_order_independent():
    a = parse_location("Texas Ave and Ohio Ave")
    b = parse_location("OHIO AVENUE & TEXAS AV")
    assert a.key == b.key == "intersection|OHIO AVE|TEXAS AVE|"


def test_unparsed_cases():
    assert parse_location("").kind == "unparsed"
    assert parse_location(None).reason == "empty"
    q = parse_location("FORREST LAWN 225` E/O MH 8340")
    assert q.kind == "unparsed" and q.reason == "no_number"
    q = parse_location("Nebraska Ave and Centinela Ave and Nebraska Ave and Centinela Ave")
    assert q.kind == "intersection" and q.street == "CENTINELA AVE"


def test_normalize_street():
    assert normalize_street("north figueroa street") == "N FIGUEROA ST"
    assert normalize_street("SAINT ANDREWS PL") == "ST ANDREWS PL"
    assert normalize_street("118 TH PLACE") == "118TH PL"
    assert normalize_street("SUNSET BLVD WEST") == "SUNSET BLVD W"
