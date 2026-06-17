#!/usr/bin/env python3
"""backfill_santi.py — aggiorna daily_content.saint_of_day sui giorni "Feria…" /
"… Domenica del Tempo Ordinario" col santo del giorno (santi_giorno.json).

Le righe già scritte conservano la vecchia dicitura "Feria del Tempo Ordinario":
questo script le ricalcola con lezionario.santo_del_giorno() (che ora sostituisce
col santo del giorno) e aggiorna SOLO quelle cambiate. Il pipeline notturno usa
già la stessa funzione per i giorni nuovi.

⚠️ La mappa è BOZZA → far passare `verificato_PM` su santi_giorno.json PRIMA di
--apply (occhio a voci obscure o non cattoliche dalla lista di Wikipedia).

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (come pipeline.py).
Uso:  python backfill_santi.py            # DRY-RUN (mostra i cambi)
      python backfill_santi.py --apply    # scrive su daily_content
"""
import os
import sys
from datetime import date

from dotenv import load_dotenv
from supabase import Client, create_client

from lezionario import santo_del_giorno

load_dotenv()  # come pipeline.py: SUPABASE_URL / SUPABASE_SERVICE_KEY dal .env

APPLY = "--apply" in sys.argv


def main() -> None:
    supabase: Client = create_client(os.environ["SUPABASE_URL"],
                                     os.environ["SUPABASE_SERVICE_KEY"])
    rows = (
        supabase.table("daily_content")
        .select("content_date, saint_of_day")
        .order("content_date")
        .execute()
        .data
    )
    cambi = 0
    for r in rows:
        cd = r["content_date"]
        vecchio = r.get("saint_of_day")
        try:
            nuovo = santo_del_giorno(date.fromisoformat(cd))
        except Exception:  # noqa: BLE001
            nuovo = None
        if nuovo and nuovo != vecchio:
            cambi += 1
            print(f"{cd}: {vecchio!r} -> {nuovo!r}")
            if APPLY:
                supabase.table("daily_content").update(
                    {"saint_of_day": nuovo}
                ).eq("content_date", cd).execute()
    modo = "APPLICATI" if APPLY else "DA APPLICARE (dry-run)"
    print(f"\n{cambi} cambi {modo}.")
    if not APPLY and cambi:
        print("Rilancia con --apply per scrivere (dopo verificato_PM su santi_giorno.json).")


if __name__ == "__main__":
    main()
