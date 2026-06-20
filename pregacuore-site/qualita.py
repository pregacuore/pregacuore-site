# -*- coding: utf-8 -*-
"""
Controllo di qualità dei contenuti REDAZIONALI del Vangelo del giorno — gli unici
campi che restano a Gemini (pensiero, caption_instagram, caption_whatsapp, hashtags):
il Vangelo, il giorno liturgico e il santo sono ormai deterministici (lezionario +
calendario italiano). Tutto programmatico → nessuna chiamata AI, quota zero.

Usato sia dalla pipeline (validazione in fase di generazione, con rigenerazione sui
problemi veri) sia da `audit_qualita.py` (sweep dei contenuti già in daily_content).
"""
import re

_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]"
)
# Appellativi plurali vietati dal tono di marca (sempre "tu" singolare).
_VIETATE = re.compile(r"\b(fratelli|carissimi|sorelle|fedeli|amici miei)\b", re.IGNORECASE)

# Forme arcaiche/letterarie vietate nei campi editoriali (NON nella Scrittura, che è
# Luzzi verbatim e non passa di qui). La lista è estendibile dalla PM.
FORME_ARCAICHE = [
    "primieramente", "quivi", "quinci",
    "perciocché", "perciocchè", "imperocché", "imperocchè",
    "conciossiaché", "conciossiacosaché", "laonde", "eziandio",
    "allorquando", "testé", "uopo",
    "codesto", "codesta", "codesti", "codeste",
    "costui", "costei", "costoro",
]
_ARC_RE = re.compile(
    r"(?<!\w)(" + "|".join(map(re.escape, FORME_ARCAICHE)) + r")(?!\w)",
    re.IGNORECASE,
)

# Segmenti citati tra caporali nei campi editoriali.
_CAPORALI_RE = re.compile(r"«\s*(.+?)\s*»", re.DOTALL)


def _norm_scrittura(s: str) -> str:
    """Normalizza per il confronto verbatim: minuscolo, via virgolette/punteggiatura,
    spazi compattati. Tiene le lettere accentate italiane."""
    s = (s or "").lower()
    s = re.sub(r"[«»\"'‘’“”]", " ", s)
    s = re.sub(r"[^0-9a-zàèéìòóù ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def check_registro(testo: str) -> list:
    """Guardia di REGISTRO sui campi editoriali: niente forme arcaiche/letterarie.
    (I caporali col versetto VERO del giorno sono ammessi: vedi check_scrittura.)"""
    problemi = []
    trovate = sorted({m.group(0).lower() for m in _ARC_RE.finditer(testo or "")})
    if trovate:
        problemi.append("forma arcaica vietata: " + ", ".join(trovate))
    return problemi


def check_scrittura(testo: str, fonte_luzzi: str) -> list:
    """Guardia anti-Scrittura-inventata. Un campo editoriale PUÒ citare tra « » SOLO
    il versetto del giorno COPIATO ALLA LETTERA dal testo Luzzi (`fonte_luzzi` =
    quote + gospel_text del giorno). Ogni segmento tra caporali che NON è un
    sotto-testo verbatim della fonte è una citazione inventata/parafrasata → problema."""
    problemi = []
    fonte = _norm_scrittura(fonte_luzzi)
    for seg in _CAPORALI_RE.findall(testo or ""):
        sn = _norm_scrittura(seg)
        if not sn:
            continue
        if not fonte or sn not in fonte:
            problemi.append(f"citazione tra « » non verbatim dal Vangelo del giorno "
                            f"(possibile versetto inventato): «{seg.strip()}»")
    return problemi


def _parole(s: str) -> set:
    return set(re.findall(r"[a-zàèéìòóù]{4,}", (s or "").lower()))


def valida_contenuto(data: dict) -> list:
    """Ritorna la lista dei problemi di qualità dei campi redazionali. Vuota = ok.
    I problemi che iniziano con 'AVVISO' sono soft (non fanno rigenerare). Soglie
    morbide: segnaliamo solo violazioni chiare, non scostamenti minimi dai range."""
    problemi = []

    # Fonte verbatim per la guardia anti-Scrittura-inventata: il versetto del giorno
    # (quote, Luzzi) + il testo del Vangelo (gospel_text Luzzi, se non placeholder).
    gtext_raw = data.get("gospel_text") or ""
    fonte = (data.get("quote") or "") + " " + ("" if gtext_raw.startswith("[") else gtext_raw)

    pensiero = (data.get("pensiero") or "").strip()
    np = len(pensiero.split())
    if np < 25:
        problemi.append(f"pensiero troppo corto ({np} parole)")
    elif np > 170:
        problemi.append(f"pensiero troppo lungo ({np} parole)")
    mv = _VIETATE.search(pensiero)
    if mv:
        problemi.append(f"pensiero usa un appellativo plurale vietato ({mv.group(0)})")
    if len(_EMOJI.findall(pensiero)) > 1:
        problemi.append("pensiero con troppe emoji")
    for p in check_registro(pensiero):
        problemi.append(f"pensiero: {p}")
    for p in check_scrittura(pensiero, fonte):
        problemi.append(f"pensiero: {p}")

    # Le caption social sono ASSEMBLATE dalla pipeline (versetto Luzzi + pensiero +
    # riferimento) → portano il pensiero intero: cap di lunghezza generosi.
    ci = (data.get("caption_instagram") or "").strip()
    if not (60 <= len(ci) <= 2200):
        problemi.append(f"caption_instagram fuori range ({len(ci)} caratteri)")
    if _VIETATE.search(ci):
        problemi.append("caption_instagram usa un appellativo plurale vietato")
    for p in check_registro(ci):
        problemi.append(f"caption_instagram: {p}")
    for p in check_scrittura(ci, fonte):
        problemi.append(f"caption_instagram: {p}")

    cw = (data.get("caption_whatsapp") or "").strip()
    if not (12 <= len(cw) <= 2200):
        problemi.append(f"caption_whatsapp fuori range ({len(cw)} caratteri)")
    for p in check_registro(cw):
        problemi.append(f"caption_whatsapp: {p}")
    for p in check_scrittura(cw, fonte):
        problemi.append(f"caption_whatsapp: {p}")

    tags = data.get("hashtags") or []
    if not isinstance(tags, list) or not (3 <= len(tags) <= 8):
        problemi.append(f"hashtags numero anomalo ({len(tags) if isinstance(tags, list) else 'non-lista'})")
    else:
        for t in tags:
            if not isinstance(t, str) or "#" in t or " " in t.strip() or t != t.lower():
                problemi.append(f"hashtag malformato: {t!r}")
                break

    # Coerenza morbida col Vangelo: il pensiero dovrebbe condividere qualche parola
    # di contenuto col testo del brano (Luzzi). Solo avviso (sinonimi ammessi).
    gtext = data.get("gospel_text") or ""
    if pensiero and gtext and not gtext.startswith("[") and not (_parole(pensiero) & _parole(gtext)):
        problemi.append("AVVISO coerenza: pensiero senza parole in comune col brano")

    return problemi
