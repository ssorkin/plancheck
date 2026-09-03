"""Location-string parser for permit records.

Right-of-way permits describe where work happens in free text: a house address, an
intersection ("TEXAS AVE and OHIO AVE"), a corner ("S/W CORNER OF X and AND Y"), an
address plus its cross street ("619,621,623 TOWNE AVE. and E. 6TH ST"), a range
("1016-20 1/2 W 23RD ST"), or a marker-prefixed address ("F 6615 FRANKLIN AVE"). The parser
turns each into an AddressQuery whose `key` is stable across spellings, so the geocode
cache is hit for the same place however it was typed.

Every step is a named regex; tests/test_address.py pins the behaviour on real strings.
"""

from __future__ import annotations

import re

from plancheck.geocode.base import AddressQuery

SUFFIXES = {
    "AVENUE": "AVE",
    "AVE": "AVE",
    "AV": "AVE",
    "AVN": "AVE",
    "STREET": "ST",
    "ST": "ST",
    "STR": "ST",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "BLV": "BLVD",
    "BL": "BLVD",
    "BOUL": "BLVD",
    "PLACE": "PL",
    "PL": "PL",
    "DRIVE": "DR",
    "DR": "DR",
    "DRV": "DR",
    "ROAD": "RD",
    "RD": "RD",
    "COURT": "CT",
    "CT": "CT",
    "CRT": "CT",
    "LANE": "LN",
    "LN": "LN",
    "LA": "LN",
    "TERRACE": "TER",
    "TER": "TER",
    "TERR": "TER",
    "HIGHWAY": "HWY",
    "HWY": "HWY",
    "HY": "HWY",
    "PARKWAY": "PKWY",
    "PKWY": "PKWY",
    "PKY": "PKWY",
    "CIRCLE": "CIR",
    "CIR": "CIR",
    "WAY": "WAY",
    "WY": "WAY",
    "TRAIL": "TRL",
    "TRL": "TRL",
    "WALK": "WALK",
    "ALLEY": "ALY",
    "ALY": "ALY",
    "SQUARE": "SQ",
    "SQ": "SQ",
    "PLAZA": "PLZ",
    "PLZ": "PLZ",
    "FREEWAY": "FWY",
    "FWY": "FWY",
    "CANYON": "CYN",
    "CYN": "CYN",
    "TERRACE.": "TER",
}
DIRECTIONALS = {
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
    "N": "N",
    "S": "S",
    "E": "E",
    "W": "W",
    "NO": "N",
    "SO": "S",
    "NE": "NE",
    "NW": "NW",
    "SE": "SE",
    "SW": "SW",
    "NORTHEAST": "NE",
    "NORTHWEST": "NW",
    "SOUTHEAST": "SE",
    "SOUTHWEST": "SW",
}

# Step 1: connectors and punctuation.
_CONNECTOR_RE = re.compile(r"\s*(?:&|@|\+|\bAT\b|/(?=\s*[A-Z])|\bAND\b)\s*")
_DOUBLE_AND_RE = re.compile(r"\bAND(?:\s+AND)+\b")
_WS_RE = re.compile(r"\s+")
# Step 2: corner / relation prefixes.
_CORNER_RE = re.compile(
    r"^(?:(?:N|S|E|W|NE|NW|SE|SW|N/E|N/W|S/E|S/W|NORTH|SOUTH|EAST|WEST|NORTHEAST|"
    r"NORTHWEST|SOUTHEAST|SOUTHWEST)\s*[-/]?\s*)?"
    r"(?:CORNER|COR|CRNR|SIDE|S/S|N/S|E/S|W/S)\s*(?:OF|\bO\b)?\s+"
)
_RELATION_RE = re.compile(
    r"^(?:REAR|FRONT|SIDE|ALLEY|ADJ(?:ACENT)?\s+TO|IN\s+FRONT\s+OF|OPP(?:OSITE)?|BEHIND|"
    r"NEAR|NEXT\s+TO|ACROSS\s+FROM|(?:N|S|E|W)/O)\s+(?:OF\s+)?"
)
# Step 3: single-letter / marker prefixes before a house number.
_MARKER_RE = re.compile(r"^(?:[A-Z]|BLDG|BUILDING|LOT|PARCEL|APN|UNIT|STE|SUITE|#)\s+(?=\d)")
# Step 4: house number (with optional fraction/letter suffix) and ranges/lists.
_NUMBER_RE = re.compile(
    r"^(\d+)(?:[A-Z](?=\s))?(?:\s+\d/\d)?"
    r"((?:\s*(?:-|–|—|/|,|\s+TO\s+|\s+THRU\s+)\s*\d+(?:[A-Z](?=\s))?(?:\s+\d/\d)?)*)\s+"
)
_NUMBER_ITEM_RE = re.compile(r"\d+")
# Step 5: split into streets.
_SPLIT_RE = re.compile(r"\s+(?:AND|BETWEEN|BTWN|BET|TO|FROM)\s+")
# Step 7: zip and city.
_ZIP_RE = re.compile(r",?\s*\b(9\d{4})(?:-\d{4})?\s*$")
_CITY_RE = re.compile(
    r",?\s*\b(?:LOS\s+ANGELES|L\.?A\.?|CA|CALIFORNIA|CITY\s+OF\s+LOS\s+ANGELES)\s*$"
)
_ORDINAL_RE = re.compile(r"\b(\d+)\s+(ST|ND|RD|TH)\b")
_UNIT_RE = re.compile(r"\s+(?:#|APT|UNIT|STE|SUITE|BLDG|FL|FLOOR|RM|ROOM)\s*[A-Z0-9-]+.*$")
_TRAILING_RANGE_RE = re.compile(r"\s+\d+\s*-\s*\d+\s*$")


_SIDE_OF_RE = re.compile(r"\b([NSEW])/O\b")


def _normalize(raw: str) -> tuple[str, str | None]:
    """Uppercase, strip punctuation, pull off a corner/relation prefix, unify connectors."""
    s = raw.upper().strip()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"\.(?=\s|$|,)", "", s)  # E. -> E, AVE. -> AVE
    s = s.replace(".", " ")  # 5249 N.VANALDEN -> 5249 N VANALDEN
    s = re.sub(r"\s*;\s*", " ", s)
    s = _WS_RE.sub(" ", s).strip(" ,-")
    relation = None
    if (m := _CORNER_RE.match(s)) or (m := _RELATION_RE.match(s)):
        relation, s = m.group(0).strip(), s[m.end() :]
    s = _SIDE_OF_RE.sub(r"\1 OF", s)
    s = _CONNECTOR_RE.sub(" AND ", s)
    s = _DOUBLE_AND_RE.sub("AND", s)
    s = re.sub(r"^\s*AND\s+|\s+AND\s*$", "", s)
    s = _WS_RE.sub(" ", s).strip(" ,-")
    return s, relation


def normalize_street(street: str) -> str:
    """'N. VANALDEN AVENUE' -> 'N VANALDEN AVE'; '118 TH PLACE' -> '118TH PL'."""
    s = _ORDINAL_RE.sub(r"\1\2", street.upper().strip(" ,"))
    s = _UNIT_RE.sub("", s)
    s = _TRAILING_RANGE_RE.sub("", s)
    words = [w for w in re.split(r"[\s,]+", s) if w]
    if not words:
        return ""
    if len(words) > 1 and words[0] in DIRECTIONALS:
        words[0] = DIRECTIONALS[words[0]]
    # Anything after the street-type word is unit/floor noise ("PICO BLVD B103 L5"),
    # except a trailing directional ("SUNSET BLVD W").
    for i in range(1, len(words)):
        if words[i] in SUFFIXES and words[i] not in DIRECTIONALS:
            tail = words[i + 1 : i + 2]
            keep = tail if tail and tail[0] in DIRECTIONALS else []
            words = words[: i + 1] + keep
            break
    if len(words) > 1 and words[-1] in DIRECTIONALS and words[-2] in SUFFIXES:
        words[-1] = DIRECTIONALS[words[-1]]
        words[-2] = SUFFIXES[words[-2]]
    elif len(words) > 1 and words[-1] in SUFFIXES:
        words[-1] = SUFFIXES[words[-1]]
    if words[0] == "SAINT":
        words[0] = "ST"
    return " ".join(words)


def _parse_numbers(m: re.Match) -> tuple[str, tuple[str, ...]]:
    primary = m.group(1)
    rest = _NUMBER_ITEM_RE.findall(re.sub(r"\d/\d", " ", m.group(2) or ""))
    alts: list[str] = []
    for n in rest:
        # Expand short range tails with the primary's prefix: 1016-20 -> 1020.
        if len(n) < len(primary):
            n = primary[: len(primary) - len(n)] + n
        if n != primary and n not in alts:
            alts.append(n)
    return primary, tuple(alts)


def parse_location(
    raw: str | None, default_zip: str | None = None, default_city: str | None = None
) -> AddressQuery:
    if not raw or not raw.strip():
        return AddressQuery(key="unparsed|", kind="unparsed", raw=raw or "", reason="empty")
    s, relation = _normalize(raw)
    zip_code = default_zip
    if m := _ZIP_RE.search(s):
        zip_code, s = m.group(1), s[: m.start()]
    s = _CITY_RE.sub("", s).strip(" ,")
    s = _MARKER_RE.sub("", s)

    number = None
    alts: tuple[str, ...] = ()
    if m := _NUMBER_RE.match(s):
        number, alts = _parse_numbers(m)
        s = s[m.end() :]
    parts = [p for p in _SPLIT_RE.split(s) if p.strip(" ,")]
    parts = [normalize_street(p) for p in parts]
    parts = [p for p in parts if p]

    if number and parts:
        street = parts[0]
        cross = parts[1] if len(parts) > 1 else None
        key = f"address|{number}|{street}|{zip_code or ''}"
        return AddressQuery(
            key=key,
            kind="address",
            raw=raw,
            number=number,
            street=street,
            cross_street=cross,
            zip=zip_code,
            city=default_city,
            number_alt=alts,
            relation=relation,
        )
    if not number and len(parts) >= 2:
        a, b = parts[0], parts[1]
        if a == b:
            return AddressQuery(
                key=f"unparsed|{a}",
                kind="unparsed",
                raw=raw,
                street=a,
                zip=zip_code,
                city=default_city,
                relation=relation,
                reason="same_street",
            )
        a, b = sorted((a, b))
        return AddressQuery(
            key=f"intersection|{a}|{b}|{zip_code or ''}",
            kind="intersection",
            raw=raw,
            street=a,
            street2=b,
            zip=zip_code,
            city=default_city,
            relation=relation,
        )
    reason = "no_number" if parts else "no_street"
    return AddressQuery(
        key=f"unparsed|{' AND '.join(parts)}",
        kind="unparsed",
        raw=raw,
        street=parts[0] if parts else None,
        zip=zip_code,
        city=default_city,
        relation=relation,
        reason=reason,
    )
