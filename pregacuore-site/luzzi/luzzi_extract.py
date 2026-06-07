"""
luzzi_extract.py — Estrazione del testo biblico dalla Riveduta Luzzi 1925.

FONTE-AGNOSTICO: lavora su un JSON normalizzato (vedi struttura sotto), così
puoi alimentarlo con QUALSIASI fonte Luzzi pulita (Wikisource, ecc.) senza
toccare questo codice. La fonte va scaricata a parte (vedi build_luzzi_from_wikisource.py).

Struttura JSON attesa (file `luzzi.json`):
{
  "John": { "19": { "25": "Or presso la croce di Gesù...", "26": "...", ... }, ... },
  "Matt": { ... },
  ...
}
Le CHIAVI dei libri sono i codici OSIS standard (Matt, Mark, Luke, John, ...).

Espone:
  - parse_riferimento("Gv 19,25-34")  -> ("John", 19, 25, 34)
  - estrai("Gv 19,25-34", clemente=True) -> str (testo del brano)

Politica versificazione (scelta dall'utente): CLEMENTE.
  Se il versetto finale del riferimento spezza una frase a metà, l'estrazione
  prosegue fino alla fine della frase (prossimo . ! ? : ») includendo i versetti
  successivi necessari. Garantisce una lettura fluida.
"""

import json
import re
import unicodedata

# ──────────────────────────────────────────────────────────────────
# 1. Mappa sigle CEI italiane → codici OSIS
#    Copre tutte le sigle comunemente usate nei riferimenti liturgici IT.
# ──────────────────────────────────────────────────────────────────

SIGLE_CEI = {
    # Vangeli e NT (i più usati nel Vangelo del giorno)
    "mt": "Matt", "mc": "Mark", "lc": "Luke", "gv": "John",
    "at": "Acts", "atti": "Acts",
    "rm": "Rom", "1cor": "1Cor", "2cor": "2Cor", "gal": "Gal", "ef": "Eph",
    "fil": "Phil", "col": "Col", "1ts": "1Thess", "2ts": "2Thess",
    "1tm": "1Tim", "2tm": "2Tim", "tt": "Titus", "fm": "Phlm",
    "eb": "Heb", "gc": "Jas", "1pt": "1Pet", "2pt": "2Pet",
    "1gv": "1John", "2gv": "2John", "3gv": "3John", "gd": "Jude", "ap": "Rev",
    # Antico Testamento (per prima lettura / salmo, se servirà)
    "gen": "Gen", "es": "Exod", "lv": "Lev", "nm": "Num", "dt": "Deut",
    "gs": "Josh", "gdc": "Judg", "rt": "Ruth", "1sam": "1Sam", "2sam": "2Sam",
    "1re": "1Kgs", "2re": "2Kgs", "1cr": "1Chr", "2cr": "2Chr",
    "esd": "Ezra", "ne": "Neh", "est": "Esth", "gb": "Job",
    "sal": "Ps", "sl": "Ps", "salmo": "Ps", "salmi": "Ps",
    "pr": "Prov", "qo": "Eccl", "ct": "Song",
    "is": "Isa", "ger": "Jer", "lam": "Lam", "ez": "Ezek", "dn": "Dan",
    "os": "Hos", "gl": "Joel", "am": "Amos", "abd": "Obad", "gio": "Jonah",
    "mi": "Mic", "na": "Nah", "ab": "Hab", "sof": "Zeph", "ag": "Hag",
    "zc": "Zech", "ml": "Mal",
}


def _norm_sigla(s: str) -> str:
    """Normalizza una sigla: minuscolo, niente spazi/punti."""
    return re.sub(r"[\s\.]", "", s.strip().lower())


# ──────────────────────────────────────────────────────────────────
# 2. Parser del riferimento CEI
#    Gestisce: "Gv 19,25-34" · "Mt 5,1-12" · "Lc 1,26-38" · "Gv 6,51"
#    (versetto singolo) · "1Cor 13,4-7" · sigle con spazio "1 Cor 13,4".
#    NB: ignora i riferimenti compositi con ';' (prende il primo blocco)
#    e i '.' interni (es. "Mt 5,1-12.17") prendendo il range esterno.
# ──────────────────────────────────────────────────────────────────

class RiferimentoNonValido(Exception):
    pass


def parse_riferimento(rif: str):
    """
    "Gv 19,25-34" -> ("John", 19, 25, 34)
    "Gv 6,51"     -> ("John", 6, 51, 51)
    Solleva RiferimentoNonValido se non interpretabile.
    """
    if not rif or not rif.strip():
        raise RiferimentoNonValido("riferimento vuoto")

    # prendi solo il primo blocco se composito (separato da ; o .)
    primo = re.split(r"[;]", rif.strip())[0].strip()

    # cattura: SIGLA  CAP1,V1  [ - [CAP2,] VEND ]  con eventuale suffisso lettera (a/b)
    # sui versetti. Gestisce anche i riferimenti A CAVALLO DI CAPITOLO,
    # es. "Gv 15,26-16,4a" -> (John, 15, 26, 16, 4).
    m = re.match(
        r"^\s*(\d?\s?[A-Za-zàèéìòù]+)\s+(\d+)\s*,\s*(\d+)[a-z]?"
        r"(?:\s*-\s*(?:(\d+)\s*,\s*)?(\d+)[a-z]?)?",
        primo,
    )
    if not m:
        raise RiferimentoNonValido(f"non interpretabile: {rif!r}")

    sigla_raw, cap1, v1, cap2, vend = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
    sigla = _norm_sigla(sigla_raw)
    libro = SIGLE_CEI.get(sigla)
    if libro is None:
        raise RiferimentoNonValido(f"sigla sconosciuta: {sigla_raw!r} (norm: {sigla!r})")

    cap1 = int(cap1)
    v1 = int(v1)
    if vend is None:           # versetto singolo
        cap2, v2 = cap1, v1
    elif cap2 is None:         # range nello stesso capitolo
        cap2, v2 = cap1, int(vend)
    else:                      # range a cavallo di capitolo
        cap2, v2 = int(cap2), int(vend)
    return (libro, cap1, v1, cap2, v2)


# ──────────────────────────────────────────────────────────────────
# 3. Ripulitura testo (rete di sicurezza)
#    La fonte PULITA (Wikisource) non dovrebbe averne bisogno, ma questa
#    funzione corregge i pochi accenti finali persi che si trovano in
#    alcuni file. NON tocca gli apostrofi (troppo ambiguo da indovinare):
#    se la fonte ha "daceto" significa che la fonte è sbagliata → va
#    cambiata fonte, non corretta a macchina.
# ──────────────────────────────────────────────────────────────────

_ACCENTI_FINALI = {
    r"\bgia\b": None,  # ambiguo, lasciato stare
}

# Sostituzioni SICURE: parole che in italiano esistono solo accentate.
_FIX_ACCENTI = [
    (re.compile(r"\bfara\b"), "farà"),
    (re.compile(r"\bdara\b"), "darà"),
    (re.compile(r"\bsara\b"), "sarà"),
    (re.compile(r"\bandra\b"), "andrà"),
    (re.compile(r"\bverra\b"), "verrà"),
    (re.compile(r"\bvivra\b"), "vivrà"),
    (re.compile(r"\bperche\b"), "perché"),
    (re.compile(r"\bpoiche\b"), "poiché"),
    (re.compile(r"\bbenche\b"), "benché"),
    (re.compile(r"\baffinche\b"), "affinché"),
    (re.compile(r"\bfinche\b"), "finché"),
    (re.compile(r"\bcitta\b"), "città"),
    (re.compile(r"\bverita\b"), "verità"),
    (re.compile(r"\bliberta\b"), "libertà"),
    (re.compile(r"\bpieta\b"), "pietà"),
    (re.compile(r"\bvolonta\b"), "volontà"),
    (re.compile(r"\bbonta\b"), "bontà"),
    (re.compile(r"\bmaesta\b"), "maestà"),
]


def ripulisci(testo: str) -> str:
    """Normalizza spazi e corregge accenti finali persi (rete di sicurezza)."""
    t = unicodedata.normalize("NFC", testo)
    t = re.sub(r"\s+", " ", t).strip()
    for pat, sost in _FIX_ACCENTI:
        t = pat.sub(sost, t)
    return t


# ──────────────────────────────────────────────────────────────────
# 4. Estrazione clemente
# ──────────────────────────────────────────────────────────────────

# fine-frase: punto, punto e virgola forte, esclamativo, interrogativo,
# due punti, o chiusura di battuta. Consideriamo "fine" se seguita da spazio
# o fine stringa.
_FINE_FRASE = re.compile(r"[\.!?»][\"'»]?\s*$")


def _versetti_ordinati(cap_dict):
    """Ritorna lista di (numero_versetto:int, testo) ordinata."""
    out = []
    for k, v in cap_dict.items():
        try:
            out.append((int(k), v))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda x: x[0])
    return out


def estrai(rif: str, luzzi: dict, clemente: bool = True) -> str:
    """
    Estrae il testo del brano dal dict `luzzi` (struttura OSIS-keyed).
    clemente=True: se l'ultimo versetto non termina una frase, prosegue
    nei versetti successivi fino al primo fine-frase.
    """
    libro, cap1, v1, cap2, v2 = parse_riferimento(rif)

    if libro not in luzzi:
        raise RiferimentoNonValido(f"libro assente nella fonte: {libro}")
    capitoli = luzzi[libro]

    def _vers_cap(capn: int):
        ck = str(capn)
        if ck not in capitoli:
            raise RiferimentoNonValido(f"capitolo assente: {libro} {capn}")
        vv = _versetti_ordinati(capitoli[ck])
        if not vv:
            raise RiferimentoNonValido(f"nessun versetto in {libro} {capn}")
        return vv

    # Raccogli i versetti da cap1:v1 fino a cap2:v2 (anche a cavallo di capitolo).
    # Per i capitoli intermedi si prende tutto il capitolo.
    pezzi = []          # testi
    ultimo_n = v1
    for capn in range(cap1, cap2 + 1):
        lo = v1 if capn == cap1 else 1
        hi = v2 if capn == cap2 else 10**9
        for n, txt in _vers_cap(capn):
            if lo <= n <= hi:
                pezzi.append(ripulisci(txt))
                ultimo_n = n

    if not pezzi:
        raise RiferimentoNonValido(f"versetti assenti in {libro} {cap1},{v1}-{cap2},{v2}")

    # CLEMENTE: se l'ultimo versetto non chiude una frase, continua nel capitolo
    # finale (cap2) fino al primo fine-frase (max 3 versetti di prolungamento).
    if clemente:
        coda = pezzi[-1]
        versetti2 = _vers_cap(cap2)
        idx = next((i for i, (n, _) in enumerate(versetti2) if n == ultimo_n), None)
        if idx is not None:
            j = idx + 1
            extra = 0
            while not _FINE_FRASE.search(coda) and j < len(versetti2) and extra < 3:
                n_next, txt_next = versetti2[j]
                add = ripulisci(txt_next)
                pezzi.append(add)
                coda = add
                j += 1
                extra += 1

    return " ".join(pezzi)


# ──────────────────────────────────────────────────────────────────
# 5. Controllo di sicurezza (capitolo validato vs tabella attesi)
# ──────────────────────────────────────────────────────────────────

class CapitoloNonValidato(Exception):
    pass


def estrai_sicuro(rif: str, luzzi: dict, attesi: dict, clemente: bool = True) -> str:
    """
    Come estrai(), ma verifica che OGNI capitolo coinvolto dal riferimento
    (cap1..cap2, anche a cavallo di capitolo) abbia il numero di versetti
    ATTESO (da versetti_attesi.json) PRIMA di servire il testo. Se un capitolo
    non combacia, solleva CapitoloNonValidato invece di restituire testo
    potenzialmente errato.
    """
    libro, cap1, _v1, cap2, _v2 = parse_riferimento(rif)
    for capn in range(cap1, cap2 + 1):
        cap_attesi = attesi.get(libro, {}).get(str(capn))
        cap_reali = len(luzzi.get(libro, {}).get(str(capn), {}))
        if cap_attesi is None:
            raise CapitoloNonValidato(f"{libro} {capn}: capitolo non in tabella attesi")
        if cap_reali != cap_attesi:
            raise CapitoloNonValidato(
                f"{libro} {capn}: {cap_reali} versetti presenti ≠ {cap_attesi} attesi "
                f"— capitolo NON validato, non servire")
    return estrai(rif, luzzi, clemente=clemente)


# ──────────────────────────────────────────────────────────────────
# 6. Estrazione con note (versetti della tradizione testuale ricevuta)
# ──────────────────────────────────────────────────────────────────

def estrai_con_note(rif: str, luzzi: dict, note: dict | None = None,
                    clemente: bool = True):
    """Come estrai(), ma ritorna (testo, note_applicabili).

    note_applicabili = lista ordinata di (versetto:int, nota:str) per i versetti
    del brano (cap1:v1 .. cap2:v2, anche a cavallo di capitolo) che hanno una
    nota in `note` (struttura {libro:{cap:{versetto:nota}}}). Sono i
    "missing-verses" del testo ricevuto: l'app li mostra fra parentesi quadre
    con la nota a piè di brano.
    """
    libro, cap1, v1, cap2, v2 = parse_riferimento(rif)
    testo = estrai(rif, luzzi, clemente=clemente)
    applicabili = []
    if note:
        libro_note = note.get(libro, {})
        for capn in range(cap1, cap2 + 1):
            cap_note = libro_note.get(str(capn), {})
            lo = v1 if capn == cap1 else 1
            hi = v2 if capn == cap2 else 10**9
            for v, n in cap_note.items():
                try:
                    vi = int(v)
                except (TypeError, ValueError):
                    continue
                if lo <= vi <= hi:
                    applicabili.append((vi, n))
    return testo, sorted(applicabili)


# ──────────────────────────────────────────────────────────────────
# 7. Self-test (solo se eseguito direttamente con una fonte di prova)
# ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    # uso: python luzzi_extract.py luzzi.json "Gv 19,25-34"
    if len(sys.argv) >= 3:
        with open(sys.argv[1], encoding="utf-8") as f:
            data = json.load(f)
        print(estrai(sys.argv[2], data))
    else:
        # test del solo parser (senza fonte)
        for r in ["Gv 19,25-34", "Mt 5,1-12", "Lc 1,26-38", "Gv 6,51",
                  "1Cor 13,4-7", "Sal 23,1-3", "Mc 1,14-20"]:
            print(f"{r!r:20} -> {parse_riferimento(r)}")
