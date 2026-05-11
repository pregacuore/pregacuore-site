"""
==============================================================================
PREGACUORE — Card Generator per Instagram (v2.1)

Cosa cambia rispetto a v2.0:
    - LOCKUP VERTICALE IN ALTO: pittogramma + wordmark "pregacuore" centrati
      sopra la citazione. E' la versione del lockup definita nel brand book
      ufficiale (sezione "Lockup verticale: per profili social").
      In basso resta solo il payoff "Prega col cuore." come firma sobria.
    - Layout a tre zone: TOP (lockup), MIDDLE (citazione + linea + ref),
      BOTTOM (solo payoff).

Cosa cambia rispetto a v1.2:
    - Tipografia protagonista: la citazione e' la cosa che lo sguardo
      cerca; il brand mark e' presente ma non invasivo.
    - Sfondo arricchito: colore base + texture papiro (multiply ~10%)
      per dare vita al colore piatto.
    - Quinta opzionale: se per il giorno esiste un'opera di pubblico
      dominio in assets/artwork/ mappata in artwork_calendar.yml, viene
      usata come sfondo desaturato + tinta bordeaux dietro la citazione.
      Quando manca, fallback silenzioso allo sfondo neutro.
    - Fix bug v1.2: il payoff non viene piu' schiarito sopra il wordmark
      cream (era piu' chiaro del wordmark, illeggibile/sbagliato). Adesso
      e' sempre derivato come una versione meno satura del wordmark.
    - Export DOPPIO: PNG (per il sito, qualita' lossless) e JPEG q92
      (per Instagram, che NON accetta PNG nella Graph API publish).
    - Caricamento DOPPIO su Supabase Storage: post_*.png + post_*.jpg
      sotto la stessa chiave di base. La colonna social_card_url tiene
      il PNG; il JPG e' ricavabile sostituendo l'estensione.

Modalita' d'uso (invariate):
    python card_generator.py                              # oggi
    python card_generator.py --date 2026-05-15            # data specifica
    python card_generator.py --from 2026-05-11 --to 2026-06-10
    python card_generator.py --tomorrow                   # solo domani
    python card_generator.py --ahead 30                   # solo T+30
    python card_generator.py --preview-only               # solo locale
    python card_generator.py --no-artwork                 # forza sfondo neutro
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
ARTWORK_DIR = ASSETS_DIR / "artwork"

OUTPUT_DIR = Path(os.environ.get("TEMP", "/tmp")) / "pregacuore_cards"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
    """Carica i 2 pittogrammi (cream e bordeaux) trasparenti per il lockup
    in alto sulla card. Se mancano, ritorna dict vuoto e compose_card
    fara' a meno del brand mark in alto (degradazione silente)."""
    out = {}
    for name in ("pictogram_cream", "pictogram_bordeaux"):
        p = ASSETS_DIR / f"{name}.png"
        if p.exists():
            out[name] = Image.open(p).convert("RGBA")
        else:
            print(f"!!  {p} non trovato. Lancia 'python setup_assets.py' per generarlo.")
    return out


def load_artwork_manifest() -> dict:
    """Carica il manifest YAML che mappa stagione/santo → file immagine.
    Ritorna un dict vuoto se il file non esiste o non e' valido."""
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
    """Cerca un'opera adatta per il giorno corrente:
    1) match su saint_of_day contro 'saints'
    2) match su liturgical_day contro 'seasons'
    3) niente (None)

    Match per sottostringa lowercase: piu' permissivo possibile.
    Restituisce il Path al file se ESISTE in assets/artwork/, altrimenti None.
    """
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

    # 1) santo del giorno (priorita' alta)
    p = match_in("saints", saint_of_day or "")
    if p:
        return Path(p)

    # 2) tempo liturgico
    p = match_in("seasons", liturgical_day or "")
    if p:
        return Path(p)

    return None


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


def compose_card(template: str, quote: str, gospel_reference: str,
                 is_story: bool, fonts: dict,
                 paper_texture: Optional[Image.Image] = None,
                 artwork_path: Optional[Path] = None,
                 pictograms: Optional[dict] = None) -> Image.Image:
    """Compone una card con layout a tre zone:
       TOP    — lockup verticale (pittogramma + 'pregacuore' centrati)
       MIDDLE — citazione + linea decorativa + riferimento Vangelo
       BOTTOM — payoff 'Prega col cuore.' (solo firma sobria)
    """
    W = 1080
    H = 1920 if is_story else 1080
    pictograms = pictograms or {}

    # Colori per template
    if template == "bordeaux":
        bg_color    = BORDEAUX
        quote_color = GOLD
        ref_color   = CREAM
        word_color  = CREAM
        rule_color  = GOLD
        artwork_tint = CREAM
        pict_key = "pictogram_cream"
    elif template == "cream":
        bg_color    = CREAM
        quote_color = BORDEAUX
        ref_color   = BORDEAUX
        word_color  = BORDEAUX
        rule_color  = GOLD
        artwork_tint = BORDEAUX
        pict_key = "pictogram_bordeaux"
    else:  # avorio
        bg_color    = AVORIO
        quote_color = BORDEAUX
        ref_color   = GOLD
        word_color  = BORDEAUX
        rule_color  = GOLD
        artwork_tint = BORDEAUX
        pict_key = "pictogram_bordeaux"

    # ── 1. Sfondo base
    img = Image.new("RGB", (W, H), bg_color)

    # ── 2. Eventuale opera d'arte come quinta (PRIMA della texture)
    if artwork_path and artwork_path.exists():
        img = apply_artwork_background(img, artwork_path, artwork_tint)

    # ── 3. Texture papiro come overlay multiply leggero
    img = apply_paper_texture(img, paper_texture, strength=0.10)

    draw = ImageDraw.Draw(img, "RGBA")

    # ── 4. TOP: lockup verticale (pittogramma + wordmark)
    pict_size = 110 if is_story else 90
    top_padding = 110 if is_story else 80
    top_zone_end = top_padding  # default se manca il pittogramma

    pict_img = pictograms.get(pict_key)
    if pict_img is not None:
        p = pict_img.resize((pict_size, pict_size), Image.LANCZOS)
        pict_x = (W - pict_size) // 2
        pict_y = top_padding
        img.paste(p, (pict_x, pict_y), p)
        # Re-creo draw dopo paste per evitare riferimenti stantii
        draw = ImageDraw.Draw(img, "RGBA")
        top_zone_end = pict_y + pict_size

    # Wordmark "pregacuore" sotto al pittogramma
    word_size = 50 if is_story else 42
    word_font = ImageFont.truetype(fonts["cormorant_medium"], word_size)
    word_text = "pregacuore"
    bb = word_font.getbbox(word_text)
    wx = (W - (bb[2] - bb[0])) // 2 - bb[0]
    word_y_gap = 14 if is_story else 10
    wy = top_zone_end + word_y_gap
    draw.text((wx, wy), word_text, font=word_font, fill=word_color)
    top_zone_end = wy + (bb[3] - bb[1])

    # ── 5. BOTTOM: solo payoff (calcolo prima la posizione cosi' so dove
    # finisce la zona disponibile per la citazione al centro)
    payoff_color = derive_payoff_color(word_color, template)
    payoff_size = 24 if is_story else 20
    payoff_font = ImageFont.truetype(fonts["inter_medium"], payoff_size)
    payoff_text = "Prega col cuore."
    bb = payoff_font.getbbox(payoff_text)
    payoff_x = (W - (bb[2] - bb[0])) // 2 - bb[0]
    payoff_y = H - (130 if is_story else 95)
    bottom_zone_start = payoff_y - 20  # margine sopra il payoff

    # Disegno il payoff dopo, mi serviva solo la posizione adesso

    # ── 6. MIDDLE: citazione + linea + ref, centrati nello spazio rimasto
    margin = 110
    max_w = W - 2 * margin
    quote_size = 110 if is_story else 86
    quote_font = ImageFont.truetype(fonts["cormorant_italic"], quote_size)

    quote_text = quote.strip()
    quote_lines = wrap_text(quote_text, quote_font, max_w)
    bb = quote_font.getbbox("Ag")
    line_h = int((bb[3] - bb[1]) * 1.22)
    total_quote_h = line_h * len(quote_lines)

    # Spazio disponibile per il blocco quote+linea+ref
    rule_gap = 60 if is_story else 40
    ref_gap = 50 if is_story else 35
    ref_font = ImageFont.truetype(fonts["inter_medium"], 30 if is_story else 26)
    ref_bb = ref_font.getbbox("Ag")
    ref_h = ref_bb[3] - ref_bb[1]
    block_total_h = total_quote_h + rule_gap + 2 + ref_gap + ref_h

    # Centro il blocco tra top_zone_end (con un po' di margine) e
    # bottom_zone_start (con un po' di margine)
    available_top = top_zone_end + 40
    available_bottom = bottom_zone_start
    block_y_start = available_top + (available_bottom - available_top - block_total_h) // 2

    # Disegno citazione
    quote_y_end = draw_centered_lines(
        draw, quote_lines, quote_font, quote_color, W, block_y_start, 1.22
    )

    # Linea decorativa
    rule_y = quote_y_end + rule_gap
    rule_w = 80
    rule_x1 = (W - rule_w) // 2
    draw.line([(rule_x1, rule_y), (rule_x1 + rule_w, rule_y)],
              fill=rule_color, width=2)

    # Riferimento Vangelo
    ref_text = f"VANGELO  ·  {gospel_reference.upper()}"
    bb = ref_font.getbbox(ref_text)
    rx = (W - (bb[2] - bb[0])) // 2 - bb[0]
    ry = rule_y + ref_gap
    draw.text((rx, ry), ref_text, font=ref_font, fill=ref_color)

    # ── 7. Disegno il payoff in basso (gia' calcolata posizione al punto 5)
    draw.text((payoff_x, payoff_y), payoff_text, font=payoff_font, fill=payoff_color)

    return img


# ------------------------------------------------------------------
# 9. Lettura/scrittura Supabase
# ------------------------------------------------------------------
def get_supabase() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


def fetch_daily_row(supabase: Client, target_date: date) -> Optional[dict]:
    res = (
        supabase.table("daily_content")
        .select("id, content_date, quote, gospel_reference, "
                "saint_of_day, liturgical_day, social_card_url")
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
                     post_url: str, story_url: str) -> None:
    """Salva l'URL del PNG come riferimento canonico. L'URL del JPEG e'
    ricavabile sostituendo .png con .jpg (stesso path)."""
    supabase.table("daily_content").update({
        "social_card_url":  post_url,
        "social_story_url": story_url,
    }).eq("id", row_id).execute()


# ------------------------------------------------------------------
# 10. Pipeline per una singola data
# ------------------------------------------------------------------
def process_date(target_date: date, fonts: dict,
                 paper_texture: Optional[Image.Image],
                 pictograms: dict,
                 manifest: dict,
                 use_artwork: bool,
                 preview_only: bool) -> bool:
    supabase = get_supabase()
    row = fetch_daily_row(supabase, target_date)
    if not row:
        print(f">>  {target_date.isoformat()}: nessun pensiero in DB. Salto.")
        return False

    quote = row["quote"]
    ref = row["gospel_reference"]
    saint = row.get("saint_of_day") or ""
    season = row.get("liturgical_day") or ""
    template = select_template(target_date)

    # Ricerca artwork (se attivata e disponibile)
    artwork = None
    if use_artwork and manifest:
        artwork = find_artwork_for_day(saint, season, manifest)
        if artwork:
            print(f">>  {target_date.isoformat()} ({template}) - artwork: {artwork.name}")
        else:
            print(f">>  {target_date.isoformat()} ({template}) - sfondo neutro")
    else:
        print(f">>  {target_date.isoformat()} ({template}) - sfondo neutro (artwork off)")
    print(f"    {quote[:80]}{'...' if len(quote) > 80 else ''}")

    post_img = compose_card(template, quote, ref, is_story=False,
                            fonts=fonts, paper_texture=paper_texture,
                            artwork_path=artwork, pictograms=pictograms)
    story_img = compose_card(template, quote, ref, is_story=True,
                             fonts=fonts, paper_texture=paper_texture,
                             artwork_path=artwork, pictograms=pictograms)

    # Salvataggio locale: PNG (per archivio) e JPEG (per IG)
    post_png_path = OUTPUT_DIR / f"post_{target_date.isoformat()}.png"
    post_jpg_path = OUTPUT_DIR / f"post_{target_date.isoformat()}.jpg"
    story_png_path = OUTPUT_DIR / f"story_{target_date.isoformat()}.png"
    story_jpg_path = OUTPUT_DIR / f"story_{target_date.isoformat()}.jpg"

    post_img.save(post_png_path, "PNG")
    post_img.save(post_jpg_path, "JPEG", quality=92, optimize=True)
    story_img.save(story_png_path, "PNG")
    story_img.save(story_jpg_path, "JPEG", quality=92, optimize=True)

    print(f"    locale: {post_png_path}")
    print(f"    locale: {post_jpg_path}")

    if preview_only:
        return True

    # Upload su Supabase Storage (PNG + JPG, stesso path con estensione diversa)
    def to_bytes(img: Image.Image, fmt: str, **kw) -> bytes:
        buf = BytesIO()
        img.save(buf, fmt, **kw)
        return buf.getvalue()

    post_png_url = upload_card(supabase, to_bytes(post_img, "PNG"),
                                f"post/{target_date.isoformat()}.png", "image/png")
    post_jpg_url = upload_card(supabase, to_bytes(post_img, "JPEG", quality=92, optimize=True),
                                f"post/{target_date.isoformat()}.jpg", "image/jpeg")
    story_png_url = upload_card(supabase, to_bytes(story_img, "PNG"),
                                 f"story/{target_date.isoformat()}.png", "image/png")
    story_jpg_url = upload_card(supabase, to_bytes(story_img, "JPEG", quality=92, optimize=True),
                                 f"story/{target_date.isoformat()}.jpg", "image/jpeg")

    print(f"    cloud post PNG:  {post_png_url}")
    print(f"    cloud post JPG:  {post_jpg_url}")
    print(f"    cloud story PNG: {story_png_url}")
    print(f"    cloud story JPG: {story_jpg_url}")

    # Aggiorno DB col PNG (URL canonico per il sito); il publisher Instagram
    # ricava il JPG sostituendo l'estensione.
    update_card_urls(supabase, row["id"], post_png_url, story_png_url)
    print(f"    OK: social_card_url + social_story_url aggiornati")
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
    p = argparse.ArgumentParser(description="Pregacuore card generator v2.0")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=parse_iso_date)
    g.add_argument("--tomorrow", action="store_true")
    g.add_argument("--ahead", type=int, metavar="N")
    p.add_argument("--from", dest="date_from", type=parse_iso_date)
    p.add_argument("--to", dest="date_to", type=parse_iso_date)
    p.add_argument("--preview-only", action="store_true",
                   help="Solo locale, no upload Supabase")
    p.add_argument("--no-artwork", action="store_true",
                   help="Forza sfondo neutro, ignora artwork_calendar.yml")
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

    print("\n>>  Pregacuore card generator v2.0")
    print(f"    {len(dates)} card ({dates[0].isoformat()} -> {dates[-1].isoformat()})")
    if args.preview_only:
        print("    Modalita': PREVIEW (no upload)")
    if args.no_artwork:
        print("    Artwork PD: disabilitato (--no-artwork)")
    print()

    fonts = ensure_fonts()
    paper_texture = load_paper_texture()
    pictograms = load_pictograms()
    manifest = {} if args.no_artwork else load_artwork_manifest()
    use_artwork = not args.no_artwork

    success = 0
    for d in dates:
        try:
            if process_date(d, fonts, paper_texture, pictograms, manifest,
                            use_artwork, args.preview_only):
                success += 1
        except Exception as e:
            print(f"X  {d.isoformat()}: {e}")
            import traceback; traceback.print_exc()

    print(f"\nOK: {success}/{len(dates)} card generate.")
    print(f"   Locale: {OUTPUT_DIR}/\n")


if __name__ == "__main__":
    main()
