# -*- coding: utf-8 -*-
"""
Sweep di QUALITÀ sui contenuti redazionali GIÀ in daily_content (pensiero,
caption_instagram, caption_whatsapp, hashtags). Usa lo stesso controllo della
pipeline (qualita.valida_contenuto) — nessuna chiamata AI.

USO:
    python audit_qualita.py 2026-06-28 2026-07-31     # range
    python audit_qualita.py 2026-06-28                # da quella data in poi (90gg)

Legge SUPABASE_URL + SUPABASE_SERVICE_KEY da .env (come pipeline.py).
"""
import os
import sys
from datetime import datetime, timedelta

from dotenv import load_dotenv
from supabase import create_client

from qualita import valida_contenuto

load_dotenv()


def main():
    if len(sys.argv) < 2:
        sys.exit("Uso: python audit_qualita.py AAAA-MM-GG [AAAA-MM-GG]")
    start = sys.argv[1]
    end = sys.argv[2] if len(sys.argv) > 2 else (
        datetime.strptime(start, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    rows = (sb.table("daily_content")
            .select("content_date,gospel_reference,gospel_text,pensiero,"
                    "caption_instagram,caption_whatsapp,hashtags")
            .gte("content_date", start).lte("content_date", end)
            .order("content_date").execute().data)

    con_problemi = 0
    for r in rows:
        probs = valida_contenuto(r)
        if probs:
            con_problemi += 1
            print(f"{r['content_date']}  ({r.get('gospel_reference','?')})")
            for p in probs:
                print(f"    - {p}")
    print(f"\nControllati {len(rows)} giorni ({start} → {end}); "
          f"con problemi/avvisi: {con_problemi}")
    sys.exit(0)


if __name__ == "__main__":
    main()
