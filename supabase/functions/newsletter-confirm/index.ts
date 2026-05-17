// supabase/functions/newsletter-confirm/index.ts
//
// Edge Function: gestisce la conferma del double opt-in.
// VERSIONE 3 — JSON-only.
//
// La presentazione (pagina di successo/errore) è servita da Vercel come
// pagina statica /conferma-iscrizione.html, che chiama questa funzione
// via fetch. Questa funzione restituisce SOLO JSON, niente HTML, così
// non incappiamo più nella sandbox CSP che Supabase impone alle Edge
// Function quando servono HTML al browser.
//
// Endpoint:
//   POST  /functions/v1/newsletter-confirm   body: { token: string }
//   GET   /functions/v1/newsletter-confirm?token=XXX   (per debug/curl)
//
// Risposte:
//   200 { ok: true, already: false }   -> appena confermato
//   200 { ok: true, already: true }    -> era già confermato
//   400 { ok: false, error: "missing_token" }
//   400 { ok: false, error: "invalid_token" }   -> token non trovato/usato
//   500 { ok: false, error: "server_error" }
//
// CORS: aperto a pregacuore.it (+ localhost per dev), include OPTIONS.

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0";

const ALLOWED_ORIGINS = new Set([
  "https://pregacuore.it",
  "https://www.pregacuore.it",
  "http://localhost:3000",
  "http://localhost:5173",
  "http://127.0.0.1:3000",
  "http://127.0.0.1:5173",
]);

function corsHeaders(origin: string | null): Record<string, string> {
  const allow = origin && ALLOWED_ORIGINS.has(origin) ? origin : "https://pregacuore.it";
  return {
    "Access-Control-Allow-Origin": allow,
    "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey, x-client-info",
    "Vary": "Origin",
  };
}

function json(body: unknown, status: number, origin: string | null): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      ...corsHeaders(origin),
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

async function extractToken(req: Request): Promise<string | null> {
  // Prova prima il body (POST), poi la query (GET fallback)
  if (req.method === "POST") {
    try {
      const body = await req.json();
      const t = (body?.token ?? "").toString().trim();
      if (t) return t;
    } catch (_) {
      // body non JSON: cade nel query fallback
    }
  }
  const url = new URL(req.url);
  const q = (url.searchParams.get("token") ?? "").trim();
  return q || null;
}

serve(async (req: Request) => {
  const origin = req.headers.get("origin");

  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: corsHeaders(origin) });
  }

  if (req.method !== "POST" && req.method !== "GET") {
    return json({ ok: false, error: "method_not_allowed" }, 405, origin);
  }

  try {
    const token = await extractToken(req);

    if (!token || token.length < 10) {
      return json({ ok: false, error: "missing_token" }, 400, origin);
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL") ?? "",
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    );

    // 1. Cerca subscriber col token
    const { data: sub, error: selErr } = await supabase
      .from("newsletter_subscribers")
      .select("id, email, status")
      .eq("confirm_token", token)
      .maybeSingle();

    if (selErr) throw selErr;

    // Token non trovato: o non è mai esistito, o è stato già usato (lo invalidiamo a confirmed)
    if (!sub) {
      return json({ ok: false, error: "invalid_token" }, 400, origin);
    }

    // Già confermato (caso teorico: token non ancora nullified per qualche motivo)
    if (sub.status === "confirmed") {
      return json({ ok: true, already: true }, 200, origin);
    }

    // 2. Conferma: flip status + nullifica token (single-use)
    const { error: updErr } = await supabase
      .from("newsletter_subscribers")
      .update({
        status: "confirmed",
        confirmed_at: new Date().toISOString(),
        confirm_token: null,
      })
      .eq("id", sub.id);

    if (updErr) throw updErr;

    return json({ ok: true, already: false }, 200, origin);

  } catch (e) {
    console.error("newsletter-confirm error:", e);
    return json({ ok: false, error: "server_error" }, 500, origin);
  }
});
