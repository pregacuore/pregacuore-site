# -*- coding: utf-8 -*-
"""
Verifica del lezionario deterministico (lezionario.py) su tutta la finestra
coperta (28/06/2026 → 31/12/2027). Due controlli indipendenti:

  A. FEDELTÀ AL CALENDARIO ITALIANO — confronta ogni giorno con un oracolo
     autorevole italiano, liturgia.silvestrini.org (che pubblica le date
     future). Snapshot in silvestrini_2026.json (T.O. 2026) e
     silvestrini_estensione.json (anno liturgico esteso).

  B. CROSS-CHECK INDIPENDENTE DEI FERIALI T.O. — per i giorni che sono feriali
     puri del Tempo Ordinario, confronta il riferimento col CICLO FERIALE
     UNIVERSALE (tabella sotto, dal lezionario romano, valida ogni anno),
     che NON dipende da silvestrini. Le uniche differenze attese sono i giorni
     in cui una festa/memoria propria sostituisce il feriale (le elenchiamo).

USO:
    python verifica_lezionario.py                 # esegue A + B
    python verifica_lezionario.py --scarica       # ri-scarica gli oracoli

I "DIVERSO" del controllo A vanno valutati a mano (di norma è il lezionario da
correggere; su qualche giorno può divergere l'oracolo). Le differenze del
controllo B che NON sono feste note sono il segnale da indagare.
"""
import re
import sys
import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lezionario import riferimento_vangelo, FINESTRA_INIZIO, FINESTRA_FINE

HERE = Path(__file__).resolve().parent
ORACOLO = HERE / "silvestrini_2026.json"
ORACOLO_EXT = HERE / "silvestrini_estensione.json"

ROM = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
       "IX": 9, "X": 10, "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
       "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20, "XXI": 21,
       "XXII": 22, "XXIII": 23, "XXIV": 24, "XXV": 25, "XXVI": 26, "XXVII": 27,
       "XXVIII": 28, "XXIX": 29, "XXX": 30, "XXXI": 31, "XXXII": 32,
       "XXXIII": 33, "XXXIV": 34}

# Ciclo feriale UNIVERSALE del Tempo Ordinario (Vangelo, uguale ogni anno).
# Settimane 1-9 = Marco, 10-21 = Matteo, 22-34 = Luca. Chiave (settimana, 0=lun..5=sab).
# Fonte: lezionario romano (catholic-resources.org), indipendente da silvestrini.
FERIALE_UNIVERSALE = {
 (1,0):'Mc 1,14-20',(1,1):'Mc 1,21-28',(1,2):'Mc 1,29-39',(1,3):'Mc 1,40-45',(1,4):'Mc 2,1-12',(1,5):'Mc 2,13-17',
 (2,0):'Mc 2,18-22',(2,1):'Mc 2,23-28',(2,2):'Mc 3,1-6',(2,3):'Mc 3,7-12',(2,4):'Mc 3,13-19',(2,5):'Mc 3,20-21',
 (3,0):'Mc 3,22-30',(3,1):'Mc 3,31-35',(3,2):'Mc 4,1-20',(3,3):'Mc 4,21-25',(3,4):'Mc 4,26-34',(3,5):'Mc 4,35-41',
 (4,0):'Mc 5,1-20',(4,1):'Mc 5,21-43',(4,2):'Mc 6,1-6',(4,3):'Mc 6,7-13',(4,4):'Mc 6,14-29',(4,5):'Mc 6,30-34',
 (5,0):'Mc 6,53-56',(5,1):'Mc 7,1-13',(5,2):'Mc 7,14-23',(5,3):'Mc 7,24-30',(5,4):'Mc 7,31-37',(5,5):'Mc 8,1-10',
 (6,0):'Mc 8,11-13',(6,1):'Mc 8,14-21',(6,2):'Mc 8,22-26',(6,3):'Mc 8,27-33',(6,4):'Mc 8,34-9,1',(6,5):'Mc 9,2-13',
 (7,0):'Mc 9,14-29',(7,1):'Mc 9,30-37',(7,2):'Mc 9,38-40',(7,3):'Mc 9,41-50',(7,4):'Mc 10,1-12',(7,5):'Mc 10,13-16',
 (8,0):'Mc 10,17-27',(8,1):'Mc 10,28-31',(8,2):'Mc 10,32-45',(8,3):'Mc 10,46-52',(8,4):'Mc 11,11-26',(8,5):'Mc 11,27-33',
 (9,0):'Mc 12,1-12',(9,1):'Mc 12,13-17',(9,2):'Mc 12,18-27',(9,3):'Mc 12,28-34',(9,4):'Mc 12,35-37',(9,5):'Mc 12,38-44',
 (10,0):'Mt 5,1-12',(10,1):'Mt 5,13-16',(10,2):'Mt 5,17-19',(10,3):'Mt 5,20-26',(10,4):'Mt 5,27-32',(10,5):'Mt 5,33-37',
 (11,0):'Mt 5,38-42',(11,1):'Mt 5,43-48',(11,2):'Mt 6,1-6.16-18',(11,3):'Mt 6,7-15',(11,4):'Mt 6,19-23',(11,5):'Mt 6,24-34',
 (12,0):'Mt 7,1-5',(12,1):'Mt 7,6.12-14',(12,2):'Mt 7,15-20',(12,3):'Mt 7,21-29',(12,4):'Mt 8,1-4',(12,5):'Mt 8,5-17',
 (13,0):'Mt 8,18-22',(13,1):'Mt 8,23-27',(13,2):'Mt 8,28-34',(13,3):'Mt 9,1-8',(13,4):'Mt 9,9-13',(13,5):'Mt 9,14-17',
 (14,0):'Mt 9,18-26',(14,1):'Mt 9,32-38',(14,2):'Mt 10,1-7',(14,3):'Mt 10,7-15',(14,4):'Mt 10,16-23',(14,5):'Mt 10,24-33',
 (15,0):'Mt 10,34-11,1',(15,1):'Mt 11,20-24',(15,2):'Mt 11,25-27',(15,3):'Mt 11,28-30',(15,4):'Mt 12,1-8',(15,5):'Mt 12,14-21',
 (16,0):'Mt 12,38-42',(16,1):'Mt 12,46-50',(16,2):'Mt 13,1-9',(16,3):'Mt 13,10-17',(16,4):'Mt 13,18-23',(16,5):'Mt 13,24-30',
 (17,0):'Mt 13,31-35',(17,1):'Mt 13,36-43',(17,2):'Mt 13,44-46',(17,3):'Mt 13,47-53',(17,4):'Mt 13,54-58',(17,5):'Mt 14,1-12',
 (18,0):'Mt 14,13-21',(18,1):'Mt 14,22-36',(18,2):'Mt 15,21-28',(18,3):'Mt 16,13-23',(18,4):'Mt 16,24-28',(18,5):'Mt 17,14-19',
 (19,0):'Mt 17,22-27',(19,1):'Mt 18,1-5.10.12-14',(19,2):'Mt 18,15-20',(19,3):'Mt 18,21-19,1',(19,4):'Mt 19,3-12',(19,5):'Mt 19,13-15',
 (20,0):'Mt 19,16-22',(20,1):'Mt 19,23-30',(20,2):'Mt 20,1-16',(20,3):'Mt 22,1-14',(20,4):'Mt 22,34-40',(20,5):'Mt 23,1-12',
 (21,0):'Mt 23,13-22',(21,1):'Mt 23,23-26',(21,2):'Mt 23,27-32',(21,3):'Mt 24,42-51',(21,4):'Mt 25,1-13',(21,5):'Mt 25,14-30',
 (22,0):'Lc 4,16-30',(22,1):'Lc 4,31-37',(22,2):'Lc 4,38-44',(22,3):'Lc 5,1-11',(22,4):'Lc 5,33-39',(22,5):'Lc 6,1-5',
 (23,0):'Lc 6,6-11',(23,1):'Lc 6,12-19',(23,2):'Lc 6,20-26',(23,3):'Lc 6,27-38',(23,4):'Lc 6,39-42',(23,5):'Lc 6,43-49',
 (24,0):'Lc 7,1-10',(24,1):'Lc 7,11-17',(24,2):'Lc 7,31-35',(24,3):'Lc 7,36-50',(24,4):'Lc 8,1-3',(24,5):'Lc 8,4-15',
 (25,0):'Lc 8,16-18',(25,1):'Lc 8,19-21',(25,2):'Lc 9,1-6',(25,3):'Lc 9,7-9',(25,4):'Lc 9,18-22',(25,5):'Lc 9,43-45',
 (26,0):'Lc 9,46-50',(26,1):'Lc 9,51-56',(26,2):'Lc 9,57-62',(26,3):'Lc 10,1-12',(26,4):'Lc 10,13-16',(26,5):'Lc 10,17-24',
 (27,0):'Lc 10,25-37',(27,1):'Lc 10,38-42',(27,2):'Lc 11,1-4',(27,3):'Lc 11,5-13',(27,4):'Lc 11,15-26',(27,5):'Lc 11,27-28',
 (28,0):'Lc 11,29-32',(28,1):'Lc 11,37-41',(28,2):'Lc 11,42-46',(28,3):'Lc 11,47-54',(28,4):'Lc 12,1-7',(28,5):'Lc 12,8-12',
 (29,0):'Lc 12,13-21',(29,1):'Lc 12,35-38',(29,2):'Lc 12,39-48',(29,3):'Lc 12,49-53',(29,4):'Lc 12,54-59',(29,5):'Lc 13,1-9',
 (30,0):'Lc 13,10-17',(30,1):'Lc 13,18-21',(30,2):'Lc 13,22-30',(30,3):'Lc 13,31-35',(30,4):'Lc 14,1-6',(30,5):'Lc 14,1.7-11',
 (31,0):'Lc 14,12-14',(31,1):'Lc 14,15-24',(31,2):'Lc 14,25-33',(31,3):'Lc 15,1-10',(31,4):'Lc 16,1-8',(31,5):'Lc 16,9-15',
 (32,0):'Lc 17,1-6',(32,1):'Lc 17,7-10',(32,2):'Lc 17,11-19',(32,3):'Lc 17,20-25',(32,4):'Lc 17,26-37',(32,5):'Lc 18,1-8',
 (33,0):'Lc 18,35-43',(33,1):'Lc 19,1-10',(33,2):'Lc 19,11-28',(33,3):'Lc 19,41-44',(33,4):'Lc 19,45-48',(33,5):'Lc 20,27-40',
 (34,0):'Lc 21,1-4',(34,1):'Lc 21,5-11',(34,2):'Lc 21,12-19',(34,3):'Lc 21,20-28',(34,4):'Lc 21,29-33',(34,5):'Lc 21,34-36',
}


def _scarica(ini, fin, path, con_titolo):
    def fetch(d):
        url = "https://liturgia.silvestrini.org/letture/%s.html" % d.isoformat()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        g = re.search(r"\bVangelo\s+(Mt|Mc|Lc|Gv)\s+([0-9][0-9,\.\-\s]*?)\s*"
                      r"(?:\([^)]*\)\s*)?Dal Vangelo secondo", txt)
        ref = "%s %s" % (g.group(1), re.sub(r"\s+", "", g.group(2)).rstrip(".,-")) if g else None
        if not con_titolo:
            return {"ref": ref}
        mt = re.search(r"(Domenica|Luned\w*|Marted\w*|Mercoled\w*|Gioved\w*|Venerd\w*|Sabato)"
                       r"[^,]*,\s*([^.<]{3,80}?)(?:Tog|RSS| Prima| Dalla| Dal )", txt)
        return {"title": re.sub(r"\s+", " ", mt.group(0)).strip()[:90] if mt else "", "ref": ref}
    res = {}
    cur = ini
    while cur <= fin:
        try:
            res[cur.isoformat()] = fetch(cur)
        except Exception as e:
            res[cur.isoformat()] = {"ref": None, "err": str(e)[:60]}
        cur += timedelta(days=1)
    json.dump(res, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    print("scaricati", len(res), "->", path.name)


def norm(r):
    if not r:
        return None
    r = r.strip().replace(" ", "")
    r = re.sub(r"([0-9])[ab]\b", r"\1", r)   # 12a -> 12
    r = r.split(".")[0]                       # 18,1-5.10.12-14 -> 18,1-5
    return r.lower()


def _oracolo_completo():
    o = {}
    for p in (ORACOLO, ORACOLO_EXT):
        if p.exists():
            o.update(json.load(open(p, encoding="utf-8")))
    return o


def main():
    if "--scarica" in sys.argv:
        from lezionario import _OT2026_INIZIO, _OT2026_FINE
        _scarica(_OT2026_INIZIO, _OT2026_FINE, ORACOLO, con_titolo=False)
        _scarica(date(2026, 11, 29), FINESTRA_FINE, ORACOLO_EXT, con_titolo=True)
        return

    oracolo = _oracolo_completo()
    if not oracolo:
        sys.exit("Mancano gli oracoli — lancia: python verifica_lezionario.py --scarica")

    # --- A. Fedeltà al calendario italiano (silvestrini) ---
    mism, no_oracolo = [], []
    cur = FINESTRA_INIZIO
    while cur <= FINESTRA_FINE:
        ds = cur.isoformat()
        mio = riferimento_vangelo(cur)
        suo = oracolo.get(ds, {}).get("ref")
        if suo is None:
            no_oracolo.append(ds)            # buco silvestrini: riempito a mano, non confrontabile
        elif norm(mio) != norm(suo):
            mism.append((ds, mio, suo))
        cur += timedelta(days=1)
    tot = (FINESTRA_FINE - FINESTRA_INIZIO).days + 1
    print(f"[A] Fedeltà calendario italiano: {tot} giorni, DIVERSI {len(mism)}, "
          f"buchi-oracolo riempiti a mano {len(no_oracolo)} {no_oracolo}")
    for ds, mio, suo in mism:
        print(f"    {ds}  LEZ={str(mio):<22} ORACOLO={str(suo)}")

    # --- B. Cross-check indipendente dei feriali T.O. (ciclo universale) ---
    titoli = json.load(open(ORACOLO_EXT, encoding="utf-8")) if ORACOLO_EXT.exists() else {}
    controllati, diff = 0, []
    for ds, v in sorted(titoli.items()):
        y, m, dd = map(int, ds.split("-"))
        d = date(y, m, dd)
        if d.weekday() == 6:
            continue
        t = re.search(r"\b([IVX]+)\s+Settimana Tempo Ordinario", v.get("title", ""))
        if not t:
            continue                          # solo feriali T.O. "puri"
        fer = FERIALE_UNIVERSALE.get((ROM[t.group(1)], d.weekday()))
        if not fer:
            continue
        controllati += 1
        if norm(fer) != norm(riferimento_vangelo(d)):
            diff.append((ds, fer, riferimento_vangelo(d)))
    print(f"[B] Feriali T.O. vs ciclo universale: controllati {controllati}, "
          f"DIVERSI {len(diff)} (attesi solo se festa/memoria sostituisce il feriale)")
    for ds, fer, mio in diff:
        print(f"    {ds}  UNIVERSALE={str(fer):<22} LEZ={str(mio)}")

    # --- C. Mutua coerenza: ogni override-Vangelo è una celebrazione nel
    # calendario italiano (LitCal) — due fonti indipendenti che concordano. ---
    from lezionario import santo_del_giorno
    sospetti = [(ds, mio) for ds, fer, mio in diff
                if (santo_del_giorno(date(*map(int, ds.split("-")))) or "").startswith("Feria del")]
    print(f"[C] Override-Vangelo che NON sono celebrazioni nel calendario: {len(sospetti)} "
          f"(atteso 0)")
    for ds, mio in sospetti:
        print(f"    {ds}  LEZ={mio}  ma calendario dice feria  <<<")

    sys.exit(1 if (mism or sospetti) else 0)


if __name__ == "__main__":
    main()
