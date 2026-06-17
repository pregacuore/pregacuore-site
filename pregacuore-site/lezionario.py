# -*- coding: utf-8 -*-
"""
==============================================================================
LEZIONARIO DETERMINISTICO — Vangelo del giorno (rito romano, calendario Italia)
==============================================================================

Perché esiste
-------------
La pipeline chiedeva il `gospel_reference` a Gemini, che SBAGLIAVA il ciclo
liturgico (usava l'Anno B sulle domeniche del 2026, che è Anno A; e sbagliava
alcuni feriali). Risultato: testo Luzzi + audio del brano sbagliato. Il fix
vero è togliere a Gemini la scelta del riferimento: qui c'è un lezionario
DETERMINISTICO. Gemini resta solo per pensiero/quote/caption.

Copertura (decisa nel HANDOFF_2026-06-13)
-----------------------------------------
**Tempo Ordinario dal 28/06/2026 al 28/11/2026.** Niente Avvento/Quaresima/
Pasqua per ora: fuori da questa finestra `riferimento_vangelo()` torna None e la
pipeline ricade su Gemini (comportamento storico).

Come funziona
-------------
Tre tabelle + una precedenza liturgica:
1. **Domeniche Anno A** (T.O., settimane 13-34; la 34ª è Cristo Re) — universali.
2. **Feriale T.O.** (ciclo UNICO, lun-sab, settimane 13-34) — universale: il
   Vangelo feriale è lo stesso ogni anno (cambiano solo prima lettura/salmo per
   Anno I/II, non il Vangelo).
3. **Celebrazioni proprie** (solennità, feste, e le poche memorie con Vangelo
   proprio) sul calendario PROPRIO dell'Italia.

Numerazione delle settimane: ancora 28/06/2026 = XIII Domenica T.O. Da lì le
settimane avanzano di 1 a domenica; un giorno feriale appartiene alla settimana
della domenica che lo precede. Verificato fino a Cristo Re (22/11/2026 = 34ª).

Precedenza (chi vince quando due cose cadono lo stesso giorno):
- **solennità** → vince sempre (anche sulla domenica T.O.);
- **festa del Signore** → vince anche sulla domenica T.O.;
- **festa** (di santo/apostolo) → vince sul feriale, MA cede alla domenica T.O.;
- **memoria con Vangelo proprio** → vince sul feriale, cede a domenica/festa.

Le date e i gradi sono stati verificati uno per uno contro
`liturgia.silvestrini.org` (calendario italiano, pubblica le date future) per
tutta la finestra — vedi `verifica_lezionario.py`.
==============================================================================
"""

import os
import json
from datetime import date, timedelta
from typing import Optional


# ------------------------------------------------------------------
# Finestra coperta
# ------------------------------------------------------------------
# La copertura è in due tratti contigui:
#  • 28/06/2026 → 28/11/2026: Tempo Ordinario Anno A, risolto dal MOTORE
#    strutturale qui sotto (ciclo settimanale + domeniche Anno A + feste).
#  • 29/11/2026 → 31/12/2027: tutto l'anno liturgico successivo (Avvento →
#    Natale → T.O. Anno B → Quaresima → Pasqua → T.O. → Avvento Anno C),
#    risolto da una MAPPA data→riferimento già verificata
#    (lezionario_estensione.json). Le stagioni proprie (Avvento/Natale/
#    Quaresima/Pasqua) non sono un ciclo settimanale: sono letture proprie
#    giorno-per-giorno, quindi sono dati, non algoritmo. La mappa è stata
#    costruita dal calendario italiano (liturgia.silvestrini.org) e verificata
#    giorno per giorno (vedi verifica_lezionario.py): i feriali T.O. combaciano
#    col ciclo universale, le feste/memorie italiane sono quelle giuste, le
#    stagioni proprie combaciano col lezionario romano universale.
FINESTRA_INIZIO = date(2026, 6, 28)
FINESTRA_FINE = date(2027, 12, 31)

# Tratto risolto dal motore strutturale (Tempo Ordinario Anno A 2026).
_OT2026_INIZIO = date(2026, 6, 28)   # XIII Domenica T.O. (Anno A)
_OT2026_FINE = date(2026, 11, 28)    # Sabato XXXIV settimana T.O.
_ANCORA = date(2026, 6, 28)
_ANCORA_SETTIMANA = 13

# Mappa data→riferimento per l'anno liturgico esteso (29/11/2026 → 31/12/2027).
_EST_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "lezionario_estensione.json")
try:
    with open(_EST_PATH, encoding="utf-8") as _f:
        _ESTENSIONE = json.load(_f)
except FileNotFoundError:  # pragma: no cover
    _ESTENSIONE = {}

# Calendario liturgico italiano (giorno liturgico + santo del giorno) per tutta
# la finestra 28/06/2026 → 31/12/2027. Sorgente: API LitCal (litcal.johnromanodorazio.com,
# calendario nazionale ITALIA/CEI) — quindi anche liturgical_day e saint_of_day
# sono DETERMINISTICI, non più affidati a Gemini. {data: {"lit": ..., "santo": ...}}.
_CAL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "calendario_italiano.json")
try:
    with open(_CAL_PATH, encoding="utf-8") as _f:
        _CALENDARIO = json.load(_f)
except FileNotFoundError:  # pragma: no cover
    _CALENDARIO = {}

# Santo del giorno (popolare) per i giorni liturgicamente VUOTI. Sui feriali e
# sulle domeniche del Tempo Ordinario il calendario CEI non dà un santo ma la
# dicitura "Feria…" / "… Domenica del Tempo Ordinario": l'app non vuole mostrare
# quella. Qui sostituiamo col santo del giorno (MM-DD → nome) da santi_giorno.json
# (generato da genera_santi_giorno.py, fonte Wikipedia "Calendario dei santi").
# ⚠️ BOZZA → verificato_PM. Le FESTE/MEMORIE vere restano quelle del CEI (non
# toccate); le domeniche di Avvento/Quaresima/Pasqua restano il loro tempo.
_SANTI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "santi_giorno.json")
try:
    with open(_SANTI_PATH, encoding="utf-8") as _f:
        _SANTI_GIORNO = json.load(_f)
except FileNotFoundError:  # pragma: no cover
    _SANTI_GIORNO = {}

# Diciture liturgiche "vuote" (niente santo proprio) → sostituibili col santo del
# giorno. NB: solo le domeniche del TEMPO ORDINARIO; quelle di Avvento/Quaresima/
# Pasqua ("… di Avvento") NON combaciano e restano il loro tempo.
import re as _re
_SENZA_SANTO = _re.compile(r"feria|domenica del tempo ordinario", _re.IGNORECASE)


# ------------------------------------------------------------------
# 1. Domeniche del Tempo Ordinario — Anno A (settimane 13-34)
#    La 34ª domenica è la solennità di Cristo Re (Mt 25,31-46).
# ------------------------------------------------------------------
DOMENICHE_ANNO_A = {
    13: "Mt 10,37-42",
    14: "Mt 11,25-30",
    15: "Mt 13,1-23",
    16: "Mt 13,24-43",
    17: "Mt 13,44-52",
    18: "Mt 14,13-21",
    19: "Mt 14,22-33",
    20: "Mt 15,21-28",
    21: "Mt 16,13-20",
    22: "Mt 16,21-27",
    23: "Mt 18,15-20",
    24: "Mt 18,21-35",
    25: "Mt 20,1-16",
    26: "Mt 21,28-32",
    27: "Mt 21,33-43",
    28: "Mt 22,1-14",
    29: "Mt 22,15-21",
    30: "Mt 22,34-40",
    31: "Mt 23,1-12",
    32: "Mt 25,1-13",
    33: "Mt 25,14-30",
    34: "Mt 25,31-46",   # Cristo Re
}


# ------------------------------------------------------------------
# 2. Feriale del Tempo Ordinario — ciclo unico (settimane 13-34)
#    Chiave: (settimana, giorno_settimana) con 0=lunedì … 5=sabato.
#    Settimane 13-21 = Matteo; 22-34 = Luca (nessun feriale T.O. da Giovanni).
#    Riferimenti in sigla CEI, allineati al calendario italiano.
# ------------------------------------------------------------------
FERIALE = {
    (13, 0): "Mt 8,18-22",   (13, 1): "Mt 8,23-27",   (13, 2): "Mt 8,28-34",
    (13, 3): "Mt 9,1-8",     (13, 4): "Mt 9,9-13",     (13, 5): "Mt 9,14-17",

    (14, 0): "Mt 9,18-26",   (14, 1): "Mt 9,32-38",   (14, 2): "Mt 10,1-7",
    (14, 3): "Mt 10,7-15",   (14, 4): "Mt 10,16-23",  (14, 5): "Mt 10,24-33",

    (15, 0): "Mt 10,34-11,1",(15, 1): "Mt 11,20-24",  (15, 2): "Mt 11,25-27",
    (15, 3): "Mt 11,28-30",  (15, 4): "Mt 12,1-8",    (15, 5): "Mt 12,14-21",

    (16, 0): "Mt 12,38-42",  (16, 1): "Mt 12,46-50",  (16, 2): "Mt 13,1-9",
    (16, 3): "Mt 13,10-17",  (16, 4): "Mt 13,18-23",  (16, 5): "Mt 13,24-30",

    (17, 0): "Mt 13,31-35",  (17, 1): "Mt 13,36-43",  (17, 2): "Mt 13,44-46",
    (17, 3): "Mt 13,47-53",  (17, 4): "Mt 13,54-58",  (17, 5): "Mt 14,1-12",

    (18, 0): "Mt 14,13-21",  (18, 1): "Mt 14,22-36",  (18, 2): "Mt 15,21-28",
    (18, 3): "Mt 16,13-23",  (18, 4): "Mt 16,24-28",  (18, 5): "Mt 17,14-19",

    (19, 0): "Mt 17,22-27",  (19, 1): "Mt 18,1-5.10.12-14", (19, 2): "Mt 18,15-20",
    (19, 3): "Mt 18,21-19,1",(19, 4): "Mt 19,3-12",   (19, 5): "Mt 19,13-15",

    (20, 0): "Mt 19,16-22",  (20, 1): "Mt 19,23-30",  (20, 2): "Mt 20,1-16",
    (20, 3): "Mt 22,1-14",   (20, 4): "Mt 22,34-40",  (20, 5): "Mt 23,1-12",

    (21, 0): "Mt 23,13-22",  (21, 1): "Mt 23,23-26",  (21, 2): "Mt 23,27-32",
    (21, 3): "Mt 24,42-51",  (21, 4): "Mt 25,1-13",   (21, 5): "Mt 25,14-30",

    (22, 0): "Lc 4,16-30",   (22, 1): "Lc 4,31-37",   (22, 2): "Lc 4,38-44",
    (22, 3): "Lc 5,1-11",    (22, 4): "Lc 5,33-39",   (22, 5): "Lc 6,1-5",

    (23, 0): "Lc 6,6-11",    (23, 1): "Lc 6,12-19",   (23, 2): "Lc 6,20-26",
    (23, 3): "Lc 6,27-38",   (23, 4): "Lc 6,39-42",   (23, 5): "Lc 6,43-49",

    (24, 0): "Lc 7,1-10",    (24, 1): "Lc 7,11-17",   (24, 2): "Lc 7,31-35",
    (24, 3): "Lc 7,36-50",   (24, 4): "Lc 8,1-3",     (24, 5): "Lc 8,4-15",

    (25, 0): "Lc 8,16-18",   (25, 1): "Lc 8,19-21",   (25, 2): "Lc 9,1-6",
    (25, 3): "Lc 9,7-9",     (25, 4): "Lc 9,18-22",   (25, 5): "Lc 9,43-45",

    (26, 0): "Lc 9,46-50",   (26, 1): "Lc 9,51-56",   (26, 2): "Lc 9,57-62",
    (26, 3): "Lc 10,1-12",   (26, 4): "Lc 10,13-16",  (26, 5): "Lc 10,17-24",

    (27, 0): "Lc 10,25-37",  (27, 1): "Lc 10,38-42",  (27, 2): "Lc 11,1-4",
    (27, 3): "Lc 11,5-13",   (27, 4): "Lc 11,15-26",  (27, 5): "Lc 11,27-28",

    (28, 0): "Lc 11,29-32",  (28, 1): "Lc 11,37-41",  (28, 2): "Lc 11,42-46",
    (28, 3): "Lc 11,47-54",  (28, 4): "Lc 12,1-7",    (28, 5): "Lc 12,8-12",

    (29, 0): "Lc 12,13-21",  (29, 1): "Lc 12,35-38",  (29, 2): "Lc 12,39-48",
    (29, 3): "Lc 12,49-53",  (29, 4): "Lc 12,54-59",  (29, 5): "Lc 13,1-9",

    (30, 0): "Lc 13,10-17",  (30, 1): "Lc 13,18-21",  (30, 2): "Lc 13,22-30",
    (30, 3): "Lc 13,31-35",  (30, 4): "Lc 14,1-6",    (30, 5): "Lc 14,1.7-11",

    (31, 0): "Lc 14,12-14",  (31, 1): "Lc 14,15-24",  (31, 2): "Lc 14,25-33",
    (31, 3): "Lc 15,1-10",   (31, 4): "Lc 16,1-8",    (31, 5): "Lc 16,9-15",

    (32, 0): "Lc 17,1-6",    (32, 1): "Lc 17,7-10",   (32, 2): "Lc 17,11-19",
    (32, 3): "Lc 17,20-25",  (32, 4): "Lc 17,26-37",  (32, 5): "Lc 18,1-8",

    (33, 0): "Lc 18,35-43",  (33, 1): "Lc 19,1-10",   (33, 2): "Lc 19,11-28",
    (33, 3): "Lc 19,41-44",  (33, 4): "Lc 19,45-48",  (33, 5): "Lc 20,27-40",

    (34, 0): "Lc 21,1-4",    (34, 1): "Lc 21,5-11",   (34, 2): "Lc 21,12-19",
    (34, 3): "Lc 21,20-28",  (34, 4): "Lc 21,29-33",  (34, 5): "Lc 21,34-36",
}


# ------------------------------------------------------------------
# 3. Celebrazioni proprie a data fissa (calendario Italia)
#    Chiave: (mese, giorno). Valore: (titolo, grado, riferimento).
#    grado ∈ {"solennita", "festa_signore", "festa", "memoria"}.
#    Solo le celebrazioni nella finestra che hanno un Vangelo PROPRIO che
#    sostituisce quello del giorno. Le memorie senza Vangelo proprio NON vanno
#    qui (tengono il feriale).
# ------------------------------------------------------------------
CELEBRAZIONI_FISSE = {
    (6, 29):  ("Ss. Pietro e Paolo, Apostoli",        "solennita",      "Mt 16,13-19"),
    (7, 3):   ("San Tommaso, Apostolo",               "festa",          "Gv 20,24-29"),
    (7, 11):  ("San Benedetto, abate, patrono d'Europa", "festa",       "Mt 19,27-29"),
    (7, 22):  ("Santa Maria Maddalena",               "festa",          "Gv 20,1.11-18"),
    (7, 23):  ("Santa Brigida, patrona d'Europa",     "festa",          "Gv 15,1-8"),
    (7, 25):  ("San Giacomo, Apostolo",               "festa",          "Mt 20,20-28"),
    (7, 29):  ("Ss. Marta, Maria e Lazzaro",          "memoria",        "Gv 11,19-27"),
    (8, 6):   ("Trasfigurazione del Signore",         "festa_signore",  "Mt 17,1-9"),
    (8, 10):  ("San Lorenzo, diacono e martire",      "festa",          "Gv 12,24-26"),
    (8, 15):  ("Assunzione della B.V. Maria",         "solennita",      "Lc 1,39-56"),
    (8, 24):  ("San Bartolomeo, Apostolo",            "festa",          "Gv 1,45-51"),
    (8, 29):  ("Martirio di San Giovanni Battista",   "memoria",        "Mc 6,17-29"),
    (9, 8):   ("Natività della B.V. Maria",           "festa",          "Mt 1,1-16.18-23"),
    (9, 14):  ("Esaltazione della Santa Croce",       "festa_signore",  "Gv 3,13-17"),
    (9, 15):  ("Beata Vergine Maria Addolorata",      "memoria",        "Gv 19,25-27"),
    (9, 21):  ("San Matteo, Apostolo ed Evangelista", "festa",          "Mt 9,9-13"),
    (9, 29):  ("Ss. Arcangeli Michele, Gabriele, Raffaele", "festa",     "Gv 1,47-51"),
    (10, 18): ("San Luca, Evangelista",               "festa",          "Lc 10,1-9"),
    (10, 28): ("Ss. Simone e Giuda, Apostoli",        "festa",          "Lc 6,12-16"),
    (11, 1):  ("Tutti i Santi",                       "solennita",      "Mt 5,1-12a"),
    (11, 2):  ("Commemorazione dei fedeli defunti",   "solennita",      "Gv 6,37-40"),
    (11, 9):  ("Dedicazione della Basilica Lateranense", "festa_signore", "Gv 2,13-22"),
    # Memorie con Vangelo proprio (vincono sul feriale, cedono a domenica/festa):
    (11, 21): ("Presentazione della B.V. Maria",      "memoria",        "Mt 12,46-50"),
}


# ------------------------------------------------------------------
# Logica
# ------------------------------------------------------------------
def _settimana_to(d: date) -> int:
    """Numero della settimana del Tempo Ordinario per la data `d`.
    Un feriale appartiene alla settimana della domenica che lo precede."""
    # domenica che apre la settimana di d (domenica <= d)
    domenica = d - timedelta(days=(d.weekday() + 1) % 7)
    return _ANCORA_SETTIMANA + (domenica - _ANCORA).days // 7


def riferimento_vangelo(d: date) -> Optional[str]:
    """Riferimento CEI del Vangelo del giorno secondo il calendario italiano,
    oppure None se la data è fuori dalla finestra coperta (→ fallback Gemini).

    Due tratti: la mappa verificata per l'anno liturgico esteso
    (29/11/2026 → 31/12/2027) ha la precedenza; per il Tempo Ordinario 2026 il
    motore strutturale (precedenza: solennità > festa del Signore > domenica
    T.O. > festa di santo > memoria con Vangelo proprio > feriale).
    """
    # Tratto esteso: mappa data→riferimento già verificata.
    ref = _ESTENSIONE.get(d.isoformat())
    if ref is not None:
        return ref

    # Tratto Tempo Ordinario 2026: motore strutturale.
    if d < _OT2026_INIZIO or d > _OT2026_FINE:
        return None

    is_domenica = d.weekday() == 6
    cel = CELEBRAZIONI_FISSE.get((d.month, d.day))
    grado = cel[1] if cel else None

    # 1. Solennità e feste del Signore battono tutto (anche la domenica T.O.)
    if grado in ("solennita", "festa_signore"):
        return cel[2]

    # 2. Domenica del Tempo Ordinario (Anno A)
    if is_domenica:
        return DOMENICHE_ANNO_A.get(_settimana_to(d))

    # 3. Festa di santo / memoria con Vangelo proprio (giorno feriale)
    if grado in ("festa", "memoria"):
        return cel[2]

    # 4. Feriale del Tempo Ordinario
    return FERIALE.get((_settimana_to(d), d.weekday()))


def giorno_liturgico_label(d: date) -> Optional[str]:
    """Giorno liturgico (campo liturgical_day) dal calendario italiano, per tutta
    la finestra; None fuori finestra. Es. 'XXVII Domenica del Tempo Ordinario',
    'Santi Pietro e Paolo, Apostoli', 'Mercoledì della Tredicesima Settimana del
    Tempo Ordinario'."""
    c = _CALENDARIO.get(d.isoformat())
    return c["lit"] if c else None


def santo_del_giorno(d: date) -> Optional[str]:
    """Santo/memoria del giorno (campo saint_of_day) dal calendario italiano, per
    tutta la finestra; None fuori finestra.

    Sui giorni liturgicamente VUOTI (il CEI dà 'Feria…' o '… Domenica del Tempo
    Ordinario') sostituiamo col SANTO DEL GIORNO popolare (santi_giorno.json) —
    così l'app mostra un santo, non 'Feria'. Le feste/memorie vere restano quelle
    del calendario CEI. Se per quel giorno non c'è un santo in mappa, si tiene la
    dicitura originale (l'app la nasconde lato client)."""
    c = _CALENDARIO.get(d.isoformat())
    if not c:
        return None
    santo = c["santo"]
    if santo and _SENZA_SANTO.search(santo):
        sostituto = _SANTI_GIORNO.get(f"{d.month:02d}-{d.day:02d}")
        if sostituto:
            return sostituto
    return santo


def info_giorno(d: date) -> Optional[dict]:
    """Diagnostica: riferimento risolto + (per il solo tratto T.O. 2026) la
    settimana e la celebrazione note al motore strutturale."""
    ref = riferimento_vangelo(d)
    if ref is None:
        return None
    info = {"data": d.isoformat(), "riferimento": ref, "domenica": d.weekday() == 6}
    if d.isoformat() in _ESTENSIONE:
        info["fonte"] = "estensione"
        return info
    cel = CELEBRAZIONI_FISSE.get((d.month, d.day))
    info.update({
        "fonte": "motore-ot2026",
        "settimana": _settimana_to(d),
        "celebrazione": cel[0] if cel else None,
        "grado": cel[1] if cel else ("domenica" if d.weekday() == 6 else "feriale"),
    })
    return info


if __name__ == "__main__":
    cur = FINESTRA_INIZIO
    while cur <= FINESTRA_FINE:
        info = info_giorno(cur)
        extra = f"  [{info.get('celebrazione')}]" if info and info.get("celebrazione") else ""
        sett = f"sett.{info['settimana']:>2}" if info and "settimana" in info else "  (ext) "
        print(f"{cur.isoformat()}  {sett}  {info['riferimento']:<20}{extra}")
        cur += timedelta(days=1)
