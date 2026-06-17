#!/usr/bin/env python3
"""
SERVIDOR RENDER — VICTOR GALAN: LA COMUNIDAD
─────────────────────────────────────────────
Cron 1: Cada día a las 8:00 Madrid → genera dashboard + sube a GitHub Pages
Cron 2: Cada minuto en horario mercado → comprueba alertas de precio
Cron 3: Lunes 9:00 Madrid → email resumen semanal via Resend

Variables de entorno necesarias en Render:
  GITHUB_TOKEN       → ghp_...
  GITHUB_USER        → victorgbolsa
  GITHUB_REPO        → LaComunidad
  RESEND_API_KEY     → re_...
  RESEND_FROM        → noreply@tudominio.com  (o el sandbox de Resend)
  SUPABASE_URL       → https://othghdtplmlkrqwfcjzk.supabase.co
  SUPABASE_KEY       → tu service_role key de Supabase
"""

import os, sys, json, base64, time, logging
from datetime import datetime, timezone
import pytz
import requests
from flask import Flask, jsonify

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

# ── Variables de entorno ──────────────────────────────────────────────────────
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER   = os.environ.get("GITHUB_USER", "victorgbolsa")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "LaComunidad")
RESEND_KEY    = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM   = os.environ.get("RESEND_FROM", "")
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "https://othghdtplmlkrqwfcjzk.supabase.co")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")  # service_role key

MADRID = pytz.timezone("Europe/Madrid")

# ══════════════════════════════════════════════════════════════════════════════
#  1. GITHUB UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_github(html_content: str) -> bool:
    """Sube index.html a GitHub Pages via API."""
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN no configurado")
        return False

    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/index.html"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LaComunidad-Server"
    }

    # Obtener SHA actual del archivo (necesario para actualizar)
    sha = None
    r = requests.get(api_url, headers=headers, timeout=30)
    if r.status_code == 200:
        sha = r.json().get("sha")
        log.info(f"SHA actual de index.html: {sha[:8]}...")
    elif r.status_code == 404:
        log.info("index.html no existe aún, se creará nuevo")
    else:
        log.error(f"Error obteniendo SHA: {r.status_code} {r.text[:200]}")
        return False

    # Preparar payload
    content_b64 = base64.b64encode(html_content.encode("utf-8")).decode("utf-8")
    ts_madrid = datetime.now(MADRID).strftime("%d/%m/%Y %H:%M")
    payload = {
        "message": f"Dashboard actualizado {ts_madrid}",
        "content": content_b64,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha

    # Subir
    r = requests.put(api_url, headers=headers, json=payload, timeout=60)
    if r.status_code in (200, 201):
        log.info(f"✓ index.html subido a GitHub correctamente")
        return True
    else:
        log.error(f"Error subiendo a GitHub: {r.status_code} {r.text[:300]}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  2. GENERAR DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def run_market_tracker() -> str | None:
    """Ejecuta market_tracker.py y devuelve el HTML generado."""
    import importlib.util, pathlib

    script_path = pathlib.Path(__file__).parent / "market_tracker.py"
    if not script_path.exists():
        log.error(f"No se encuentra market_tracker.py en {script_path}")
        return None

    log.info("▶ Iniciando generación del dashboard...")

    try:
        spec = importlib.util.spec_from_file_location("market_tracker", script_path)
        mod  = importlib.util.module_from_spec(spec)

        # Parchear webbrowser.open para que no falle en servidor
        import webbrowser
        webbrowser.open = lambda *a, **kw: None

        spec.loader.exec_module(mod)

        # Llamar a main() que genera el HTML
        # Capturamos el HTML desde el archivo que escribe el script
        mod.main()

        # Leer el index.html que generó
        idx_path = pathlib.Path(__file__).parent / "index.html"
        if idx_path.exists():
            html = idx_path.read_text(encoding="utf-8")
            log.info(f"✓ HTML generado: {len(html):,} bytes")
            return html
        else:
            log.error("market_tracker.py no generó index.html")
            return None

    except Exception as e:
        log.error(f"Error ejecutando market_tracker: {e}", exc_info=True)
        return None


# ══════════════════════════════════════════════════════════════════════════════
#  3. ALERTAS DE PRECIO
# ══════════════════════════════════════════════════════════════════════════════

def get_alertas_activas() -> list:
    """Obtiene alertas activas de Supabase."""
    if not SUPABASE_KEY:
        return []
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/alertas?activa=eq.true&select=*",
        headers=headers, timeout=15
    )
    if r.status_code == 200:
        return r.json()
    log.error(f"Error obteniendo alertas: {r.status_code}")
    return []


def get_precio_actual(ticker: str) -> float | None:
    """Obtiene precio actual via yfinance."""
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)
        hist = tk.history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        log.warning(f"Error precio {ticker}: {e}")
    return None


def marcar_alerta_disparada(alerta_id: int) -> None:
    """Marca alerta como inactiva en Supabase."""
    if not SUPABASE_KEY:
        return
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/alertas?id=eq.{alerta_id}",
        headers=headers,
        json={"activa": False, "disparada_at": datetime.now(timezone.utc).isoformat()},
        timeout=10
    )


def enviar_push_notificacion(subscription: dict, titulo: str, cuerpo: str) -> None:
    """Envía push notification via Web Push."""
    try:
        from pywebpush import webpush, WebPushException
        VAPID_PRIVATE = os.environ.get("VAPID_PRIVATE_KEY", "")
        VAPID_EMAIL   = os.environ.get("VAPID_EMAIL", "admin@lacomunidad.com")
        if not VAPID_PRIVATE:
            return
        webpush(
            subscription_info=subscription,
            data=json.dumps({"title": titulo, "body": cuerpo}),
            vapid_private_key=VAPID_PRIVATE,
            vapid_claims={"sub": f"mailto:{VAPID_EMAIL}"}
        )
    except Exception as e:
        log.warning(f"Error push: {e}")


def get_subscripciones_usuario(user_id: str) -> list:
    """Obtiene subscripciones push de un usuario."""
    if not SUPABASE_KEY:
        return []
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions?user_id=eq.{user_id}&select=subscription",
        headers=headers, timeout=10
    )
    if r.status_code == 200:
        return [row["subscription"] for row in r.json()]
    return []


def check_alertas() -> dict:
    """Comprueba todas las alertas activas y dispara las que se cumplen."""
    now_madrid = datetime.now(MADRID)
    # Solo en horario de mercado USA: 14:30 - 21:15 Madrid (aprox)
    if not (14 <= now_madrid.hour < 21 or (now_madrid.hour == 21 and now_madrid.minute <= 15)):
        return {"status": "fuera_horario", "hora": now_madrid.strftime("%H:%M")}

    alertas = get_alertas_activas()
    if not alertas:
        return {"status": "ok", "alertas": 0}

    disparadas = 0
    for alerta in alertas:
        ticker    = alerta.get("ticker", "")
        condicion = alerta.get("condicion", "")  # "mayor" o "menor"
        precio_obj = float(alerta.get("precio_objetivo", 0))
        user_id   = alerta.get("user_id", "")

        precio_actual = get_precio_actual(ticker)
        if precio_actual is None:
            continue

        cumplida = (
            (condicion == "mayor" and precio_actual >= precio_obj) or
            (condicion == "menor" and precio_actual <= precio_obj)
        )

        if cumplida:
            log.info(f"🔔 Alerta disparada: {ticker} {condicion} {precio_obj} (actual: {precio_actual})")
            marcar_alerta_disparada(alerta["id"])
            disparadas += 1

            # Push notification
            simbolo = "⬆️" if condicion == "mayor" else "⬇️"
            titulo  = f"{simbolo} Alerta: {ticker}"
            cuerpo  = f"{ticker} ha {'superado' if condicion == 'mayor' else 'bajado de'} {precio_obj:.2f}$ (actual: {precio_actual:.2f}$)"

            for sub in get_subscripciones_usuario(user_id):
                enviar_push_notificacion(sub, titulo, cuerpo)

    return {"status": "ok", "alertas_revisadas": len(alertas), "disparadas": disparadas}


# ══════════════════════════════════════════════════════════════════════════════
#  4. EMAIL SEMANAL
# ══════════════════════════════════════════════════════════════════════════════

def get_todos_los_emails() -> list:
    """Obtiene todos los emails de alumnos desde Supabase profiles."""
    if not SUPABASE_KEY:
        return []
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/profiles?select=email,alias",
        headers=headers, timeout=15
    )
    if r.status_code == 200:
        return r.json()
    log.error(f"Error obteniendo emails: {r.status_code}")
    return []


def get_top_ideas() -> list:
    """Obtiene las top 5 ideas de la semana por votos."""
    if not SUPABASE_KEY:
        return []
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/ideas?select=titulo,votos,ticker&order=votos.desc&limit=5",
        headers=headers, timeout=15
    )
    if r.status_code == 200:
        return r.json()
    return []


def enviar_email_semanal() -> dict:
    """Envía el email resumen semanal a todos los alumnos."""
    if not RESEND_KEY or not RESEND_FROM:
        log.error("RESEND_API_KEY o RESEND_FROM no configurados")
        return {"status": "error", "msg": "Resend no configurado"}

    alumnos  = get_todos_los_emails()
    ideas    = get_top_ideas()
    semana   = datetime.now(MADRID).strftime("Semana del %d de %B de %Y")

    if not alumnos:
        return {"status": "ok", "enviados": 0}

    # Construir lista de top ideas en HTML
    ideas_html = ""
    for i, idea in enumerate(ideas, 1):
        ticker = idea.get("ticker", "")
        titulo = idea.get("titulo", "")
        votos  = idea.get("votos", 0)
        ideas_html += f"""
        <tr>
          <td style="padding:8px;font-weight:bold;color:#1a56db;">#{i}</td>
          <td style="padding:8px;font-weight:bold;">{ticker}</td>
          <td style="padding:8px;">{titulo}</td>
          <td style="padding:8px;color:#6b7280;">⭐ {votos}</td>
        </tr>"""

    html_email = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family:Inter,Arial,sans-serif;background:#f9fafb;margin:0;padding:0;">
      <div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;margin-top:20px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">

        <!-- Header -->
        <div style="background:#1a56db;padding:32px;text-align:center;">
          <h1 style="color:#fff;margin:0;font-size:24px;">📊 Victor Galán: La Comunidad</h1>
          <p style="color:#bfdbfe;margin:8px 0 0;">{semana}</p>
        </div>

        <!-- Cuerpo -->
        <div style="padding:32px;">
          <h2 style="color:#111827;margin-top:0;">¡Hola! 👋</h2>
          <p style="color:#374151;line-height:1.6;">
            Aquí tienes el resumen semanal de <strong>La Comunidad</strong>.
            Accede al dashboard para ver el análisis completo del mercado.
          </p>

          <!-- Botón dashboard -->
          <div style="text-align:center;margin:24px 0;">
            <a href="https://victorgbolsa.github.io/LaComunidad/"
               style="background:#1a56db;color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;">
              Ver Dashboard →
            </a>
          </div>

          <!-- Top ideas -->
          {"<h3 style='color:#111827;'>🏆 Top Ideas de la Comunidad</h3><table style='width:100%;border-collapse:collapse;'><thead><tr style='background:#f3f4f6;'><th style='padding:8px;text-align:left;'>#</th><th style='padding:8px;text-align:left;'>Ticker</th><th style='padding:8px;text-align:left;'>Idea</th><th style='padding:8px;text-align:left;'>Votos</th></tr></thead><tbody>" + ideas_html + "</tbody></table>" if ideas else ""}

          <hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0;">
          <p style="color:#9ca3af;font-size:14px;text-align:center;">
            Este email fue enviado automáticamente cada lunes.<br>
            © Victor Galán · La Comunidad
          </p>
        </div>
      </div>
    </body>
    </html>
    """

    # Enviar a cada alumno
    enviados  = 0
    errores   = 0
    emails_lista = [a["email"] for a in alumnos if a.get("email")]

    # Resend permite hasta 50 destinatarios por llamada — hacemos batches
    BATCH = 50
    for i in range(0, len(emails_lista), BATCH):
        batch = emails_lista[i:i+BATCH]
        payload = {
            "from": RESEND_FROM,
            "to":   batch,
            "subject": f"📊 Resumen semanal — {semana}",
            "html": html_email
        }
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=30
        )
        if r.status_code in (200, 201):
            enviados += len(batch)
            log.info(f"✓ Email enviado a {len(batch)} alumnos (batch {i//BATCH + 1})")
        else:
            errores += len(batch)
            log.error(f"Error enviando batch: {r.status_code} {r.text[:200]}")

    return {"status": "ok", "enviados": enviados, "errores": errores}


# ══════════════════════════════════════════════════════════════════════════════
#  5. ENDPOINTS FLASK (llamados por Render Cron Jobs)
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "servicio": "Victor Galán: La Comunidad — Servidor Render",
        "hora_madrid": datetime.now(MADRID).strftime("%d/%m/%Y %H:%M:%S"),
        "endpoints": {
            "/cron/dashboard": "Genera y sube el dashboard a GitHub Pages",
            "/cron/alertas":   "Comprueba alertas de precio y envía push",
            "/cron/email":     "Envía email resumen semanal"
        }
    })


@app.route("/cron/dashboard")
def cron_dashboard():
    """Genera el dashboard y lo sube a GitHub Pages."""
    log.info("═══ CRON: Generando dashboard ═══")
    start = time.time()

    html = run_market_tracker()
    if not html:
        return jsonify({"status": "error", "msg": "Error generando HTML"}), 500

    ok = upload_to_github(html)
    elapsed = round(time.time() - start, 1)

    if ok:
        log.info(f"✓ Dashboard completado en {elapsed}s")
        return jsonify({"status": "ok", "elapsed_s": elapsed, "html_bytes": len(html)})
    else:
        return jsonify({"status": "error", "msg": "Error subiendo a GitHub"}), 500


@app.route("/cron/alertas")
def cron_alertas():
    """Comprueba alertas de precio."""
    resultado = check_alertas()
    return jsonify(resultado)


@app.route("/cron/email")
def cron_email():
    """Envía email resumen semanal."""
    log.info("═══ CRON: Enviando email semanal ═══")
    resultado = enviar_email_semanal()
    return jsonify(resultado)


# ══════════════════════════════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    log.info(f"Servidor arrancando en puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
