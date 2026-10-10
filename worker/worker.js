// worker.js — Puente entre el dashboard (GitHub Pages) y el robot (GitHub Actions)
// =============================================================================
// La página es estática y no puede guardar el token de GitHub; este Worker de
// Cloudflare lo guarda y solo dispara el robot si la clave es correcta.
//
// Variables del Worker (Settings → Variables and Secrets):
//   GH_TOKEN  (Secret)  token de GitHub con permiso "Actions: Read and write" sobre el repo
//   CLAVE     (Secret)  clave que escriben los usuarios para generar/borrar fichas
//   REPO      (Text)    PacoTinoco/Enoe-Report
//   ORIGEN    (Text)    https://pacotinoco.github.io   (dominio de la página, sin "/" final)
//
// Rutas:
//   GET  /estado   → últimas ejecuciones del robot
//   POST /generar  → { periodo, correo, forzar, sinMail, clave }
//   POST /borrar   → { periodo, clave }

const WORKFLOW = "robot.yml";
const RE_PERIODO = /^\d{4}_T[1-4]$/;
const RE_CORREO = /^[^@\s,]+@[^@\s,]+\.[^@\s,]+$/;

export default {
  async fetch(req, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ORIGEN || "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
      "Vary": "Origin",
    };
    const responder = (cuerpo, status = 200) =>
      new Response(JSON.stringify(cuerpo), { status, headers: { ...cors, "Content-Type": "application/json; charset=utf-8" } });

    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const github = (ruta, init = {}) =>
      fetch(`https://api.github.com/repos/${env.REPO}/actions/workflows/${WORKFLOW}${ruta}`, {
        ...init,
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "User-Agent": "enoe-jalisco-worker",
          ...(init.body ? { "Content-Type": "application/json" } : {}),
        },
      });

    const { pathname } = new URL(req.url);

    // ── Estado ──────────────────────────────────────────────────────────────
    if (req.method === "GET" && pathname === "/estado") {
      const r = await github("/runs?per_page=6");
      if (!r.ok) return responder({ error: "No se pudo consultar GitHub." }, 502);
      const { workflow_runs } = await r.json();
      return responder({
        ejecuciones: workflow_runs.map((x) => ({
          evento: x.event, estado: x.status, resultado: x.conclusion, creada: x.created_at, url: x.html_url,
        })),
      });
    }

    // ── Generar / borrar ────────────────────────────────────────────────────
    if (req.method === "POST" && (pathname === "/generar" || pathname === "/borrar")) {
      let d;
      try { d = await req.json(); } catch { return responder({ error: "Solicitud inválida." }, 400); }

      if (!env.CLAVE || String(d.clave || "") !== env.CLAVE) {
        await new Promise((r) => setTimeout(r, 1000));          // frena intentos repetidos
        return responder({ error: "Clave incorrecta." }, 401);
      }
      const periodo = String(d.periodo || "").trim();
      if (periodo && !RE_PERIODO.test(periodo)) return responder({ error: "Trimestre inválido (formato AAAA_T#)." }, 400);

      let inputs;
      if (pathname === "/borrar") {
        if (!periodo) return responder({ error: "Falta el trimestre a borrar." }, 400);
        inputs = { borrar: periodo };
      } else {
        const correos = String(d.correo || "").split(",").map((c) => c.trim()).filter(Boolean);
        if (correos.length > 5) return responder({ error: "Máximo 5 correos." }, 400);
        if (!correos.every((c) => RE_CORREO.test(c))) return responder({ error: "Revisa el correo: parece tener un error." }, 400);
        inputs = { periodo, forzar: String(Boolean(d.forzar)), sin_email: String(Boolean(d.sinMail)), destinatario: correos.join(",") };
      }

      const desde = new Date().toISOString();
      const r = await github("/dispatches", { method: "POST", body: JSON.stringify({ ref: "main", inputs }) });
      if (!r.ok) return responder({ error: `GitHub rechazó la solicitud (${r.status}).` }, 502);
      return responder({ ok: true, desde });
    }

    return responder({ error: "Ruta no encontrada." }, 404);
  },
};
