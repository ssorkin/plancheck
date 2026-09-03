"""Build a self-contained, shareable atlas page (data/export/atlas.html) from the exports.

Unlike site/index.html this page has no basemap tiles, so it works wherever external
images are blocked; the city outline and council districts give the context instead.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = ROOT / "data" / "export"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else EXPORT / "atlas.html"

tracts = json.loads((EXPORT / "tracts.geojson").read_text())
cds = json.loads((EXPORT / "council_districts.geojson").read_text())
city = json.loads((EXPORT / "city_boundary.geojson").read_text())
series = json.loads((EXPORT / "series.json").read_text())
meta = json.loads((EXPORT / "meta.json").read_text())

# Trim tract properties to what the page uses (building + right_of_way, listed metrics).
KEEP = ["n_permits", "n_new_building", "n_adu", "n_solar", "valuation_sum", "du_net"]
for f in tracts["features"]:
    p = f["properties"]
    slim = {"geoid": p["geoid"], "arealand_km2": p["arealand_km2"]}
    for cls in ("building", "electrical", "mechanical", "right_of_way"):
        if cls in p:
            slim[cls] = {y: {k: v for k, v in yy.items() if k in KEEP} for y, yy in p[cls].items()}
    if "acs" in p:
        slim["acs"] = p["acs"]
    f["properties"] = slim

cov = meta["geocode_coverage"]
total = sum(r["n"] for r in cov)
located = sum(r["n"] for r in cov if r["method"] != "none")
years = meta["config"]["years"]
payload = {"tracts": tracts, "cds": cds, "city": city, "series": series,
           "years": years, "generated": meta["generated"][:10],
           "total": total, "located": located}
blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

leaflet_css = (ROOT / "site" / "leaflet.css").read_text()  # inlined: the page may be served under a CSP
html = (ROOT / "site" / "atlas_template.html").read_text()
html = html.replace("/*__LEAFLET_CSS__*/", leaflet_css).replace("/*__DATA__*/null", blob)
OUT.write_text(html)
print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")
