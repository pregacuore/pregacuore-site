"""
==============================================================================
PREGACUORE — Pipeline contenuto quotidiano (v2.1)

Cosa cambia rispetto a v2.0:
    • Fix FinishReason.RECITATION: il prompt chiedeva la versione CEI 2008
      (coperta da copyright). Gemini lo blocca preventivamente.
    • Ora chiediamo la Riveduta Luzzi 1925 (pubblico dominio, lingua più
      moderna della Diodati, in linea con la scelta del progetto).
    • Retry chain a 3 livelli: Luzzi → parafrasi → solo riferimento.
      La pipeline non si pianta più su RECITATION.
    • Fallback non-null per gospel_text (in caso il campo resti NOT NULL).

Modalità d'uso:
    python pipeline.py                              # solo oggi
    python pipeline.py --date 2026-05-15            # data specifica
    python pipeline.py --from 2026-05-11 --to 2026-06-10   # range (backfill)
    python pipeline.py --tomorrow                   # solo domani
    python pipeline.py --ahead 30                   # solo il giorno T+30
    python pipeline.py --dry-run --date 2026-05-10  # solo anteprima

Setup:
    pip install -r requirements.txt
    .env con GEMINI_API_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY
==============================================================================
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client


# ------------------------------------------------------------------
# 1. Configurazione
# ------------------------------------------------------------------
load_dotenv()

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SERVICE_KEY = os.environ["SUPABASE_SERVICE_KEY"]

MODEL_NAME = "gemini-2.5-flash"
BATCH_DELAY_SECONDS = 5

# gospel_text NON è più generato dall'AI: viene preso dal testo REALE della
# Riveduta Luzzi 1925 (luzzi.json) via estrai_con_note() — che ritorna anche le
# note dei versetti della tradizione ricevuta (gospel_text_notes). All'AI
# chiediamo solo il riferimento + i contenuti redazionali, in modalità
# reference_only (gospel_text vuoto), così niente rischio di blocco RECITATION
# né di testo allucinato.
GOSPEL_MODES = ["reference_only"]

# Carica il testo Luzzi (Vangeli + Atti) e l'estrattore CEI.
_LUZZI_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "luzzi")
sys.path.insert(0, _LUZZI_DIR)
try:
    from luzzi_extract import estrai_con_note, RiferimentoNonValido
    with open(os.path.join(_LUZZI_DIR, "luzzi.json"), encoding="utf-8") as _f:
        LUZZI = json.load(_f)
    # Note dei versetti della tradizione "ricevuta" (assenti nei codici antichi):
    # opzionale, se manca il file le note semplicemente non vengono applicate.
    try:
        with open(os.path.join(_LUZZI_DIR, "luzzi_note.json"), encoding="utf-8") as _f:
            LUZZI_NOTE = json.load(_f)
    except FileNotFoundError:
        LUZZI_NOTE = {}
    print(f"[luzzi] caricati {len(LUZZI)} libri da luzzi.json"
          f" ({sum(len(c) for b in LUZZI_NOTE.values() for c in b.values())} note)")
except Exception as _e:  # pragma: no cover
    LUZZI = None
    LUZZI_NOTE = {}
    RiferimentoNonValido = Exception  # type: ignore
    print(f"[luzzi] ATTENZIONE: luzzi.json non caricato ({_e}). gospel_text resterà placeholder.")


# ------------------------------------------------------------------
# 2. System instruction
# ------------------------------------------------------------------
SYSTEM_INSTRUCTION = """Sei un redattore di Pregacuore, un'app cattolica italiana di preghiera quotidiana.

Il tuo compito: dato il Vangelo del giorno secondo il calendario liturgico cattolico romano italiano, generare contenuti per i fedeli.

Tono di marca:
- Sobrio, caldo, pastorale. Mai clericale, mai predicozzante, mai infantilizzante.
- Italiano corretto e contemporaneo. Niente arcaismi, niente espressioni "da catechismo".
- Frasi brevi. Una frase, un pensiero.
- Riferimenti biblici e liturgici solo quando aggiungono valore, mai per ostentazione.
- Mai usare "fratelli", "carissimi", "voi" plurale. Sempre "tu" singolare.
- Niente emoji decorative. Eccezione rara: una sola, max.

Pubblico target:
- Fedele cattolico italiano, 35-65 anni, praticante o cercatore.
- Apre l'app al mattino prima del lavoro o la sera prima di dormire.
- Cerca un momento di calma e una parola che gli resta dentro.

Importante sul copyright:
- La traduzione CEI 2008 e' coperta da copyright. NON riportarla mai integralmente.
- Anche Nuova Diodati e Nuova Riveduta sono coperte da copyright: NON usarle.
- Per il testo del Vangelo, usa SOLO la versione Riveduta Luzzi 1925 (pubblico
  dominio mondiale) oppure una parafrasi originale, secondo le istruzioni che ti darò.

Niente disclaimer, niente "io penso che", niente "ricordiamo che". Vai dritto al senso.
"""


# ------------------------------------------------------------------
# 3. Prompt builders per i 3 modi di generazione gospel_text
# ------------------------------------------------------------------
def _gospel_text_instruction(mode: str) -> str:
    """Restituisce la riga di prompt per il campo gospel_text in base al modo."""
    if mode == "luzzi":
        return (
            '"gospel_text": "Il testo del Vangelo del giorno nella versione RIVEDUTA '
            'LUZZI 1925 (traduzione italiana di Giovanni Luzzi, pubblico dominio mondiale). '
            'Riportalo fedelmente come si trova nelle edizioni della Riveduta 1925. '
            'NON usare CEI 2008 ne Nuova Diodati ne Nuova Riveduta ne altre versioni '
            'moderne coperte da copyright."'
        )
    if mode == "paraphrase":
        return (
            '"gospel_text": "Una PARAFRASI ORIGINALE del Vangelo del giorno: 4-6 frasi '
            'in italiano contemporaneo, scritte con parole tue, che restituiscono fedelmente '
            'il contenuto narrativo e il senso del passaggio. NON riprodurre verbatim alcuna '
            'traduzione esistente."'
        )
    # reference_only
    return (
        '"gospel_text": "Lascia questo campo come stringa vuota."'
    )


def _build_user_prompt(target_date: date, weekday_it: str, gospel_mode: str) -> str:
    gospel_text_field = _gospel_text_instruction(gospel_mode)

    # Uso concatenazione invece di .format() per evitare problemi con le graffe del JSON
    prompt = (
        f"La data per cui devi generare il contenuto e' ESATTAMENTE: "
        f"{target_date.isoformat()} ({weekday_it}).\n\n"
        f"Non usare la data di oggi se diversa. Lavora sul {target_date.isoformat()}.\n\n"
        "Cerca il Vangelo per quella data esatta secondo il calendario liturgico cattolico "
        "romano italiano (rito romano, non ambrosiano). Verifica con fonti ufficiali italiane: "
        "Vatican News, lachiesa.it, evangeli.net, chiesacattolica.it.\n\n"
        "Genera un JSON con QUESTI campi esatti:\n\n"
        "{\n"
        '  "gospel_reference": "es. \'Gv 15,18-21\' (sigla CEI italiana)",\n'
        f"  {gospel_text_field},\n"
        '  "liturgical_day": "es. \'Sabato V settimana di Pasqua\', \'IV Domenica di Avvento\'. Sempre presente.",\n'
        '  "saint_of_day": "OBBLIGATORIO, mai null. Il santo o la memoria liturgica del giorno secondo il martirologio romano italiano. Esempi: \'Santa Caterina da Siena\', \'San Pio da Pietrelcina, sacerdote\', \'Beata Vergine Maria di Fatima\'. Se e\' una feria senza memoria specifica, scrivi il tempo liturgico: \'Feria del Tempo Pasquale\', \'Feria del Tempo di Avvento\', \'Feria del Tempo Ordinario\'. MAI restituire null o stringa vuota.",\n'
        '  "quote": "una citazione brevissima del Vangelo, max 60 caratteri, racchiusa in caporali. Puo\' essere una frase chiave parafrasata se serve evitare verbatim CEI.",\n'
        '  "pensiero": "una riflessione di 2-4 frasi (60-100 parole) sul Vangelo. Tono pastorale e diretto, mai astratto. Si rivolge al lettore con \'tu\'.",\n'
        '  "caption_instagram": "post Instagram di 150-220 caratteri. Formula: citazione + 1 frase di pensiero + riferimento.",\n'
        '  "caption_whatsapp": "messaggio WhatsApp brevissimo, 30-80 caratteri. Formula: citazione tra caporali + saluto del momento.",\n'
        '  "hashtags": ["array di 4-6 hashtag in italiano lowercase senza il simbolo #"]\n'
        "}\n\n"
        "Rispondi SOLO con il JSON. Niente preamboli, niente markdown wrapper, niente spiegazioni.\n"
    )
    return prompt


# ------------------------------------------------------------------
# 4. Eccezione custom per RECITATION
# ------------------------------------------------------------------
class RecitationBlocked(Exception):
    """Sollevata quando Gemini blocca per RECITATION."""
    pass


# ------------------------------------------------------------------
# 5. Singolo tentativo di generazione
# ------------------------------------------------------------------
def _generate_attempt(target_date: date, weekday_it: str, gospel_mode: str,
                      use_search: bool = True) -> dict:
    """Un tentativo di generazione con un certo gospel_mode. Solleva
    RecitationBlocked se il modello blocca per copyright.

    `use_search=False` disabilita il google_search grounding: utile
    sui retry, dove il grounding e' la causa principale di "Risposta
    vuota" e di output 'tool_code' anziche' JSON.
    """

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = _build_user_prompt(target_date, weekday_it, gospel_mode)

    config_kwargs = {
        "system_instruction": SYSTEM_INSTRUCTION,
        "temperature": 0.7,
    }
    if use_search:
        config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    else:
        # Senza grounding richiediamo esplicitamente JSON come response format,
        # cosi' Gemini non si sbizzarrisce con codice o markdown.
        config_kwargs["response_mime_type"] = "application/json"

    config = types.GenerateContentConfig(**config_kwargs)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
        config=config,
    )

    # Diagnostica finish_reason
    if response.candidates:
        finish = response.candidates[0].finish_reason
        finish_str = str(finish)

        # RECITATION: il modello ha bloccato per copyright
        if "RECITATION" in finish_str:
            raise RecitationBlocked(
                f"Bloccato da Gemini per RECITATION (mode='{gospel_mode}')"
            )

        # Altri finish_reason problematici
        if "SAFETY" in finish_str:
            raise RuntimeError(f"Bloccato da safety filter: {finish_str}")
        if "MAX_TOKENS" in finish_str:
            raise RuntimeError("Output troncato (MAX_TOKENS).")

    # Estrai testo (response.text può sollevare ValueError in alcune versioni SDK
    # quando i parts includono thought-blocks o grounding metadata)
    raw_text = None
    try:
        if response.text is not None:
            raw_text = response.text.strip()
    except (ValueError, AttributeError):
        pass

    if not raw_text and response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
        raw_text = "".join(
            part.text for part in response.candidates[0].content.parts
            if hasattr(part, "text") and part.text
        ).strip()

    if not raw_text:
        finish = (
            response.candidates[0].finish_reason
            if response.candidates else "nessun candidato"
        )
        raise ValueError(f"Risposta vuota. Finish reason: {finish}")

    # Sgrosso markdown wrapper
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]
        raw_text = raw_text.strip()

    # Tentativo 1: parsing diretto
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    # Tentativo 2: estrazione del primo blocco {...} valido dalla risposta.
    # Serve quando Gemini emette codice (tool_code), markdown extra o testo
    # esplicativo intorno al JSON.
    extracted = _extract_json_from_blob(raw_text)
    if extracted is not None:
        return extracted

    print("X  Output non e' JSON valido (anche dopo estrazione):")
    print(raw_text[:1000])
    raise json.JSONDecodeError("JSON non estraibile dalla risposta", raw_text, 0)


def _extract_json_from_blob(blob: str) -> Optional[dict]:
    """Cerca il primo blocco {...} bilanciato dentro `blob` e prova a
    parsarlo. Torna None se non trova nulla di valido."""

    # Trova tutti i candidati che iniziano con `{`
    starts = [i for i, c in enumerate(blob) if c == "{"]
    for start in starts:
        # Scansiona forward bilanciando le parentesi graffe.
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(blob)):
            c = blob[i]
            if escape:
                escape = False
                continue
            if c == "\\":
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = blob[start:i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # questo `{` non chiude un JSON valido, prova il prossimo
    return None


# ------------------------------------------------------------------
# 6. Generazione con retry chain Luzzi -> parafrasi -> solo riferimento
# ------------------------------------------------------------------
_EMPTY_RESPONSE_RETRIES = 3
_EMPTY_RESPONSE_BACKOFF = [5, 15, 30]  # secondi tra i retry


def generate_daily_content(target_date: date) -> dict:
    """Genera con retry chain a 3 livelli (gospel_mode) + retry per risposta vuota
    o JSON malformato. Al primo tentativo di ciascun mode usa Google Search
    grounding; sui retry lo disattiva (riduce drasticamente le risposte vuote
    e gli output tool_code).
    """

    weekday_it_map = {
        0: "lunedi", 1: "martedi", 2: "mercoledi", 3: "giovedi",
        4: "venerdi", 5: "sabato", 6: "domenica",
    }
    weekday = weekday_it_map[target_date.weekday()]

    print(f">>  Genero contenuto per {target_date.isoformat()} ({weekday})...")

    last_error = None
    for mode in GOSPEL_MODES:
        for attempt in range(_EMPTY_RESPONSE_RETRIES):
            # Search grounding: ON al primo tentativo, OFF sui retry.
            use_search = (attempt == 0)
            try:
                grounding_label = "" if use_search else " [no-search]"
                print(f"    -> tentativo gospel_text mode: '{mode}'" +
                      (f" (retry {attempt})" if attempt else "") +
                      grounding_label)
                data = _generate_attempt(target_date, weekday, mode,
                                         use_search=use_search)
                data["_gospel_text_mode"] = mode
                return _fill_gospel_from_luzzi(_validate_and_normalize(data, target_date))

            except RecitationBlocked as e:
                print(f"    !!  {e}. Provo modalita' successiva...")
                last_error = e
                break  # passa al prossimo gospel_mode

            except json.JSONDecodeError as e:
                # JSON malformato (es. Gemini ha emesso tool_code).
                # Retry entro lo stesso mode; al successivo grounding sara' OFF.
                last_error = e
                if attempt < _EMPTY_RESPONSE_RETRIES - 1:
                    wait = _EMPTY_RESPONSE_BACKOFF[attempt]
                    print(f"    !!  JSON non valido. Riprovo tra {wait}s senza grounding...")
                    time.sleep(wait)
                    continue
                # Esauriti i retry: passa al prossimo gospel_mode.
                print(f"    !!  JSON non valido dopo {attempt + 1} tentativi. Provo modalita' successiva...")
                break

            except ValueError as e:
                # Risposta vuota: transiente con Gemini 2.5 Flash + grounding.
                # Retry entro lo stesso gospel_mode (grounding OFF dal 2o tentativo).
                last_error = e
                if "Risposta vuota" in str(e) and attempt < _EMPTY_RESPONSE_RETRIES - 1:
                    wait = _EMPTY_RESPONSE_BACKOFF[attempt]
                    print(f"    !!  {e}. Riprovo tra {wait}s...")
                    time.sleep(wait)
                    continue
                # Esauriti i retry o errore diverso: passa al prossimo mode.
                if "Risposta vuota" in str(e):
                    print(f"    !!  Risposta vuota dopo {attempt + 1} tentativi. Provo modalita' successiva...")
                    break
                raise

    if last_error:
        raise RuntimeError(
            f"Impossibile generare contenuto per {target_date}: "
            f"tutte le modalita' ({', '.join(GOSPEL_MODES)}) hanno fallito. "
            f"Ultimo errore: {last_error}"
        )


def _validate_and_normalize(data: dict, target_date: date) -> dict:
    """Valida i campi e applica fallback per quelli mancanti."""

    # saint_of_day fallback
    if not data.get("saint_of_day") or str(data["saint_of_day"]).lower() in ("null", "none", ""):
        litday = data.get("liturgical_day", "").lower()
        if "pasqu" in litday:
            data["saint_of_day"] = "Feria del Tempo Pasquale"
        elif "avvent" in litday:
            data["saint_of_day"] = "Feria del Tempo di Avvento"
        elif "quaresim" in litday:
            data["saint_of_day"] = "Feria del Tempo di Quaresima"
        elif "natal" in litday:
            data["saint_of_day"] = "Feria del Tempo di Natale"
        else:
            data["saint_of_day"] = "Feria del Tempo Ordinario"
        print(f"    !!  saint_of_day mancante: fallback a '{data['saint_of_day']}'")

    # gospel_text fallback (per evitare violazioni NOT NULL se la colonna lo e')
    gospel_text = data.get("gospel_text") or ""
    if not gospel_text.strip():
        ref = data.get("gospel_reference", "")
        data["gospel_text"] = (
            f"[Testo del Vangelo: {ref} - Riveduta Luzzi 1925, da popolare "
            f"dall'importer della Bibbia.]"
        )
        print(f"    !!  gospel_text vuoto: placeholder applicato")

    return data


def _quote_verbatim_luzzi(quote_ai: Optional[str], gospel_text: str) -> str:
    """La citazione breve delle card dev'essere Luzzi VERBATIM (pubblico
    dominio), non una parafrasi AI (che a volte scivolava su forme CEI). Sceglie
    la frase del brano Luzzi che condivide più parole con la quote suggerita
    dall'AI (cioè il versetto "saliente"); se nessuna combacia, usa la prima
    frase. Toglie eventuali numeri di versetto iniziali, accorcia con grazia, e
    racchiude fra caporali. Preferisce frasi di lunghezza decente: evita
    frammenti troppo corti tipo «Andate.»."""
    MIN_LEN, MAX_LEN = 40, 120
    g = (gospel_text or "").strip()
    qa = (quote_ai or "").strip()
    if not g:
        return qa

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^0-9a-zàèéìòóù ]", "", (s or "").lower())).strip()

    # Frasi del brano Luzzi (senza numero di versetto iniziale).
    frasi = [
        re.sub(r"^\d+\s*", "", f.strip()).strip()
        for f in re.split(r"(?<=[.!?;])\s+|\n+", g)
        if f.strip()
    ]
    if not frasi:
        return f"«{qa}»" if qa else ""

    # 1. Se la quote dell'AI è GIÀ Luzzi verbatim ED è abbastanza lunga, tienila
    #    (è la frase saliente che l'AI ha scelto).
    qn = norm(qa)
    if len(qn) >= MIN_LEN and qn in norm(g):
        clean = re.sub(r"^\d+\s*", "", qa.strip("«»\"' ")).strip()
        return f"«{clean}»"

    # 2. Altrimenti: la frase Luzzi con più parole in comune con la quote AI; a
    #    parità, la più lunga. Si preferiscono le frasi "sostanziose" (>= MIN_LEN)
    #    così non escono frammenti tipo «Andate.».
    def parole(s: str) -> set:
        return set(re.findall(r"[a-zàèéìòóù]{3,}", (s or "").lower()))

    target = parole(qa)
    candidate = [f for f in frasi if len(f) >= MIN_LEN] or frasi
    best, best_key = candidate[0], (-1, -1)
    for f in candidate:
        key = (len(parole(f) & target), len(f))  # overlap, poi lunghezza
        if key > best_key:
            best, best_key = f, key
    if len(best) > MAX_LEN:
        best = best[:MAX_LEN].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return f"«{best}»"


def _fill_gospel_from_luzzi(data: dict) -> dict:
    """Sostituisce gospel_text col testo REALE della Riveduta Luzzi 1925,
    estratto da luzzi.json in base a gospel_reference (modalità clemente:
    completa la frase a fine brano). Se il riferimento non è nel corpus
    (es. una prima lettura AT che non abbiamo, o sigla non interpretabile)
    o luzzi.json non è caricato, lascia il placeholder e segna la fonte 'none'."""
    ref = (data.get("gospel_reference") or "").strip()
    data["_gospel_source"] = "none"
    data["gospel_text_notes"] = None
    if not LUZZI or not ref:
        return data
    try:
        testo, note_app = estrai_con_note(ref, LUZZI, LUZZI_NOTE, clemente=True)
    except RiferimentoNonValido as e:
        print(f"    !!  Luzzi: riferimento non estraibile '{ref}' ({e}); gospel_text resta placeholder")
        return data
    if testo and testo.strip():
        data["gospel_text"] = testo
        data["gospel_long_text"] = testo
        data["_gospel_source"] = "luzzi-1925"
        # Note dei versetti della tradizione ricevuta toccati dal brano (se ci sono):
        # mappa {"<versetto>": "<nota>"}, NULL altrimenti.
        if note_app:
            data["gospel_text_notes"] = {str(v): n for v, n in note_app}
            print(f"    ==  gospel_text da Riveduta Luzzi 1925 ({len(testo)} car.; "
                  f"note: {', '.join(str(v) for v, _ in note_app)})")
        else:
            print(f"    ==  gospel_text da Riveduta Luzzi 1925 ({len(testo)} car.)")
        # La quote delle card: Luzzi verbatim, non parafrasi AI.
        data["quote"] = _quote_verbatim_luzzi(data.get("quote"), testo)
    return data


# ------------------------------------------------------------------
# 7. Salvataggio su Supabase
# ------------------------------------------------------------------
def save_to_supabase(target_date: date, content: dict) -> None:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    row = {
        "content_date":      target_date.isoformat(),
        "gospel_reference":  content["gospel_reference"],
        "gospel_text":       content["gospel_text"],
        "gospel_long_text":  content.get("gospel_long_text"),
        "quote":             content["quote"],
        "pensiero":          content["pensiero"],
        "caption_instagram": content["caption_instagram"],
        "caption_whatsapp":  content["caption_whatsapp"],
        "hashtags":          content["hashtags"],
        "liturgical_day":    content.get("liturgical_day"),
        "saint_of_day":      content.get("saint_of_day"),
        "llm_model":         f"{MODEL_NAME} (gospel: {content.get('_gospel_source', 'unknown')})",
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "is_published":      True,
    }

    # Licenza/fonte del testo del Vangelo: valorizzate solo quando il testo è
    # davvero la Riveduta Luzzi 1925 (pubblico dominio).
    if content.get("_gospel_source") == "luzzi-1925":
        row["liturgy_source"] = "Riveduta Luzzi 1925"
        row["liturgy_text_license"] = "Riveduta Luzzi 1925 — pubblico dominio"
        row["liturgy_fetched_at"] = datetime.now(timezone.utc).isoformat()
        # Note dei versetti della tradizione ricevuta (NULL se nessuna).
        row["gospel_text_notes"] = content.get("gospel_text_notes")

    result = (
        supabase.table("daily_content")
        .upsert(row, on_conflict="content_date")
        .execute()
    )

    print(f"==  Salvato. ID: {result.data[0]['id']}")


# ------------------------------------------------------------------
# 8. Anteprima a console
# ------------------------------------------------------------------
def print_preview(content: dict) -> None:
    print("\n" + "=" * 60)
    print(f"  {content.get('liturgical_day', '-')}")
    if content.get("saint_of_day"):
        print(f"  > {content['saint_of_day']}")
    print(f"  > modalita' gospel_text: {content.get('_gospel_text_mode', 'unknown')}")
    print("=" * 60)
    print(f"\n  {content.get('gospel_reference', '')}")
    print(f"\n   {content.get('quote', '')}")
    print(f"\n  PENSIERO\n")
    print(f"   {content.get('pensiero', '')}")
    if content.get("gospel_text") and not content["gospel_text"].startswith("["):
        text = content['gospel_text']
        print(f"\n  TESTO ({content.get('_gospel_text_mode', '')})\n")
        print(f"   {text[:200]}{'...' if len(text) > 200 else ''}")
    print(f"\n  IG: {content.get('caption_instagram', '')[:120]}...")
    print(f"\n  WA: {content.get('caption_whatsapp', '')}")
    print("\n" + "=" * 60 + "\n")


# ------------------------------------------------------------------
# 9. Helpers per range di date
# ------------------------------------------------------------------
def daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def parse_iso_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


# ------------------------------------------------------------------
# 10. Argparse + main
# ------------------------------------------------------------------
def parse_args():
    p = argparse.ArgumentParser(
        description="Pregacuore content pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=parse_iso_date)
    g.add_argument("--tomorrow", action="store_true")
    g.add_argument("--ahead", type=int, metavar="N")
    p.add_argument("--from", dest="date_from", type=parse_iso_date)
    p.add_argument("--to", dest="date_to", type=parse_iso_date)
    p.add_argument("--dry-run", action="store_true",
                   help="Solo anteprima, no salvataggio Supabase")
    return p.parse_args()


def resolve_dates(args) -> list:
    today = date.today()
    if args.date_from and args.date_to:
        if args.date_to < args.date_from:
            sys.exit("X  --to deve essere >= --from")
        return list(daterange(args.date_from, args.date_to))
    if args.date_from or args.date_to:
        sys.exit("X  --from e --to vanno usati insieme")
    if args.date:
        return [args.date]
    if args.tomorrow:
        return [today + timedelta(days=1)]
    if args.ahead is not None:
        return [today + timedelta(days=args.ahead)]
    return [today]


def main():
    args = parse_args()
    dates = resolve_dates(args)

    print(f"\n>>  Pregacuore pipeline v2.1 - {len(dates)} giorno/i")
    print(f"    Da {dates[0].isoformat()} a {dates[-1].isoformat()}")
    if args.dry_run:
        print("    Modalita': DRY RUN (nessun salvataggio)")
    print()

    successes = 0
    failures = []

    for i, target in enumerate(dates):
        try:
            content = generate_daily_content(target)
            print_preview(content)
            if not args.dry_run:
                save_to_supabase(target, content)
            successes += 1
        except Exception as e:
            print(f"X  Errore su {target.isoformat()}: {e}")
            failures.append((target, str(e)))

        if len(dates) > 1 and i < len(dates) - 1:
            print(f"... Pausa {BATCH_DELAY_SECONDS}s...\n")
            time.sleep(BATCH_DELAY_SECONDS)

    print("\n" + "=" * 60)
    print(f"  RIEPILOGO  -  {successes}/{len(dates)} riusciti")
    if failures:
        print(f"  Falliti:")
        for d, err in failures:
            print(f"    - {d.isoformat()}  ->  {err}")
    print("=" * 60 + "\n")

    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
