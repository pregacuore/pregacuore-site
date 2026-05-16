// supabase/functions/newsletter-confirm/index.ts
//
// Edge Function: gestisce la conferma del double opt-in.
// Riceve GET /?token=XXX → marca subscriber come 'confirmed' → mostra pagina HTML di successo

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0";

const SITE_URL = "https://pregacuore.it";

function pageHtml(opts: { success: boolean; message: string }): string {
  const color = opts.success ? "#7B1F22" : "#a83b3e";
  const icon = opts.success ? "✓" : "✗";
  return `
<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Pregacuore — ${opts.success ? "Iscrizione confermata" : "Errore"}</title>
  <link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital@0;1&family=Inter:wght@400;500&display=swap" rel="stylesheet">
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:'Inter',sans-serif;background:#FAF6EE;color:#3A3A3F;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;}
    .card{background:#FFF;border-radius:20px;padding:60px 40px;max-width:520px;text-align:center;box-shadow:0 4px 40px rgba(0,0,0,0.04);}
    .icon{width:80px;height:80px;background:${color};border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-size:36px;color:#F5EBD8;margin-bottom:30px;}
    h1{font-family:'Cormorant Garamond',Georgia,serif;font-size:36px;font-weight:500;color:${color};margin-bottom:20px;font-style:italic;line-height:1.2;}
    p{font-size:16px;line-height:1.7;margin-bottom:30px;opacity:0.85;}
    a.btn{background:#D4A24A;color:#2A1506;padding:14px 32px;border-radius:100px;text-decoration:none;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;font-size:12px;display:inline-block;}
    a.btn:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(212,162,74,0.3);}
    .quote{font-family:'Cormorant Garamond',serif;font-size:14px;font-style:italic;color:#7B1F22;opacity:0.5;margin-top:40px;}
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">${icon}</div>
    <h1>${opts.success ? "Iscrizione confermata" : "Qualcosa non ha funzionato"}</h1>
    <p>${opts.message}</p>
    <a class="btn" href="${SITE_URL}">Torna a pregacuore.it</a>
    <p class="quote">Prega col cuore. Mai da solo.</p>
  </div>
</body>
</html>
  `.trim();
}

serve(async (req: Request) => {
  try {
    const url = new URL(req.url);
    const token = url.searchParams.get("token");

    if (!token || token.length < 10) {
      return new Response(pageHtml({
        success: false,
        message: "Link non valido. Prova a iscriverti di nuovo dal sito.",
      }), { status: 400, headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL") ?? "",
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    );

    // Trova subscriber col token
    const { data: sub, error: selErr } = await supabase
      .from("newsletter_subscribers")
      .select("id, email, status")
      .eq("confirm_token", token)
      .maybeSingle();

    if (selErr) throw selErr;

    if (!sub) {
      return new Response(pageHtml({
        success: false,
        message: "Token scaduto o già usato. Se non hai ancora confermato, prova a iscriverti di nuovo.",
      }), { status: 404, headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    if (sub.status === "confirmed") {
      return new Response(pageHtml({
        success: true,
        message: "La tua email è già confermata. Riceverai il pensiero del giorno ogni mattina alle 7:30.",
      }), { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    // Conferma
    const { error: updErr } = await supabase
      .from("newsletter_subscribers")
      .update({
        status: "confirmed",
        confirmed_at: new Date().toISOString(),
        confirm_token: null, // invalida il token, è single-use
      })
      .eq("id", sub.id);

    if (updErr) throw updErr;

    return new Response(pageHtml({
      success: true,
      message: "Grazie. La tua iscrizione a Pregacuore è confermata. Riceverai il pensiero del giorno ogni mattina alle 7:30.",
    }), { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } });

  } catch (e) {
    console.error("newsletter-confirm error:", e);
    return new Response(pageHtml({
      success: false,
      message: "Errore tecnico. Riprova tra qualche minuto o scrivici a info@pregacuore.it.",
    }), { status: 500, headers: { "Content-Type": "text/html; charset=utf-8" } });
  }
});
