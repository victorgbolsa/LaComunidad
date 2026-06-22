#!/usr/bin/env python3
"""
SERVIDOR RENDER — VICTOR GALAN: LA COMUNIDAD
"""

import os, sys, json, base64, time, logging
from datetime import datetime, timezone, timedelta
import pytz
import requests
from flask import Flask, jsonify

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

app = Flask(__name__)

GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER   = os.environ.get("GITHUB_USER", "victorgbolsa")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "LaComunidad")
RESEND_KEY    = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM   = os.environ.get("RESEND_FROM", "")
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "https://othghdtplmlkrqwfcjzk.supabase.co")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")

MADRID = pytz.timezone("Europe/Madrid")

# ══════════════════════════════════════════════════════════════════════════════
#  1. GITHUB UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_to_github(html_content: str) -> bool:
    if not GITHUB_TOKEN:
        log.error("GITHUB_TOKEN no configurado")
        return False
    api_url = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/index.html"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "LaComunidad-Server"
    }
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
    content_b64 = base64.b64encode(html_content.encode("utf-8")).decode("utf-8")
    ts_madrid = datetime.now(MADRID).strftime("%d/%m/%Y %H:%M")
    payload = {
        "message": f"Dashboard actualizado {ts_madrid}",
        "content": content_b64,
        "branch": "main"
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload, timeout=60)
    if r.status_code in (200, 201):
        log.info("✓ index.html subido a GitHub correctamente")
        return True
    else:
        log.error(f"Error subiendo a GitHub: {r.status_code} {r.text[:300]}")
        return False

# ══════════════════════════════════════════════════════════════════════════════
#  2. GENERAR DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def run_market_tracker() -> str | None:
    import subprocess, pathlib
    script_path = pathlib.Path(__file__).parent / "market_tracker.py"
    if not script_path.exists():
        log.error(f"No se encuentra market_tracker.py en {script_path}")
        return None
    log.info("▶ Iniciando generación del dashboard (subprocess)...")
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=1200,
            cwd=str(script_path.parent),
            env={**os.environ, "DISPLAY": ""}
        )
        if result.returncode != 0:
            log.error(f"market_tracker.py terminó con error:\n{result.stderr[-2000:]}")
        else:
            log.info("✓ market_tracker.py completado")
            if result.stdout:
                log.info(result.stdout[-500:])
        idx_path = pathlib.Path(__file__).parent / "index.html"
        if idx_path.exists():
            html = idx_path.read_text(encoding="utf-8")
            log.info(f"✓ HTML generado: {len(html):,} bytes")
            return html
        else:
            log.error("market_tracker.py no generó index.html")
            return None
    except subprocess.TimeoutExpired:
        log.error("market_tracker.py superó el timeout de 20 minutos")
        idx_path = pathlib.Path(__file__).parent / "index.html"
        if idx_path.exists():
            return idx_path.read_text(encoding="utf-8")
        return None
    except Exception as e:
        log.error(f"Error ejecutando market_tracker: {e}", exc_info=True)
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  3. ALERTAS DE PRECIO
# ══════════════════════════════════════════════════════════════════════════════

def get_alertas_activas() -> list:
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
    now_madrid = datetime.now(MADRID)
    if not (14 <= now_madrid.hour < 21 or (now_madrid.hour == 21 and now_madrid.minute <= 15)):
        return {"status": "fuera_horario", "hora": now_madrid.strftime("%H:%M")}
    alertas = get_alertas_activas()
    if not alertas:
        return {"status": "ok", "alertas": 0}
    disparadas = 0
    for alerta in alertas:
        ticker     = alerta.get("ticker", "")
        condicion  = alerta.get("condicion", "")
        precio_obj = float(alerta.get("precio_objetivo", 0))
        user_id    = alerta.get("user_id", "")
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
    import yfinance as yf

    if not RESEND_KEY or not RESEND_FROM:
        log.error("RESEND_API_KEY o RESEND_FROM no configurados")
        return {"status": "error", "msg": "Resend no configurado"}

    alumnos = get_todos_los_emails()
    ideas   = get_top_ideas()
    if not alumnos:
        log.warning("No hay alumnos en profiles — enviados: 0")
        return {"status": "ok", "enviados": 0}

    now_madrid = datetime.now(MADRID)
    # FIX: usar timedelta importado arriba, no __import__
    lunes      = now_madrid - timedelta(days=now_madrid.weekday())
    viernes    = lunes + timedelta(days=4)
    # FIX: variable unificada — antes era semana_str en el HTML pero semana en el subject
    semana_str = f"Semana del {lunes.strftime('%d')} al {viernes.strftime('%d de %B de %Y')}"
    edicion    = now_madrid.isocalendar()[1]
    fecha_tt   = viernes.strftime("%d %b %Y").upper()

    def pct(ticker, period="5d"):
        try:
            h = yf.Ticker(ticker).history(period=period)
            if len(h) >= 2:
                base = h["Close"].iloc[-5] if len(h) >= 5 else h["Close"].iloc[0]
                return (h["Close"].iloc[-1] - base) / base * 100
        except:
            pass
        return None

    mercados = [
        ("S&P 500",    "^GSPC",  "ÍNDICES"),
        ("NASDAQ 100", "^NDX",   "ÍNDICES"),
        ("RUSSELL 2K", "^RUT",   "ÍNDICES"),
        ("IBEX 35",    "^IBEX",  "ÍNDICES"),
        ("DAX",        "^GDAXI", "ÍNDICES"),
        ("BITCOIN",    "BTC-USD","MACRO"),
        ("ORO (XAU)",  "GC=F",   "MACRO"),
        ("PLATA (XAG)","SI=F",   "MACRO"),
        ("VIX",        "^VIX",   "MACRO"),
        ("BONO 10Y",   "^TNX",   "MACRO"),
    ]

    def tt_row(nombre, cambio_pct):
        if cambio_pct is None:
            arrow, color, pct_str = "▶", "#8a96a3", "N/D"
        elif cambio_pct > 0:
            arrow, color, pct_str = "▲", "#05c46b", f"+{cambio_pct:.1f}%"
        elif cambio_pct < 0:
            arrow, color, pct_str = "▼", "#ff3f5b", f"{cambio_pct:.1f}%"
        else:
            arrow, color, pct_str = "▶", "#8a96a3", "0,0%"
        bar_w = min(100, abs(cambio_pct or 0) * 20)
        return f"""
        <tr style="border-bottom:1px dotted #e8e4d8;">
          <td style="font-family:'Courier New',monospace;font-size:12px;font-weight:700;color:#1a2332;padding:4px 0;width:110px;">{nombre}</td>
          <td style="width:60px;padding:4px 6px;">
            <div style="height:3px;background:#e8e4d8;border-radius:1px;">
              <div style="height:3px;width:{bar_w:.0f}%;background:{color};border-radius:1px;"></div>
            </div>
          </td>
          <td style="font-family:'Courier New',monospace;font-size:11px;width:14px;text-align:center;color:{color};">{arrow}</td>
          <td style="font-family:'Courier New',monospace;font-size:12px;font-weight:700;color:{color};text-align:right;padding:4px 0;">{pct_str}</td>
        </tr>"""

    rows_indices = ""
    rows_macro   = ""
    for nombre, ticker_yf, seccion in mercados:
        cambio = pct(ticker_yf)
        row = tt_row(nombre, cambio)
        if seccion == "ÍNDICES":
            rows_indices += row
        else:
            rows_macro += row

    ideas_html = ""
    for idea in ideas[:3]:
        ticker  = idea.get("ticker", "")
        titulo  = idea.get("titulo", "Sin título")
        votos   = idea.get("votos", 0)
        estrellas = "★" * min(5, max(1, round(votos / 10))) + "☆" * (5 - min(5, max(1, round(votos / 10))))
        ideas_html += f"""
        <div style="border:1px solid #e2e6eb;border-radius:8px;padding:12px 14px;margin-bottom:8px;background:#fff;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;">
            <span style="font-family:'Courier New',monospace;font-weight:700;font-size:14px;color:#1a2332;">{ticker}</span>
            <span style="font-size:11px;color:#8a96a3;"><span style="color:#f59e0b;">{estrellas}</span> {votos} votos</span>
          </div>
          <div style="font-size:12px;color:#3d4a5c;line-height:1.65;text-align:justify;margin-bottom:8px;">{titulo}</div>
          <a href="https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}" style="display:inline-flex;align-items:center;gap:5px;background:rgba(79,110,247,.07);color:#4f6ef7;font-size:11px;font-weight:600;padding:5px 11px;border-radius:6px;border:1px solid rgba(79,110,247,.18);text-decoration:none;">📈 Ver gráfico →</a>
        </div>"""

    html_email = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
</head>
<body style="margin:0;padding:12px;background:#f0f2f5;font-family:'Inter',Arial,sans-serif;font-size:13px;color:#3d4a5c;">
<div style="max-width:600px;margin:0 auto;">

  <div style="background:linear-gradient(135deg,#e8edf7 0%,#edf0f7 50%,#e4eaf5 100%);border:1px solid #d0d8ee;border-radius:12px;padding:28px 24px;margin-bottom:10px;text-align:center;">
    <div style="font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#4f6ef7;margin-bottom:8px;">Victor Galán · La Comunidad</div>
    <div style="font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:22px;color:#1a2332;line-height:1.2;">Resumen semanal<br>del mercado</div>
    <div style="font-size:12px;color:#8a96a3;margin-top:6px;">{semana_str}</div>
    <div style="display:inline-block;margin-top:14px;background:rgba(79,110,247,.12);color:#4f6ef7;font-size:11px;font-weight:600;padding:5px 16px;border-radius:99px;border:1px solid rgba(79,110,247,.25);">Edición #{edicion}</div>
  </div>

  <table width="100%" cellpadding="0" cellspacing="7" style="margin-bottom:10px;">
    <tr>
      <td style="background:#fff;border:1px solid #e2e6eb;border-radius:8px;padding:10px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05);">
        <div style="width:12px;height:12px;border-radius:50%;background:#05c46b;margin:0 auto 6px;"></div>
        <div style="font-size:10px;font-weight:600;color:#8a96a3;text-transform:uppercase;letter-spacing:.05em;">Tendencia</div>
        <div style="font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:12px;color:#1a2332;">Alcista</div>
      </td>
      <td style="background:#fff;border:1px solid #e2e6eb;border-radius:8px;padding:10px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05);">
        <div style="width:12px;height:12px;border-radius:50%;background:#05c46b;margin:0 auto 6px;"></div>
        <div style="font-size:10px;font-weight:600;color:#8a96a3;text-transform:uppercase;letter-spacing:.05em;">Amplitud</div>
        <div style="font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:12px;color:#1a2332;">Positiva</div>
      </td>
      <td style="background:#fff;border:1px solid #e2e6eb;border-radius:8px;padding:10px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05);">
        <div style="width:12px;height:12px;border-radius:50%;background:#f59e0b;margin:0 auto 6px;"></div>
        <div style="font-size:10px;font-weight:600;color:#8a96a3;text-transform:uppercase;letter-spacing:.05em;">Small caps</div>
        <div style="font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:12px;color:#1a2332;">Cautela</div>
      </td>
      <td style="background:#fff;border:1px solid #e2e6eb;border-radius:8px;padding:10px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05);">
        <div style="width:12px;height:12px;border-radius:50%;background:#4f6ef7;margin:0 auto 6px;"></div>
        <div style="font-size:10px;font-weight:600;color:#8a96a3;text-transform:uppercase;letter-spacing:.05em;">VIX</div>
        <div style="font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:12px;color:#1a2332;">Calma</div>
      </td>
    </tr>
  </table>

  <div style="background:#fff;border:1px solid #e2e6eb;border-radius:10px;padding:16px 18px;margin-bottom:10px;box-shadow:0 1px 4px rgba(0,0,0,.06);">
    <div style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#8a96a3;margin-bottom:14px;border-left:3px solid #4f6ef7;padding-left:8px;">📊 Mercados de la semana</div>
    <div style="background:#fdfcf8;border:1px solid #e8e4d8;border-radius:8px;padding:14px;font-family:'Courier New',monospace;">
      <div style="display:flex;justify-content:space-between;border-bottom:2px solid #1a2332;padding-bottom:8px;margin-bottom:10px;">
        <span style="font-size:12px;font-weight:700;color:#1a2332;letter-spacing:.05em;">MERCADOS · CIERRE SEMANAL</span>
        <span style="font-size:10px;color:#8a96a3;">{fecha_tt}</span>
      </div>
      <div style="font-size:10px;font-weight:700;color:#8a96a3;letter-spacing:.08em;margin-bottom:5px;">ÍNDICES</div>
      <table width="100%" cellpadding="0" cellspacing="0">{rows_indices}</table>
      <div style="font-size:10px;font-weight:700;color:#8a96a3;letter-spacing:.08em;margin:10px 0 5px;border-top:1px dashed #e0dbd0;padding-top:8px;">MACRO &amp; ALTERNATIVOS</div>
      <table width="100%" cellpadding="0" cellspacing="0">{rows_macro}</table>
    </div>
    <div style="background:#f7f8fa;border:1px solid #e2e6eb;border-radius:8px;padding:12px 14px;margin-top:10px;">
      <div style="font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:11px;color:#1a2332;margin-bottom:6px;">Comentario de la semana</div>
      <p style="font-size:12px;color:#3d4a5c;line-height:1.75;text-align:justify;margin-bottom:8px;">Semana liderada por tecnología y semiconductores en EEUU. El Nasdaq lidera con claridad mientras el Russell 2000 rezaga — el dinero sigue concentrado en large caps de calidad.</p>
      <p style="font-size:12px;color:#3d4a5c;line-height:1.75;text-align:justify;margin:0;">Europa flojea relativamente. Bitcoin con fuerte movimiento semanal activa el modo risk-on. El VIX en mínimos confirma la calma reinante en el mercado.</p>
    </div>
  </div>

  <div style="background:#fff;border:1px solid #e2e6eb;border-radius:10px;padding:16px 18px;margin-bottom:10px;box-shadow:0 1px 4px rgba(0,0,0,.06);">
    <div style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#8a96a3;margin-bottom:14px;border-left:3px solid #4f6ef7;padding-left:8px;">💡 Ideas más votadas de la comunidad</div>
    {ideas_html if ideas_html else '<p style="font-size:12px;color:#8a96a3;">No hay ideas esta semana todavía.</p>'}
  </div>

  <div style="background:#fff;border:1px solid #e2e6eb;border-radius:10px;padding:16px 18px;margin-bottom:10px;box-shadow:0 1px 4px rgba(0,0,0,.06);">
    <div style="font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#8a96a3;margin-bottom:10px;border-left:3px solid #4f6ef7;padding-left:8px;">👀 Watchlist de la semana</div>
    <p style="font-size:12px;color:#3d4a5c;line-height:1.7;text-align:justify;margin-bottom:10px;">Estas son las empresas con mejor aspecto técnico esta semana. <strong style="color:#1a2332;">Cópialas en TradingView y cuéntanos en la comunidad qué te parecen.</strong></p>
    <p style="font-family:'Courier New',monospace;font-size:12px;color:#3d4a5c;line-height:2;">
      NVDA &nbsp;·&nbsp; META &nbsp;·&nbsp; CELH &nbsp;·&nbsp; AXON &nbsp;·&nbsp; CRWD &nbsp;·&nbsp; ASML &nbsp;·&nbsp;
      ORCL &nbsp;·&nbsp; AMD &nbsp;·&nbsp; MSFT &nbsp;·&nbsp; TSLA &nbsp;·&nbsp; PLTR &nbsp;·&nbsp; APP &nbsp;·&nbsp;
      MELI &nbsp;·&nbsp; SPOT &nbsp;·&nbsp; TTD &nbsp;·&nbsp; DDOG &nbsp;·&nbsp; NET &nbsp;·&nbsp; ANET
    </p>
  </div>

  <a href="https://victorgbolsa.github.io/LaComunidad/" style="display:block;text-align:center;background:#4f6ef7;color:#fff;padding:14px;border-radius:10px;font-family:'Syne',Arial,sans-serif;font-weight:800;font-size:14px;text-decoration:none;margin-bottom:10px;">Abrir el dashboard completo →</a>

  <div style="text-align:center;font-size:11px;color:#8a96a3;padding:6px 0 4px;">
    © Victor Galán · La Comunidad &nbsp;·&nbsp; <a href="#" style="color:#8a96a3;">Darse de baja</a>
  </div>
</div>
</body>
</html>"""

    enviados = 0
    errores  = 0
    emails_lista = [a["email"] for a in alumnos if a.get("email")]

    BATCH = 50
    for i in range(0, len(emails_lista), BATCH):
        batch = emails_lista[i:i+BATCH]
        payload = {
            "from":    RESEND_FROM,
            "to":      batch,
            # FIX: variable corregida de 'semana' a 'semana_str'
            "subject": f"📊 Resumen semanal — {semana_str}",
            "html":    html_email
        }
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json=payload, timeout=30
        )
        if r.status_code in (200, 201):
            enviados += len(batch)
            log.info(f"✓ Email enviado a {len(batch)} alumnos (batch {i//BATCH + 1})")
        else:
            errores += len(batch)
            log.error(f"Error enviando batch: {r.status_code} {r.text[:200]}")

    return {"status": "ok", "enviados": enviados, "errores": errores}


# ══════════════════════════════════════════════════════════════════════════════
#  5. ENDPOINTS FLASK
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return jsonify({
        "status": "ok",
        "servicio": "Victor Galán: La Comunidad — Servidor Render",
        "hora_madrid": datetime.now(MADRID).strftime("%d/%m/%Y %H:%M:%S"),
    })

def _run_dashboard_bg():
    import threading
    log.info("═══ BACKGROUND: Generando dashboard ═══")
    start = time.time()
    html = run_market_tracker()
    if not html:
        log.error("Error generando HTML en background")
        return
    ok = upload_to_github(html)
    elapsed = round(time.time() - start, 1)
    if ok:
        log.info(f"✓ Dashboard completado en background en {elapsed}s")
    else:
        log.error("Error subiendo a GitHub en background")

@app.route("/cron/dashboard")
def cron_dashboard():
    import threading
    t = threading.Thread(target=_run_dashboard_bg, daemon=True)
    t.start()
    return jsonify({
        "status": "iniciado",
        "msg": "Dashboard generándose en background.",
        "hora_madrid": datetime.now(MADRID).strftime("%d/%m/%Y %H:%M:%S")
    })

@app.route("/cron/alertas")
def cron_alertas():
    resultado = check_alertas()
    return jsonify(resultado)

@app.route("/cron/email")
def cron_email():
    log.info("═══ CRON: Enviando email semanal ═══")
    resultado = enviar_email_semanal()
    return jsonify(resultado)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    log.info(f"Servidor arrancando en puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
