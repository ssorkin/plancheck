"""Load the committed YAML configuration (analysis tunables and the AHJ source registry)."""

from __future__ import annotations

from functools import lru_cache

import yaml

from plancheck.paths import ANALYSIS_CONFIG_PATH, SOURCES_PATH


@lru_cache(maxsize=1)
def analysis_config() -> dict:
    return yaml.safe_load(ANALYSIS_CONFIG_PATH.read_text())


@lru_cache(maxsize=1)
def sources_config() -> dict:
    return yaml.safe_load(SOURCES_PATH.read_text())
