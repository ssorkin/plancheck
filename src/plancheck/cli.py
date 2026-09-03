"""plancheck pipeline CLI: acquire → ingest → geocode → check → analyze → export."""

import typer

app = typer.Typer(no_args_is_help=True, help=__doc__)

AHJ_OPT = typer.Option("all", help="AHJ slug from config/sources.yaml, or all")
SOURCE_OPT = typer.Option("all", help="Source slug or family (e.g. ladbs_building_issued), or all")


@app.command()
def sources(ahj: str = AHJ_OPT) -> None:
    """List registered AHJs and sources with their download/ingest status."""
    from plancheck.acquire.runner import show_sources

    show_sources(ahj=ahj)


@app.command()
def acquire(
    ahj: str = AHJ_OPT,
    source: str = SOURCE_OPT,
    family: str = typer.Option(
        "all", help="permits | geometries | reference | covariates | tiger | census | all"
    ),
    refresh: bool = typer.Option(False, help="Re-check upstream (conditional GET / count)"),
    force: bool = typer.Option(False, help="Re-download even if cached"),
) -> None:
    """Download source files and record provenance manifests."""
    from plancheck.acquire.runner import run_acquire

    run_acquire(ahj=ahj, source=source, family=family, refresh=refresh, force=force)


@app.command()
def ingest(
    ahj: str = AHJ_OPT,
    source: str = SOURCE_OPT,
    family: str = typer.Option("all", help="permits | geometries | reference | census | all"),
) -> None:
    """Normalize raw files into Parquet and rebuild the DuckDB views."""
    from plancheck.ingest.runner import run_ingest

    run_ingest(ahj=ahj, source=source, family=family)


@app.command()
def geocode(
    ahj: str = AHJ_OPT,
    source: str = SOURCE_OPT,
    limit: int | None = typer.Option(None, help="Cap the number of locator queries"),
    no_network: bool = typer.Option(False, help="Use cached geocodes only"),
    dry_run: bool = typer.Option(False, help="Report tier counts without writing"),
    compact: bool = typer.Option(False, help="Merge geocode cache parts"),
) -> None:
    """Resolve a location for every permit (source coords → AHJ geometry → locators)."""
    from plancheck.geocode.runner import run_geocode

    run_geocode(
        ahj=ahj,
        source=source,
        limit=limit,
        no_network=no_network,
        dry_run=dry_run,
        compact=compact,
    )


@app.command("geocode-one")
def geocode_one(
    text: str = typer.Argument(..., help="A raw location string"),
    ahj: str = typer.Option("la_city"),
    geocoder: str = typer.Option("", help="Locator name from config (default: all)"),
) -> None:
    """Parse one location string and query the locators live (debugging aid)."""
    from plancheck.geocode.runner import geocode_one as run

    run(text=text, ahj=ahj, geocoder=geocoder)


@app.command()
def check(
    strict: bool = typer.Option(False, help="Exit 1 on anomalies"),
    verify_hashes: bool = typer.Option(False, help="Re-hash every raw file"),
) -> None:
    """Run data-quality checks and regenerate DATA_QUALITY.md."""
    from plancheck.quality.runner import run_checks

    findings = run_checks(verify_hashes=verify_hashes)
    if strict and any(f.severity == "anomaly" for f in findings):
        raise typer.Exit(code=1)


@app.command()
def analyze(
    ahj: str = AHJ_OPT,
    figures: bool = typer.Option(True, help="Render figures to analysis/figures/"),
) -> None:
    """Compute development-intensity aggregates and covariate joins; render figures."""
    from plancheck.analysis.runner import run_analysis

    run_analysis(ahj=ahj, figures=figures)


@app.command()
def export(
    inline: bool = typer.Option(False, help="Also write data/export/map.html with data inlined"),
) -> None:
    """Write GeoJSON/JSON for the map page (and optionally a self-contained map.html)."""
    from plancheck.analysis.export import run_export

    run_export(inline=inline)


if __name__ == "__main__":
    app()
