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


def _parole(s: str) -> set:
    return set(re.findall(r"[a-zàèéìòóù]{4,}", (s or "").lower()))


def valida_contenuto(data: dict) -> list:
    """Ritorna la lista dei problemi di qualità dei campi redazionali. Vuota = ok.
    I problemi che iniziano con 'AVVISO' sono soft (non fanno rigenerare). Soglie
    morbide: segnaliamo solo violazioni chiare, non scostamenti minimi dai range."""
    problemi = []

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

    ci = (data.get("caption_instagram") or "").strip()
    if not (60 <= len(ci) <= 320):
        problemi.append(f"caption_instagram fuori range ({len(ci)} caratteri)")
    if _VIETATE.search(ci):
        problemi.append("caption_instagram usa un appellativo plurale vietato")

    cw = (data.get("caption_whatsapp") or "").strip()
    if not (12 <= len(cw) <= 160):
        problemi.append(f"caption_whatsapp fuori range ({len(cw)} caratteri)")

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
