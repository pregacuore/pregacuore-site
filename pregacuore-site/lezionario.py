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

from datetime import date, timedelta
from typing import Optional


# ------------------------------------------------------------------
# Finestra coperta + ancora settimanale
# ------------------------------------------------------------------
FINESTRA_INIZIO = date(2026, 6, 28)   # XIII Domenica T.O. (Anno A)
FINESTRA_FINE = date(2026, 11, 28)    # Sabato XXXIV settimana T.O.
_ANCORA = date(2026, 6, 28)
_ANCORA_SETTIMANA = 13


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

    Precedenza: solennità > festa del Signore > domenica T.O. > festa di santo
    > memoria con Vangelo proprio > feriale.
    """
    if d < FINESTRA_INIZIO or d > FINESTRA_FINE:
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


_ORDINALI = {
    13: "XIII", 14: "XIV", 15: "XV", 16: "XVI", 17: "XVII", 18: "XVIII",
    19: "XIX", 20: "XX", 21: "XXI", 22: "XXII", 23: "XXIII", 24: "XXIV",
    25: "XXV", 26: "XXVI", 27: "XXVII", 28: "XXVIII", 29: "XXIX", 30: "XXX",
    31: "XXXI", 32: "XXXII", 33: "XXXIII", 34: "XXXIV",
}


def giorno_liturgico_label(d: date) -> Optional[str]:
    """Etichetta del giorno liturgico (per il campo liturgical_day), oppure None
    fuori finestra. Es. 'Lunedì della XIII settimana del Tempo Ordinario',
    'XXVII Domenica del Tempo Ordinario', il titolo della celebrazione propria,
    o 'Nostro Signore Gesù Cristo Re dell'Universo' per la 34ª domenica."""
    if d < FINESTRA_INIZIO or d > FINESTRA_FINE:
        return None
    cel = CELEBRAZIONI_FISSE.get((d.month, d.day))
    is_domenica = d.weekday() == 6
    # solennità/festa del Signore: vince sempre → mostra la celebrazione
    if cel and cel[1] in ("solennita", "festa_signore"):
        return cel[0]
    sett = _settimana_to(d)
    if is_domenica:
        if sett == 34:
            return "Nostro Signore Gesù Cristo Re dell'Universo"
        return f"{_ORDINALI.get(sett, sett)} Domenica del Tempo Ordinario"
    # giorno feriale: festa/memoria propria, altrimenti la feria
    if cel and cel[1] in ("festa", "memoria"):
        return cel[0]
    giorni = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato"]
    return f"{giorni[d.weekday()]} della {_ORDINALI.get(sett, sett)} settimana del Tempo Ordinario"


def info_giorno(d: date) -> Optional[dict]:
    """Diagnostica: settimana, eventuale celebrazione, riferimento risolto."""
    ref = riferimento_vangelo(d)
    if ref is None:
        return None
    cel = CELEBRAZIONI_FISSE.get((d.month, d.day))
    return {
        "data": d.isoformat(),
        "settimana": _settimana_to(d),
        "domenica": d.weekday() == 6,
        "celebrazione": cel[0] if cel else None,
        "grado": cel[1] if cel else ("domenica" if d.weekday() == 6 else "feriale"),
        "riferimento": ref,
    }


if __name__ == "__main__":
    cur = FINESTRA_INIZIO
    while cur <= FINESTRA_FINE:
        info = info_giorno(cur)
        extra = f"  [{info['celebrazione']}]" if info and info["celebrazione"] else ""
        print(f"{cur.isoformat()}  sett.{info['settimana']:>2}  {info['riferimento']:<18}{extra}")
        cur += timedelta(days=1)
