"""
==============================================================================
PREGACUORE — Card Generator per Instagram, Pinterest e Story (v3.3)

Cosa cambia rispetto a v3.2:
    - LAYOUT MEDAGLIONE: tre fasce - cream sopra (icona squircle brand +
      wordmark "pregacuore" bordeaux) - paesaggio nel centro con cartiglio -
      cream sotto (payoff "Prega col cuore." bordeaux). Estetica "santino
      moderno / cover di rivista d'arte". Leggibilita' assoluta di lockup
      e payoff perche' sempre su cream.
    - ICONA SQUIRCLE BRAND come logo della card: l'app icon ufficiale di
      pregacuore (cuore cream + candela cream + fiamma oro su squircle
      bordeaux) viene ricaricata come asset e mostrata sulla fascia top.
    - LINEE ORO sottili tra fasce e paesaggio per definire il "passe-partout".
    - RIMOSSE: cornicetta 8px (v3.2), veil verticale (v3.0). Le fasce cream
      fanno da firma cromatica brand sufficiente.

Cosa cambia rispetto a v2.1:
    - PAESAGGI come sfondo: catalogo strutturato (assets/landscape_manifest.yml)
      con mood-tagging. Selezione deterministica sulla data.
    - PALETTE LITURGICA da Supabase: usata SOLO per `cartiglio_alpha` e
      `landscape_mood` (filtraggio paesaggi). I colori UI sono fissi brand.
    - CARTIGLIO sopra il paesaggio: rettangolo cream alpha con quote bordeaux.
    - NUOVO FORMATO PINTEREST: 1080x1620 in parallelo a post e story.
    - Retrocompatibilita': se paesaggio assente, fallback v2.1 (bordeaux pieno).

Modalita' d'uso:
    python card_generator.py                              # oggi
    python card_generator.py --date 2026-05-15            # data specifica
    python card_generator.py --from 2026-05-11 --to 2026-06-10
    python card_generator.py --tomorrow                   # solo domani
    python card_generator.py --ahead 30                   # solo T+30
    python card_generator.py --preview-only               # solo locale
    python card_generator.py --no-landscape               # forza sfondo neutro
    python card_generator.py --no-artwork                 # alias retrocompat
==============================================================================
"""

from __future__ import annotations

import os
import sys
import argparse
import re
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageOps
from supabase import create_client, Client


# ------------------------------------------------------------------
# 1. Configurazione
# ------------------------------------------------------------------
load_dotenv()
SUPABASE_URL = os.environ["SUPABASE_URL"].strip() 
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"].strip() 

BUCKET = "social-cards"

SCRIPT_DIR = Path(__file__).parent
FONTS_DIR = SCRIPT_DIR / "fonts"
ASSETS_DIR = SCRIPT_DIR / "assets"
LANDSCAPES_DIR = ASSETS_DIR / "landscapes"
# Retrocompatibilita': il vecchio path artwork e' ancora supportato per
# eventuali file legacy mappati in artwork_calendar.yml
ARTWORK_DIR = ASSETS_DIR / "artwork"

OUTPUT_DIR = Path(os.environ.get("TEMP", "/tmp")) / "pregacuore_cards"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Dimensioni dei tre formati. v4 (card-santino): allineati a card_layout.formats
# nel landscape_manifest.yml e agli asset HOUSE incorniciati (assets/immagini).
CARD_SIZES = {
    "post":      (1254, 1254),
    "story":     (1080, 1920),
    "pinterest": (1000, 1500),
}


# ------------------------------------------------------------------
# 2. Brand colors (RGB)
# ------------------------------------------------------------------
BORDEAUX = (123, 31, 34)
CREAM    = (245, 235, 216)
GOLD     = (212, 162, 74)
PIOMBO   = (58, 58, 63)
AVORIO   = (250, 246, 238)


# ------------------------------------------------------------------
# 3. Font management — tollerante (invariato dalla v1.2)
# ------------------------------------------------------------------
def find_font_file(directory: Path, must_contain: list,
                   must_not_contain: list = None) -> Optional[Path]:
    must_not_contain = must_not_contain or []
    if not directory.exists():
        return None
    for f in sorted(directory.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".ttf", ".otf"):
            continue
        name = f.name.lower()
        if all(kw.lower() in name for kw in must_contain):
            if not any(kw.lower() in name for kw in must_not_contain):
                return f
    return None


def find_system_font(*candidates) -> Optional[str]:
    system_paths = [
        Path("C:/Windows/Fonts"),
        Path("/Library/Fonts"),
        Path("/System/Library/Fonts"),
        Path("/usr/share/fonts/truetype"),
        Path("/usr/share/fonts"),
    ]
    for sp in system_paths:
        if not sp.exists():
            continue
        for cand in candidates:
            for f in sp.rglob("*"):
                if f.is_file() and f.name.lower() == cand.lower():
                    return str(f)
    return None


def ensure_fonts() -> dict:
    paths = {}

    # Cormorant Italic per la quote
    p = find_font_file(FONTS_DIR, ["cormorant", "italic"])
    if not p:
        p = find_font_file(FONTS_DIR, ["italic"])
    if not p:
        p = find_font_file(FONTS_DIR, ["cormorant"])
        if p:
            print(f"!!  Cormorant Italic non trovato. Uso {p.name} (non corsivo).")
    if not p:
        sysf = find_system_font("cambriai.ttf", "georgiai.ttf", "timesi.ttf",
                                "DejaVuSerif-Italic.ttf")
        if sysf:
            p = Path(sysf)
            print(f"!!  Cormorant non trovato. Uso font sistema: {p.name}")
    if not p:
        print("X  Nessun font serif trovato. Vedi istruzioni in README_FONTS.md")
        sys.exit(1)
    paths["cormorant_italic"] = str(p)
    print(f"OK  font citazione:   {Path(paths['cormorant_italic']).name}")

    # Cormorant Medium per il wordmark
    p = find_font_file(FONTS_DIR, ["cormorant", "medium"], must_not_contain=["italic"])
    if not p:
        p = find_font_file(FONTS_DIR, ["cormorant", "regular"], must_not_contain=["italic"])
    if not p:
        p = find_font_file(FONTS_DIR, ["cormorant"], must_not_contain=["italic"])
    if not p:
        sysf = find_system_font("cambria.ttc", "cambria.ttf", "georgia.ttf", "times.ttf",
                                "DejaVuSerif.ttf")
        if sysf:
            p = Path(sysf)
            print(f"!!  Cormorant Medium non trovato. Uso sistema: {p.name}")
    if not p:
        p = Path(paths["cormorant_italic"])
        print(f"!!  Cormorant Medium non trovato. Uso lo stesso del corsivo.")
    paths["cormorant_medium"] = str(p)
    print(f"OK  font wordmark:    {Path(paths['cormorant_medium']).name}")

    # Inter per UI
    p = find_font_file(FONTS_DIR, ["inter"])
    if not p:
        sysf = find_system_font("Inter-Medium.ttf", "arial.ttf", "verdana.ttf",
                                "calibri.ttf", "DejaVuSans.ttf")
        if sysf:
            p = Path(sysf)
            print(f"!!  Inter non trovato. Uso sistema: {p.name}")
    if not p:
        p = Path(paths["cormorant_medium"])
        print(f"!!  Inter non trovato. Uso Cormorant come fallback.")
    paths["inter_medium"] = str(p)
    print(f"OK  font UI:          {Path(paths['inter_medium']).name}")
    print()
    return paths


# ------------------------------------------------------------------
# 4. Asset loading: texture papiro + manifest artwork
# ------------------------------------------------------------------
def load_paper_texture() -> Optional[Image.Image]:
    """Carica la texture papiro grayscale. Se manca, ritorna None e il
    card_generator lavora senza overlay (sfondo piatto)."""
    path = ASSETS_DIR / "texture_paper.png"
    if not path.exists():
        print(f"!!  {path} non trovata. Lancia 'python setup_assets.py' per generarla.")
        return None
    return Image.open(path).convert("L")  # grayscale


def load_pictograms() -> dict:
    """Carica i pittogrammi/icone usate nel lockup della card.
    v3.3: il layout "medaglione" usa l'ICONA SQUIRCLE BRAND (cuore cream
    + candela cream + fiamma oro su fondo squircle bordeaux) come logo
    della card, sopra la fascia cream superiore.

    File attesi in assets/:
      - pregacuore_lockup_icon_brand.png   (squircle brand colori, RGBA)

    Per retrocompatibilita' v2/v3.2 carico anche i pittogrammi mono:
      - pictogram_cream.png       (cuore+candela cream, RGBA trasparente)
      - pictogram_bordeaux.png    (cuore+candela bordeaux, RGBA trasparente)

    Ritorna dict, chiavi mancanti per file assenti (degradazione silente).
    """
    out = {}
    # Icona brand (v3.3): asset primario
    p = ASSETS_DIR / "pregacuore_lockup_icon_brand.png"
    if p.exists():
        out["icon_brand"] = Image.open(p).convert("RGBA")
    else:
        print(f"!!  {p} non trovato. La card user lockup mono come fallback.")

    # Pittogrammi mono (retrocompat con v2.x e v3.2)
    for name in ("pictogram_cream", "pictogram_bordeaux"):
        p = ASSETS_DIR / f"{name}.png"
        if p.exists():
            out[name] = Image.open(p).convert("RGBA")
    return out


def load_artwork_manifest() -> dict:
    """Carica il manifest YAML legacy che mappa stagione/santo → file immagine.
    Mantenuto per retrocompatibilita': se assets/artwork_calendar.yml esiste,
    viene letto. Altrimenti dict vuoto."""
    path = ASSETS_DIR / "artwork_calendar.yml"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data
    except Exception as e:
        print(f"!!  Errore lettura {path}: {e}")
        return {}


def find_artwork_for_day(saint_of_day: str, liturgical_day: str,
                         manifest: dict) -> Optional[Path]:
    """Cerca un'opera adatta per il giorno corrente nel manifest LEGACY
    `artwork_calendar.yml`. Usato solo per retrocompatibilita': il sistema
    primario e' load_landscape_manifest + select_landscape_for_day."""
    def match_in(group: str, against: str) -> Optional[str]:
        if not against:
            return None
        haystack = against.lower()
        items = (manifest.get(group) or {})
        for key, payload in items.items():
            if not isinstance(payload, dict):
                continue
            file_name = (payload.get("file") or "").strip()
            if not file_name:
                continue
            if key.lower() in haystack:
                candidate = ARTWORK_DIR / file_name
                if candidate.exists():
                    return str(candidate)
        return None

    p = match_in("saints", saint_of_day or "")
    if p:
        return Path(p)
    p = match_in("seasons", liturgical_day or "")
    if p:
        return Path(p)
    return None


def load_landscape_manifest() -> list:
    """Carica il manifest dei paesaggi PD (v3.0).
    Ritorna lista di entry, ognuna con {slug, artist, title, moods, ...}.
    Lista vuota se il file non esiste o e' malformato (degradazione silente
    al rendering bordeaux pieno)."""
    path = ASSETS_DIR / "landscape_manifest.yml"
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        entries = data.get("landscapes", []) or []
        return entries
    except Exception as e:
        print(f"!!  Errore lettura {path}: {e}")
        return []


def fetch_liturgical_palette(supabase: Client) -> dict:
    """Carica tutte le righe della tabella `liturgical_palette` da Supabase,
    indicizzate per season. Ritorna dict {season -> palette_row} o {}
    se la tabella non esiste o e' vuota (fallback al rendering v2.1).

    Ogni palette_row ha campi: primary, secondary, accent, text, quote_color,
    payoff_color, rule_color, landscape_mood (array), landscape_opacity,
    cartiglio_alpha, overlay_tone, description.
    """
    try:
        res = supabase.table("liturgical_palette").select("*").execute()
        rows = res.data or []
        if not rows:
            return {}
        return {row["season"]: row for row in rows}
    except Exception as e:
        # Tabella inesistente o errore: fallback silenzioso al rendering v2.1
        print(f"!!  liturgical_palette non disponibile ({e}). Uso colori brand statici.")
        return {}


def select_landscape_for_day(target_date: date,
                              season: str,
                              palette: dict,
                              manifest: list) -> Optional[Path]:
    """Selezione deterministica del paesaggio per il giorno corrente.

    Algoritmo:
      1. Recupera la lista di mood compatibili per la `season` da palette
      2. Filtra il manifest tenendo solo paesaggi con ALMENO un mood matchante
      3. Se >= 3 candidati non-riserva, esclude i `reserve:true`
      4. Sceglie deterministicamente: hash(content_date) % len(candidates)
      5. Verifica che il file ESISTA in assets/landscapes/<slug>_post.png
      6. Se manca, prova il successivo della lista; se nessuno, None

    Ritorna il Path al file POST (1080x1080); le altre dimensioni vengono
    risolte separatamente in compose_card.
    """
    if not manifest:
        return None

    # Recupera mood compatibili per questa season
    palette_row = palette.get(season) if palette else None
    if palette_row:
        compatible_moods = set(palette_row.get("landscape_mood") or [])
    else:
        compatible_moods = set()

    # Filtra candidati per mood (se ci sono mood, altrimenti tutti)
    if compatible_moods:
        candidates = [
            l for l in manifest
            if set(l.get("moods", [])) & compatible_moods
        ]
    else:
        candidates = list(manifest)

    if not candidates:
        return None

    # Privilegia non-riserva se abbastanza
    non_reserve = [c for c in candidates if not c.get("reserve")]
    if len(non_reserve) >= 3:
        candidates = non_reserve

    # Selezione deterministica per data (stesso giorno -> stesso paesaggio
    # ovunque, su tutti i 3 formati e su tutte le esecuzioni)
    date_str = target_date.isoformat()
    # hash stabile cross-platform (non Python's hash() builtin che e' randomized)
    import hashlib
    seed = int(hashlib.md5(date_str.encode()).hexdigest()[:8], 16)

    # Provo i candidati in ordine cyclic-shift partendo dall'indice scelto,
    # cosi' se il file primario manca cado sul successivo della lista
    n = len(candidates)
    start = seed % n
    for offset in range(n):
        cand = candidates[(start + offset) % n]
        slug = cand.get("slug", "")
        post_path = LANDSCAPES_DIR / f"{slug}_post.png"
        if post_path.exists():
            return post_path

    # Nessun file fisico disponibile
    return None


def derive_season_from_row(row: dict, target_date: date) -> str:
    """Determina la `season` per la palette a partire dalla riga
    daily_content. Logica:
      1. Se row['liturgical_season'] e' esplicito, usalo
      2. Altrimenti, mappa euristica da `liturgical_day` (es. "Tempo di
         Pasqua", "I Domenica di Avvento", ecc.) a season chiavi
      3. Fallback: tempo_ordinario
    """
    # 1) Campo esplicito
    explicit = (row.get("liturgical_season") or "").strip().lower()
    if explicit in ("avvento", "natale", "quaresima", "pasqua",
                    "tempo_ordinario", "feste_signore", "santi_maria"):
        return explicit

    # 2) Euristica dal testo liturgical_day
    day = (row.get("liturgical_day") or "").lower()
    saint = (row.get("saint_of_day") or "").lower()

    if "avvento" in day:
        return "avvento"
    if "natale" in day or "natività" in day or "epifania" in day or "battesimo del signore" in day:
        return "natale"
    if "quaresima" in day or "ceneri" in day or "passione" in day:
        return "quaresima"
    if "pasqua" in day or "settimana santa" in day or "ottava di pasqua" in day:
        return "pasqua"
    if "trasfigurazione" in day or "cristo re" in day or "ascensione" in day or "trinità" in day or "santissima trinità" in day or "corpus" in day:
        return "feste_signore"
    if "maria" in saint or "madonna" in saint or "vergine" in saint or "immacolata" in day or "assunta" in day:
        return "santi_maria"
    if "san " in saint or "santa " in saint or "santi " in saint or "beato" in saint or "beata" in saint:
        return "santi_maria"

    return "tempo_ordinario"


# ------------------------------------------------------------------
# 5. Composizione sfondo
# ------------------------------------------------------------------
def apply_paper_texture(img: Image.Image, texture: Optional[Image.Image],
                        strength: float = 0.12) -> Image.Image:
    """Applica la texture papiro come overlay multiply leggero. La texture
    e' grayscale: dove e' chiara (240+) lascia passare il colore di base,
    dove e' piu' scura (220-) lo scurisce di un soffio."""
    if texture is None:
        return img
    W, H = img.size
    # Resize texture a coprire l'intera card
    tex = texture.resize((W, H), Image.LANCZOS)

    # Converto la texture in un overlay RGBA con alpha proporzionale
    # all'intensita' (piu' la grana e' scura, piu' opaca diventa)
    arr = tex.point(lambda v: int((255 - v) * strength))
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    overlay.putalpha(arr)
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def apply_artwork_background(img: Image.Image, artwork_path: Path,
                              tint_color: tuple) -> Image.Image:
    """Compone l'opera d'arte come quinta SOTTILE dietro il colore di
    sfondo della card. Strategia:
       1) crop centrato a copertura della card (cover)
       2) desaturazione totale → grayscale
       3) tint nel colore tint_color (bordeaux per template scuro,
          piombo per template chiaro)
       4) blur gentilissimo (3px) per dare aria, evita di rubare
          attenzione alla citazione
       5) blend al 25-30% sopra lo sfondo del template

    L'opera resta riconoscibile a chi la conosce, sparisce nello sfondo
    a chi non se ne accorge: un'eco, non un protagonista."""
    W, H = img.size

    art = Image.open(artwork_path).convert("RGB")

    # Cover crop: ridimensiono mantenendo aspect e taglio l'eccesso
    art_w, art_h = art.size
    scale = max(W / art_w, H / art_h)
    new_w = int(art_w * scale)
    new_h = int(art_h * scale)
    art = art.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    art = art.crop((left, top, left + W, top + H))

    # Grayscale → tint nel colore di brand
    art_gray = ImageOps.grayscale(art)
    tinted = ImageOps.colorize(
        art_gray,
        black=tuple(int(c * 0.25) for c in tint_color),  # ombre
        white=tint_color,                                  # luci
    )

    # Soft blur per non rubare attenzione
    from PIL import ImageFilter
    tinted = tinted.filter(ImageFilter.GaussianBlur(radius=3))

    # Blend col fondo (l'opera sopra l'immagine, peso 28%)
    return Image.blend(img, tinted, 0.28)


def apply_landscape_background(img: Image.Image, landscape_path: Path,
                               opacity: float = 1.0,
                               desaturate_factor: float = 0.10) -> Image.Image:
    """Versione v3.2: paesaggio PURO, niente blend col fondo brand.
    La firma cromatica del brand e' affidata SOLO alla cornice 8px
    (vedi `apply_border`). Il paesaggio mantiene i suoi colori originali
    con una minima desaturazione (0.10) e blur (1.5px) per dare unita'
    pittorica e ammorbidire i dettagli piu' fitti.

    Strategia:
      1. cover crop centrato sulla card
      2. soft desaturazione (factor 0.10 = pochissimo, conserva i colori)
      3. blur 1.5px per ammorbidire pennellate troppo nette

    Parametri:
      opacity: parametro legacy mantenuto per retrocompatibilita',
        ora IGNORATO (il paesaggio sostituisce sempre il fondo). Si
        legge ancora dalla palette ma e' di fatto un no-op.
      desaturate_factor: 0.0 = colori originali, 1.0 = grayscale.
        Default 0.10 = appena percepibile, no shock cromatico.
    """
    W, H = img.size
    art = Image.open(landscape_path).convert("RGB")

    # Cover crop
    art_w, art_h = art.size
    scale = max(W / art_w, H / art_h)
    new_w = int(art_w * scale)
    new_h = int(art_h * scale)
    art = art.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - W) // 2
    top = (new_h - H) // 2
    art = art.crop((left, top, left + W, top + H))

    # Soft desaturazione
    if desaturate_factor > 0:
        enhancer = ImageEnhance.Color(art)
        art = enhancer.enhance(1.0 - desaturate_factor)

    # Blur ammorbidente
    from PIL import ImageFilter
    art = art.filter(ImageFilter.GaussianBlur(radius=1.5))

    # Paesaggio puro (il parametro opacity e' un no-op in v3.2 ma viene
    # mantenuto in firma per retrocompatibilita' col DB e con i caller)
    return art


def apply_border(img: Image.Image, border_px: int = 8,
                 color: tuple = None) -> Image.Image:
    """Aggiunge una cornice bordeaux di N pixel attorno alla card.
    E' l'unica firma cromatica brand di pregacuore v3.2: paesaggio puro
    al centro, cornicetta come passe-partout.

    Implementazione: nuovo canvas pieno del colore bordo, paesaggio
    ridimensionato e centrato all'interno con i margini.
    """
    if color is None:
        color = BORDEAUX
    if border_px <= 0:
        return img
    W, H = img.size
    bordered = Image.new("RGB", (W, H), color)
    inner = img.resize((W - 2 * border_px, H - 2 * border_px), Image.LANCZOS)
    bordered.paste(inner, (border_px, border_px))
    return bordered


def apply_veil_gradient(img: Image.Image, color: tuple,
                        top_alpha: float = 0.55,
                        center_alpha: float = 0.15,
                        bottom_alpha: float = 0.55) -> Image.Image:
    """Applica un gradiente verticale del colore di palette sopra l'immagine.
    Default: ai bordi 55% di alpha, al centro 15% → protegge lockup (top)
    e payoff (bottom) dal paesaggio sottostante, lasciando piu' apertura
    al centro dove sta il cartiglio.

    Il gradiente e' lineare a 3 stop: top→center, center→bottom.
    Implementazione: costruisco una colonna 1px con i valori giusti, poi
    la riscalo a tutta l'altezza con NEAREST (replica pixel per riga).
    Molto piu' veloce di un loop pixel-per-pixel.
    """
    W, H = img.size
    a_top = int(top_alpha * 255)
    a_mid = int(center_alpha * 255)
    a_bot = int(bottom_alpha * 255)

    # Costruisco la colonna 1px x H con il gradiente
    column = Image.new("L", (1, H), 0)
    cpixels = column.load()
    mid = H // 2
    for y in range(H):
        if y < mid:
            t = y / mid if mid else 0
            v = int(a_top + (a_mid - a_top) * t)
        else:
            t = (y - mid) / (H - mid) if (H - mid) else 0
            v = int(a_mid + (a_bot - a_mid) * t)
        cpixels[0, y] = max(0, min(255, v))

    # Riscalo a larghezza piena con NEAREST (replica orizzontale rapida)
    mask = column.resize((W, H), Image.NEAREST)

    overlay_rgb = Image.new("RGB", (W, H), color)
    overlay = Image.merge("RGBA", (*overlay_rgb.split(), mask))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def draw_cartiglio(img: Image.Image, x: int, y: int, w: int, h: int,
                   fill_color: tuple, alpha: float = 0.80,
                   border_color: Optional[tuple] = None,
                   border_alpha: float = 0.45,
                   corner_radius: int = 6) -> Image.Image:
    """Disegna un cartiglio (rettangolo cream con alpha) sotto la quote.
    L'alpha rende il cartiglio semi-trasparente, lasciando trasparire il
    paesaggio sottostante in modo controllato.

    Parametri:
      x, y, w, h: bounding box del cartiglio
      fill_color: tipicamente cream da palette
      alpha: opacita' del riempimento (0.0-1.0)
      border_color: opzionale, gold da palette
      border_alpha: opacita' del bordo
      corner_radius: raggio dei vertici (radius molto piccolo, look "etichetta")
    """
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fill_rgba = (*fill_color, int(alpha * 255))
    draw.rounded_rectangle(
        [(x, y), (x + w, y + h)],
        radius=corner_radius,
        fill=fill_rgba,
    )
    if border_color is not None:
        border_rgba = (*border_color, int(border_alpha * 255))
        draw.rounded_rectangle(
            [(x, y), (x + w, y + h)],
            radius=corner_radius,
            outline=border_rgba,
            width=2,
        )
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


# ------------------------------------------------------------------
# 6. Helpers tipografici
# ------------------------------------------------------------------
def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
    words = text.replace("\n", " \n ").split()
    lines, current = [], []
    for word in words:
        if word == "\n":
            if current:
                lines.append(" ".join(current))
                current = []
            continue
        test = " ".join(current + [word])
        bb = font.getbbox(test)
        if (bb[2] - bb[0]) <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines


def draw_centered_lines(draw, lines, font, color, canvas_w, y_start,
                        line_height_factor=1.22):
    bb = font.getbbox("Ag")
    line_h = int((bb[3] - bb[1]) * line_height_factor)
    y = y_start
    for line in lines:
        bb = font.getbbox(line)
        x = (canvas_w - (bb[2] - bb[0])) // 2 - bb[0]
        draw.text((x, y), line, font=font, fill=color)
        y += line_h
    return y


# ------------------------------------------------------------------
# 7. Selezione template (basata sul giorno della settimana)
# ------------------------------------------------------------------
def select_template(target_date: date) -> str:
    wd = target_date.weekday()
    if wd == 5:   # sabato
        return "cream"
    if wd == 6:   # domenica
        return "avorio"
    return "bordeaux"


# ------------------------------------------------------------------
# 8. Composizione della card
# ------------------------------------------------------------------
def desaturate_color(rgb: tuple, factor: float) -> tuple:
    """Avvicina rgb al suo grigio equivalente. factor 0=invariato,
    1=totalmente grigio."""
    gray = sum(rgb) // 3
    return tuple(int(c + (gray - c) * factor) for c in rgb)


def derive_payoff_color(word_color: tuple, template: str) -> tuple:
    """Il payoff deve essere SEMPRE meno presente del wordmark.
    Per template scuri (bordeaux) il wordmark e' cream → payoff = cream
    desaturato e leggermente piu' scuro.
    Per template chiari (cream/avorio) il wordmark e' bordeaux → payoff =
    bordeaux desaturato e leggermente piu' chiaro."""
    if template == "bordeaux":
        # cream → cream meno saturo, leggermente piu' scuro
        c = desaturate_color(word_color, 0.35)
        return tuple(max(0, x - 35) for x in c)
    else:
        # bordeaux → bordeaux meno saturo, leggermente piu' chiaro
        c = desaturate_color(word_color, 0.40)
        return tuple(min(255, x + 25) for x in c)


def _hex_to_rgb(hex_str: str) -> tuple:
    """Converte stringa hex (6 char, senza #) in tupla RGB."""
    s = hex_str.lstrip("#").strip()
    if len(s) != 6:
        return None
    try:
        return tuple(int(s[i:i+2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def resolve_palette_colors(palette_row: Optional[dict], template: str) -> dict:
    """Risolve i colori della card. v3.1: la palette in DB serve SOLO a
    leggere `cartiglio_alpha` e `landscape_opacity`, NON a sovrascrivere
    i colori brand. Il brand pregacuore e' UNO: bordeaux + cream + gold,
    consistente su tutte le card. La stagione liturgica influenza la
    scelta del paesaggio (via mood) e l'alpha del cartiglio, non il
    cromatismo della UI.

    Colori brand (sempre questi):
      - Fondo: bordeaux (#722F37 ~ BORDEAUX)
      - Cartiglio: cream (#F5E6D3 ~ CREAM)
      - Quote dentro cartiglio: bordeaux
      - Wordmark sul fondo: cream
      - Payoff sul fondo: cream sbiadito
      - Linea decorativa: oro (#D4A954 ~ GOLD)
      - Veil verticale: bordeaux (stesso colore del fondo)

    Solo da palette_row leggo: cartiglio_alpha, landscape_opacity
    Default se palette_row e' None: 0.80 e 0.55
    """
    if palette_row:
        cartiglio_alpha = float(palette_row.get("cartiglio_alpha") or 0.85)
        landscape_opacity = float(palette_row.get("landscape_opacity") or 1.0)
    else:
        cartiglio_alpha = 0.85
        landscape_opacity = 1.0

    return {
        "bg_color":          BORDEAUX,
        "cartiglio_fill":    CREAM,
        "cartiglio_border":  GOLD,
        "quote_color":       BORDEAUX,   # quote SU cartiglio cream
        "ref_color":         BORDEAUX,   # ref SU cartiglio cream
        "word_color":        CREAM,      # wordmark SU bordeaux
        "payoff_color":      None,       # derivato (cream desaturato)
        "rule_color":        GOLD,
        "veil_color":        BORDEAUX,
        "pict_key":          "pictogram_cream",  # cream su bordeaux
        "cartiglio_alpha":   cartiglio_alpha,
        "landscape_opacity": landscape_opacity,
    }


def compose_card(template: str, quote: str, gospel_reference: str,
                 fmt: str, fonts: dict,
                 paper_texture: Optional[Image.Image] = None,
                 landscape_path: Optional[Path] = None,
                 pictograms: Optional[dict] = None,
                 palette_row: Optional[dict] = None) -> Image.Image:
    """Compone una card v3.3 con layout MEDAGLIONE a tre fasce:
       FASCIA SUPERIORE CREAM — icona squircle brand (cuore+candela) + wordmark "pregacuore" bordeaux
       PAESAGGIO CENTRALE     — quadro PD con cartiglio cream alpha contenente la quote
       FASCIA INFERIORE CREAM — payoff "Prega col cuore." bordeaux

    Le fasce cream fungono da "passe-partout" che incornicia il paesaggio e
    ospita gli elementi tipografici brand su un fondo che ne garantisce
    leggibilita' assoluta. Il paesaggio resta puro al centro.

    Senza paesaggio (fallback v2.1):
       Niente fasce, solo bordeaux pieno con quote in oro come la v2.1.

    Parametri:
       fmt: 'post' (1080x1080), 'story' (1080x1920), 'pinterest' (1080x1620)
       palette_row: row dalla tabella liturgical_palette (puo' essere None);
                    in v3.3 si legge SOLO `cartiglio_alpha` (default 0.85).
    """
    if fmt not in CARD_SIZES:
        raise ValueError(f"Formato non supportato: {fmt}")
    W, H = CARD_SIZES[fmt]
    pictograms = pictograms or {}

    # Risolvi parametri leggibilita' da palette
    colors = resolve_palette_colors(palette_row, template)
    landscape_active = landscape_path and landscape_path.exists()

    # =========================================================
    # FALLBACK SENZA PAESAGGIO: rendering v2.1 puro
    # =========================================================
    if not landscape_active:
        return _compose_card_fallback_v2(
            quote, gospel_reference, fmt, fonts, paper_texture, pictograms, template
        )

    # =========================================================
    # LAYOUT MEDAGLIONE v3.3 (con paesaggio)
    # =========================================================

    # Dimensioni fasce proporzionate al formato
    if fmt == "story":  # 1080x1920
        FASCIA_TOP = 360
        FASCIA_BOT = 160
        ICON_SIZE = 170
        WORD_SIZE = 60
        WORD_GAP = 16
        PAYOFF_SIZE = 28
        CART_MARGIN_X = 110
        CART_INNER_PAD = 70
        QUOTE_SIZE_IDEAL = 90
        QUOTE_SIZE_MIN = 64
        QUOTE_MAX_LINES = 5
        REF_SIZE = 30
        RULE_GAP = 45
        REF_GAP = 38
    elif fmt == "pinterest":  # 1080x1620
        FASCIA_TOP = 310
        FASCIA_BOT = 130
        ICON_SIZE = 150
        WORD_SIZE = 56
        WORD_GAP = 14
        PAYOFF_SIZE = 25
        CART_MARGIN_X = 100
        CART_INNER_PAD = 60
        QUOTE_SIZE_IDEAL = 80
        QUOTE_SIZE_MIN = 58
        QUOTE_MAX_LINES = 5
        REF_SIZE = 26
        RULE_GAP = 38
        REF_GAP = 32
    else:  # post 1080x1080
        FASCIA_TOP = 230
        FASCIA_BOT = 95
        ICON_SIZE = 120
        WORD_SIZE = 44
        WORD_GAP = 12
        PAYOFF_SIZE = 22
        CART_MARGIN_X = 95
        CART_INNER_PAD = 55
        QUOTE_SIZE_IDEAL = 66
        QUOTE_SIZE_MIN = 48
        QUOTE_MAX_LINES = 4
        REF_SIZE = 22
        RULE_GAP = 30
        REF_GAP = 26

    # ── 1. Fondo cream (sara' coperto dal paesaggio nel centro,
    # ma visibile nelle fasce sopra/sotto)
    img = Image.new("RGB", (W, H), CREAM)

    # ── 2. Paesaggio nel rettangolo centrale
    landscape_h = H - FASCIA_TOP - FASCIA_BOT
    art = apply_landscape_background(
        Image.new("RGB", (W, landscape_h), CREAM),
        landscape_path,
        opacity=1.0,
        desaturate_factor=0.10,
    )
    img.paste(art, (0, FASCIA_TOP))

    draw = ImageDraw.Draw(img)
    # Linee oro che separano paesaggio dalle fasce
    draw.line([(0, FASCIA_TOP - 1), (W, FASCIA_TOP - 1)], fill=GOLD, width=1)
    draw.line([(0, H - FASCIA_BOT), (W, H - FASCIA_BOT)], fill=GOLD, width=1)

    # ── 3. Texture papiro leggera sulle fasce cream (opzionale, da' grana)
    if paper_texture is not None:
        # Applico solo alle 2 fasce, non al paesaggio
        for y_band, h_band in [(0, FASCIA_TOP - 1), (H - FASCIA_BOT + 1, FASCIA_BOT - 1)]:
            band = img.crop((0, y_band, W, y_band + h_band))
            band = apply_paper_texture(band, paper_texture, strength=0.06)
            img.paste(band, (0, y_band))

    # ── 4. LOCKUP nella fascia superiore cream
    # Icona squircle brand (v3.3) o pittogramma cream (fallback)
    icon_img = pictograms.get("icon_brand") or pictograms.get("pictogram_bordeaux")
    if icon_img is not None:
        # Mantengo l'aspect ratio dell'icona originale
        aspect = icon_img.size[0] / icon_img.size[1]
        if aspect >= 1:
            ic_w, ic_h = ICON_SIZE, int(ICON_SIZE / aspect)
        else:
            ic_w, ic_h = int(ICON_SIZE * aspect), ICON_SIZE
        icon_resized = icon_img.resize((ic_w, ic_h), Image.LANCZOS)
        ic_x = (W - ic_w) // 2
        # Posiziono verticalmente cosi' che icona + gap + wordmark siano
        # centrati nella fascia top
        word_font = ImageFont.truetype(fonts["cormorant_medium"], WORD_SIZE)
        wbb = word_font.getbbox("pregacuore")
        word_h = wbb[3] - wbb[1]
        lockup_total_h = ic_h + WORD_GAP + word_h
        ic_y = (FASCIA_TOP - lockup_total_h) // 2
        img.paste(icon_resized, (ic_x, ic_y), icon_resized)
        # Wordmark bordeaux su cream
        draw = ImageDraw.Draw(img)
        wx = (W - (wbb[2] - wbb[0])) // 2 - wbb[0]
        wy = ic_y + ic_h + WORD_GAP
        draw.text((wx, wy), "pregacuore", font=word_font, fill=BORDEAUX)
    else:
        # Fallback senza icona: solo wordmark bordeaux centrato in fascia
        word_font = ImageFont.truetype(fonts["cormorant_medium"], WORD_SIZE)
        wbb = word_font.getbbox("pregacuore")
        draw = ImageDraw.Draw(img)
        wx = (W - (wbb[2] - wbb[0])) // 2 - wbb[0]
        wy = (FASCIA_TOP - (wbb[3] - wbb[1])) // 2 - wbb[1]
        draw.text((wx, wy), "pregacuore", font=word_font, fill=BORDEAUX)

    # ── 5. CARTIGLIO nel paesaggio (cream alpha con quote bordeaux)
    # Pre-calcolo dimensioni del contenuto per dimensionare il cartiglio
    text_max_w = (W - 2 * CART_MARGIN_X) - 2 * 50  # margine interno orizzontale
    quote_size = QUOTE_SIZE_IDEAL
    quote_font = ImageFont.truetype(fonts["cormorant_italic"], quote_size)
    quote_lines = wrap_text(quote.strip(), quote_font, text_max_w)
    while len(quote_lines) > QUOTE_MAX_LINES and quote_size > QUOTE_SIZE_MIN:
        quote_size -= 4
        quote_font = ImageFont.truetype(fonts["cormorant_italic"], quote_size)
        quote_lines = wrap_text(quote.strip(), quote_font, text_max_w)

    qbb = quote_font.getbbox("Ag")
    line_h = int((qbb[3] - qbb[1]) * 1.22)
    total_q_h = line_h * len(quote_lines)

    ref_font = ImageFont.truetype(fonts["inter_medium"], REF_SIZE)
    rbb = ref_font.getbbox("Ag")
    ref_h = rbb[3] - rbb[1]

    content_h = total_q_h + RULE_GAP + 2 + REF_GAP + ref_h
    cart_h = content_h + 2 * CART_INNER_PAD
    cart_w = W - 2 * CART_MARGIN_X
    cart_x = CART_MARGIN_X
    # Centro il cartiglio nel paesaggio
    cart_y = FASCIA_TOP + (landscape_h - cart_h) // 2

    img = draw_cartiglio(
        img, cart_x, cart_y, cart_w, cart_h,
        fill_color=CREAM,
        alpha=colors["cartiglio_alpha"],
        border_color=GOLD,
        border_alpha=0.40,
        corner_radius=6,
    )
    draw = ImageDraw.Draw(img, "RGBA")

    # Quote dentro cartiglio
    text_y_start = cart_y + CART_INNER_PAD
    quote_y_end = draw_centered_lines(
        draw, quote_lines, quote_font, BORDEAUX, W, text_y_start, 1.22
    )

    # Linea oro decorativa
    rule_y = quote_y_end + RULE_GAP
    rule_w = 80
    rule_x1 = (W - rule_w) // 2
    draw.line([(rule_x1, rule_y), (rule_x1 + rule_w, rule_y)],
              fill=GOLD, width=2)

    # Ref Vangelo
    ref_text = f"VANGELO · {gospel_reference.upper()}"
    rbb2 = ref_font.getbbox(ref_text)
    rx = (W - (rbb2[2] - rbb2[0])) // 2 - rbb2[0]
    ry = rule_y + REF_GAP
    draw.text((rx, ry), ref_text, font=ref_font, fill=BORDEAUX)

    # ── 6. PAYOFF nella fascia inferiore cream, bordeaux
    payoff_font = ImageFont.truetype(fonts["inter_medium"], PAYOFF_SIZE)
    payoff_text = "Prega col cuore."
    pbb = payoff_font.getbbox(payoff_text)
    px = (W - (pbb[2] - pbb[0])) // 2 - pbb[0]
    py = H - FASCIA_BOT + (FASCIA_BOT - (pbb[3] - pbb[1])) // 2 - pbb[1]
    draw = ImageDraw.Draw(img)
    draw.text((px, py), payoff_text, font=payoff_font, fill=BORDEAUX)

    return img


def _compose_card_fallback_v2(quote: str, gospel_reference: str, fmt: str,
                              fonts: dict,
                              paper_texture: Optional[Image.Image],
                              pictograms: dict,
                              template: str) -> Image.Image:
    """Rendering v2.1-style usato quando il paesaggio manca: bordeaux pieno,
    quote in oro, niente fasce ne' cartiglio. Mantiene la firma brand su
    fondo solido."""
    W, H = CARD_SIZES[fmt]
    img = Image.new("RGB", (W, H), BORDEAUX)
    img = apply_paper_texture(img, paper_texture, strength=0.08)
    draw = ImageDraw.Draw(img, "RGBA")

    is_story = (fmt == "story")
    is_pinterest = (fmt == "pinterest")
    if is_story:
        pict_size = 110; top_padding = 130; word_size = 50; word_y_gap = 14
    elif is_pinterest:
        pict_size = 100; top_padding = 110; word_size = 46; word_y_gap = 12
    else:
        pict_size = 90;  top_padding = 80;  word_size = 42; word_y_gap = 10

    # Lockup mono cream
    pict_img = pictograms.get("pictogram_cream") or pictograms.get("icon_brand")
    top_zone_end = top_padding
    if pict_img is not None:
        aspect = pict_img.size[0] / pict_img.size[1]
        ic_w = int(pict_size * aspect) if aspect < 1 else pict_size
        ic_h = int(pict_size / aspect) if aspect >= 1 else pict_size
        p = pict_img.resize((ic_w, ic_h), Image.LANCZOS)
        img.paste(p, ((W - ic_w) // 2, top_padding), p)
        draw = ImageDraw.Draw(img, "RGBA")
        top_zone_end = top_padding + ic_h

    word_font = ImageFont.truetype(fonts["cormorant_medium"], word_size)
    bb = word_font.getbbox("pregacuore")
    wx = (W - (bb[2] - bb[0])) // 2 - bb[0]
    wy = top_zone_end + word_y_gap
    draw.text((wx, wy), "pregacuore", font=word_font, fill=CREAM)
    top_zone_end = wy + (bb[3] - bb[1])

    # Payoff
    payoff_color = derive_payoff_color(CREAM, "bordeaux")
    payoff_size = 24 if is_story else (22 if is_pinterest else 20)
    payoff_font = ImageFont.truetype(fonts["inter_medium"], payoff_size)
    payoff_text = "Prega col cuore."
    bb = payoff_font.getbbox(payoff_text)
    payoff_x = (W - (bb[2] - bb[0])) // 2 - bb[0]
    payoff_y = H - (130 if is_story else (105 if is_pinterest else 95))
    bottom_zone_start = payoff_y - 20

    # Quote in oro
    margin = 120 if is_story else 140
    max_w = W - 2 * margin
    if is_story:
        size_ideal, size_min, size_step = 110, 72, 4; max_lines = 5
    elif is_pinterest:
        size_ideal, size_min, size_step = 96, 64, 4; max_lines = 5
    else:
        size_ideal, size_min, size_step = 86, 56, 4; max_lines = 4

    quote_size = size_ideal
    quote_font = ImageFont.truetype(fonts["cormorant_italic"], quote_size)
    quote_lines = wrap_text(quote.strip(), quote_font, max_w)
    while len(quote_lines) > max_lines and quote_size > size_min:
        quote_size -= size_step
        quote_font = ImageFont.truetype(fonts["cormorant_italic"], quote_size)
        quote_lines = wrap_text(quote.strip(), quote_font, max_w)

    bb = quote_font.getbbox("Ag")
    line_h = int((bb[3] - bb[1]) * 1.22)
    total_quote_h = line_h * len(quote_lines)
    rule_gap = 60 if is_story else 40
    ref_gap = 50 if is_story else 35
    ref_font = ImageFont.truetype(fonts["inter_medium"], 30 if is_story else 26)
    ref_bb = ref_font.getbbox("Ag")
    ref_h = ref_bb[3] - ref_bb[1]
    block_total_h = total_quote_h + rule_gap + 2 + ref_gap + ref_h
    available_top = top_zone_end + 40
    available_bottom = bottom_zone_start
    block_y_start = available_top + (available_bottom - available_top - block_total_h) // 2

    quote_y_end = draw_centered_lines(
        draw, quote_lines, quote_font, GOLD, W, block_y_start, 1.22
    )
    rule_y = quote_y_end + rule_gap
    rule_w = 80
    rule_x1 = (W - rule_w) // 2
    draw.line([(rule_x1, rule_y), (rule_x1 + rule_w, rule_y)],
              fill=GOLD, width=2)
    ref_text = f"VANGELO · {gospel_reference.upper()}"
    bb = ref_font.getbbox(ref_text)
    rx = (W - (bb[2] - bb[0])) // 2 - bb[0]
    draw.text((rx, rule_y + ref_gap), ref_text, font=ref_font, fill=CREAM)
    draw.text((payoff_x, payoff_y), payoff_text, font=payoff_font, fill=payoff_color)
    return img


# ------------------------------------------------------------------
# 8bis. LAYOUT "CARD-SANTINO" (v4)
# ------------------------------------------------------------------
# Passe-partout crema (#F5EBD8): riquadro DATA in alto a sinistra (numero
# grande + mese/anno), VERSETTO bordeaux a destra, finestra immagine con
# keyline oro, LOGO al piede a destra. Sorgente di stile: SPEC_card_generator
# + `card_layout` in landscape_manifest.yml.
#
# Due fonti (SPEC §1): HOUSE (`local_file`) arrivano GIA' incorniciate in
# assets/immagini/<base>_<fmt>.png (bande+immagine+keyline+logo bakeati) →
# qui si disegnano solo data+versetto. PD (`wikimedia_file`) vengono
# incorniciati a runtime (cover-crop nella finestra + tonalizzazione
# desaturate 0.45 + velo bordeaux 0.35 + bande/keyline/logo).
#
# La geometria delle bande DEVE combaciare con estendi_verticali_house.py
# (gli asset HOUSE sono bakeati con questi valori).
GOLD_FRAME = (201, 162, 75)      # #C9A24B — keyline/cornice
BORDEAUX_TENUE = (150, 75, 78)   # riferimento del versetto

MESI_IT = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
           "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]

SANTINO_LAYOUT = {
    "post":      {"W": 1254, "H": 1254, "top": 320, "bottom": 150, "verse_scale": 1.15},
    "story":     {"W": 1080, "H": 1920, "top": 500, "bottom": 150, "verse_scale": 1.00},
    "pinterest": {"W": 1000, "H": 1500, "top": 320, "bottom": 150, "verse_scale": 1.00},
}
SANTINO_LOGO_H = 65
SANTINO_LOGO_MARGIN_PCT = 0.05


def _sized_font(path, size, weight=None):
    f = ImageFont.truetype(path, max(6, int(size)))
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])   # Cormorant variabile: peso
        except Exception:
            pass
    return f


def _fit_height(path, text, target_h, weight=None):
    """Font la cui altezza-bbox del testo ~= target_h."""
    size = max(8, target_h)
    for _ in range(40):
        f = _sized_font(path, size, weight)
        bb = f.getbbox(text)
        h = bb[3] - bb[1]
        if h <= 0:
            break
        ratio = target_h / h
        if abs(ratio - 1) < 0.02:
            break
        size = max(6, int(size * ratio))
    return _sized_font(path, size, weight)


def _fit_width(path, text, target_w, max_size, weight=None):
    size = max_size
    while size > 8:
        f = _sized_font(path, size, weight)
        if f.getlength(text) <= target_w:
            return f
        size -= 2
    return _sized_font(path, 8, weight)


def _cover(src, W, Hh):
    sw, sh = src.size
    scale = max(W / sw, Hh / sh)
    nw, nh = round(sw * scale), round(sh * scale)
    r = src.resize((nw, nh), Image.LANCZOS)
    l, t = (nw - W) // 2, (nh - Hh) // 2
    return r.crop((l, t, l + W, t + Hh))


def _trim_alpha(img):
    bb = img.getbbox()
    return img.crop(bb) if bb else img


def tonalize_pd(art: Image.Image) -> Image.Image:
    """PD: desaturazione 0.45 + velo bordeaux 0.35 (card_layout.tonalization.pd)."""
    art = ImageEnhance.Color(art).enhance(1.0 - 0.45)
    veil = Image.new("RGB", art.size, BORDEAUX)
    return Image.blend(art, veil, 0.35)


def santino_draw_logo(canvas, fmt, fonts, pictograms):
    pit = (pictograms or {}).get("pictogram_bordeaux")
    if pit is None:
        return
    L = SANTINO_LAYOUT[fmt]
    W, H, bottom = L["W"], L["H"], L["bottom"]
    pit = _trim_alpha(pit)
    logo_h = min(SANTINO_LOGO_H, bottom - round(0.018 * H))
    margin = round(SANTINO_LOGO_MARGIN_PCT * W)
    pw, ph = pit.size
    pic_w = round(pw * (logo_h / ph))
    pic = pit.resize((pic_w, logo_h), Image.LANCZOS)

    font = _sized_font(fonts["cormorant_medium"], round(logo_h * 1.25), 600)
    draw = ImageDraw.Draw(canvas)
    wbb = draw.textbbox((0, 0), "pregacuore", font=font)
    gap = round(logo_h * 0.32)
    total_w = pic_w + gap + (wbb[2] - wbb[0])
    x0 = W - margin - total_w
    cy = H - bottom // 2
    canvas.paste(pic, (x0, cy - logo_h // 2), pic)
    draw.text((x0 + pic_w + gap - wbb[0], cy - (wbb[3] + wbb[1]) // 2),
              "pregacuore", font=font, fill=BORDEAUX)


def santino_build_frame(src, fmt, fonts, pictograms, is_pd):
    """Cornice a runtime (bande crema + finestra immagine + keyline + logo).
    Usata per i PD e come fallback se manca l'asset HOUSE incorniciato.
    Le HOUSE pre-incorniciate NON passano di qui."""
    L = SANTINO_LAYOUT[fmt]
    W, H, top, bottom = L["W"], L["H"], L["top"], L["bottom"]
    region_h = H - top - bottom

    canvas = Image.new("RGB", (W, H), CREAM)
    art = _cover(src.convert("RGB"), W, region_h)
    if is_pd:
        art = tonalize_pd(art)
    canvas.paste(art, (0, top))

    draw = ImageDraw.Draw(canvas)
    draw.line([(0, top - 1), (W, top - 1)], fill=GOLD_FRAME, width=1)
    draw.line([(0, top + region_h), (W, top + region_h)], fill=GOLD_FRAME, width=1)

    santino_draw_logo(canvas, fmt, fonts, pictograms)
    return canvas


def santino_draw_date(draw, fmt, day, mese_anno, fonts):
    """Riquadro quadrato a sinistra: keyline oro, numero grande, mese+anno."""
    L = SANTINO_LAYOUT[fmt]
    band_h = L["top"]
    box_side = round(band_h * 0.50)
    inset = round(band_h * 0.05)
    x0 = inset
    y0 = (band_h - box_side) // 2
    draw.rectangle([x0, y0, x0 + box_side, y0 + box_side], outline=GOLD_FRAME, width=3)

    pad = round(box_side * 0.08)
    inner_w = box_side - 2 * pad
    num_font = _fit_height(fonts["cormorant_medium"], day, round(box_side * 0.70), weight=600)
    nb = num_font.getbbox(day)
    num_w, num_h = nb[2] - nb[0], nb[3] - nb[1]
    ma_font = _fit_width(fonts["cormorant_medium"], mese_anno, inner_w,
                         round(box_side * 0.20), weight=600)
    mb = ma_font.getbbox(mese_anno)
    ma_w, ma_h = mb[2] - mb[0], mb[3] - mb[1]

    gap = round(box_side * 0.05)
    block_h = num_h + gap + ma_h
    top_y = y0 + (box_side - block_h) // 2
    cx = x0 + box_side // 2
    draw.text((cx - num_w / 2 - nb[0], top_y - nb[1]), day, font=num_font, fill=BORDEAUX)
    my = top_y + num_h + gap
    draw.text((cx - ma_w / 2 - mb[0], my - mb[1]), mese_anno, font=ma_font, fill=BORDEAUX)
    return x0 + box_side


def santino_draw_verse(draw, fmt, quote, ref, box_right, fonts):
    """Versetto bordeaux corsivo centro/destra + riferimento sotto."""
    L = SANTINO_LAYOUT[fmt]
    band_h, W, scale = L["top"], L["W"], L["verse_scale"]
    margin = round(0.045 * W)
    gap = round(0.03 * W)
    zx0 = box_right + gap
    zone_w = W - zx0 - margin

    ideal = round(band_h * 0.17 * scale)
    vmin = round(band_h * 0.08)
    size = ideal
    while size > vmin:
        f = _sized_font(fonts["cormorant_italic"], size)
        lines = wrap_text(quote.strip(), f, zone_w)
        too_wide = any(f.getlength(ln) > zone_w for ln in lines)
        if not too_wide and len(lines) <= 5:
            break
        size -= 2
    v_font = _sized_font(fonts["cormorant_italic"], size)
    v_lines = wrap_text(quote.strip(), v_font, zone_w)
    vh = v_font.getbbox("Ag")
    vlh = int((vh[3] - vh[1]) * 1.22)

    r_font = _sized_font(fonts["cormorant_italic"], round(size * 0.5))
    rb = r_font.getbbox(ref or "Ag")
    ref_h = rb[3] - rb[1]
    ref_gap = round(band_h * 0.05)

    block_h = vlh * len(v_lines) + (ref_gap + ref_h if ref else 0)
    vy = (band_h - block_h) // 2
    cx = zx0 + zone_w // 2
    for ln in v_lines:
        lw = v_font.getlength(ln)
        draw.text((cx - lw / 2, vy), ln, font=v_font, fill=BORDEAUX)
        vy += vlh
    if ref:
        rw = r_font.getlength(ref)
        draw.text((cx - rw / 2, vy + ref_gap), ref, font=r_font, fill=BORDEAUX_TENUE)


def santino_resolve_source(entry, fmt):
    """Risolve il file sorgente per (entry, formato).
    HOUSE (local_file) → asset incorniciato immagini/<base>_<fmt>.png
      ('house_framed'); fallback al quadrato grezzo ('house_raw').
    PD (wikimedia_file) → crop puro landscapes/<slug>_<fmt>.png ('pd'),
      fallback al crop _post. Ritorna (kind, Path) o (None, None)."""
    if not entry:
        return (None, None)
    if entry.get("local_file"):
        base = Path(entry["local_file"]).stem
        framed = ASSETS_DIR / "immagini" / f"{base}_{fmt}.png"
        if framed.exists():
            return ("house_framed", framed)
        raw = ASSETS_DIR / "immagini" / f"{base}.png"
        if raw.exists():
            return ("house_raw", raw)
        return (None, None)
    slug = entry.get("slug", "")
    for cand in (LANDSCAPES_DIR / f"{slug}_{fmt}.png",
                 LANDSCAPES_DIR / f"{slug}_post.png"):
        if cand.exists():
            return ("pd", cand)
    return (None, None)


def select_entry_for_day(target_date, season, palette, manifest):
    """Come select_landscape_for_day ma ritorna l'ENTRY del manifest (per
    distinguere HOUSE/PD), verificando che esista un file usabile."""
    if not manifest:
        return None
    palette_row = palette.get(season) if palette else None
    moods = set(palette_row.get("landscape_mood") or []) if palette_row else set()
    if moods:
        candidates = [l for l in manifest if set(l.get("moods", [])) & moods]
    else:
        candidates = list(manifest)
    if not candidates:
        candidates = list(manifest)
    non_reserve = [c for c in candidates if not c.get("reserve")]
    if len(non_reserve) >= 3:
        candidates = non_reserve

    import hashlib
    seed = int(hashlib.md5(target_date.isoformat().encode()).hexdigest()[:8], 16)
    n = len(candidates)
    start = seed % n
    for off in range(n):
        cand = candidates[(start + off) % n]
        if santino_resolve_source(cand, "post")[1] is not None:
            return cand
    return None


def compose_card_santino(target_date, quote, ref, fmt, fonts,
                         kind, src_path, pictograms):
    """Compone la card-santino per un formato. `kind` da santino_resolve_source."""
    pictograms = pictograms or {}
    if kind == "house_framed":
        base = Image.open(src_path).convert("RGB")
    elif kind in ("house_raw", "pd"):
        src = Image.open(src_path)
        base = santino_build_frame(src, fmt, fonts, pictograms, is_pd=(kind == "pd"))
    else:
        # Nessuno sfondo disponibile: fallback bordeaux pieno (v2.1)
        return _compose_card_fallback_v2(quote, ref, fmt, fonts, None, pictograms, "bordeaux")

    draw = ImageDraw.Draw(base)
    day = str(target_date.day)
    mese_anno = f"{MESI_IT[target_date.month - 1]} {target_date.year}"
    box_right = santino_draw_date(draw, fmt, day, mese_anno, fonts)
    santino_draw_verse(draw, fmt, quote, ref, box_right, fonts)
    return base


# ------------------------------------------------------------------
# 9. Lettura/scrittura Supabase
# ------------------------------------------------------------------
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_daily_row(supabase: Client, target_date: date) -> Optional[dict]:
    """Carica la riga daily_content del giorno target.
    NOTA: in v3.0 selezioniamo anche `liturgical_season` (se la colonna
    esiste) e `social_pinterest_url`. Per retrocompatibilita', se la
    colonna `liturgical_season` non esiste ancora a schema, la select
    fallisce e fallback su `*` (tutti i campi).
    """
    try:
        res = (
            supabase.table("daily_content")
            .select("id, content_date, quote, gospel_reference, "
                    "saint_of_day, liturgical_day, liturgical_season, "
                    "social_card_url, social_story_url, social_pinterest_url")
            .eq("content_date", target_date.isoformat())
            .limit(1)
            .execute()
        )
    except Exception:
        # Colonne nuove non ancora presenti; fallback piu' permissivo
        res = (
            supabase.table("daily_content")
            .select("*")
            .eq("content_date", target_date.isoformat())
            .limit(1)
            .execute()
        )
    if not res.data:
        return None
    return res.data[0]


def upload_card(supabase: Client, png_bytes: bytes, key: str,
                content_type: str = "image/png") -> str:
    storage = supabase.storage.from_(BUCKET)
    try:
        storage.upload(
            path=key,
            file=png_bytes,
            file_options={
                "content-type": content_type,
                "cache-control": "public, max-age=86400",
                "upsert": "true",
            },
        )
    except Exception as e:
        msg = str(e).lower()
        if "not found" in msg or "bucket" in msg:
            print(f"X  Bucket '{BUCKET}' non trovato. Crealo su Supabase Studio (Public).")
            sys.exit(1)
        if "415" in msg or "invalid_mime_type" in msg or "mime type" in msg:
            print(
                f"X  {key}: {e}\n"
                f"   Soluzione: Supabase Studio → Storage → {BUCKET} → Edit bucket\n"
                f"   → Allowed MIME types → aggiungi 'image/jpeg'"
            )
            sys.exit(1)
        raise
    return storage.get_public_url(key).rstrip("?")


def update_card_urls(supabase: Client, row_id: int,
                     post_url: str, story_url: str,
                     pinterest_url: Optional[str] = None) -> None:
    """Salva gli URL dei PNG come riferimento canonico. Gli URL dei JPEG
    sono ricavabili sostituendo .png con .jpg (stesso path).
    `pinterest_url` e' opzionale per retrocompatibilita': se la colonna
    `social_pinterest_url` non esiste, l'update viene riprovato senza
    quel campo."""
    payload = {
        "social_card_url":  post_url,
        "social_story_url": story_url,
    }
    if pinterest_url:
        payload["social_pinterest_url"] = pinterest_url

    try:
        supabase.table("daily_content").update(payload).eq("id", row_id).execute()
    except Exception as e:
        # La colonna social_pinterest_url potrebbe non esistere ancora a schema.
        if pinterest_url and ("pinterest" in str(e).lower() or "column" in str(e).lower()):
            payload.pop("social_pinterest_url", None)
            supabase.table("daily_content").update(payload).eq("id", row_id).execute()
            print(f"!!  Colonna social_pinterest_url assente, salvati solo post+story.")
        else:
            raise


# ------------------------------------------------------------------
# 10. Pipeline per una singola data
# ------------------------------------------------------------------
def process_date(target_date: date, fonts: dict,
                 paper_texture: Optional[Image.Image],
                 pictograms: dict,
                 landscape_manifest: list,
                 palette: dict,
                 legacy_artwork_manifest: dict,
                 use_landscape: bool,
                 preview_only: bool) -> bool:
    supabase = get_supabase()
    row = fetch_daily_row(supabase, target_date)
    if not row:
        print(f">>  {target_date.isoformat()}: nessun pensiero in DB. Salto.")
        return False

    quote = row["quote"]
    ref = row["gospel_reference"]

    # Season liturgica → mood per la scelta dello sfondo (v4: il template
    # giorno-settimana non incide piu' sul look, la card-santino e' unica)
    season = derive_season_from_row(row, target_date)

    # Selezione ENTRY del manifest (HOUSE o PD), deterministica sulla data
    entry = None
    origin = "neutro (fallback bordeaux)"
    if use_landscape:
        entry = select_entry_for_day(target_date, season, palette, landscape_manifest)
        if entry:
            tipo = "house" if entry.get("local_file") else "pd"
            origin = f"{tipo}: {entry.get('slug', '?')}"

    print(f">>  {target_date.isoformat()} [{season}] - {origin}")
    print(f"    {quote[:80]}{'...' if len(quote) > 80 else ''}")

    # Genero le 3 card-santino (post, story, pinterest)
    images = {}
    for fmt in ("post", "story", "pinterest"):
        kind, src_path = santino_resolve_source(entry, fmt)
        images[fmt] = compose_card_santino(
            target_date, quote, ref, fmt, fonts, kind, src_path, pictograms
        )

    # Salvataggio locale: PNG + JPEG per ciascun formato
    local_paths = {}
    for fmt, img in images.items():
        png_path = OUTPUT_DIR / f"{fmt}_{target_date.isoformat()}.png"
        jpg_path = OUTPUT_DIR / f"{fmt}_{target_date.isoformat()}.jpg"
        img.save(png_path, "PNG")
        img.save(jpg_path, "JPEG", quality=92, optimize=True)
        local_paths[fmt] = (png_path, jpg_path)

    print(f"    locale post:      {local_paths['post'][0]}")
    print(f"    locale story:     {local_paths['story'][0]}")
    print(f"    locale pinterest: {local_paths['pinterest'][0]}")

    if preview_only:
        return True

    # Upload su Supabase Storage
    def to_bytes(img: Image.Image, fmt: str, **kw) -> bytes:
        buf = BytesIO()
        img.save(buf, fmt, **kw)
        return buf.getvalue()

    urls = {}
    for fmt, img in images.items():
        urls[f"{fmt}_png"] = upload_card(
            supabase, to_bytes(img, "PNG"),
            f"{fmt}/{target_date.isoformat()}.png", "image/png"
        )
        urls[f"{fmt}_jpg"] = upload_card(
            supabase, to_bytes(img, "JPEG", quality=92, optimize=True),
            f"{fmt}/{target_date.isoformat()}.jpg", "image/jpeg"
        )

    print(f"    cloud post PNG:      {urls['post_png']}")
    print(f"    cloud story PNG:     {urls['story_png']}")
    print(f"    cloud pinterest PNG: {urls['pinterest_png']}")

    # Aggiorno DB
    update_card_urls(
        supabase, row["id"],
        post_url=urls["post_png"],
        story_url=urls["story_png"],
        pinterest_url=urls["pinterest_png"],
    )
    print(f"    OK: social_card_url + social_story_url + social_pinterest_url aggiornati")
    return True


# ------------------------------------------------------------------
# 11. CLI
# ------------------------------------------------------------------
def parse_iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def parse_args():
    p = argparse.ArgumentParser(description="Pregacuore card generator v3.0")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=parse_iso_date)
    g.add_argument("--tomorrow", action="store_true")
    g.add_argument("--ahead", type=int, metavar="N")
    p.add_argument("--from", dest="date_from", type=parse_iso_date)
    p.add_argument("--to", dest="date_to", type=parse_iso_date)
    p.add_argument("--preview-only", action="store_true",
                   help="Solo locale, no upload Supabase")
    p.add_argument("--no-landscape", action="store_true",
                   help="Forza sfondo neutro, ignora landscape_manifest.yml")
    # Alias retrocompatibile con v2.1
    p.add_argument("--no-artwork", action="store_true",
                   help="Alias di --no-landscape per retrocompatibilita")
    return p.parse_args()


def resolve_dates(args) -> list:
    today = date.today()
    if args.date_from and args.date_to:
        if args.date_to < args.date_from:
            sys.exit("X  --to deve essere >= --from")
        return list(daterange(args.date_from, args.date_to))
    if args.date_from or args.date_to:
        sys.exit("X  --from e --to vanno usati insieme")
    if args.date:
        return [args.date]
    if args.tomorrow:
        return [today + timedelta(days=1)]
    if args.ahead is not None:
        return [today + timedelta(days=args.ahead)]
    return [today]


def main():
    args = parse_args()
    dates = resolve_dates(args)

    # --no-artwork e --no-landscape sono alias
    use_landscape = not (args.no_landscape or args.no_artwork)

    print("\n>>  Pregacuore card generator v3.0")
    print(f"    {len(dates)} card x 3 formati ({dates[0].isoformat()} -> {dates[-1].isoformat()})")
    if args.preview_only:
        print("    Modalita': PREVIEW (no upload)")
    if not use_landscape:
        print("    Paesaggi: disabilitati")
    print()

    fonts = ensure_fonts()
    paper_texture = load_paper_texture()
    pictograms = load_pictograms()
    # Caricamento asset v3.0
    landscape_manifest = [] if not use_landscape else load_landscape_manifest()
    if landscape_manifest:
        print(f"    Landscape manifest: {len(landscape_manifest)} paesaggi caricati")
    # Legacy artwork (retrocompat con v2.1)
    legacy_artwork_manifest = {} if not use_landscape else load_artwork_manifest()

    # Carico palette liturgica una volta sola (validita' su tutto il run)
    supabase = get_supabase()
    palette = fetch_liturgical_palette(supabase)
    if palette:
        print(f"    Palette liturgica: {len(palette)} stagioni caricate")
    else:
        print(f"    Palette liturgica: non disponibile, uso template brand statici")

    success = 0
    for d in dates:
        try:
            if process_date(d, fonts, paper_texture, pictograms,
                            landscape_manifest, palette, legacy_artwork_manifest,
                            use_landscape, args.preview_only):
                success += 1
        except Exception as e:
            print(f"X  {d.isoformat()}: {e}")
            import traceback; traceback.print_exc()

    print(f"\nOK: {success}/{len(dates)} giorni elaborati (3 formati ciascuno).")
    print(f"   Locale: {OUTPUT_DIR}/\n")


if __name__ == "__main__":
    main()