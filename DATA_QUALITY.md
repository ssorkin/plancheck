# Data Quality Report

Generated 2026-09-03 by `pc check`. Problems in the source data are surfaced here and in `known_issues/`, never silently patched.

## Known issues (documented registry)

### BOE Permits Geocoder sublayer 61 ("U Permits Polygons") answers 502 on every query

*source-outage, affects la_city_boe_geocoder 2026* — id `boe-geocoder-layer-61-unavailable`

The city's map service returns HTTP 502 for layer 61 (U Permits Polygons, about 2,000 features) on count and feature queries, across retries and repeated runs on 2026-09-03, while the other 47 permit sublayers download normally.

**Handling:** The layer is skipped and reported by pc acquire; affected excavation permits fall through to the CAMS and centerline locators on their location string. Rerun `pc acquire --family geometries` to pick the layer up once the service recovers.

### BOE permit locations are free text (addresses, intersections, corners, ranges)

*schema, affects boe_permits 1987, 2026* — id `boe-location-free-text`

The Bureau of Engineering table (j7mw-thyc) has no coordinates. LOCATION is typed by staff: "5249 N VANALDEN AVE", "Texas Ave and Ohio Ave", "S/W CORNER OF VIRGINA AVE and AND ST ANDREWS PL", "619,621,623 TOWNE AVE. and E. 6TH ST", "F 6615 FRANKLIN AVE", or descriptions with no street ("FORREST LAWN 225` E/O MH 8340"). 979 rows are null.

**Handling:** Two-step: (1) join to the city's own BOE Permits Geocoder map service by RefNo, which carries points/lines/polygons for ~603k of 636k permits; (2) parse the string (geocode/address.py) into an address or intersection and query the county CAMS locator, then the city centerline locator, accepting only score >= 90 with a match type consistent with the parsed kind. Unparseable strings stay unlocated with a reason code.

### BOE PermitNo is not unique; ID (type + RefNo) is the row key

*key, affects boe_permits 1987, 2026* — id `boe-permitno-not-unique`

635,754 rows carry 597,599 distinct PermitNo values but 635,754 distinct ID values. Several permit types share numbering, and a permit can be re-issued under the same number.

**Handling:** permit_id = ID; permit_ref = RefNo (the join key to the geometry service). Aggregates count rows, i.e. permit records, not distinct PermitNo values.

### Council district boundaries were redrawn in 2012 and 2022; source CD fields reflect the boundaries at issue time

*vintage, affects la_city_reference/council_districts, ladbs CD column 2000, 2026* — id `council-district-vintage`

LADBS assigns CD when a permit is processed, so historical rows carry whichever district map was in force. The pipeline's spatial join uses the current boundaries from maps.lacity.org (Mapping/Boundaries layer 4, which carries Effective/Revised dates). The GeoHub "Council_Districts" feature service still lists pre-2022 members and is not used.

**Handling:** Both fields are kept: council_district_src (as published) and council_district (current boundaries). Time series by district use the current boundaries so every year is on the same map; the disagreement rate is published in DATA_QUALITY.md.

### LADBS census tract (CT) is assigned at processing time and may predate the 2020 tract vintage

*vintage, affects ladbs CT column 2000, 2026* — id `ladbs-ct-tract-vintage`

CT values such as "1173.01" match 2010 or 2020 tract codes depending on when the record was processed. The pipeline joins every located permit to 2020 TIGER tracts spatially and keeps the source value as tract_src.

**Handling:** All tract-level analysis uses the spatially joined 2020 tract_geoid; tract_src is retained for auditing only.

### Pre-2010 LADBS permits lack coordinates on roughly 3–5% of rows

*coverage-gap, affects ladbs_building_issued_pre2010, ladbs_mechanical_issued_pre2010, ladbs_electrical_issued_pre2010 1990, 2009* — id `ladbs-null-coordinates-pre2010`

The LADBS exports carry LAT/LON assigned by the department (TYPE_LAT_LON = ADDRESS, BUILDING or PIN). For permits issued before 2010 about 3.4% of building rows (21,889 of 639,942) and 4.8% of mechanical rows (28,281 of 583,619) have no coordinates, versus 0.15% for 2020-present. Older address strings are also less standardized.

**Handling:** Rows without source coordinates fall through the geocode chain (CAMS then the city centerline locator) using PRIMARY_ADDRESS + ZIP_CODE; the resulting geocode_method and score travel with the row, and pc check reports coverage by source and year. Nothing is imputed; unlocated permits are counted as n_unlocated in every aggregate.

### Submitted and issued tables describe the same permits at different stages

*double-counting, affects ladbs *_submitted and *_issued families 1990, 2026* — id `ladbs-submitted-vs-issued-overlap`

A permit that was submitted and later issued appears in both the Submitted and Issued datasets (same PERMIT_NBR). Era datasets within a family can also overlap at the boundaries.

**Handling:** Intensity aggregates use record_kind = 'issued' only and deduplicate on (ahj, permit_id) keeping the latest refresh_time. Submitted rows are retained for pipeline/lead-time analysis only.

### LADBS tables are replaced wholesale every week; row histories are not retained upstream

*provenance, affects all LADBS datasets 2026* — id `socrata-weekly-full-refresh`

Every row carries the same REFRESH_TIME and Socrata :updated_at after each weekly load, so status changes (issued -> finaled -> expired) overwrite earlier states and incremental pulls are impossible. The BOE table refreshes daily the same way.

**Handling:** pc acquire downloads full snapshots with ETag/Last-Modified conditional requests and records sha256 + the portal's count(*) in manifests/socrata.json. Status-transition analysis would require keeping dated snapshots (not done in v1).

## Check findings

### admin_disagreement

- 🟡 **census tract** spatial join disagrees with the source field on >10% of located permits in 27 year(s): 1996–2022 (max 55%); expected where the source vintage predates the current boundaries — see known_issues
- 🟡 **council district** spatial join disagrees with the source field on >10% of located permits in 18 year(s): 1996–2013 (max 40%); expected where the source vintage predates the current boundaries — see known_issues
### coord_coverage

- 🟡 **ladbs_building_issued_pre2010** >5% of permits lack source coordinates in 4 year(s) 1998–2001 (max 7%); these rows go through the locator chain
- 🟡 **ladbs_building_submitted_pre2010** >5% of permits lack source coordinates in 7 year(s) 1996–2002 (max 21%); these rows go through the locator chain
- 🟡 **ladbs_electrical_issued_pre2010** >5% of permits lack source coordinates in 7 year(s) 1996–2002 (max 18%); these rows go through the locator chain
- 🟡 **ladbs_electrical_submitted_pre2010** >5% of permits lack source coordinates in 8 year(s) 1997–2004 (max 17%); these rows go through the locator chain
- 🟡 **ladbs_mechanical_issued_pre2010** >5% of permits lack source coordinates in 6 year(s) 1996–2001 (max 19%); these rows go through the locator chain
- 🟡 **ladbs_mechanical_submitted_pre2010** >5% of permits lack source coordinates in 10 year(s) 1996–2005 (max 31%); these rows go through the locator chain
### admin_disagreement

- ℹ️ **census tract** recent years — 2019: 18.0%, 2020: 16.8%, 2021: 16.8%, 2022: 11.8%, 2023: 2.2%, 2024: 1.4%, 2025: 1.0%, 2026: 0.8%
- ℹ️ **council district** recent years — 2019: 8.5%, 2020: 8.0%, 2021: 8.0%, 2022: 1.6%, 2023: 0.8%, 2024: 0.6%, 2025: 0.5%, 2026: 0.3%
### date_sanity

- ℹ️ 123 permits issued before their submitted date
### geocode_rates

- ℹ️ unlocated by reason: unmatched=21,942, low_score=11,398
- ℹ️ **boe_permits** 98.1% located: boe_point=475,227, cams=110,002, boe_line_centroid=36,357, none=11,989, centerline=1,400, boe_polygon_centroid=779
- ℹ️ **ladbs_building_issued_2010** 100.0% located: source=532,656, cams=359, none=244, centerline=108
- ℹ️ **ladbs_building_issued_2020** 100.0% located: source=409,009, cams=409, none=175, centerline=26
- ℹ️ **ladbs_building_issued_pre2010** 99.5% located: source=618,053, cams=18,487, none=2,939, centerline=463
- ℹ️ **ladbs_building_submitted_2010** 99.8% located: source=426,290, none=1,065, cams=448, centerline=93
- ℹ️ **ladbs_building_submitted_2020** 99.9% located: source=302,776, none=431, cams=385, centerline=25
- ℹ️ **ladbs_building_submitted_pre2010** 99.2% located: source=327,013, cams=12,244, none=2,724, centerline=341
- ℹ️ **ladbs_electrical_issued_2010** 100.0% located: source=390,801, cams=267, none=163, centerline=76
- ℹ️ **ladbs_electrical_issued_2020** 100.0% located: source=357,178, cams=316, none=57, centerline=37
- ℹ️ **ladbs_electrical_issued_pre2010** 98.6% located: source=341,938, cams=13,678, none=4,957, centerline=479
- ℹ️ **ladbs_electrical_submitted_2010** 99.8% located: source=77,398, cams=189, none=176, centerline=16
- ℹ️ **ladbs_electrical_submitted_2020** 99.9% located: source=77,670, cams=145, none=57, centerline=20
- ℹ️ **ladbs_electrical_submitted_pre2010** 98.6% located: source=36,259, cams=1,837, none=531, centerline=42
- ℹ️ **ladbs_mechanical_issued_2010** 99.9% located: source=502,213, cams=587, none=252, centerline=229
- ℹ️ **ladbs_mechanical_issued_2020** 100.0% located: source=294,973, cams=310, none=120, centerline=29
- ℹ️ **ladbs_mechanical_issued_pre2010** 99.0% located: source=555,338, cams=21,863, none=5,881, centerline=537
- ℹ️ **ladbs_mechanical_submitted_2010** 99.7% located: source=88,190, cams=444, none=310, centerline=210
- ℹ️ **ladbs_mechanical_submitted_2020** 99.8% located: source=64,354, cams=190, none=102, centerline=16
- ℹ️ **ladbs_mechanical_submitted_pre2010** 97.9% located: source=49,221, cams=4,197, none=1,167, centerline=189
### manifest

- ℹ️ all manifest entries present and sized
### permit_id_unique

- ℹ️ permit_id unique within every source
### row_counts

- ℹ️ **boe_permits** 635,754 rows = portal count
- ℹ️ **ladbs_building_issued_2010** 533,367 rows = portal count
- ℹ️ **ladbs_building_issued_2020** 409,619 rows = portal count
- ℹ️ **ladbs_building_issued_pre2010** 639,942 rows = portal count
- ℹ️ **ladbs_building_submitted_2010** 427,896 rows = portal count
- ℹ️ **ladbs_building_submitted_2020** 303,617 rows = portal count
- ℹ️ **ladbs_building_submitted_pre2010** 342,322 rows = portal count
- ℹ️ **ladbs_electrical_issued_2010** 391,307 rows = portal count
- ℹ️ **ladbs_electrical_issued_2020** 357,588 rows = portal count
- ℹ️ **ladbs_electrical_issued_pre2010** 361,052 rows = portal count
- ℹ️ **ladbs_electrical_submitted_2010** 77,779 rows = portal count
- ℹ️ **ladbs_electrical_submitted_2020** 77,892 rows = portal count
- ℹ️ **ladbs_electrical_submitted_pre2010** 38,669 rows = portal count
- ℹ️ **ladbs_mechanical_issued_2010** 503,281 rows = portal count
- ℹ️ **ladbs_mechanical_issued_2020** 295,432 rows = portal count
- ℹ️ **ladbs_mechanical_issued_pre2010** 583,619 rows = portal count
- ℹ️ **ladbs_mechanical_submitted_2010** 89,154 rows = portal count
- ℹ️ **ladbs_mechanical_submitted_2020** 64,662 rows = portal count
- ℹ️ **ladbs_mechanical_submitted_pre2010** 54,774 rows = portal count
### valuation_outliers

- ℹ️ largest declared valuations (kept as published)
  - 1,966,896,355 — 25014-10000-03198 (ladbs_building_issued_2020) 500 WORLD WAY
  - 1,966,896,355 — 25014-10000-03198 (ladbs_building_submitted_2020) 500 WORLD WAY
  - 1,547,436,478 — 25010-10000-02100 (ladbs_building_submitted_2020) 6100 N TOPANGA CANYON BLVD
  - 1,332,414,581 — 25014-10001-03198 (ladbs_building_submitted_2020) 500 WORLD WAY
  - 992,724,830 — 26010-10000-01776 (ladbs_building_submitted_2020) 6400 N CANOGA AVE
