"""Standalone Leaflet map page. `site/index.html` fetches ../data/export/*.geojson;
`data/export/map.html` inlines the data so it opens from disk or can be shared."""

from __future__ import annotations

import json
from pathlib import Path

from plancheck.paths import EXPORT_DIR, SITE_DIR

TEMPLATE = SITE_DIR / "index.html"


def write_map_html(inline: bool) -> Path:
    html = TEMPLATE.read_text()
    if not inline:
        return TEMPLATE
    payload = {}
    for name in ("tracts", "hex_r8", "council_districts", "city_boundary"):
        p = EXPORT_DIR / f"{name}.geojson"
        if p.exists():
            payload[name] = json.loads(p.read_text())
    payload["meta"] = json.loads((EXPORT_DIR / "meta.json").read_text())
    payload["series"] = json.loads((EXPORT_DIR / "series.json").read_text())
    blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace("/*__INLINE_DATA__*/null", blob)
    out = EXPORT_DIR / "map.html"
    out.write_text(html)
    return out
