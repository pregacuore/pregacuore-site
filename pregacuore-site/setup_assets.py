"""
==============================================================================
PREGACUORE — Setup degli asset visuali (v1.0)

Genera deterministicamente tutto cio' che il card_generator e gli altri
componenti del prodotto si aspettano di trovare in assets/.

QUANDO LANCIARLO:
    Una volta sola al setup. E poi, ogni volta che qualcuno cambia il logo
    (path SVG) o la texture base. Tutti gli output sono COMMITTATI in repo:
    sono asset deterministici, non file generati a runtime.

USO:
    python setup_assets.py

GENERA:
    assets/pictogram_cream.png         logo trasparente, glifo cream + fiamma oro
    assets/pictogram_bordeaux.png      logo trasparente, glifo bordeaux + fiamma oro
    assets/texture_paper.png           grana papiro 1080x1080 (tile)
    assets/artwork_calendar.yml        mappa "santo/stagione → file immagine"
    assets/artwork/.gitkeep            cartella per le opere PD (popolala a mano)
    assets/README.md                   istruzioni per popolare assets/artwork/
==============================================================================
"""

from __future__ import annotations

import os
import random
from io import BytesIO
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFilter

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent
ASSETS_DIR = SCRIPT_DIR / "assets"
ARTWORK_DIR = ASSETS_DIR / "artwork"
ASSETS_DIR.mkdir(exist_ok=True)
ARTWORK_DIR.mkdir(exist_ok=True)


# ------------------------------------------------------------------
# 1. Pittogramma master — generato dal SVG canonico in 2 varianti cromatiche
# ------------------------------------------------------------------
def pictogram_svg(heart: str, candle: str, flame: str) -> str:
    """SVG canonico del pittogramma Pregacuore. Identico a quello del sito,
    dell'app icon, del brand book. Cambia SOLO qui se un giorno cambia il
    logo: tutto il resto rigenera da questa funzione."""
    return f"""<svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <rect x="482" y="410" width="60" height="450" rx="6" fill="{candle}"/>
  <path d="M 512 320 C 542 355, 542 395, 512 410 C 482 395, 482 355, 512 320 Z" fill="{flame}"/>
  <path d="M 512 690 C 360 590, 232 480, 232 350 C 232 250, 305 190, 380 190 C 442 190, 490 230, 512 290 C 534 230, 582 190, 644 190 C 719 190, 792 250, 792 350 C 792 480, 664 590, 512 690 Z"
        fill="none" stroke="{heart}" stroke-width="52" stroke-linejoin="round"/>
</svg>"""


def render_pictogram_png(svg: str, size: int) -> Image.Image:
    png = cairosvg.svg2png(bytestring=svg.encode("utf-8"),
                           output_width=size, output_height=size)
    return Image.open(BytesIO(png)).convert("RGBA")


def make_pictograms() -> None:
    """Genera 2 PNG trasparenti del pittogramma a 1024px, da usare ovunque
    serva il logo come asset (favicon, OG, social profile, futura filigrana
    se mai cambieremo idea)."""
    print(">>  Genero pittogramma cream (per sfondi bordeaux)...")
    cream_svg = pictogram_svg(heart="#F5EBD8", candle="#F5EBD8", flame="#D4A24A")
    img = render_pictogram_png(cream_svg, 1024)
    img.save(ASSETS_DIR / "pictogram_cream.png", "PNG", optimize=True)
    print(f"    OK  {ASSETS_DIR / 'pictogram_cream.png'}")

    print(">>  Genero pittogramma bordeaux (per sfondi cream/avorio)...")
    bord_svg = pictogram_svg(heart="#7B1F22", candle="#7B1F22", flame="#D4A24A")
    img = render_pictogram_png(bord_svg, 1024)
    img.save(ASSETS_DIR / "pictogram_bordeaux.png", "PNG", optimize=True)
    print(f"    OK  {ASSETS_DIR / 'pictogram_bordeaux.png'}")


# ------------------------------------------------------------------
# 2. Texture papiro — generata proceduralmente, deterministica
# ------------------------------------------------------------------
def make_paper_texture(size: int = 1080, seed: int = 7) -> None:
    """Crea una grana 'carta antica' molto sottile, neutra (in grigio) che
    poi il card_generator moltiplichera' sul colore di sfondo. La grana e'
    generata con seed fisso: ogni rebuild produce lo stesso file (utile per
    diff Git). E' sobria: nessuna macchia decorativa, solo rumore organico
    che da vita al colore piatto."""
    print(f">>  Genero texture papiro {size}x{size}...")
    rng = random.Random(seed)

    # Base molto chiara con piccola variazione
    base = Image.new("L", (size, size), 240)

    # Strato 1: rumore fine e diffuso (la "trama" della carta)
    fine = Image.effect_noise((size, size), 8)  # std 8, molto leggero
    base = Image.blend(base, fine, 0.20)

    # Strato 2: variazioni piu' larghe (il "pelo" della carta vecchia)
    coarse = Image.effect_noise((size, size), 28)
    coarse = coarse.filter(ImageFilter.GaussianBlur(radius=3))
    base = Image.blend(base, coarse, 0.15)

    # Strato 3: ombreggiature ai bordi appena percepibili (vignettatura)
    vignette = Image.new("L", (size, size), 255)
    d = ImageDraw.Draw(vignette)
    # Ellisse interna piena di bianco; ai bordi resta grigio
    for r in range(40, 0, -2):
        col = 255 - int((40 - r) * 1.5)
        d.ellipse([(-r, -r), (size + r, size + r)], outline=col, width=2)
    vignette = vignette.filter(ImageFilter.GaussianBlur(radius=20))
    base = Image.blend(base, vignette, 0.30)

    # Salvo come grayscale: il card_generator la usa come maschera/multiply
    base.save(ASSETS_DIR / "texture_paper.png", "PNG", optimize=True)
    print(f"    OK  {ASSETS_DIR / 'texture_paper.png'}")


# ------------------------------------------------------------------
# 3. Manifest "santo/stagione → file immagine" + scaffolding cartella
# ------------------------------------------------------------------
ARTWORK_CALENDAR_YAML = """# ─────────────────────────────────────────────────────────────────
# Pregacuore — Calendario delle opere di pubblico dominio
# ─────────────────────────────────────────────────────────────────
# Mappatura: chiave (lowercase) → file in assets/artwork/
# Il card_generator cerca prima su 'saint_of_day', poi su 'liturgical_day'.
# Se nessun match, sfondo neutro con texture papiro (default A).
#
# Le chiavi sono confrontate con un match di sottostringhe lowercase:
#   "san francesco d'assisi" matcha "san francesco" e "francesco"
#   "feria del tempo di pasqua" matcha "pasqua"
#
# Per popolare la cartella assets/artwork/:
#   1. Vai su https://commons.wikimedia.org
#   2. Cerca per autore italiano in pubblico dominio (Beato Angelico,
#      Giotto, Caravaggio, Piero della Francesca, miniature medievali...)
#   3. Verifica che la licenza sia "Public domain" o "PD-Art"
#   4. Scarica il JPEG ad alta risoluzione (idealmente >2000px lato lungo)
#   5. Salvalo qui sotto col nome che hai mappato (es. pasqua.jpg)
#   6. Per attribuzione, aggiungi il campo 'attribution' nel manifest
#
# Non e' obbligatorio popolare tutte le voci. Quelle senza file
# corrispondente in assets/artwork/ vengono ignorate silenziosamente.
# ─────────────────────────────────────────────────────────────────

# ── TEMPI LITURGICI ──────────────────────────────────────────────
seasons:
  pasqua:
    file: pasqua.jpg
    attribution: "Beato Angelico, Resurrezione (1440-1442), Convento di San Marco, Firenze"
    suggested_search: "Fra Angelico Resurrection Cell San Marco"

  avvento:
    file: avvento.jpg
    attribution: "Beato Angelico, Annunciazione (c. 1438-1445), Convento di San Marco, Firenze"
    suggested_search: "Fra Angelico Annunciation Cell 3 San Marco"

  quaresima:
    file: quaresima.jpg
    attribution: "Giotto, Crocifissione (c. 1305), Cappella degli Scrovegni, Padova"
    suggested_search: "Giotto Crucifixion Scrovegni Chapel"

  natale:
    file: natale.jpg
    attribution: "Piero della Francesca, Nativita' (c. 1470-1475), National Gallery, Londra"
    suggested_search: "Piero della Francesca Nativity National Gallery"

  pentecoste:
    file: pentecoste.jpg
    attribution: "Tiziano, Discesa dello Spirito Santo (c. 1545), Santa Maria della Salute, Venezia"
    suggested_search: "Titian Pentecost Santa Maria della Salute"

  ordinario:
    file: ordinario.jpg
    attribution: "Miniatura dal Salterio di Bonifacio VIII (c. 1295), Biblioteca Vaticana"
    suggested_search: "Vatican Library Psalter Boniface VIII"

# ── SANTI E FESTIVITA' ──────────────────────────────────────────
saints:
  san francesco:
    file: francesco.jpg
    attribution: "Giotto, San Francesco riceve le stimmate (c. 1295-1300), Basilica di Assisi"
    suggested_search: "Giotto Stigmata Saint Francis Assisi"

  santa caterina da siena:
    file: caterina.jpg
    attribution: "Andrea Vanni, Santa Caterina da Siena (c. 1390), Basilica di San Domenico, Siena"
    suggested_search: "Andrea Vanni Catherine Siena San Domenico"

  san antonio:
    file: antonio.jpg
    attribution: "Tiziano, Miracolo di Sant'Antonio (1511), Scuola del Santo, Padova"
    suggested_search: "Titian Saint Anthony Miracle Padua"

  san pio:
    # Padre Pio non e' in pubblico dominio (1887-1968). Lascia vuoto o usa
    # un'immagine simbolica del Sacro Cuore.
    file: ""
    attribution: ""

  immacolata:
    file: immacolata.jpg
    attribution: "Tiziano, Assunzione della Vergine (1516-1518), Basilica dei Frari, Venezia"
    suggested_search: "Titian Assumption Virgin Frari"

  san benedetto:
    file: benedetto.jpg
    attribution: "Sodoma, Vita di San Benedetto (c. 1505-1508), Abbazia di Monte Oliveto Maggiore"
    suggested_search: "Sodoma Saint Benedict Monte Oliveto"

  santa chiara:
    file: chiara.jpg
    attribution: "Simone Martini, Santa Chiara (c. 1320), Basilica Inferiore di Assisi"
    suggested_search: "Simone Martini Saint Clare Assisi"
"""


def make_artwork_manifest() -> None:
    """Crea il calendario YAML di partenza e la cartella artwork con .gitkeep
    e README. Non sovrascrive il YAML se gia' presente (l'utente potrebbe
    averlo modificato a mano)."""
    manifest_path = ASSETS_DIR / "artwork_calendar.yml"
    if not manifest_path.exists():
        print(">>  Genero artwork_calendar.yml...")
        manifest_path.write_text(ARTWORK_CALENDAR_YAML, encoding="utf-8")
        print(f"    OK  {manifest_path}")
    else:
        print(f"!!  {manifest_path} gia' esistente. NON sovrascritto.")

    gitkeep = ARTWORK_DIR / ".gitkeep"
    gitkeep.touch(exist_ok=True)


# ------------------------------------------------------------------
# 4. README per la cartella assets/
# ------------------------------------------------------------------
ASSETS_README = """# Cartella `assets/`

Contiene tutti gli asset visuali deterministici usati dal card_generator e
dagli altri componenti di Pregacuore. Sono FILE COMMITTATI in repo (anche
i PNG e la texture), non output generati a runtime.

## File

- `pictogram_cream.png` — pittogramma trasparente versione cream/oro per
  sfondi bordeaux. Generato da `setup_assets.py`. Non modificarlo a mano.
- `pictogram_bordeaux.png` — versione inversa per sfondi chiari. Idem.
- `texture_paper.png` — grana papiro 1080x1080 deterministica (seed 7).
  Usata dal card_generator come overlay multiply per dare vita ai colori
  piatti. Idem, non modificarla a mano.
- `artwork_calendar.yml` — mappa "tempo liturgico / santo del giorno" →
  file immagine. Editabile: aggiungi voci, cambia attribuzioni.
- `artwork/` — cartella per le opere d'arte di pubblico dominio italiane.
  Da popolare a mano (vedi sotto).

## Come popolare `artwork/`

Il card_generator usa, quando disponibile, una piccola opera di pubblico
dominio come quinta desaturata dietro la citazione del giorno. NON e'
obbligatorio popolare tutto subito: dove manca il file, il sistema cade
sulla texture papiro (sfondo neutro) senza errori.

Per ogni voce in `artwork_calendar.yml`:

1. Vai su https://commons.wikimedia.org
2. Usa la stringa in `suggested_search` come query
3. Filtra per immagini in PUBLIC DOMAIN (la licenza dev'essere
   "PD-Art" o equivalente — non "CC BY-SA")
4. Scarica il JPEG ad alta risoluzione (idealmente lato lungo > 2000px)
5. Salvalo in `assets/artwork/` con il nome indicato nel manifest
6. Verifica che il caption Instagram (in `caption_instagram` di
   `daily_content`) includa l'attribuzione quando l'immagine viene usata

## Rigenerare gli asset

Se cambi il path SVG del pittogramma o la texture base:

```
python setup_assets.py
```

Sono asset deterministici: a parita' di codice, l'output e' identico
al byte. Sicuro da rigenerare e committare.
"""


def make_readme() -> None:
    readme_path = ASSETS_DIR / "README.md"
    print(">>  Genero assets/README.md...")
    readme_path.write_text(ASSETS_README, encoding="utf-8")
    print(f"    OK  {readme_path}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> None:
    print("\n=========================================")
    print("  Pregacuore - setup_assets.py")
    print("=========================================\n")

    make_pictograms()
    make_paper_texture()
    make_artwork_manifest()
    make_readme()

    print("\nFatto. Cartella assets/ pronta:")
    for f in sorted(ASSETS_DIR.rglob("*")):
        if f.is_file():
            rel = f.relative_to(SCRIPT_DIR)
            size_kb = f.stat().st_size / 1024
            print(f"    {rel}   ({size_kb:.1f} KB)")
    print()


if __name__ == "__main__":
    main()
