"""
Pregacuore - verify_landscapes.py
====================================

Genera una pagina HTML statica (`assets/landscapes_preview.html`) che mostra
in griglia tutti i paesaggi scaricati in `assets/landscapes/`, ciascuno con
slug, artista, titolo, e una nota se il file non e' presente.

Serve a verificare VISIVAMENTE che i quadri scaricati siano davvero quelli
attesi, prima di lanciare la generazione delle card. Il search fallback di
Wikimedia talvolta scarica file diversi dal quadro corretto (homonim, studi,
schizzi); con questa pagina li trovi subito.

USO:
    python verify_landscapes.py
    # poi apri il file con: open assets/landscapes_preview.html

CONTROLLO:
    - Manifest dichiara N paesaggi
    - Per ognuno verifico file <slug>_post.png, <slug>_pinterest.png, <slug>_story.png
    - Conto mancanti
    - Genero HTML con thumb 250x250, etichette, e segnalazione mancanti

OUTPUT:
    assets/landscapes_preview.html  (auto-contenuto, immagini path relativi)
"""
from __future__ import annotations

import argparse
import sys
import html
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPT_DIR / "assets"
MANIFEST_PATH = ASSETS_DIR / "landscape_manifest.yml"
LANDSCAPES_DIR = ASSETS_DIR / "landscapes"
OUTPUT_HTML = ASSETS_DIR / "landscapes_preview.html"


def render_html(entries: list, missing_count: int) -> str:
    """Genera HTML auto-contenuto con griglia di paesaggi."""
    cards_html = []
    for entry in entries:
        slug = entry["slug"]
        artist = html.escape(entry.get("artist", ""))
        title = html.escape(entry.get("title", ""))
        year = entry.get("year", "")
        moods = ", ".join(entry.get("moods", []))
        reserve = entry.get("reserve", False)

        # File post per il preview (1080x1080, piu' rappresentativo)
        post = LANDSCAPES_DIR / f"{slug}_post.png"
        pinterest = LANDSCAPES_DIR / f"{slug}_pinterest.png"
        story = LANDSCAPES_DIR / f"{slug}_story.png"

        # Stato dei file
        post_ok = post.exists()
        pin_ok = pinterest.exists()
        story_ok = story.exists()
        all_ok = post_ok and pin_ok and story_ok

        # Img tag (path relativo da assets/ → landscapes/<file>)
        if post_ok:
            img_html = f'<img src="landscapes/{slug}_post.png" alt="{slug}" />'
        elif pin_ok:
            img_html = f'<img src="landscapes/{slug}_pinterest.png" alt="{slug}" />'
        else:
            img_html = '<div class="missing-img">FILE MANCANTE</div>'

        status_badges = []
        if not post_ok: status_badges.append('<span class="badge bad">post</span>')
        if not pin_ok: status_badges.append('<span class="badge bad">pinterest</span>')
        if not story_ok: status_badges.append('<span class="badge bad">story</span>')
        if reserve: status_badges.append('<span class="badge reserve">RISERVA</span>')

        status_html = "".join(status_badges)
        card_class = "card" + (" missing" if not all_ok else "")
        cards_html.append(f"""
            <div class="{card_class}">
                <div class="thumb">{img_html}</div>
                <div class="info">
                    <div class="slug">{html.escape(slug)}</div>
                    <div class="title">{title}</div>
                    <div class="artist">{artist}{', ' + str(year) if year else ''}</div>
                    <div class="moods">{html.escape(moods)}</div>
                    <div class="status">{status_html}</div>
                </div>
            </div>
        """)

    total = len(entries)
    ok_count = total - missing_count

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Pregacuore - Landscape Preview ({total} paesaggi)</title>
<style>
    * {{ box-sizing: border-box; }}
    body {{
        margin: 0;
        padding: 24px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: #F5E6D3;
        color: #3A3A3F;
    }}
    h1 {{
        color: #722F37;
        margin: 0 0 8px;
        font-size: 28px;
    }}
    .summary {{
        margin-bottom: 24px;
        padding: 12px 16px;
        background: white;
        border-radius: 4px;
        border-left: 4px solid #D4A954;
    }}
    .summary .ok {{ color: #2a7a3a; }}
    .summary .bad {{ color: #b53030; font-weight: 600; }}
    .grid {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
        gap: 16px;
    }}
    .card {{
        background: white;
        border-radius: 6px;
        overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .card.missing {{
        border: 2px solid #b53030;
    }}
    .thumb {{
        width: 100%;
        aspect-ratio: 1 / 1;
        background: #ddd;
        overflow: hidden;
    }}
    .thumb img {{
        width: 100%;
        height: 100%;
        object-fit: cover;
        display: block;
    }}
    .missing-img {{
        display: flex;
        align-items: center;
        justify-content: center;
        height: 100%;
        color: #b53030;
        font-weight: 600;
        background: #f5e6e6;
    }}
    .info {{
        padding: 12px 14px;
    }}
    .slug {{
        font-family: monospace;
        font-size: 12px;
        color: #888;
        margin-bottom: 4px;
    }}
    .title {{
        font-weight: 600;
        font-size: 15px;
        margin-bottom: 2px;
        line-height: 1.3;
    }}
    .artist {{
        font-size: 13px;
        color: #555;
        font-style: italic;
        margin-bottom: 6px;
    }}
    .moods {{
        font-size: 11px;
        color: #888;
        margin-bottom: 8px;
    }}
    .badge {{
        display: inline-block;
        padding: 2px 6px;
        border-radius: 3px;
        font-size: 10px;
        font-weight: 600;
        margin-right: 4px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }}
    .badge.bad {{ background: #b53030; color: white; }}
    .badge.reserve {{ background: #888; color: white; }}
</style>
</head>
<body>
<h1>Pregacuore - Landscape Preview</h1>
<div class="summary">
    <span class="ok">{ok_count} paesaggi completi</span>
    {' | <span class="bad">' + str(missing_count) + ' con file mancanti</span>' if missing_count else ''}
    | Totale manifest: {total}
</div>
<div class="grid">
{"".join(cards_html)}
</div>
</body>
</html>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH,
                        help=f"Path al manifest YAML (default: {MANIFEST_PATH})")
    parser.add_argument("--output", type=Path, default=OUTPUT_HTML,
                        help=f"Path output HTML (default: {OUTPUT_HTML})")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"X  Manifest non trovato: {args.manifest}")
        sys.exit(1)

    with open(args.manifest, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    entries = data.get("landscapes", []) or []

    # Conta mancanti
    missing = 0
    for e in entries:
        slug = e["slug"]
        files = [LANDSCAPES_DIR / f"{slug}_{kind}.png"
                 for kind in ("post", "story", "pinterest")]
        if not all(f.exists() for f in files):
            missing += 1

    html_content = render_html(entries, missing)
    args.output.write_text(html_content, encoding="utf-8")
    print(f"OK Preview generata: {args.output}")
    print(f"   {len(entries) - missing}/{len(entries)} paesaggi completi")
    if missing:
        print(f"   {missing} paesaggi con almeno un file mancante (segnati in rosso)")
    print()
    print(f"Apri con: open {args.output}")


if __name__ == "__main__":
    main()
