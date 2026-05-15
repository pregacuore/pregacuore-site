"""
Pregacuore - download_landscapes.py
=====================================

Scarica i paesaggi di pubblico dominio definiti in
`assets/landscape_manifest.yml` da Wikimedia Commons e li salva in
`assets/landscapes/` nelle 3 dimensioni usate dal card_generator:

    - <slug>_post.png      1080x1080  (Instagram post)
    - <slug>_story.png     1080x1920  (Instagram/FB story, reel)
    - <slug>_pinterest.png 1080x1620  (Pinterest 2:3)

Strategia di risoluzione (due tentativi a cascata):
    1. Prova il `wikimedia_file` esatto del manifest
    2. Se fallisce, cerca su Wikimedia con artista+titolo e prende
       il primo risultato sensato (filtra per estensione, scora per
       presenza cognome artista + parole-chiave titolo + dimensione)

I file scoperti via search vengono loggati alla fine cosi possiamo
aggiornare il manifest con i nomi corretti.

CLI:
    python download_landscapes.py                  # tutti
    python download_landscapes.py --only <slug>    # uno solo
    python download_landscapes.py --skip-reserve   # esclude Friedrich/Grimshaw
    python download_landscapes.py --force          # riscarica anche cached
    python download_landscapes.py --dry-run        # mostra cosa farebbe
"""

from __future__ import annotations

import argparse
import sys
import time
from io import BytesIO
from pathlib import Path

import requests
import yaml
from PIL import Image

# ---------------------------------------------------------------------------
# Path config
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = SCRIPT_DIR / "assets"
MANIFEST_PATH = ASSETS_DIR / "landscape_manifest.yml"
LANDSCAPES_DIR = ASSETS_DIR / "landscapes"

# ---------------------------------------------------------------------------
# Dimensioni di output (DEVE essere allineato con card_generator.py)
# ---------------------------------------------------------------------------
SIZES = {
    "post":      (1080, 1080),
    "story":     (1080, 1920),
    "pinterest": (1080, 1620),
}

# ---------------------------------------------------------------------------
# Wikimedia API
# ---------------------------------------------------------------------------
WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "PregacuoreLandscapeFetcher/1.0 (https://pregacuore.it; info@pregacuore.it)"

# Massima dimensione richiesta a Wikimedia (lato lungo). 2400px e' largamente
# sufficiente per crop a 1080 (lascia >2x oversampling per crop verticali).
MAX_FETCH_LONG_SIDE = 2400


def resolve_exact_filename(file_name: str, session: requests.Session) -> tuple[str | None, str | None]:
    """Prova il nome esatto. Ritorna (url, filename_usato) o (None, None) se non trovato."""
    params = {
        "action": "query",
        "format": "json",
        "titles": f"File:{file_name}",
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": MAX_FETCH_LONG_SIDE,
    }
    try:
        r = session.get(WIKIMEDIA_API, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"   !! API error per {file_name}: {e}")
        return None, None

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return None, None
    page = next(iter(pages.values()))
    if "missing" in page:
        return None, None
    info = page.get("imageinfo", [])
    if not info:
        return None, None
    ii = info[0]
    return (ii.get("thumburl") or ii.get("url"), file_name)


def search_wikimedia_file(artist: str, title: str, session: requests.Session,
                          year: int | None = None) -> tuple[str | None, str | None]:
    """Cerca su Wikimedia Commons un file matching artista+titolo.
    Usa generator=search per ottenere candidati nel namespace File: (ns=6).
    Ritorna (url, filename) del primo candidato adatto, o (None, None).

    Strategia: lancia piu query in cascata, accumula candidati da tutte,
    sceglie il migliore con scoring robusto.

    Ranking:
      - Solo file con estensione immagine (.jpg, .jpeg, .png, .tif, .tiff)
      - Bonus se nome contiene cognome o nome alternativo dell'artista
      - Bonus per ogni parola-chiave del titolo presente
      - Bonus per anno (esatto o nelle stringhe "1864", "(1864)")
      - Bonus per file Google Art Project
      - Penalita: detail, thumb, study, sketch, frame_only, small, icon
    """
    # Costruisci le varianti del nome artista (gestisce nomi compositi)
    artist_parts = artist.split() if artist else []
    last_name = artist_parts[-1].lower() if artist_parts else ""
    full_lower = artist.lower() if artist else ""

    # Mappe di nomi alternativi noti su Wikimedia
    ALTERNATIVE_NAMES = {
        "aivazovsky": ["aivazovsky", "konstantinovich aivazovsky", "ayvazyan",
                       "aivasovsky"],
        "hokusai": ["hokusai", "katsushika hokusai"],
        "van gogh": ["van gogh", "vincent van gogh"],
        "monet": ["monet", "claude monet"],
        "renoir": ["renoir", "auguste renoir", "pierre-auguste renoir"],
        "turner": ["turner", "jmw turner", "j.m.w. turner", "william turner",
                   "mallord william turner"],
        "constable": ["constable", "john constable"],
        "pissarro": ["pissarro", "camille pissarro"],
        "sisley": ["sisley", "alfred sisley"],
        "corot": ["corot", "camille corot", "jean-baptiste-camille corot"],
        "homer": ["homer", "winslow homer"],
        "inness": ["inness", "george inness"],
        "bierstadt": ["bierstadt", "albert bierstadt"],
        "church": ["church", "frederic edwin church", "frederic church"],
        "cole": ["cole", "thomas cole"],
        "rousseau": ["rousseau", "theodore rousseau", "théodore rousseau"],
        "roberts": ["roberts", "david roberts"],
        "friedrich": ["friedrich", "caspar david friedrich"],
        "bruegel": ["bruegel", "brueghel", "pieter bruegel"],
        "hiroshige": ["hiroshige", "utagawa hiroshige", "andō hiroshige"],
        "grimshaw": ["grimshaw", "atkinson grimshaw"],
    }
    # Tutti i nomi alternativi rilevanti per questo artista
    artist_aliases = []
    for key, aliases in ALTERNATIVE_NAMES.items():
        if key in full_lower:
            artist_aliases.extend(aliases)
            break
    if not artist_aliases:
        artist_aliases = [last_name] if last_name else []

    # Parole chiave del titolo
    stop = {"the", "of", "a", "il", "la", "le", "in", "su", "al", "del", "della",
            "di", "e", "o", "un", "una", "and", "from", "to", "for", "on",
            "at", "with", "by", "il", "lo"}
    # Pulisci punteggiatura, tieni anche varianti tra italiano e altre lingue
    title_words_raw = [w.lower().strip(".,;:'\"()«»") for w in title.split()]
    title_words = [w for w in title_words_raw if w and w not in stop and len(w) > 2]

    # Query da provare (in ordine)
    queries = [
        f"{artist} {title}",            # tutto insieme
        f"{last_name} {title}",         # cognome + titolo
        title,                          # solo titolo (le opere famose si trovano cosi)
    ]
    # Dedup
    queries = list(dict.fromkeys(queries))

    BAD_KEYWORDS = ["detail", "thumb", "icon", "frame_only", "frame_detail",
                    "small_", "low_res", "study_for", "sketch_for",
                    "_study_", "_sketch_", "_copy_", "_print_after"]
    IMG_EXTS = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp")

    all_candidates = {}  # filename -> (score, width, url)

    for q in queries:
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": q,
            "gsrnamespace": 6,
            "gsrlimit": 15,
            "prop": "imageinfo",
            "iiprop": "url|size|mime",
            "iiurlwidth": MAX_FETCH_LONG_SIDE,
        }
        try:
            r = session.get(WIKIMEDIA_API, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception:
            continue

        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            title_page = page.get("title", "")
            fn = title_page.replace("File:", "")
            fn_lower = fn.lower()

            if not fn_lower.endswith(IMG_EXTS):
                continue
            if any(b in fn_lower for b in BAD_KEYWORDS):
                continue

            info = page.get("imageinfo", [])
            if not info:
                continue
            ii = info[0]
            url = ii.get("thumburl") or ii.get("url")
            if not url:
                continue

            # Scoring
            score = 0
            # Cognome o alias artista presente
            if any(alias and alias.replace(" ", "_") in fn_lower or
                   alias and alias in fn_lower
                   for alias in artist_aliases if alias):
                score += 10
            # Parole-chiave titolo
            score += sum(2 for w in title_words if w in fn_lower)
            # Anno
            if year and (str(year) in fn_lower):
                score += 3
            # Google Art Project (massima qualita)
            if "google_art_project" in fn_lower or "google art project" in fn_lower:
                score += 4
            # Wikimedia Commons direct upload da musei spesso buoni
            if "wga" in fn_lower:
                score += 2
            # Dimensione
            w = ii.get("width", 0)
            if w >= 3000:
                score += 4
            elif w >= 2000:
                score += 2
            elif w >= 1500:
                score += 1
            else:
                score -= 2  # troppo piccolo per la card

            # Conserva il punteggio massimo per file (se piu query lo trovano)
            if fn not in all_candidates or score > all_candidates[fn][0]:
                all_candidates[fn] = (score, w, url)

    if not all_candidates:
        return None, None

    # Ordina: prima per score, poi per width discendente
    ranked = sorted(
        all_candidates.items(),
        key=lambda kv: (-kv[1][0], -kv[1][1])
    )
    best_fn, (best_score, best_w, best_url) = ranked[0]

    # Soglia minima: almeno l'artista riconosciuto OPPURE 3 parole-titolo
    # OPPURE 2 parole-titolo + dim >= 2000
    if best_score < 6:
        return None, None
    return (best_url, best_fn)


def resolve_wikimedia_url(entry: dict, session: requests.Session) -> tuple[str | None, str | None, bool]:
    """Tenta a cascata di risolvere l'URL di un'opera.

    1) Prova il `wikimedia_file` esatto del manifest
    2) Se fallisce, fa una ricerca su artista+titolo

    Ritorna (url, filename_usato, da_search) dove `da_search` indica
    se l'URL e' stato trovato via fallback (cioe' il manifest e' da aggiornare).
    """
    file_name = entry.get("wikimedia_file", "")

    # Tentativo 1: nome esatto
    if file_name:
        url, fn = resolve_exact_filename(file_name, session)
        if url:
            return url, fn, False

    # Tentativo 2: search fallback
    artist = entry.get("artist", "")
    title = entry.get("title", "")
    year = entry.get("year")
    if artist and title:
        url, fn = search_wikimedia_file(artist, title, session, year=year)
        if url:
            return url, fn, True

    return None, None, False


def download_image(url: str, session: requests.Session) -> Image.Image | None:
    """Scarica un'immagine, ritorna PIL Image RGB."""
    try:
        r = session.get(url, timeout=60)
        r.raise_for_status()
        img = Image.open(BytesIO(r.content))
        return img.convert("RGB")
    except Exception as e:
        print(f"   !! download error: {e}")
        return None


def cover_crop(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Ridimensiona mantenendo aspect, poi crop centrato a target_w x target_h.
    Cover behavior: l'immagine COPRE l'intera area, tagliando l'eccesso."""
    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(round(src_w * scale))
    new_h = int(round(src_h * scale))
    img2 = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img2.crop((left, top, left + target_w, top + target_h))


def process_entry(entry: dict, session: requests.Session,
                  force: bool, dry_run: bool) -> tuple[bool, str, str | None]:
    """Scarica e processa un singolo paesaggio.
    Ritorna (success, message, discovered_filename) dove discovered_filename
    e' non-None solo se l'URL e' stata risolta via search fallback (il
    manifest e' da aggiornare con quel valore)."""
    slug = entry["slug"]
    file_name = entry.get("wikimedia_file", "")
    title = entry.get("title", "")
    artist = entry.get("artist", "")

    output_paths = {
        kind: LANDSCAPES_DIR / f"{slug}_{kind}.png"
        for kind in SIZES
    }

    # Cache check
    if not force and all(p.exists() for p in output_paths.values()):
        return True, "cached", None

    if dry_run:
        return True, f"would download {file_name}", None

    # Risolvi URL (con fallback search)
    url, used_fn, from_search = resolve_wikimedia_url(entry, session)
    if not url:
        return False, "URL non risolta (neanche via search)", None

    # Scarica originale
    img = download_image(url, session)
    if img is None:
        return False, "download fallito", None

    # Genera le 3 versioni
    for kind, (w, h) in SIZES.items():
        cropped = cover_crop(img, w, h)
        out_path = output_paths[kind]
        cropped.save(out_path, "PNG", optimize=True)

    msg = f"OK ({img.size[0]}x{img.size[1]} -> 3 crop)"
    if from_search:
        msg += f"  [via search: {used_fn}]"
    discovered = used_fn if from_search else None
    return True, msg, discovered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", type=str, default=None,
                        help="Scarica solo lo slug specificato")
    parser.add_argument("--skip-reserve", action="store_true",
                        help="Salta paesaggi con reserve:true")
    parser.add_argument("--force", action="store_true",
                        help="Riscarica anche se gia presente")
    parser.add_argument("--dry-run", action="store_true",
                        help="Mostra cosa farebbe senza scaricare")
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH,
                        help=f"Path al manifest YAML (default: {MANIFEST_PATH})")
    parser.add_argument("--output-dir", type=Path, default=LANDSCAPES_DIR,
                        help=f"Directory di output (default: {LANDSCAPES_DIR})")
    parser.add_argument("--throttle", type=float, default=0.5,
                        help="Pausa in secondi tra richieste (default: 0.5)")
    args = parser.parse_args()

    # Output dir
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Carica manifest
    if not args.manifest.exists():
        print(f"X  Manifest non trovato: {args.manifest}")
        sys.exit(1)

    with open(args.manifest, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    entries = data.get("landscapes", [])
    if not entries:
        print("X  Nessun landscape nel manifest")
        sys.exit(1)

    # Filtri
    if args.only:
        entries = [e for e in entries if e["slug"] == args.only]
        if not entries:
            print(f"X  Slug non trovato: {args.only}")
            sys.exit(1)

    if args.skip_reserve:
        entries = [e for e in entries if not e.get("reserve")]

    print(f"Pregacuore - Landscape downloader")
    print(f"=" * 60)
    print(f"Manifest:    {args.manifest}")
    print(f"Output dir:  {args.output_dir}")
    print(f"Entries:     {len(entries)}")
    print(f"Force:       {args.force}")
    print(f"Dry run:     {args.dry_run}")
    print()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    success = []
    failed = []
    cached = []
    discovered = []  # (slug, old_filename, new_filename)

    for i, entry in enumerate(entries, 1):
        slug = entry["slug"]
        artist = entry.get("artist", "")
        title = entry.get("title", "")
        reserve_tag = " [RISERVA]" if entry.get("reserve") else ""
        print(f"[{i}/{len(entries)}]{reserve_tag} {slug}")
        print(f"   {artist} - {title}")

        ok, msg, disc_fn = process_entry(entry, session, args.force, args.dry_run)
        if ok:
            if "cached" in msg:
                cached.append(slug)
                print(f"   .. {msg}")
            else:
                success.append(slug)
                print(f"   OK {msg}")
                if disc_fn:
                    discovered.append((slug, entry.get("wikimedia_file", ""), disc_fn))
        else:
            failed.append((slug, msg))
            print(f"   X  {msg}")

        # Throttle per non martellare Wikimedia
        if not args.dry_run and i < len(entries):
            time.sleep(args.throttle)

    # Riepilogo
    print()
    print("=" * 60)
    print(f"RIEPILOGO:")
    print(f"  scaricati:        {len(success)}")
    print(f"  via search:       {len(discovered)} (manifest da aggiornare)")
    print(f"  in cache:         {len(cached)}")
    print(f"  falliti:          {len(failed)}")

    if discovered:
        print()
        print("FILENAME SCOPERTI VIA SEARCH (aggiorna il manifest con questi valori):")
        for slug, old_fn, new_fn in discovered:
            print(f"  - slug: {slug}")
            print(f"    OLD: {old_fn}")
            print(f"    NEW: {new_fn}")

    if failed:
        print()
        print("FALLITI (nemmeno il search ha trovato risultati):")
        for slug, msg in failed:
            print(f"  - {slug}: {msg}")
        sys.exit(2)


if __name__ == "__main__":
    main()