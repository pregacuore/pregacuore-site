#!/usr/bin/env python3
"""genera_santi_giorno.py — costruisce santi_giorno.json (MM-DD -> "santo del giorno").

Sorgente: pagine-giorno di Wikipedia in italiano (es. "11 luglio"), sezione
"Religiose": è il calendario dei santi indicato dal PM
(https://it.wikipedia.org/wiki/Calendario_dei_santi). Per ogni giorno prende il
PRIMO santo/beato/memoria mariana elencato e lo accorcia al nome principale.

⚠️ BOZZA → verificato_PM. Limite noto: la lista del giorno NON è ordinata per
importanza liturgica, quindi su alcuni giorni con memoria facoltativa nota (es.
16/07 B.V. del Carmelo) il "primo" non è il più conosciuto. La mappa è un JSON
piatto e facilmente correggibile a mano. NB: questo santo si usa SOLO nei giorni
liturgicamente "Feria…"/"Domenica del Tempo Ordinario" (le feste/memorie vere
restano quelle del calendario CEI), quindi non tocca le solennità.

Uso:  python genera_santi_giorno.py            # tutti i 366 giorni
      python genera_santi_giorno.py 7          # solo luglio (debug)
"""
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

MESI = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
GIORNI_MESE = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]  # febbraio 29 (bisestili)

# Trust store del dev scaduto → contesto non verificato (dati pubblici read-only).
_CTX = ssl._create_unverified_context()
_INIZIO = re.compile(r'^(San|Santa|Santi|Sante|Beat[oaie]|Madonna|Maria|Nostra Signora|'
                     r'Immacolata|Sacro Cuore|Sacratissimo|Cuore Immacolato|Preziosissimo|'
                     r'Santissim[oa]|Vergine|Commemorazione|Conversione|Natività|Assunzione|'
                     r'Presentazione|Visitazione|Dedicazione)\b', re.I)


def _wikitext_batch(pages: list[str]) -> dict[str, str]:
    """Wikitext di più pagine in UNA richiesta (fino a 50): gentile col rate-limit
    (niente 429). Ritorna {titolo: wikitext}. Con backoff su 429/errori rete."""
    titoli = '|'.join(pages)
    url = ('https://it.wikipedia.org/w/api.php?action=query&prop=revisions'
           '&rvprop=content&rvslots=main&format=json&formatversion=2&titles='
           + urllib.parse.quote(titoli))
    req = urllib.request.Request(url, headers={'User-Agent': 'PregacuoreBot/1.0 (santi del giorno; +https://pregacuore.it)'})
    for tentativo in range(5):
        try:
            with urllib.request.urlopen(req, timeout=30, context=_CTX) as r:
                data = json.load(r)
            out: dict[str, str] = {}
            for p in data['query']['pages']:
                rev = p.get('revisions')
                if rev:
                    out[p['title']] = rev[0]['slots']['main']['content']
            return out
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 * (tentativo + 1))
                continue
            raise
        except Exception:  # noqa: BLE001
            time.sleep(2 * (tentativo + 1))
    raise RuntimeError('batch fallito dopo i retry')


def _pulisci(s: str) -> str:
    s = re.sub(r'<ref[^>]*>.*?</ref>', '', s, flags=re.S)   # <ref>…</ref>
    s = re.sub(r'<ref[^>]*/>', '', s)
    s = re.sub(r'\{\{[^}]*\}\}', '', s)                      # {{template}}
    s = re.sub(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]', r'\1', s)  # [[a|b]] -> b
    s = s.replace("'''", '').replace("''", '')
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _accorcia(nome: str) -> str:
    """Nome principale: taglia alla prima virgola/parentesi (toglie i titoli lunghi).
    'San Benedetto da Norcia, abate, patrono d'Europa' -> 'San Benedetto da Norcia'."""
    nome = re.split(r'[,(]', nome)[0].strip()
    return nome


def santo_da_wikitext(wt: str) -> str | None:
    m = re.search(r'===+\s*Religiose\s*===+(.*?)(?:\n==[^=]|\Z)', wt, re.S)
    blk = m.group(1) if m else wt
    for line in blk.splitlines():
        t = line.strip()
        if not t.startswith('*'):
            continue
        t = _pulisci(t.lstrip('*').strip())
        if _INIZIO.match(t):
            return _accorcia(t)
    return None


def main() -> None:
    mesi = [int(sys.argv[1])] if len(sys.argv) > 1 else list(range(1, 13))
    # tutte le pagine-giorno richieste
    coppie = [(f"{mese:02d}-{giorno:02d}", f"{giorno} {MESI[mese]}")
              for mese in mesi for giorno in range(1, GIORNI_MESE[mese] + 1)]
    per_titolo = {t: k for k, t in coppie}

    out: dict[str, str] = {}
    BATCH = 50
    titoli = [t for _, t in coppie]
    for i in range(0, len(titoli), BATCH):
        gruppo = titoli[i:i + BATCH]
        wt_map = _wikitext_batch(gruppo)
        for titolo in gruppo:
            key = per_titolo[titolo]
            wt = wt_map.get(titolo)
            s = santo_da_wikitext(wt) if wt else None
            if s:
                out[key] = s
            else:
                print(f"  [!] {key} ({titolo}): nessun santo estratto")
        time.sleep(1)  # gentile tra i batch

    dest = Path(__file__).with_name('santi_giorno.json')
    dest.write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True), encoding='utf-8')
    print(f"OK {len(out)}/{len(coppie)} giorni -> {dest.name}")


if __name__ == '__main__':
    main()
