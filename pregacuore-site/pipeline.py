"""
==============================================================================
PREGACUORE — Pipeline contenuto quotidiano (v2.1)

Cosa cambia rispetto a v2.0:
    • Fix FinishReason.RECITATION: il prompt chiedeva la versione CEI 2008
      (coperta da copyright). Gemini lo blocca preventivamente.
    • Ora chiediamo la Diodati 1641 (pubblico dominio, in linea con la scelta
      MVP del progetto).
    • Retry chain a 3 livelli: Diodati → parafrasi → solo riferimento.
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

# Modalità di generazione gospel_text in ordine di preferenza
GOSPEL_MODES = ["diodati", "paraphrase", "reference_only"]


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
- Per il testo del Vangelo, usa SOLO la versione Diodati 1641 (pubblico dominio mondiale)
  oppure una parafrasi originale, secondo le istruzioni che ti darò.

Niente disclaimer, niente "io penso che", niente "ricordiamo che". Vai dritto al senso.
"""


# ------------------------------------------------------------------
# 3. Prompt builders per i 3 modi di generazione gospel_text
# ------------------------------------------------------------------
def _gospel_text_instruction(mode: str) -> str:
    """Restituisce la riga di prompt per il campo gospel_text in base al modo."""
    if mode == "diodati":
        return (
            '"gospel_text": "Il testo del Vangelo del giorno nella versione DIODATI 1641 '
            '(traduzione italiana del XVII secolo, pubblico dominio mondiale). '
            'Riportalo esattamente come si trova nelle edizioni storiche. '
            'NON usare CEI 2008 ne IEP ne altre versioni moderne coperte da copyright."'
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
def _generate_attempt(target_date: date, weekday_it: str, gospel_mode: str) -> dict:
    """Un tentativo di generazione con un certo gospel_mode. Solleva
    RecitationBlocked se il modello blocca per copyright."""

    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = _build_user_prompt(target_date, weekday_it, gospel_mode)

    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        temperature=0.7,
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )

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

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        print("X  Output non e' JSON valido:")
        print(raw_text[:1000])
        raise

    return data


# ------------------------------------------------------------------
# 6. Generazione con retry chain Diodati -> parafrasi -> solo riferimento
# ------------------------------------------------------------------
_EMPTY_RESPONSE_RETRIES = 3
_EMPTY_RESPONSE_BACKOFF = [5, 15, 30]  # secondi tra i retry


def generate_daily_content(target_date: date) -> dict:
    """Genera con retry chain a 3 livelli (gospel_mode) + retry per risposta vuota."""

    weekday_it_map = {
        0: "lunedi", 1: "martedi", 2: "mercoledi", 3: "giovedi",
        4: "venerdi", 5: "sabato", 6: "domenica",
    }
    weekday = weekday_it_map[target_date.weekday()]

    print(f">>  Genero contenuto per {target_date.isoformat()} ({weekday})...")

    last_error = None
    for mode in GOSPEL_MODES:
        for attempt in range(_EMPTY_RESPONSE_RETRIES):
            try:
                print(f"    -> tentativo gospel_text mode: '{mode}'" +
                      (f" (retry {attempt})" if attempt else ""))
                data = _generate_attempt(target_date, weekday, mode)
                data["_gospel_text_mode"] = mode
                return _validate_and_normalize(data, target_date)

            except RecitationBlocked as e:
                print(f"    !!  {e}. Provo modalita' successiva...")
                last_error = e
                break  # passa al prossimo gospel_mode

            except ValueError as e:
                # Risposta vuota: transiente con Gemini 2.5 Flash + grounding.
                # Retry con backoff entro lo stesso gospel_mode.
                if "Risposta vuota" in str(e) and attempt < _EMPTY_RESPONSE_RETRIES - 1:
                    wait = _EMPTY_RESPONSE_BACKOFF[attempt]
                    print(f"    !!  {e}. Riprovo tra {wait}s...")
                    time.sleep(wait)
                    continue
                raise

    if last_error:
        raise RuntimeError(
            f"Impossibile generare contenuto per {target_date}: "
            f"tutte le modalita' ({', '.join(GOSPEL_MODES)}) bloccate. "
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
            f"[Testo del Vangelo: {ref} - Diodati 1641, da popolare "
            f"dall'importer della Bibbia.]"
        )
        print(f"    !!  gospel_text vuoto: placeholder applicato")

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
        "quote":             content["quote"],
        "pensiero":          content["pensiero"],
        "caption_instagram": content["caption_instagram"],
        "caption_whatsapp":  content["caption_whatsapp"],
        "hashtags":          content["hashtags"],
        "liturgical_day":    content.get("liturgical_day"),
        "saint_of_day":      content.get("saint_of_day"),
        "llm_model":         f"{MODEL_NAME} ({content.get('_gospel_text_mode', 'unknown')})",
        "generated_at":      datetime.now(timezone.utc).isoformat(),
        "is_published":      True,
    }

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
