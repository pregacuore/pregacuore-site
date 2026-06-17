#!/usr/bin/env python3
"""genera_santi_giorno.py — costruisce santi_giorno.json (MM-DD -> "santo del giorno").

Sorgente: **chiesacattolica.it** (sito ufficiale CEI), pagina "Santo del giorno"
(?data-liturgia=YYYYMMDD). Il titolo <h1> è il santo principale del giorno secondo
il calendario/Martirologio CEI → autorevole (niente figure non cattoliche). Dà un
santo anche nei feriali (es. 01/07 -> "Sant'Aronne") e nelle domeniche
(es. 28/06 -> "Sant'Ireneo"). Fallback: santodelgiorno.it.

NB: sulle solennità mobili la pagina dà la festa (es. "Domenica di Pasqua"); quei
giorni però NON sono "Feria" nel calendario, quindi NON vengono sostituiti (vedi
lezionario.santo_del_giorno) → nessun effetto. Resta una mappa per-data fissa.

Uso:  python genera_santi_giorno.py            # tutti i 366 giorni
      python genera_santi_giorno.py 7          # solo luglio (debug)
"""
import html as _html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
GIORNI_MESE = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # febbraio 29

# Trust store del dev scaduto → contesto non verificato (dati pubblici read-only).
_CTX = ssl._create_unverified_context()
_UA = {'User-Agent': 'Mozilla/5.0 PregacuoreBot (santo del giorno)'}
# Anno di riferimento: i santi sono a data fissa, quindi un anno qualsiasi va bene.
# 2026 per tutto; il 29/02 (bisestile) lo prendiamo dal 2028.
_ANNO = 2026
_ANNO_BISESTILE = 2028


def _html_get(url: str) -> str | None:
    for tentativo in range(4):
        try:
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=25, context=_CTX) as r:
                return r.read().decode('utf-8', 'replace')
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            time.sleep(1.5 * (tentativo + 1))
        except Exception:  # noqa: BLE001
            time.sleep(1.5 * (tentativo + 1))
    return None


def _h1(html_doc: str) -> str | None:
    m = re.search(r'<h1[^>]*>(.*?)</h1>', html_doc, re.S | re.I)
    if not m:
        return None
    txt = _html.unescape(re.sub(r'<[^>]+>', '', m.group(1)))
    txt = re.sub(r'\s+', ' ', txt).strip()
    # Normalizza il trattino lungo che a volte appare nelle solennità.
    return txt.replace('–', '-').replace('—', '-').strip() or None


def _cei(mese: int, giorno: int) -> str | None:
    anno = _ANNO_BISESTILE if (mese == 2 and giorno == 29) else _ANNO
    html_doc = _html_get('https://www.chiesacattolica.it/santo-del-giorno/'
                         f'?data-liturgia={anno}{mese:02d}{giorno:02d}')
    return _h1(html_doc) if html_doc else None


def _santodelgiorno(mese: int, giorno: int) -> str | None:
    """Fallback: santodelgiorno.it/DD/mese/."""
    html_doc = _html_get(f'https://www.santodelgiorno.it/{giorno:02d}/{MESI[mese]}/')
    if not html_doc:
        return None
    return _h1(html_doc)


def main() -> None:
    mesi = [int(sys.argv[1])] if len(sys.argv) > 1 else list(range(1, 13))
    out: dict[str, str] = {}
    for mese in mesi:
        for giorno in range(1, GIORNI_MESE[mese] + 1):
            key = f"{mese:02d}-{giorno:02d}"
            s = _cei(mese, giorno) or _santodelgiorno(mese, giorno)
            if s:
                out[key] = s
            else:
                print(f"  [!] {key}: nessun santo")
            time.sleep(0.25)  # gentile
    dest = Path(__file__).with_name('santi_giorno.json')
    # Merge: non perdere giorni gia' presenti se rigenero un solo mese.
    if len(mesi) < 12 and dest.exists():
        base = json.loads(dest.read_text(encoding='utf-8'))
        base.update(out)
        out = base
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    print(f"OK {len(out)} giorni -> {dest.name}")


if __name__ == '__main__':
    main()
