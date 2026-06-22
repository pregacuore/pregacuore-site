# -*- coding: utf-8 -*-
r"""
modernizza_luzzi — resa conservativa della Riveduta Luzzi 1925 (pubblico dominio).

Gemello Python di `lib/luzzi-moderno.ts` del web (pregacuore-web). Ammoderna gli
arcaismi della Luzzi con sostituzioni **1 parola → 1 parola** (decisione 22/06):
- il conteggio parole NON cambia → il karaoke (mappa per indice) resta allineato;
- resta riconoscibilmente Luzzi (niente ristrutturazione di frase);
- rischio legale minimo: non ci avviciniamo alla CEI (coperta).

Applicato in pipeline.py a gospel_text/gospel_long_text (e quindi alla quote, che
ne deriva) così daily_content è salvato già pulito e le card social lo usano.

⚠️ Ambigui ESCLUSI di proposito (una regola cieca sbaglierebbe): «onde» (in Luzzi
è quasi sempre il sostantivo «onde» del mare o «da dove», non «perciò»), «fé»,
«ratto», «innanzi/appresso».

In Python 3 `\b`/`\w` sono già Unicode-aware (le lettere accentate sono word
char), quindi `\bparola\b` chiude bene anche dopo é/à — niente lookahead come in JS.
"""

import re

# Nomi divini con elisione dell'articolo (prima delle regole generiche).
_NOMI_DIVINI = [
    (r"\bdell'Eterno\b", "del Signore"), (r"\ball'Eterno\b", "al Signore"),
    (r"\bnell'Eterno\b", "nel Signore"), (r"\bsull'Eterno\b", "sul Signore"),
    (r"\bdall'Eterno\b", "dal Signore"),
    (r"\bL'Eterno\b", "Il Signore"), (r"\bl'Eterno\b", "il Signore"),
    (r"\bEterno\b", "Signore"),
    (r"\bdell'Iddio\b", "del Dio"), (r"\ball'Iddio\b", "al Dio"),
    (r"\bnell'Iddio\b", "nel Dio"), (r"\bsull'Iddio\b", "sul Dio"),
    (r"\bdall'Iddio\b", "dal Dio"),
    (r"\bL'Iddio\b", "Il Dio"), (r"\bl'Iddio\b", "il Dio"),
    (r"\bIddio\b", "Dio"),
    (r"\bteco\b", "con te"), (r"\bmeco\b", "con me"), (r"\bseco\b", "con sé"),
    (r"\bv'è\b", "vi è"),
]

# parola minuscola -> resa. Espansa in minuscolo + iniziale maiuscola.
_COPPIE = [
    # connettivi
    ("acciocché", "affinché"), ("perciocché", "poiché"),
    ("imperocché", "poiché"), ("imperciocché", "poiché"),
    ("conciossiaché", "poiché"), ("laonde", "perciò"),
    ("eziandio", "anche"), ("allorché", "quando"),
    # avverbi luogo/tempo
    ("giudicio", "giudizio"), ("giudicii", "giudizi"),
    ("quivi", "lì"), ("ivi", "lì"), ("colà", "là"),
    ("poscia", "poi"), ("indi", "poi"), ("sovente", "spesso"),
    ("incontanente", "subito"), ("immantinente", "subito"),
    ("dimani", "domani"), ("stamane", "stamattina"),
    # verbi arcaici
    ("dee", "deve"), ("ponno", "possono"),
    ("veggo", "vedo"), ("veggio", "vedo"), ("veggiamo", "vediamo"),
    ("veggono", "vedono"), ("vegga", "veda"),
    ("fia", "sarà"), ("fiano", "saranno"), ("sien", "siano"), ("sieno", "siano"),
    ("saria", "sarebbe"), ("sarian", "sarebbero"),
    ("avria", "avrebbe"), ("avrian", "avrebbero"),
    ("faria", "farebbe"), ("farian", "farebbero"),
    ("diria", "direbbe"), ("dirian", "direbbero"),
    ("vorria", "vorrebbe"), ("potria", "potrebbe"), ("dovria", "dovrebbe"),
    ("disser", "dissero"), ("fecer", "fecero"), ("ebber", "ebbero"),
    ("vider", "videro"), ("venner", "vennero"), ("preser", "presero"),
    ("miser", "misero"), ("trasser", "trassero"), ("risposer", "risposero"),
    ("dieder", "diedero"),
    ("son", "sono"), ("han", "hanno"), ("posson", "possono"),
    ("saran", "saranno"), ("abbiam", "abbiamo"), ("siam", "siamo"),
    ("possiam", "possiamo"), ("voglion", "vogliono"),
    ("dimandò", "domandò"), ("dimanda", "domanda"), ("dimandarono", "domandarono"),
    # sostantivi/aggettivi (chiavi già capitalizzate = regola esatta)
    ("Figliuolo", "Figlio"), ("figliuolo", "figlio"),
    ("Figliuol", "Figlio"), ("figliuol", "figlio"),
    ("Figliuoli", "Figli"), ("figliuoli", "figli"),
    ("Figliuole", "Figlie"), ("figliuole", "figlie"),
    ("sacrifizio", "sacrificio"), ("sacrifizi", "sacrifici"),
    ("annunzio", "annuncio"), ("annunzi", "annunci"),
    ("allegrezza", "gioia"), ("allegrezze", "gioie"),
    ("lagrima", "lacrima"), ("lagrime", "lacrime"),
    ("picchiate", "bussate"), ("sicurtà", "sicurezza"), ("tosto", "presto"),
    ("veduto", "visto"), ("veduta", "vista"), ("Signor", "Signore"),
]


def _costruisci_regole():
    regole = [(re.compile(p), r) for p, r in _NOMI_DIVINI]
    for da, a in _COPPIE:
        if da[0].isupper():
            regole.append((re.compile(r"\b" + re.escape(da) + r"\b"), a))
        else:
            da_cap = da[0].upper() + da[1:]
            a_cap = a[0].upper() + a[1:]
            regole.append((re.compile(r"\b" + re.escape(da_cap) + r"\b"), a_cap))
            regole.append((re.compile(r"\b" + re.escape(da) + r"\b"), a))
    return regole


_REGOLE = _costruisci_regole()


def modernizza_luzzi(testo):
    """Applica la resa modernizzata 1:1 al testo Luzzi. Idempotente, pura."""
    if not testo:
        return testo
    s = testo
    for rx, rep in _REGOLE:
        s = rx.sub(rep, s)
    return s
