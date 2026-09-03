# plancheck — project conventions

Open-source pipeline for building, trade (electrical/mechanical) and right-of-way permits
from Los Angeles-area AHJs (authorities having jurisdiction), geocoded with provenance and
mapped. Plan of record: `acquire → ingest → geocode → check → analyze → export` in Python;
visualization is Python-first (matplotlib figures + GeoJSON exports + a standalone Leaflet
page in `site/index.html`). AHJs are pluggable: `config/sources.yaml` + `src/plancheck/ahj/<slug>/`.

## Commands

- `uv sync --extra dev` — install; `uv run pc --help` — pipeline CLI:
  `sources`, `acquire [--family permits|geometries|reference|covariates|tiger|census] [--refresh]`,
  `ingest`, `geocode [--dry-run] [--no-network] [--limit N]`, `geocode-one "<string>"`,
  `check [--strict]`, `analyze [--no-figures]`, `export [--inline]`. All take `--ahj` and most
  `--source <slug|family>`.
- `uv run pytest` — tests (no network; fixtures in `tests/fixtures/`); `uv run ruff check src tests`.
- Keys: `SOCRATA_APP_TOKEN` (optional) and `CENSUS_API_KEY` (required for ACS) in the
  environment or a git-ignored `.env`.
- Site: `scripts/build_atlas.py --standalone data/site/index.html` builds the LA Permit Atlas
  (dark by default, theme toggle) and `detail.html`, the per-area permit list. The detail
  page reads `data/detail/permits.parquet` (one file, sorted by H3 r9, 8,192-row groups,
  zstd) through `index_<geo>.json` (area id → row groups) with HTTP range requests via the
  vendored hyparquet build in `site/vendor/` — no server-side query. `analysis/detail.py`
  writes the store; the map's URL hash is the permalink; `scripts/og_image.py` renders the
  social card; `scripts/deploy.sh [--no-build] [--no-verify]` rsyncs
  `data/site/` to dronesclub `/var/www/plancheck-releases/<ts>/`, swaps the
  `/var/www/plancheck-current` symlink (`ln -s` + `mv -T`), prunes to 3, verifies
  https://plancheck.sorkinlabs.com (Cloudflare-proxied; nginx config in `contrib/nginx/`,
  cert via certbot webroot). NEVER `rsync --delete` into the live root.
- Weekly refresh: `scripts/refresh.sh` (acquire --refresh → … → export; add `scripts/deploy.sh`
  after it when scheduling).
- Full rebuild from nothing: `pc acquire` (~4 GB, ~40 min) → `pc ingest` → `pc geocode`
  (network for unmatched strings only; cached in `data/parquet/geocode_cache/`) → `pc check`
  → `pc analyze` → `pc export --inline`.

## Hard rules (data integrity)

- **Source coordinates are trusted only inside the AHJ bbox and never 0/0; a lat/lon swap
  is flagged (`swapped_axes`), never auto-fixed.** Every located row carries
  `geocode_method` (source | boe_point | boe_line_centroid | boe_polygon_centroid | cams |
  centerline | none), score, match type and reason. Coverage by method is a published
  figure and a `pc check` finding.
- **A locator match counts only if score ≥ `geocode.min_score` (90), the point is inside
  the bbox, and the match type agrees with the parsed kind** (intersection → `StreetInt`;
  address → `PointAddress`/`StreetAddress`/`Subaddress`). "118TH PLACE and BROADWAY AVE" →
  "118 Palace St" (score 87) is the canonical false positive this rule exists for.
- **Net dwelling units means completed units.** `du_net` sums `dwelling_units_change` only
  over permits that reached a certificate of occupancy (`final_date`) or demolitions with
  status "Permit Finaled", bucketed by *completion* year (`analysis/intensity.py:
  completions_sql`). The declared change on every issued permit is a separate metric,
  `du_permitted`, by issue year. Never present the latter as units built.
- **Issued only, deduplicated.** Aggregates use `record_kind='issued'` and one row per
  `(ahj, permit_id)` (latest `refresh_time`); submitted tables describe the same permits
  earlier in life. Never sum issued + submitted.
- **Geography is joined spatially to fixed vintages** (2020 tracts, current council
  districts, CPA, NC); the source's own `*_src` fields are kept for audit and the
  disagreement rate is reported by year (redistricting shows up as steps, not errors).
- **Nothing is imputed.** Unlocated permits are `n_unlocated` in every aggregate;
  valuations are heavy-tailed and published as sums and medians, never trimmed.
- **Raw is lossless.** `permits_raw` keeps every source column as text; `permits` is the
  normalized view; mappers must not drop information, only add typed columns.
- **Every download has a manifest entry** (URL, sha256, size, ETag/Last-Modified, and for
  Socrata the portal's `count(*)` at download time); `pc check` compares ingested rows to it.
- Data problems go in `known_issues/` and `DATA_QUALITY.md` — never silently patched.
- `data/` is gitignored; `manifests/`, `known_issues/`, `analysis/figures/` are committed.

## Style

- Python 3.12+, ruff (line length 100), typer CLI with lazy imports, polars for ingest,
  DuckDB views over Parquet (never a store of record), shapely + GeoJSON (no geopandas, no
  shapefiles), matplotlib Agg figures using the reference dataviz palette in
  `analysis/geo_plot.py` (one sequential hue for magnitude, blue–red with gray midpoint for
  polarity, fixed categorical order).
- Per-capita denominators come from 2020 census blocks (`analysis/population.py`: block
  internal points summed within each geography, P.L. 94-171 POP100/HU100); the atlas
  defaults to per 1,000 residents and leaves areas under 100 residents unshaded.
- Areas and rates are imperial: acres and per-acre, never km² (internal `area_km2`
  fields are converted at display time, 247.105 acres per km²).
- Copy describes associations ("correlated with"), never causes; the final year is
  labelled partial.
- Adding an AHJ: one block in `config/sources.yaml` (sources, geometries, reference,
  covariates, geocoders, chain) + `src/plancheck/ahj/<slug>/__init__.py` exporting
  `MAPPERS` and `build_tiers`. Stage code never special-cases a slug.
