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
args = [a for a in sys.argv[1:] if not a.startswith("--")]
STANDALONE = "--standalone" in sys.argv  # full document, dark by default, with a theme toggle
SITE_URL = "https://plancheck.sorkinlabs.com"
OUT = Path(args[0]) if args else EXPORT / "atlas.html"

cds = json.loads((EXPORT / "council_districts.geojson").read_text())
city = json.loads((EXPORT / "city_boundary.geojson").read_text())
series = json.loads((EXPORT / "series.json").read_text())
meta = json.loads((EXPORT / "meta.json").read_text())

# Trim properties to what the page uses; every geography shares one shape.
KEEP = ["n_permits", "n_new_building", "n_adu", "n_solar", "valuation_sum", "du_net"]
ORDER = [
    "tract",
    "lausd_elementary",
    "lausd_middle",
    "lausd_high",
    "neighborhood",
    "council_district",
    "zip",
]
geos = {}
for slug in ORDER:
    g = meta["geographies"].get(slug)
    if not g:
        continue
    fc = json.loads((EXPORT / g["file"]).read_text())
    for f in fc["features"]:
        p = f["properties"]
        slim = {"id": p["id"], "name": p["name"], "area_km2": p["area_km2"]}
        for k in ("pop", "housing_units"):
            if k in p:
                slim[k] = p[k]
        for cls in ("building", "electrical", "mechanical", "right_of_way"):
            if cls in p:
                slim[cls] = {
                    y: {k: v for k, v in yy.items() if k in KEEP} for y, yy in p[cls].items()
                }
        if "acs" in p:
            slim["acs"] = p["acs"]
        f["properties"] = slim
    geos[slug] = {"label": g["label"], "fc": fc}

cov = meta["geocode_coverage"]
total = sum(r["n"] for r in cov)
located = sum(r["n"] for r in cov if r["method"] != "none")
years = meta["config"]["years"]
payload = {
    "geos": geos,
    "cds": cds,
    "city": city,
    "series": series,
    "years": years,
    "generated": meta["generated"][:10],
    "total": total,
    "located": located,
}
blob = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")

leaflet_css = (
    ROOT / "site" / "leaflet.css"
).read_text()  # inlined: the page may be served under a CSP
html = (ROOT / "site" / "atlas_template.html").read_text()
html = html.replace("/*__LEAFLET_CSS__*/", leaflet_css).replace("/*__DATA__*/null", blob)
if not STANDALONE:
    # The artifact cannot read the parquet store; send clicks to the live site.
    html = html.replace('/*__DETAIL_BASE__*/"detail.html"', f'"{SITE_URL}/detail.html"')
    html = html.replace("/*__SHARE_BASE__*/null", f'"{SITE_URL}/"')
if STANDALONE:
    yr = f"{years['start']}–{years['end']}"
    og_desc = (
        "Building, trade and right-of-way permits across Los Angeles by tract, school area, "
        f"neighborhood, council district or ZIP, {yr}."
    )
    head = (
        "\n".join(
            [
                "<!doctype html>",
                '<html lang="en" data-theme="dark">',
                "<head>",
                '<meta charset="utf-8">',
                '<meta name="viewport" content="width=device-width, initial-scale=1">',
                f'<meta name="description" content="{og_desc}">',
                '<link rel="icon" href="data:image/svg+xml,'
                "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' "
                "font-size='90'%3E%F0%9F%8F%97%EF%B8%8F%3C/text%3E%3C/svg%3E\">",
                '<meta property="og:title" content="LA Permit Atlas">',
                f'<meta property="og:description" content="{og_desc}">',
                f'<meta property="og:image" content="{SITE_URL}/og/atlas.png">',
                '<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">',
                f'<meta property="og:url" content="{SITE_URL}/">',
                '<meta property="og:type" content="website">',
                '<meta name="twitter:card" content="summary_large_image">',
                '<script>try{const t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t;}catch(e){}</script>',
            ]
        )
        + "\n"
    )
    html = html.replace("<title>", head + "<title>", 1)
    html = html.replace("</title>", "</title>\n</head>\n<body>", 1) + "\n</body>\n</html>\n"
    html = html.replace(
        '<span class="toggle-slot"></span>',
        '<button id="theme" class="theme" type="button" aria-label="Switch theme">Light</button>',
    )
OUT.write_text(html)
print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB)")

if STANDALONE:
    # Detail page (client-side; reads data/detail/ from the same site).
    dhtml = (ROOT / "site" / "detail_template.html").read_text()
    dmeta = {
        "years": years,
        "generated": meta["generated"],
        "geographies": {k: {"label": v["label"]} for k, v in meta["geographies"].items()},
    }
    dhtml = dhtml.replace("/*__LEAFLET_CSS__*/", leaflet_css).replace(
        "/*__META__*/null", json.dumps(dmeta, separators=(",", ":")).replace("</", "<\\/")
    )
    dhead = head.replace(
        '<meta property="og:url" content="' + SITE_URL + '/">',
        '<meta property="og:url" content="' + SITE_URL + '/detail.html">',
    )
    dhtml = dhtml.replace("<title>", dhead + "<title>", 1)
    dhtml = dhtml.replace("</title>", "</title>\n</head>\n<body>", 1) + "\n</body>\n</html>\n"
    dout = OUT.parent / "detail.html"
    dout.write_text(dhtml)
    print(f"wrote {dout} ({dout.stat().st_size / 1e3:.0f} KB)")
