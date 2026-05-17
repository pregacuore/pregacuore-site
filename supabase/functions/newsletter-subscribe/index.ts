// supabase/functions/newsletter-subscribe/index.ts
//
// Edge Function: gestisce iscrizione newsletter Pregacuore.
// Flusso:
//   1. Riceve POST {email, gdpr} dal sito
//   2. Valida email
//   3. Inserisce/aggiorna riga su newsletter_subscribers (status=pending)
//   4. Genera confirm_token + unsubscribe_token
//   5. Manda email di conferma via Resend
//   6. Notifica admin (info@pregacuore.it)

import { serve } from "https://deno.land/std@0.208.0/http/server.ts";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2.39.0";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*", // restringere a pregacuore.it in prod
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
};

const SITE_URL = "https://pregacuore.it";
const FROM_EMAIL = "newsletter@pregacuore.it";// poi: newsletter@pregacuore.it
const FROM_NAME = "Pregacuore";
const ADMIN_EMAIL = "info@pregacuore.it";

function isValidEmail(email: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) && email.length <= 254;
}

function genToken(): string {
  // 32 caratteri random URL-safe
  const arr = new Uint8Array(24);
  crypto.getRandomValues(arr);
  return btoa(String.fromCharCode(...arr))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

async function sendResendEmail(opts: {
  to: string;
  subject: string;
  html: string;
  resendKey: string;
}) {
  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${opts.resendKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from: `${FROM_NAME} <${FROM_EMAIL}>`,
      to: [opts.to],
      subject: opts.subject,
      html: opts.html,
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Resend ${res.status}: ${errText}`);
  }
  return await res.json();
}

function confirmEmailHtml(confirmUrl: string): string {
  return `
<!DOCTYPE html>
<html lang="it">
<body style="margin:0;padding:0;background:#FAF6EE;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#FAF6EE;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="540" cellpadding="0" cellspacing="0" style="background:#FFFFFF;border-radius:16px;padding:50px 40px;max-width:540px;">
          <tr>
            <td align="center" style="padding-bottom:30px;">
              <div style="width:60px;height:60px;background:#7B1F22;border-radius:50%;display:inline-block;line-height:60px;">
                <span style="color:#D4A24A;font-size:24px;">🕯️</span>
              </div>
            </td>
          </tr>
          <tr>
            <td style="font-family:Georgia,serif;font-size:28px;color:#7B1F22;text-align:center;font-style:italic;padding-bottom:24px;line-height:1.3;">
              Conferma la tua iscrizione
            </td>
          </tr>
          <tr>
            <td style="font-size:16px;color:#3A3A3F;line-height:1.7;padding-bottom:30px;text-align:center;">
              Grazie per esserti iscritto a Pregacuore.<br>
              Clicca il bottone qui sotto per confermare la tua email e iniziare a ricevere il pensiero del giorno ogni mattina.
            </td>
          </tr>
          <tr>
            <td align="center" style="padding-bottom:30px;">
              <a href="${confirmUrl}" style="background:#D4A24A;color:#2A1506;padding:16px 36px;border-radius:100px;text-decoration:none;font-weight:600;letter-spacing:0.08em;text-transform:uppercase;font-size:13px;display:inline-block;">
                Conferma iscrizione
              </a>
            </td>
          </tr>
          <tr>
            <td style="font-size:13px;color:#999;line-height:1.6;text-align:center;padding-top:20px;border-top:1px solid #eee;">
              Se non riesci a cliccare il bottone, copia questo link nel browser:<br>
              <span style="color:#7B1F22;word-break:break-all;">${confirmUrl}</span>
            </td>
          </tr>
          <tr>
            <td style="font-size:12px;color:#999;text-align:center;padding-top:30px;font-style:italic;">
              Se non hai mai chiesto di iscriverti, ignora questa email — non riceverai altri messaggi.
            </td>
          </tr>
        </table>
        <p style="font-family:Georgia,serif;font-size:14px;color:#7B1F22;opacity:0.6;font-style:italic;margin-top:30px;">
          Prega col cuore. Mai da solo.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
  `.trim();
}

function adminNotifyHtml(email: string, totalCount: number): string {
  return `
<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;padding:20px;background:#FAF6EE;">
  <h2 style="color:#7B1F22;">📩 Nuova iscrizione newsletter</h2>
  <p><strong>Email:</strong> ${email}</p>
  <p><strong>Data:</strong> ${new Date().toLocaleString("it-IT")}</p>
  <p><strong>Stato:</strong> in attesa di conferma (double opt-in)</p>
  <hr style="border:none;border-top:1px solid #ddd;">
  <p style="color:#666;font-size:14px;">Totale iscritti (incluso pending): ${totalCount}</p>
</body>
</html>
  `.trim();
}

serve(async (req: Request) => {
  // CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Method not allowed" }),
      { status: 405, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }

  try {
    // 1. Parse body
    const body = await req.json();
    const email = (body.email || "").trim().toLowerCase();
    const gdpr = body.gdpr === true || body.gdpr === "true";
    const source = body.source || "website";
    const referrer = body.referrer || "";

    // 2. Validate
    if (!isValidEmail(email)) {
      return new Response(
        JSON.stringify({ error: "Email non valida" }),
        { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }
    if (!gdpr) {
      return new Response(
        JSON.stringify({ error: "Consenso GDPR richiesto" }),
        { status: 400, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
      );
    }

    // 3. Setup Supabase client (service role bypassa RLS)
    const supabase = createClient(
      Deno.env.get("SUPABASE_URL") ?? "",
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "",
    );

    // 4. Genera token
    const confirmToken = genToken();
    const unsubscribeToken = genToken();

    // 5. Estrai metadata utente
    const userAgent = req.headers.get("user-agent") || "";
    const ip = req.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "";

    // 6. UPSERT (se l'email esiste già pending, rigenera token e rimanda email)
    const { data: existing, error: selErr } = await supabase
      .from("newsletter_subscribers")
      .select("id, status")
      .eq("email", email)
      .maybeSingle();

    if (selErr) throw selErr;

    if (existing) {
      if (existing.status === "confirmed") {
        // Già iscritto e confermato: rispondi success ma non rimandare email
        return new Response(
          JSON.stringify({ ok: true, already_confirmed: true }),
          { status: 200, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
        );
      }
      // Status pending o unsubscribed: rigeneriamo token
      const { error: updErr } = await supabase
        .from("newsletter_subscribers")
        .update({
          status: "pending",
          confirm_token: confirmToken,
          unsubscribe_token: unsubscribeToken,
          gdpr_consent_at: new Date().toISOString(),
          gdpr_consent_ip: ip,
          gdpr_consent_user_agent: userAgent,
        })
        .eq("id", existing.id);
      if (updErr) throw updErr;
    } else {
      // Nuovo iscritto
      const { error: insErr } = await supabase
        .from("newsletter_subscribers")
        .insert({
          email,
          status: "pending",
          confirm_token: confirmToken,
          unsubscribe_token: unsubscribeToken,
          gdpr_consent_at: new Date().toISOString(),
          gdpr_consent_ip: ip,
          gdpr_consent_user_agent: userAgent,
          source,
          referrer,
        });
      if (insErr) throw insErr;
    }

    // 7. Manda email di conferma
    const resendKey = Deno.env.get("RESEND_API_KEY") ?? "";
    if (!resendKey) throw new Error("RESEND_API_KEY non configurata");

    const confirmUrl = `${SITE_URL}/conferma-iscrizione?token=${confirmToken}`;
    await sendResendEmail({
      to: email,
      subject: "Conferma la tua iscrizione a Pregacuore",
      html: confirmEmailHtml(confirmUrl),
      resendKey,
    });

    // 8. Notifica admin (non blocca se fallisce)
    try {
      const { count } = await supabase
        .from("newsletter_subscribers")
        .select("*", { count: "exact", head: true });
      await sendResendEmail({
        to: ADMIN_EMAIL,
        subject: `📩 Nuova iscrizione: ${email}`,
        html: adminNotifyHtml(email, count ?? 0),
        resendKey,
      });
    } catch (e) {
      console.warn("admin notify failed:", e);
    }

    // 9. Success
    return new Response(
      JSON.stringify({ ok: true }),
      { status: 200, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  } catch (e) {
    console.error("newsletter-subscribe error:", e);
    return new Response(
      JSON.stringify({ error: "Errore interno, riprova tra qualche minuto." }),
      { status: 500, headers: { ...CORS_HEADERS, "Content-Type": "application/json" } }
    );
  }
});
