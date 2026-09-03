# Data Quality Report

Generated 2026-09-03 by `pc check`. Problems in the source data are surfaced here and in `known_issues/`, never silently patched.

## Known issues (documented registry)

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

- 🟡 **2020** census tract: spatial join disagrees with the source field on 15.8% of 51,824 located permits
- 🟡 **2021** census tract: spatial join disagrees with the source field on 15.4% of 57,337 located permits
- 🟡 **2022** census tract: spatial join disagrees with the source field on 12.4% of 65,204 located permits
- ℹ️ census tract: worst year 2020 at 15.8% disagreement
- ℹ️ council district: worst year 2021 at 8.5% disagreement
### coord_coverage

- ℹ️ no source-year with >5% missing source coordinates
### geocode_rates

- ℹ️ unlocated by reason: unmatched=607, out_of_bbox=3
- ℹ️ **ladbs_building_issued_2020** 99.9% located: source=409,009, none=610
### manifest

- ℹ️ all manifest entries present and sized
### permit_id_unique

- ℹ️ permit_id unique within every source
### row_counts

- ℹ️ **ladbs_building_issued_2020** 409,619 rows = portal count
### valuation_outliers

- ℹ️ largest declared valuations (kept as published)
  - 1,966,896,355 — 25014-10000-03198 (ladbs_building_issued_2020) 500 WORLD WAY
  - 554,147,741 — 21014-10000-03646 (ladbs_building_issued_2020) 400 WORLD WAY
  - 375,000,000 — 24010-10000-03878 (ladbs_building_issued_2020) 1301 S FIGUEROA ST
  - 333,103,645 — 25014-10002-03198 (ladbs_building_issued_2020) 500 WORLD WAY
  - 300,000,000 — 17010-10000-03447 (ladbs_building_issued_2020) 1950 S AVENUE OF THE STARS
