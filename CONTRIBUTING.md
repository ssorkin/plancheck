# Contributing to plancheck

Everything here — downloaders, transforms, geocoding, checks, figures — is open, and every
number in a figure must be reproducible from this repository plus the public sources.

## Getting set up

```bash
git clone https://github.com/ssorkin/plancheck
cd plancheck
uv sync --extra dev
cp .env.example .env   # add CENSUS_API_KEY (free: https://api.census.gov/data/key_signup.html)
```

Pipeline (from the repo root):

```bash
uv run pc sources                 # what is registered, downloaded, ingested
uv run pc acquire                 # ~4 GB of CSV/GeoJSONL, manifests recorded
uv run pc ingest                  # Parquet + DuckDB views
uv run pc geocode                 # tier chain + spatial joins -> permits_geo
uv run pc check                   # DATA_QUALITY.md
uv run pc analyze                 # aggregates + analysis/figures/*.png
uv run pc export --inline         # data/export/*.geojson + map.html
uv run pytest && uv run ruff check src tests
```

`pc geocode-one "S/W CORNER OF X AVE and Y ST"` shows how a string is parsed and what each
locator returns — use it before changing the parser or acceptance rules.

## Repository map

| Path | Contents |
|---|---|
| `src/plancheck/ahj/` | AHJ abstraction; `la_city/` mappers + BOE geometry tier |
| `src/plancheck/acquire/` | Socrata exports, paginated ArcGIS layers, TIGER, ACS |
| `src/plancheck/ingest/` | CSV → Parquet, normalized schema, geometries, DuckDB views |
| `src/plancheck/geocode/` | address parser, locator client, cache, tier chain, spatial joins |
| `src/plancheck/quality/` | checks + DATA_QUALITY.md generator |
| `src/plancheck/analysis/` | intensity aggregates, ACS covariates, figures, exports, Leaflet |
| `config/` | `sources.yaml` (AHJ registry), `analysis.yaml` (tunables) |
| `manifests/`, `known_issues/` | provenance and documented data problems (committed) |
| `analysis/figures/` | rendered figures (committed) |
| `site/index.html` | standalone Leaflet map (reads `data/export/`) |

## Adding a data source or an AHJ

1. Register it in `config/sources.yaml`. A permit table needs `kind`, `dataset_id` or `url`,
   `permit_class`, `record_kind`, `mapper`, `partition_date`.
2. Write the mapper in `src/plancheck/ahj/<slug>/` producing the columns of
   `ingest/schema.py::PERMITS_SCHEMA` (missing ones are nulled by `conform`). Add a 3–5 row
   CSV fixture and a test like `tests/test_mappers.py`.
3. If the AHJ publishes its own permit geometries, add a `geometries` entry and a tier
   (see `BoeGeometryTier`); otherwise the generic `source_coords` + locator chain applies.
4. Run `pc acquire --source <slug>`, `pc ingest --source <slug>`, `pc geocode --source
   <slug> --dry-run`, then `pc check`. Document anything odd in `known_issues/`.

## The rules that keep the numbers honest

See `CLAUDE.md` § Hard rules. In short: trust coordinates only inside the bbox, accept
locator matches only with score ≥ 90 and a consistent match type, count issued permits
once, join geography spatially to fixed vintages, impute nothing, and put every data
problem in `known_issues/` rather than in code.

## Data licensing

Code is MIT. Source data is published by the City of Los Angeles (LADBS, Bureau of
Engineering, GeoHub), Los Angeles County (CAMS locator, Assessor) and the U.S. Census
Bureau under their respective open-data terms; derived aggregates are redistributed with
attribution.
