# -*- coding: utf-8 -*-
"""
Pregacuore — Rete di sicurezza per daily_content (contenuto + card).

Il workflow "Daily Content" genera solo il giorno T+30: se un singolo giro
fallisce (es. 503 Gemini), resta un BUCO silenzioso 30 giorni dopo — e Make
fallisce la pubblicazione ("Missing required parameter 'image_url'") perché quel
giorno non ha la card (social_card_url vuoto).

Questo script scandisce la finestra futura e RIPARA i buchi:
  - manca la riga / gospel_text vuoto/placeholder  -> pipeline.py (contenuto) + card_generator.py
  - contenuto ok ma social_card_url vuoto           -> solo card_generator.py
con retry sui fallimenti transitori. Idempotente; exit != 0 se resta un buco
(così lo scheduler può allertare).

  python fill_missing.py                 # finestra oggi..oggi+30, ripara i buchi
  python fill_missing.py --days 35
  python fill_missing.py --start 2026-07-01 --days 40
  python fill_missing.py --dry-run       # mostra i buchi, NON genera
  python fill_missing.py --max-retries 4

Setup: stesso .env/secret di pipeline.py (SUPABASE_URL, SUPABASE_SERVICE_KEY,
GEMINI_API_KEY). Eseguire col Python che ha le dipendenze (card_generator usa
Pillow/cairosvg): in CI il workflow installa requirements.txt + setup_assets.py.
"""
import os
import sys
import time
import argparse
import subprocess
from datetime import date, datetime, timedelta

from dotenv import load_dotenv
from supabase import create_client

HERE = os.path.dirname(os.path.abspath(__file__))
PIPELINE = os.path.join(HERE, "pipeline.py")
CARDS = os.path.join(HERE, "card_generator.py")

load_dotenv()
SB = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])


def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def stato(iso: str) -> dict:
    """Ritorna {has_row, has_text, has_card} per una data."""
    rows = (
        SB.table("daily_content")
        .select("gospel_text,social_card_url")
        .eq("content_date", iso)
        .execute()
        .data
    )
    if not rows:
        return {"row": False, "text": False, "card": False}
    r = rows[0]
    gt = (r.get("gospel_text") or "").strip()
    return {
        "row": True,
        "text": bool(gt) and not gt.startswith("["),  # "[...placeholder...]" = vuoto
        "card": bool((r.get("social_card_url") or "").strip()),
    }


def run(script: str, iso: str) -> None:
    subprocess.run([sys.executable, script, "--date", iso])


def main() -> int:
    ap = argparse.ArgumentParser(description="Ripara i buchi di daily_content (contenuto + card).")
    ap.add_argument("--start", help="data iniziale YYYY-MM-DD (default: oggi)")
    ap.add_argument("--days", type=int, default=30, help="ampiezza finestra (default 30 = buffer)")
    ap.add_argument("--max-retries", type=int, default=3, help="tentativi per data (default 3)")
    ap.add_argument("--dry-run", action="store_true", help="mostra i buchi, NON genera")
    args = ap.parse_args()

    start = parse_date(args.start) if args.start else date.today()
    end = start + timedelta(days=args.days)

    buchi = []
    d = start
    while d <= end:
        iso = d.isoformat()
        s = stato(iso)
        if not (s["row"] and s["text"] and s["card"]):
            manca = []
            if not s["text"]:
                manca.append("contenuto")
            if not s["card"]:
                manca.append("card")
            buchi.append((iso, "contenuto" if not s["text"] else "card"))
            print(f"  buco {iso}: manca {', '.join(manca)}")
        d += timedelta(days=1)

    tot = (end - start).days + 1
    print(f"Finestra {start} .. {end} ({tot} gg) — buchi: {len(buchi)}")
    if not buchi:
        print("Nessun buco. OK")
        return 0
    if args.dry_run:
        print("DRY-RUN: niente generazione.")
        return 1

    falliti = []
    for iso, tipo in buchi:
        ok = False
        for tent in range(1, args.max_retries + 1):
            print(f"\n>>> {iso} (manca {tipo}) — tentativo {tent}/{args.max_retries}")
            if tipo == "contenuto":
                run(PIPELINE, iso)   # rigenera contenuto (Luzzi)
                run(CARDS, iso)      # e la card
            else:
                run(CARDS, iso)      # solo la card
            s = stato(iso)
            if s["row"] and s["text"] and s["card"]:
                ok = True
                print(f"    OK {iso} completo (contenuto + card)")
                break
            attesa = 10 * tent
            print(f"    ! {iso} ancora incompleto; attendo {attesa}s...")
            time.sleep(attesa)
        if not ok:
            falliti.append(iso)

    print("\n=== REPORT ===")
    print(f"Riparati: {len(buchi) - len(falliti)}/{len(buchi)}")
    if falliti:
        print(f"ANCORA INCOMPLETI: {', '.join(falliti)}")
        return 1
    print("Tutti i buchi riparati. OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
