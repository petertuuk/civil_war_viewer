"""Assemble the public website (GitHub Pages) from the viewer and its data.

    python3 pipeline/build_site.py [out_dir=site] [--url https://civilwar.petertuuk.com/] [--cname civilwar.petertuuk.com]

Copies viewer/war/index.html and viewer/war/data/* (built by `rebuild.sh war`) plus viewer/site/* (About page, icon,
preview image, self-hosted fonts and MapLibre) into out_dir. In the page, the Google Fonts and cdnjs links become the
local copies, and the preview tags (Open Graph) are added, with absolute URLs when --url is given. Writes .nojekyll
(serve files as they are) and CNAME for a custom domain. Nothing is fetched from the network.
deploy_site.sh runs this and publishes out_dir to the gh-pages branch.
"""
import argparse
import re
import shutil
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TITLE = "Civil War, Day by Day"
DESC = ("Where every regiment, battery and company of the American Civil War was, day by day, 1861-1865: "
        "a map with a timeline, drawn from Dyer's Compendium, the Official Records and other sources.")


def page(html, url):
    n = len(html)
    html = re.sub(r'<link rel="preconnect" href="https://fonts\.googleapis\.com">\s*\n?', "", html)
    html = re.sub(r'<link href="https://fonts\.googleapis\.com/css2[^"]*" rel="stylesheet">',
                  '<link rel="stylesheet" href="fonts/fonts.css">', html)
    html = re.sub(r'<script src="https://cdnjs\.cloudflare\.com/ajax/libs/maplibre-gl/[^"]*/maplibre-gl\.js"></script>',
                  '<script src="vendor/maplibre-gl.js"></script>', html)
    if "fonts/fonts.css" not in html or "vendor/maplibre-gl.js" not in html:
        raise SystemExit("build_site: could not replace the font or MapLibre links in index.html")
    base = url.rstrip("/") + "/" if url else ""
    og = [f'<meta property="og:type" content="website">',
          f'<meta property="og:title" content="{escape(TITLE)}">',
          f'<meta property="og:description" content="{escape(DESC)}">',
          f'<meta property="og:image" content="{base}og.png">',
          '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
          '<meta name="twitter:card" content="summary_large_image">']
    if base:
        og.insert(0, f'<meta property="og:url" content="{base}">')
        og.append(f'<link rel="canonical" href="{base}">')
    html = html.replace("</title>\n", "</title>\n" + "\n".join(og) + "\n", 1)
    assert len(html) > n * 0.9
    return html


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out", nargs="?", default="site")
    ap.add_argument("--url", default="", help="public address, for absolute preview-image links")
    ap.add_argument("--cname", default="", help="custom domain for GitHub Pages (writes CNAME)")
    a = ap.parse_args()
    out = Path(a.out)
    if not out.is_absolute():
        out = ROOT / out
    if out.exists():
        shutil.rmtree(out)
    data = ROOT / "viewer" / "war" / "data"
    need = ["units.json", "backdrop.json", "activity.json", "basemap.json", *[f"y{y}.json" for y in range(1861, 1866)]]
    missing = [f for f in need if not (data / f).exists()]
    if missing:
        raise SystemExit(f"build_site: missing {missing} in {data}: run `bash pipeline/rebuild.sh war` first")
    shutil.copytree(ROOT / "viewer" / "site", out)
    shutil.copytree(data, out / "data", ignore=shutil.ignore_patterns("*.tmp", "*_before_*"))
    src = (ROOT / "viewer" / "war" / "index.html").read_text(encoding="utf-8")
    (out / "index.html").write_text(page(src, a.url), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    if a.cname:
        (out / "CNAME").write_text(a.cname.strip() + "\n")
    files = [p for p in out.rglob("*") if p.is_file()]
    print(f"site: {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB in {out}")


if __name__ == "__main__":
    main()
