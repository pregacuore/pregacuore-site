# -*- coding: utf-8 -*-
"""
Verifica il lezionario deterministico (lezionario.py) contro un oracolo
autorevole italiano (liturgia.silvestrini.org, che pubblica le date future).

USO:
    # 1) prepara l'oracolo (una volta), scaricando la finestra:
    python verifica_lezionario.py --scarica   # -> silvestrini_2026.json
    # 2) confronta:
    python verifica_lezionario.py              # legge silvestrini_2026.json

Normalizza i riferimenti prima di confrontarli (spazi, suffissi a/b, range
non-contigui con '.'), così "Mt 5,1-12a" == "Mt 5,1-12". I "DIVERSO" vanno
valutati a mano: di norma è il lezionario da correggere, ma su qualche giorno
può divergere l'oracolo.
"""
import re
import sys
import json
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lezionario import riferimento_vangelo, FINESTRA_INIZIO, FINESTRA_FINE, info_giorno

ORACOLO = Path(__file__).resolve().parent / "silvestrini_2026.json"


def scarica():
    def fetch(d):
        url = "https://liturgia.silvestrini.org/letture/%s.html" % d.isoformat()
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        html = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
        g = re.search(
            r"Vangelo\s+(Mt|Mc|Lc|Gv)\s+(\d+)\s*,\s*([0-9][0-9\.,\-ab ]*?)\s*"
            r"(?:\([^)]*\)\s*)?Dal Vangelo", txt)
        ref = "%s %s,%s" % (g.group(1), g.group(2), re.sub(r"\s+", "", g.group(3))) if g else None
        return ref
    res = {}
    cur = FINESTRA_INIZIO
    while cur <= FINESTRA_FINE:
        try:
            res[cur.isoformat()] = {"ref": fetch(cur)}
        except Exception as e:
            res[cur.isoformat()] = {"ref": None, "err": str(e)[:60]}
        cur += timedelta(days=1)
    json.dump(res, open(ORACOLO, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    miss = [k for k, v in res.items() if not v["ref"]]
    print("scaricati", len(res), "giorni; senza ref:", len(miss), miss)


def norm(r):
    """Normalizza un riferimento per il confronto: minuscolo, niente spazi,
    via i suffissi a/b sui versetti, via i range non-contigui (tieni il blocco
    principale prima del primo '.')."""
    if not r:
        return None
    r = r.strip().replace(" ", "")
    r = re.sub(r"([0-9])[ab]\b", r"\1", r)   # 12a -> 12
    r = r.split(".")[0]                       # 18,1-5.10.12-14 -> 18,1-5
    return r.lower()


def main():
    if "--scarica" in sys.argv:
        scarica()
        return
    if not ORACOLO.exists():
        sys.exit("Manca %s — lancia prima: python verifica_lezionario.py --scarica" % ORACOLO.name)
    oracolo = json.load(open(ORACOLO, encoding="utf-8"))

    mism = []
    cur = FINESTRA_INIZIO
    while cur <= FINESTRA_FINE:
        ds = cur.isoformat()
        mio = riferimento_vangelo(cur)
        suo = oracolo.get(ds, {}).get("ref")
        if norm(mio) != norm(suo):
            info = info_giorno(cur)
            cel = info["celebrazione"] if info else ""
            mism.append((ds, mio, suo, cel or info["grado"]))
        cur += timedelta(days=1)

    tot = (FINESTRA_FINE - FINESTRA_INIZIO).days + 1
    print(f"Confrontati {tot} giorni. DIVERSI: {len(mism)}")
    for ds, mio, suo, cel in mism:
        print(f"  {ds}  LEZ={str(mio):<18} ORACOLO={str(suo):<18} [{cel}]")
    sys.exit(1 if mism else 0)


if __name__ == "__main__":
    main()
