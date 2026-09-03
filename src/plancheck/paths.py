"""Canonical repository paths."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PARQUET_DIR = DATA_DIR / "parquet"
EXPORT_DIR = DATA_DIR / "export"
DUCKDB_PATH = DATA_DIR / "plancheck.duckdb"
MANIFEST_DIR = REPO_ROOT / "manifests"
KNOWN_ISSUES_DIR = REPO_ROOT / "known_issues"
CONFIG_DIR = REPO_ROOT / "config"
SOURCES_PATH = CONFIG_DIR / "sources.yaml"
ANALYSIS_CONFIG_PATH = CONFIG_DIR / "analysis.yaml"
FIG_DIR = REPO_ROOT / "analysis" / "figures"
SITE_DIR = REPO_ROOT / "site"
