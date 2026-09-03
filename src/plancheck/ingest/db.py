"""Build the DuckDB database as views over the Parquet store (never a store of record)."""

from __future__ import annotations

import duckdb

from plancheck.paths import DUCKDB_PATH, PARQUET_DIR


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    DUCKDB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DUCKDB_PATH), read_only=read_only)


def build() -> list[str]:
    con = connect()
    pq = str(PARQUET_DIR)
    made: list[str] = []

    def view(name: str, glob: str, hive: bool = True, sql: str | None = None) -> bool:
        root = PARQUET_DIR / glob.split("/")[0]
        if not root.exists() or not any(root.rglob("*.parquet")):
            return False
        src = sql or (
            f"SELECT * FROM read_parquet('{pq}/{glob}', union_by_name=true, "
            f"hive_partitioning={'true' if hive else 'false'})"
        )
        con.execute(f"CREATE OR REPLACE VIEW {name} AS {src}")
        made.append(name)
        return True

    view("permits_raw", "permits_raw/ahj=*/source=*/year=*/data.parquet")
    have_norm = view("permits_norm", "permits/ahj=*/source=*/year=*/data.parquet")
    have_geo = view("permits_geo", "permits_geo/ahj=*/source=*/data.parquet")
    if have_norm and have_geo:
        con.execute(
            """
            CREATE OR REPLACE VIEW permits AS
            SELECT n.*, g.* EXCLUDE (ahj, source, permit_id, source_dataset)
            FROM permits_norm n
            LEFT JOIN permits_geo g
              ON n.ahj = g.ahj AND n.source_dataset = g.source_dataset
             AND n.permit_id = g.permit_id
            """
        )
        made.append("permits")
    elif have_norm:
        con.execute("CREATE OR REPLACE VIEW permits AS SELECT * FROM permits_norm")
        made.append("permits")
    view("boe_geom", "boe_geom/ahj=*/layer=*/data.parquet")
    view("ref_layers", "ref/ahj=*/layer=*/data.parquet")
    view("tracts", "tracts/data.parquet", hive=False)
    view("blocks", "blocks/data.parquet", hive=False)
    view("census_acs", "census_acs/*.parquet", hive=False)
    view("assessor", "assessor/*.parquet", hive=False)
    view("geocode_cache", "geocode_cache/geocoder=*/*.parquet")
    analysis_dir = PARQUET_DIR / "analysis"
    if analysis_dir.exists():
        for p in sorted(analysis_dir.glob("*.parquet")):
            con.execute(
                f"CREATE OR REPLACE VIEW analysis_{p.stem} AS SELECT * FROM read_parquet('{p}')"
            )
            made.append(f"analysis_{p.stem}")
    con.close()
    print(f"  views: {', '.join(made) or '(none)'}")
    return made
