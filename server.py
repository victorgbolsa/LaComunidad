#!/usr/bin/env python3
"""
SERVIDOR RENDER — VICTOR GALAN: LA COMUNIDAD
─────────────────────────────────────────────
Cron 1: Lunes-Viernes 14:00 y 21:00 UTC → genera dashboard + sube a GitHub Pages
Cron 2: Cada minuto en horario mercado → comprueba alertas de precio
Cron 3: Lunes 8:00 UTC → email resumen semanal via Resend
"""

import os, sys, json, base64, time, logging
from datetime import datetime, timezone, timedelta
import pytz
import requests
from flask import Flask, jsonify, request

def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "https://victorgbolsa.github.io"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    # 09/07/2026: se añadió el header Authorization (Bearer token de Supabase)
    # a las llamadas de /snaptrade/* para el fix de seguridad — sin permitirlo
    # aquí, el navegador bloquea la petición en el preflight y da
    # "Failed to fetch" antes de que llegue siquiera al servidor.
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.after_request(add_cors)

@app.route("/snaptrade/connect", methods=["OPTIONS"])
@app.route("/snaptrade/data", methods=["OPTIONS"])
def snaptrade_options():
    return jsonify({})

GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER   = os.environ.get("GITHUB_USER", "victorgbolsa")
GITHUB_REPO   = os.environ.get("GITHUB_REPO", "LaComunidad")
RESEND_KEY    = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM   = os.environ.get("RESEND_FROM", "")
SUPABASE_URL  = os.environ.get("SUPABASE_URL", "https://othghdtplmlkrqwfcjzk.supabase.co")
SUPABASE_KEY  = os.environ.get("SUPABASE_KEY", "")
MADRID        = pytz.timezone("Europe/Madrid")


# ══════════════════════════════════════════════════════════════════════════════
#  SEGURIDAD (08/07/2026) — /snaptrade/connect y /snaptrade/data recibían el
#  user_id directamente del body sin comprobar que quien llama es de verdad
#  ese usuario. Como el user_id es visible para otros alumnos logueados (via
#  ideas/votos), cualquiera podía pedir el userSecret de otra persona y leer
#  sus posiciones reales de broker. Esta función exige el token de sesión de
#  Supabase (Authorization: Bearer ...) y confirma que pertenece al user_id
#  solicitado antes de dejar pasar la petición.
# ══════════════════════════════════════════════════════════════════════════════
def verify_supabase_user(req, expected_user_id):
    """Devuelve True solo si el token de sesión adjunto pertenece de verdad
    a expected_user_id. Cualquier fallo (sin token, token inválido, no
    coincide) devuelve False."""
    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer ") or not expected_user_id:
        return False
    token = auth_header[7:].strip()
    if not token:
        return False
    try:
        r = requests.get(
            f"{SUPABASE_URL}/auth/v1/user",
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if r.status_code != 200:
            return False
        real_user_id = r.json().get("id", "")
        return bool(real_user_id) and real_user_id == expected_user_id
    except Exception as e:
        log.warning(f"verify_supabase_user error: {e}")
        return False


# ══════════════════════════════════════════════════════════════════════════════
#  ENDPOINTS FLASK — definidos primero para que quede claro el mapa de rutas
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Health check — ruta raíz. SOLO devuelve estado, nunca envía emails."""
    return jsonify({
        "status": "ok",
        "servicio": "Victor Galán: La Comunidad",
        "hora_madrid": datetime.now(MADRID).strftime("%d/%m/%Y %H:%M:%S"),
    })


@app.route("/cron/dashboard")
def cron_dashboard():
    """Lanza la generación del dashboard en background."""
    import threading
    log.info("═══ CRON: Lanzando dashboard en background ═══")
    t = threading.Thread(target=_run_dashboard_bg, daemon=True)
    t.start()
    return jsonify({
        "status": "iniciado",
        "hora_madrid": datetime.now(MADRID).strftime("%d/%m/%Y %H:%M:%S")
    })


@app.route("/cron/alertas")
def cron_alertas():
    """Comprueba alertas de precio."""
    resultado = check_alertas()
    return jsonify(resultado)


@app.route("/cron/email")
def cron_email():
    """Envía email semanal — con protección anti-duplicados."""
    log.info("═══ CRON: Solicitud de email semanal ═══")

    # ── CORTAFUEGOS 1: solo lunes ─────────────────────────────────────────
    now_madrid = datetime.now(MADRID)
    # Permitir bypass con ?force=1 solo para pruebas desde IP local
    force = request.args.get("force", "0") == "1"
    test_email = request.args.get("test", "")  # ?test=tu@email.com

    if not force and now_madrid.weekday() != 0:  # 0 = lunes
        log.info(f"Hoy es {now_madrid.strftime('%A')} — email solo se envía los lunes")
        return jsonify({"status": "ok", "enviados": 0, "msg": "No es lunes"})

    # ── CORTAFUEGOS 2: solo una vez por semana (flag en Supabase) ────────
    if not force and not test_email:
        semana_actual = now_madrid.isocalendar()[1]
        año_actual    = now_madrid.year
        if ya_enviado_esta_semana(semana_actual, año_actual):
            log.info(f"Email semana {semana_actual}/{año_actual} ya enviado — omitiendo")
            return jsonify({"status": "ok", "enviados": 0, "msg": "Ya enviado esta semana"})

    resultado = enviar_email_semanal(test_email=test_email)

    # ── Marcar como enviado en Supabase ──────────────────────────────────
    if resultado.get("enviados", 0) > 0 and not test_email and not force:
        marcar_email_enviado(now_madrid.isocalendar()[1], now_madrid.year)

    return jsonify(resultado)


# ══════════════════════════════════════════════════════════════════════════════
#  CORTAFUEGOS — control de envío único semanal
# ══════════════════════════════════════════════════════════════════════════════

def ya_enviado_esta_semana(semana: int, año: int) -> bool:
    """Comprueba en Supabase si el email de esta semana ya fue enviado."""
    if not SUPABASE_KEY:
        return False
    try:
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        r = requests.get(
            f"{SUPABASE_URL}/rest/v1/email_log?semana=eq.{semana}&año=eq.{año}&select=id",
            headers=headers, timeout=10
        )
        if r.status_code == 200:
            return len(r.json()) > 0
    except Exception as e:
        log.warning(f"Error comprobando email_log: {e}")
    return False


def marcar_email_enviado(semana: int, año: int) -> None:
    """Registra en Supabase que el email de esta semana ya fue enviado."""
    if not SUPABASE_KEY:
        return
    try:
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal"
        }
        requests.post(
            f"{SUPABASE_URL}/rest/v1/email_log",
            headers=headers,
            json={"semana": semana, "año": año, "enviado_at": datetime.now(timezone.utc).isoformat()},
            timeout=10
        )
        log.info(f"✓ Email semana {semana}/{año} marcado como enviado")
    except Exception as e:
        log.warning(f"Error marcando email_log: {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  GITHUB UPLOAD
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
    elif r.status_code != 404:
        log.error(f"Error obteniendo SHA: {r.status_code}")
        return False
    content_b64 = base64.b64encode(html_content.encode("utf-8")).decode("utf-8")
    ts_madrid = datetime.now(MADRID).strftime("%d/%m/%Y %H:%M")
    payload = {"message": f"Dashboard actualizado {ts_madrid}", "content": content_b64, "branch": "main"}
    if sha:
        payload["sha"] = sha
    r = requests.put(api_url, headers=headers, json=payload, timeout=60)
    if r.status_code in (200, 201):
        log.info("✓ index.html subido a GitHub correctamente")
        return True
    log.error(f"Error subiendo a GitHub: {r.status_code} {r.text[:300]}")
    return False


# ══════════════════════════════════════════════════════════════════════════════
#  GENERAR DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════

def _run_dashboard_bg():
    import subprocess, pathlib
    log.info("═══ BACKGROUND: Generando dashboard ═══")
    start = time.time()
    script_path = pathlib.Path(__file__).parent / "market_tracker.py"
    if not script_path.exists():
        log.error("No se encuentra market_tracker.py")
        return
    try:
        result = subprocess.run(
            [sys.executable, str(script_path)],
            capture_output=True, text=True, timeout=1200,
            cwd=str(script_path.parent),
            env={**os.environ, "DISPLAY": ""}
        )
        if result.returncode != 0:
            log.error(f"market_tracker.py error:\n{result.stderr[-2000:]}")
        idx_path = pathlib.Path(__file__).parent / "index.html"
        if idx_path.exists():
            html = idx_path.read_text(encoding="utf-8")
            upload_to_github(html)
            log.info(f"✓ Dashboard completado en {round(time.time()-start,1)}s")
        else:
            log.error("market_tracker.py no generó index.html")
    except subprocess.TimeoutExpired:
        log.error("market_tracker.py superó el timeout de 20 minutos")
    except Exception as e:
        log.error(f"Error ejecutando market_tracker: {e}", exc_info=True)


# ══════════════════════════════════════════════════════════════════════════════
#  ALERTAS DE PRECIO
# ══════════════════════════════════════════════════════════════════════════════

def get_alertas_activas() -> list:
    if not SUPABASE_KEY:
        return []
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/alertas?activa=eq.true&select=*",
        headers=headers, timeout=15
    )
    return r.json() if r.status_code == 200 else []


def get_precio_actual(ticker: str) -> float | None:
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period="1d", interval="1m")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        log.warning(f"Error precio {ticker}: {e}")
    return None


def marcar_alerta_disparada(alerta_id: int) -> None:
    if not SUPABASE_KEY:
        return
    headers = {
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal"
    }
    requests.patch(
        f"{SUPABASE_URL}/rest/v1/alertas?id=eq.{alerta_id}",
        headers=headers,
        json={"activa": False, "disparada_at": datetime.now(timezone.utc).isoformat()},
        timeout=10
    )


def enviar_push_notificacion(subscription: dict, titulo: str, cuerpo: str) -> None:
    try:
        from pywebpush import webpush
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
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/push_subscriptions?user_id=eq.{user_id}&select=subscription",
        headers=headers, timeout=10
    )
    return [row["subscription"] for row in r.json()] if r.status_code == 200 else []


def check_alertas() -> dict:
    now_madrid = datetime.now(MADRID)
    if not (14 <= now_madrid.hour < 21 or (now_madrid.hour == 21 and now_madrid.minute <= 15)):
        return {"status": "fuera_horario", "hora": now_madrid.strftime("%H:%M")}
    alertas = get_alertas_activas()
    if not alertas:
        return {"status": "ok", "alertas": 0}
    disparadas = 0
    for alerta in alertas:
        ticker        = alerta.get("ticker", "")
        condicion     = alerta.get("condicion") or alerta.get("direccion", "")
        precio_obj_raw = alerta.get("precio_objetivo") or alerta.get("precio")
        if precio_obj_raw is None or not condicion:
            continue
        precio_obj    = float(precio_obj_raw)
        precio_actual = get_precio_actual(ticker)
        if precio_actual is None:
            continue
        cumplida = (
            (condicion in ("mayor", "above") and precio_actual >= precio_obj) or
            (condicion in ("menor", "below") and precio_actual <= precio_obj)
        )
        if cumplida:
            log.info(f"🔔 Alerta: {ticker} {condicion} {precio_obj} (actual: {precio_actual})")
            marcar_alerta_disparada(alerta["id"])
            disparadas += 1
            es_subida = condicion in ("mayor", "above")
            titulo = f"{'⬆️' if es_subida else '⬇️'} Alerta: {ticker}"
            cuerpo = f"{ticker} ha {'superado' if es_subida else 'bajado de'} {precio_obj:.2f}$ (actual: {precio_actual:.2f}$)"
            for sub in get_subscripciones_usuario(alerta.get("user_id", "")):
                enviar_push_notificacion(sub, titulo, cuerpo)
    return {"status": "ok", "alertas_revisadas": len(alertas), "disparadas": disparadas}


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL SEMANAL — funciones auxiliares
# ══════════════════════════════════════════════════════════════════════════════

def get_todos_los_emails() -> list:
    if not SUPABASE_KEY:
        return []
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/profiles?select=email,nombre",
        headers=headers, timeout=15
    )
    if r.status_code == 200:
        return r.json()
    log.error(f"Error obteniendo emails: {r.status_code}")
    return []


def get_top_ideas() -> list:
    if not SUPABASE_KEY:
        return []
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/ideas?select=titulo,votos,ticker&order=votos.desc&limit=5",
        headers=headers, timeout=15
    )
    return r.json() if r.status_code == 200 else []


def get_ranking_miembros() -> list:
    if not SUPABASE_KEY:
        return []
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/profiles?select=nombre,racha,dias_total&order=racha.desc&limit=10",
        headers=headers, timeout=15
    )
    return r.json() if r.status_code == 200 else []


def get_email_summary() -> dict:
    import pathlib
    path = pathlib.Path(__file__).parent / "email_summary.json"
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Error leyendo email_summary.json: {e}")
    return {}


def calcular_semaforos(s: dict) -> list:
    score    = s.get("score", 50)
    pct50    = s.get("pct_abv50", 50)
    vix      = s.get("vix", 20)
    gspc_chg = s.get("gspc_chg", 0)
    rut_chg  = s.get("rut_chg", 0)
    try:
        vix_val = float(vix)
    except (TypeError, ValueError):
        vix_val = 20

    if score >= 65:   tend_dot, tend_val = "dot-green", "Alcista"
    elif score >= 45: tend_dot, tend_val = "dot-amber", "Neutral"
    else:             tend_dot, tend_val = "dot-red",   "Bajista"

    if pct50 >= 60:   amp_dot, amp_val = "dot-green", "Positiva"
    elif pct50 >= 40: amp_dot, amp_val = "dot-amber", "Mixta"
    else:             amp_dot, amp_val = "dot-red",   "Débil"

    diff_rut = rut_chg - gspc_chg
    if diff_rut > 0.5:    sc_dot, sc_val = "dot-green", "Fuerte"
    elif diff_rut > -0.5: sc_dot, sc_val = "dot-amber", "Cautela"
    else:                 sc_dot, sc_val = "dot-red",   "Débil"

    if vix_val < 15:   vix_dot, vix_label = "dot-green", "Calma"
    elif vix_val < 20: vix_dot, vix_label = "dot-blue",  f"{vix_val:.0f} — Normal"
    elif vix_val < 25: vix_dot, vix_label = "dot-amber", f"{vix_val:.0f} — Precaución"
    else:              vix_dot, vix_label = "dot-red",   f"{vix_val:.0f} — Miedo"

    return [
        {"label": "Tendencia",  "dot": tend_dot, "val": tend_val},
        {"label": "Amplitud",   "dot": amp_dot,  "val": amp_val},
        {"label": "Small caps", "dot": sc_dot,   "val": sc_val},
        {"label": "VIX",        "dot": vix_dot,  "val": vix_label},
    ]


def get_datos_mercado_polygon() -> list:
    POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
    if not POLYGON_KEY:
        return []
    import datetime as dt_mod
    end   = dt_mod.date.today()
    start = end - dt_mod.timedelta(days=10)
    mercados_config = [
        ("S&P 500",    "I:SPX",    "ÍNDICES"),
        ("NASDAQ 100", "I:NDX",    "ÍNDICES"),
        ("RUSSELL 2K", "I:RUT",    "ÍNDICES"),
        ("IBEX 35",    "EWP",      "ÍNDICES"),
        ("DAX",        "EWG",      "ÍNDICES"),
        ("BITCOIN",    "X:BTCUSD", "MACRO"),
        ("ORO (XAU)",  "GLD",      "MACRO"),
        ("PLATA (XAG)","SLV",      "MACRO"),
        ("VIX",        "I:VIX",    "MACRO"),
        ("BONO 10Y",   "IEF",      "MACRO"),
    ]
    resultado = []
    for nombre, ticker, seccion in mercados_config:
        try:
            r = requests.get(
                f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                params={"apiKey": POLYGON_KEY, "sort": "asc", "limit": 10}, timeout=10
            )
            if r.status_code != 200:
                continue
            bars = r.json().get("results", [])
            if len(bars) < 2:
                continue
            precio_actual  = bars[-1]["c"]
            precio_hace_5d = bars[-5]["c"] if len(bars) >= 5 else bars[0]["c"]
            pct_semana     = (precio_actual / precio_hace_5d - 1) * 100
            resultado.append({"nombre": nombre, "ticker": ticker, "seccion": seccion,
                               "precio": precio_actual, "pct": pct_semana})
        except Exception as e:
            log.warning(f"Error datos {ticker}: {e}")
    return resultado


def get_sectores_semana() -> dict:
    POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
    if not POLYGON_KEY:
        return {"mejores": [], "peores": []}
    import datetime as dt_mod
    end   = dt_mod.date.today()
    start = end - dt_mod.timedelta(days=10)
    sectores = {
        "XLK":"Tecnología","XLE":"Energía","XLF":"Financiero","XLV":"Salud",
        "XLU":"Utilities","XLRE":"Inmobiliario","XLC":"Comunicación",
        "XLI":"Industriales","XLY":"Consumo discr.","XLP":"Consumo básico","XLB":"Materiales",
    }
    perf = []
    for ticker, nombre in sectores.items():
        try:
            r = requests.get(
                f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}",
                params={"apiKey": POLYGON_KEY, "sort": "asc", "limit": 10}, timeout=8
            )
            if r.status_code != 200:
                continue
            bars = r.json().get("results", [])
            if len(bars) < 2:
                continue
            p_actual = bars[-1]["c"]
            p_base   = bars[-5]["c"] if len(bars) >= 5 else bars[0]["c"]
            perf.append({"nombre": nombre, "sector": ticker, "pct": (p_actual/p_base-1)*100})
        except:
            pass
    perf.sort(key=lambda x: x["pct"], reverse=True)
    return {"mejores": perf[:4], "peores": perf[-4:]}


def get_top_rs_stocks() -> list:
    import pathlib
    email_summ = get_email_summary()
    if email_summ.get("top_rs"):
        return email_summ["top_rs"]
    return [
        {"ticker": "NVDA", "rs": 99, "sector": "Semiconductores", "pct_1w": 0},
        {"ticker": "META", "rs": 97, "sector": "Redes sociales",  "pct_1w": 0},
        {"ticker": "AXON", "rs": 95, "sector": "Defensa / Tech",  "pct_1w": 0},
        {"ticker": "ORCL", "rs": 93, "sector": "Software nube",   "pct_1w": 0},
        {"ticker": "CRWD", "rs": 91, "sector": "Ciberseguridad",  "pct_1w": 0},
        {"ticker": "PLTR", "rs": 89, "sector": "Big Data / IA",   "pct_1w": 0},
    ]


def generar_comentario_ia(datos_mercado: list) -> dict:
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    fallback = {
        "mercados":    "Semana con movimientos diferenciados. La tecnología sigue liderando el avance.",
        "timing":      "La amplitud muestra señales constructivas. Mantener exposición en valores de calidad.",
        "sentimiento": "El VIX en zona de calma. Bitcoin activa el risk-on. Flujos institucionales positivos.",
        "macro":       "Los tipos estables no añaden presión adicional. Oro consolidando cerca de máximos.",
    }
    if not ANTHROPIC_KEY or not datos_mercado:
        return fallback
    resumen = "\n".join([
        f"- {d['nombre']}: {'+' if d['pct']>=0 else ''}{d['pct']:.1f}% semanal (precio: {d['precio']:.2f})"
        for d in datos_mercado
    ])
    prompt = f"""Eres Victor Galán, trader y educador financiero español.
Genera 4 comentarios CORTOS (2-3 frases) en español para el email semanal de La Comunidad,
basados en estos datos reales:

{resumen}

Devuelve SOLO un JSON válido con estas 4 claves:
"mercados", "timing", "sentimiento", "macro"

Sé directo, técnico y accionable."""
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": "claude-sonnet-4-6", "max_tokens": 600,
                  "messages": [{"role": "user", "content": prompt}]},
            timeout=30
        )
        if r.status_code == 200:
            texto = r.json()["content"][0]["text"].replace("```json","").replace("```","").strip()
            return json.loads(texto)
    except Exception as e:
        log.warning(f"Error IA: {e}")
    return fallback


# ══════════════════════════════════════════════════════════════════════════════
#  EMAIL SEMANAL — función principal
# ══════════════════════════════════════════════════════════════════════════════

def enviar_email_semanal(test_email: str = "") -> dict:
    """Genera y envía el email semanal.
    Si test_email está definido, solo envía a esa dirección."""

    if not RESEND_KEY or not RESEND_FROM:
        log.error("RESEND_API_KEY o RESEND_FROM no configurados")
        return {"status": "error", "msg": "Resend no configurado"}

    # Destinatarios
    if test_email:
        emails_lista = [test_email]
        log.info(f"Modo TEST — enviando solo a {test_email}")
    else:
        alumnos = get_todos_los_emails()
        if not alumnos:
            log.warning("No hay alumnos en profiles")
            return {"status": "ok", "enviados": 0}
        emails_lista = [a["email"] for a in alumnos if a.get("email")]

    if not emails_lista:
        return {"status": "ok", "enviados": 0}

    log.info(f"Preparando email para {len(emails_lista)} destinatarios...")

    # Fechas
    now_madrid = datetime.now(MADRID)
    lunes      = now_madrid - timedelta(days=now_madrid.weekday())
    viernes    = lunes + timedelta(days=4)
    semana_str = f"Semana del {lunes.strftime('%d')} al {viernes.strftime('%d de %B de %Y')}"
    edicion    = now_madrid.isocalendar()[1]
    fecha_tt   = viernes.strftime("%d %b %Y").upper()

    # Datos
    log.info("Obteniendo datos de mercado...")
    datos_mercado = get_datos_mercado_polygon()
    sectores      = get_sectores_semana()
    ideas         = get_top_ideas()
    ranking       = get_ranking_miembros()
    email_summ    = get_email_summary()
    semaforos     = calcular_semaforos(email_summ)
    top_rs        = get_top_rs_stocks()

    log.info("Generando comentarios con IA...")
    comentarios = generar_comentario_ia(datos_mercado)

    # HTML helpers
    def tt_row_mercado(d):
        pct = d["pct"]; precio = d["precio"]
        if pct > 0.5:    color, arrow, cls = "#05c46b", "▲", "tt-pct-up"
        elif pct < -0.5: color, arrow, cls = "#ff3f5b", "▼", "tt-pct-dn"
        else:            color, arrow, cls = "#8a96a3", "▶", "tt-pct-neu"
        bar_w   = min(100, abs(pct) * 15)
        pct_str = f"+{pct:.1f}%" if pct > 0 else f"{pct:.1f}%"
        precio_fmt = f"${precio:,.0f}" if precio > 1000 else f"${precio:.2f}" if precio > 10 else f"{precio:.1f}"
        return (f'<div class="tt-row"><span class="tt-name">{d["nombre"]}</span>'
                f'<span class="tt-val">{precio_fmt}</span>'
                f'<div class="tt-bar"><div class="tt-bar-fill" style="width:{bar_w:.0f}%;background:{color};"></div></div>'
                f'<span class="tt-arrow" style="color:{color};">{arrow}</span>'
                f'<span class="{cls}">{pct_str}</span></div>')

    rows_indices = "".join(tt_row_mercado(d) for d in datos_mercado if d["seccion"] == "ÍNDICES")
    rows_macro   = "".join(tt_row_mercado(d) for d in datos_mercado if d["seccion"] == "MACRO")

    def ind_card(item, up=True):
        cls  = "up" if up else "dn"
        bcls = "bup" if up else "bdn"
        pct_str = f"+{item['pct']:.1f}%" if item['pct'] > 0 else f"{item['pct']:.1f}%"
        return (f'<div class="ind-card {cls}"><div><div class="ind-name">{item["nombre"]}</div>'
                f'<div class="ind-sector">{item["sector"]}</div></div>'
                f'<span class="{bcls}">{pct_str}</span></div>')

    mejores_html = "".join(ind_card(i, True)  for i in sectores["mejores"])
    peores_html  = "".join(ind_card(i, False) for i in sectores["peores"])

    def setup_row(s):
        rs = s.get("rs", 80); pct = s.get("pct_1w", 0)
        pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
        return (f'<div class="setup-row"><span class="s-ticker">{s["ticker"]}</span>'
                f'<span class="s-sector">{s.get("sector","")}</span>'
                f'<div class="s-bar-bg"><div class="s-bar-fill" style="width:{rs}%;"></div></div>'
                f'<span class="s-rs">{rs}</span><span class="s-arrow">▲</span>'
                f'<span class="s-pct">{pct_str}</span></div>')

    setups_html   = "".join(setup_row(s) for s in top_rs)
    tv_links_html = "".join(
        f'<a href="https://www.tradingview.com/chart/?symbol=NASDAQ:{s["ticker"]}" class="tv-link">'
        f'<div style="display:flex;align-items:center;gap:8px;"><span>📈</span>'
        f'<div><div class="tv-ticker-l">{s["ticker"]}</div>'
        f'<div class="tv-label-l">{s.get("sector","")} · RS {s.get("rs","")} · '
        f'{("+" if s.get("pct_1w",0)>=0 else "") + str(round(s.get("pct_1w",0),1))}% semana</div>'
        f'</div></div><span class="tv-btn">Ver chart →</span></a>'
        for s in top_rs[:3]
    )

    def idea_card(idea):
        ticker = idea.get("ticker",""); votos = idea.get("votos", 0)
        stars  = "★"*min(5,max(1,round(votos/10))) + "☆"*(5-min(5,max(1,round(votos/10))))
        return (f'<div class="idea-card"><div class="idea-top">'
                f'<span class="idea-ticker">{ticker}</span>'
                f'<div><span class="idea-stars">{stars}</span>'
                f'<span class="idea-votes">{votos} votos</span></div></div>'
                f'<div class="idea-desc">{idea.get("titulo","")}</div>'
                f'<a href="https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}" class="idea-tv-btn">📈 Ver gráfico →</a></div>')

    ideas_html = "".join(idea_card(i) for i in ideas[:3]) if ideas else \
        '<p style="font-size:12px;color:#8a96a3;">No hay ideas esta semana todavía.</p>'

    def rank_row(idx, m):
        nombre = m.get("nombre","?"); racha = m.get("racha", 0)
        medalla  = ["🥇","🥈","🥉"][idx] if idx < 3 else ""
        num_html = f'<span class="rank-medal">{medalla}</span>' if idx < 3 else f'<span class="rank-num">{idx+1}</span>'
        icono    = "🔥" if racha > 20 else "✨" if racha > 10 else "🌱"
        return (f'<div class="rank-row">{num_html}'
                f'<div class="rank-av">{nombre[:2].upper()}</div>'
                f'<span class="rank-name">{nombre}</span>'
                f'<span class="rank-streak">{icono} {racha} días</span></div>')

    ranking_html = "".join(rank_row(i, m) for i, m in enumerate(ranking)) if ranking else \
        '<p style="font-size:12px;color:#8a96a3;">Sin datos de actividad esta semana.</p>'

    semaforos_html = "".join(
        f'<div class="sem-card"><div class="sem-dot {sem["dot"]}"></div>'
        f'<div class="sem-label">{sem["label"]}</div>'
        f'<div class="sem-val">{sem["val"]}</div></div>'
        for sem in semaforos
    )

    html_email = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Syne:wght@700;800&family=Courier+Prime:wght@400;700&display=swap" rel="stylesheet">
<style>
*{{box-sizing:border-box;margin:0;padding:0;}}
.ew{{max-width:600px;margin:0 auto;font-family:'Inter',sans-serif;font-size:13px;color:#3d4a5c;line-height:1.5;background:#f0f2f5;padding:12px;}}
.sec{{background:#fff;border:1px solid #e2e6eb;border-radius:10px;padding:16px 18px;margin-bottom:10px;box-shadow:0 1px 4px rgba(0,0,0,.06);}}
.sec-label{{font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#8a96a3;margin-bottom:14px;display:flex;align-items:center;gap:6px;border-left:3px solid #4f6ef7;padding-left:8px;}}
.divider-label{{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin:12px 0 8px;color:#8a96a3;}}
p{{text-align:justify;}}
.hdr{{background:linear-gradient(135deg,#e8edf7 0%,#edf0f7 50%,#e4eaf5 100%);border:1px solid #d0d8ee;border-radius:12px;padding:28px 24px;margin-bottom:10px;text-align:center;}}
.hdr-eyebrow{{font-size:10px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#4f6ef7;margin-bottom:8px;}}
.hdr-title{{font-family:'Syne',sans-serif;font-weight:800;font-size:22px;color:#1a2332;letter-spacing:-.02em;line-height:1.2;}}
.hdr-sub{{font-size:12px;color:#8a96a3;margin-top:6px;}}
.hdr-pill{{display:inline-block;margin-top:14px;background:rgba(79,110,247,.12);color:#4f6ef7;font-size:11px;font-weight:600;padding:5px 16px;border-radius:99px;border:1px solid rgba(79,110,247,.25);}}
.semaforos{{display:grid;grid-template-columns:repeat(4,1fr);gap:7px;margin-bottom:10px;}}
.sem-card{{background:#fff;border:1px solid #e2e6eb;border-radius:8px;padding:10px 8px;text-align:center;box-shadow:0 1px 3px rgba(0,0,0,.05);}}
.sem-dot{{width:12px;height:12px;border-radius:50%;margin:0 auto 6px;}}
.sem-label{{font-size:10px;font-weight:600;color:#8a96a3;text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px;}}
.sem-val{{font-family:'Syne',sans-serif;font-weight:800;font-size:12px;color:#1a2332;}}
.dot-green{{background:#05c46b;}}.dot-amber{{background:#f59e0b;}}.dot-blue{{background:#4f6ef7;}}.dot-red{{background:#ff3f5b;}}
.bup{{background:rgba(5,196,107,.1);color:#05c46b;display:inline-flex;font-size:11px;font-weight:600;padding:3px 8px;border-radius:99px;}}
.bdn{{background:rgba(255,63,91,.1);color:#ff3f5b;display:inline-flex;font-size:11px;font-weight:600;padding:3px 8px;border-radius:99px;}}
.tt-wrap{{background:#fdfcf8;border:1px solid #e8e4d8;border-radius:8px;padding:14px;font-family:'Courier Prime','Courier New',monospace;}}
.tt-head{{display:flex;justify-content:space-between;border-bottom:2px solid #1a2332;padding-bottom:8px;margin-bottom:10px;}}
.tt-head-title{{font-size:12px;font-weight:700;color:#1a2332;letter-spacing:.05em;}}
.tt-head-sub{{font-size:10px;color:#8a96a3;}}
.tt-section{{font-size:10px;font-weight:700;color:#8a96a3;letter-spacing:.08em;margin:10px 0 5px;border-top:1px dashed #e0dbd0;padding-top:8px;}}
.tt-row{{display:flex;align-items:center;padding:4px 0;border-bottom:1px dotted #e8e4d8;gap:0;}}
.tt-row:last-child{{border-bottom:none;}}
.tt-name{{font-size:12px;font-weight:700;color:#1a2332;width:110px;flex-shrink:0;}}
.tt-val{{font-size:12px;font-weight:700;color:#3d4a5c;width:76px;flex-shrink:0;}}
.tt-bar{{flex:1;height:3px;background:#e8e4d8;border-radius:1px;margin:0 8px;}}
.tt-bar-fill{{height:3px;border-radius:1px;}}
.tt-arrow{{font-size:11px;width:16px;text-align:center;flex-shrink:0;}}
.tt-pct-up{{font-size:12px;font-weight:700;color:#05c46b;width:54px;text-align:right;}}
.tt-pct-dn{{font-size:12px;font-weight:700;color:#ff3f5b;width:54px;text-align:right;}}
.tt-pct-neu{{font-size:12px;font-weight:700;color:#8a96a3;width:54px;text-align:right;}}
.setup-row{{display:flex;align-items:center;padding:5px 0;border-bottom:1px dotted #e8e4d8;gap:6px;}}
.setup-row:last-child{{border-bottom:none;}}
.s-ticker{{font-weight:700;font-size:12px;color:#1a2332;width:44px;flex-shrink:0;}}
.s-sector{{font-size:11px;color:#8a96a3;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}}
.s-bar-bg{{width:56px;height:3px;background:#e8e4d8;border-radius:1px;flex-shrink:0;}}
.s-bar-fill{{height:3px;border-radius:1px;background:#4f6ef7;}}
.s-rs{{font-size:12px;font-weight:700;color:#4f6ef7;width:22px;text-align:right;flex-shrink:0;}}
.s-arrow{{font-size:11px;color:#05c46b;width:14px;text-align:center;flex-shrink:0;}}
.s-pct{{font-size:12px;font-weight:700;color:#05c46b;width:40px;text-align:right;flex-shrink:0;}}
.comment-block{{background:#f7f8fa;border:1px solid #e2e6eb;border-radius:8px;padding:12px 14px;margin-top:10px;}}
.comment-block p{{font-size:12px;color:#3d4a5c;line-height:1.75;text-align:justify;margin-bottom:8px;}}
.comment-block p:last-child{{margin-bottom:0;}}
.mt-block{{background:#f7f8fa;border:1px solid #e2e6eb;border-radius:8px;padding:12px 14px;margin-bottom:8px;}}
.mt-block:last-of-type{{margin-bottom:0;}}
.mt-block-title{{font-family:'Syne',sans-serif;font-weight:800;font-size:11px;color:#1a2332;margin-bottom:5px;}}
.mt-block-txt{{font-size:12px;color:#3d4a5c;line-height:1.75;text-align:justify;}}
.ind-grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px;}}
.ind-card{{border:1px solid #e2e6eb;border-radius:8px;padding:9px 11px;display:flex;justify-content:space-between;align-items:center;background:#fff;}}
.ind-card.up{{border-left:3px solid #05c46b;}}.ind-card.dn{{border-left:3px solid #ff3f5b;}}
.ind-name{{font-size:12px;font-weight:600;color:#1a2332;}}.ind-sector{{font-size:10px;color:#8a96a3;}}
.tv-link{{display:flex;align-items:center;justify-content:space-between;background:#f7f8fa;border:1px solid #e2e6eb;border-radius:7px;padding:8px 12px;margin-top:5px;text-decoration:none;}}
.tv-ticker-l{{font-family:'Courier Prime','Courier New',monospace;font-weight:700;font-size:12px;color:#1a2332;}}
.tv-label-l{{font-size:10px;color:#8a96a3;}}
.tv-btn{{background:rgba(79,110,247,.09);color:#4f6ef7;font-size:10px;font-weight:600;padding:4px 10px;border-radius:6px;border:1px solid rgba(79,110,247,.2);white-space:nowrap;}}
.idea-card{{border:1px solid #e2e6eb;border-radius:8px;padding:12px 14px;margin-bottom:8px;background:#fff;}}
.idea-card:last-child{{margin-bottom:0;}}
.idea-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}}
.idea-ticker{{font-family:'Syne',sans-serif;font-weight:800;font-size:14px;color:#1a2332;}}
.idea-votes{{font-size:11px;color:#8a96a3;}}.idea-stars{{color:#f59e0b;font-size:12px;margin-right:3px;}}
.idea-desc{{font-size:12px;color:#3d4a5c;line-height:1.65;margin-bottom:8px;text-align:justify;}}
.idea-tv-btn{{display:inline-flex;align-items:center;gap:5px;background:rgba(79,110,247,.07);color:#4f6ef7;font-size:11px;font-weight:600;padding:5px 11px;border-radius:6px;border:1px solid rgba(79,110,247,.18);text-decoration:none;}}
.rank-row{{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f0f2f5;}}
.rank-row:last-child{{border-bottom:none;}}
.rank-medal{{font-size:13px;width:18px;text-align:center;flex-shrink:0;}}
.rank-num{{font-size:11px;font-weight:700;color:#8a96a3;width:18px;text-align:center;flex-shrink:0;}}
.rank-av{{width:24px;height:24px;border-radius:50%;background:rgba(79,110,247,.1);color:#4f6ef7;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;flex-shrink:0;border:1px solid rgba(79,110,247,.18);}}
.rank-name{{font-weight:600;font-size:12px;color:#1a2332;flex:1;}}
.rank-streak{{font-size:11px;color:#8a96a3;}}
.cta{{display:block;text-align:center;background:#4f6ef7;color:#fff;padding:14px;border-radius:10px;font-family:'Syne',sans-serif;font-weight:800;font-size:14px;text-decoration:none;letter-spacing:-.01em;margin-bottom:10px;}}
.footer{{text-align:center;font-size:11px;color:#8a96a3;padding:6px 0 4px;}}
</style></head>
<body style="background:#f0f2f5;"><div class="ew">
<div class="hdr">
  <div class="hdr-eyebrow">Victor Galán · La Comunidad</div>
  <div class="hdr-title">Resumen semanal<br>del mercado</div>
  <div class="hdr-sub">{semana_str}</div>
  <div class="hdr-pill">Edición #{edicion}</div>
</div>
<div class="semaforos">{semaforos_html}</div>
<div class="sec">
  <div class="sec-label">📊 Mercados de la semana</div>
  <div class="tt-wrap">
    <div class="tt-head"><span class="tt-head-title">MERCADOS · CIERRE SEMANAL</span><span class="tt-head-sub">{fecha_tt}</span></div>
    <div class="tt-section">ÍNDICES</div>{rows_indices}
    <div class="tt-section">MACRO &amp; ALTERNATIVOS</div>{rows_macro}
  </div>
  <div class="comment-block"><p>{comentarios.get("mercados","")}</p></div>
</div>
<div class="sec">
  <div class="sec-label">⚡ Market timing</div>
  <div class="mt-block"><div class="mt-block-title">Amplitud de mercado</div><div class="mt-block-txt">{comentarios.get("timing","")}</div></div>
  <div class="mt-block"><div class="mt-block-title">Sentimiento &amp; Flujos</div><div class="mt-block-txt">{comentarios.get("sentimiento","")}</div></div>
  <div class="mt-block"><div class="mt-block-title">Macro de la semana</div><div class="mt-block-txt">{comentarios.get("macro","")}</div></div>
</div>
<div class="sec">
  <div class="sec-label">🏭 Industrias de la semana</div>
  <div class="divider-label" style="color:#05c46b;">4 mejores</div>
  <div class="ind-grid" style="margin-bottom:12px;">{mejores_html}</div>
  <div class="divider-label" style="color:#ff3f5b;">4 peores</div>
  <div class="ind-grid">{peores_html}</div>
</div>
<div class="sec">
  <div class="sec-label">⭐ Líderes por RS — setups destacados</div>
  <div class="tt-wrap">
    <div class="tt-head"><span class="tt-head-title">LÍDERES · FUERZA RELATIVA</span><span class="tt-head-sub">SEMANA {fecha_tt}</span></div>
    {setups_html}
  </div>
  <div class="divider-label" style="margin-top:12px;">Ver gráficos en TradingView</div>
  {tv_links_html}
</div>
<div class="sec"><div class="sec-label">💡 Ideas más votadas de la comunidad</div>{ideas_html}</div>
<div class="sec"><div class="sec-label">🏆 Top 10 miembros más activos</div>{ranking_html}</div>
<a href="https://victorgbolsa.github.io/LaComunidad/" class="cta">Abrir el dashboard completo →</a>
<div class="footer">© Victor Galán · La Comunidad &nbsp;·&nbsp; <a href="#" style="color:#8a96a3;">Darse de baja</a></div>
</div></body></html>"""

    # Envío
    enviados = 0
    errores  = 0
    BATCH = 50
    for i in range(0, len(emails_lista), BATCH):
        batch = emails_lista[i:i+BATCH]
        r = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={"from": RESEND_FROM, "to": batch,
                  "subject": f"📊 Resumen semanal — {semana_str}", "html": html_email},
            timeout=30
        )
        if r.status_code in (200, 201):
            enviados += len(batch)
            log.info(f"✓ Email enviado a {len(batch)} destinatarios (batch {i//BATCH+1})")
        else:
            errores += len(batch)
            log.error(f"Error batch: {r.status_code} {r.text[:200]}")

    return {"status": "ok", "enviados": enviados, "errores": errores}


# ══════════════════════════════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════════════════════════════

@app.route("/snaptrade/connect", methods=["POST"])
def snaptrade_connect():
    """Genera una URL de conexión de SnapTrade para el usuario."""
    import hmac, hashlib, json as _json, datetime as dt
    from base64 import b64encode
    SNAPTRADE_CLIENT_ID    = os.environ.get("SNAPTRADE_CLIENT_ID", "")
    SNAPTRADE_CONSUMER_KEY = os.environ.get("SNAPTRADE_CONSUMER_KEY", "")
    if not SNAPTRADE_CLIENT_ID or not SNAPTRADE_CONSUMER_KEY:
        return jsonify({"error": "SnapTrade no configurado"}), 500

    body = request.get_json() or {}
    user_id = body.get("user_id", "")
    if not user_id:
        return jsonify({"error": "user_id requerido"}), 400
    if not verify_supabase_user(request, user_id):
        return jsonify({"error": "No autorizado."}), 401

    def snaptrade_request(method, path, req_body=None, extra_query=""):
        """Hace una request autenticada a SnapTrade según la documentación oficial."""
        ts = str(int(dt.datetime.now(timezone.utc).timestamp()))
        query = f"clientId={SNAPTRADE_CLIENT_ID}&timestamp={ts}"
        if extra_query:
            query += f"&{extra_query}"

        # Signature content = JSON con content, path, query (keys ordenadas alfabéticamente)
        sig_obj = {
            "content": req_body,
            "path": path,
            "query": query
        }
        sig_content = _json.dumps(sig_obj, separators=(",", ":"), sort_keys=True)
        sig_digest = hmac.new(
            SNAPTRADE_CONSUMER_KEY.encode(),
            sig_content.encode(),
            hashlib.sha256
        ).digest()
        signature = b64encode(sig_digest).decode()

        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Signature": signature
        }
        url = f"https://api.snaptrade.com{path}?{query}"
        if method == "POST":
            return requests.post(url, headers=headers,
                                 json=req_body if req_body else None, timeout=15)
        else:
            return requests.get(url, headers=headers, timeout=15)

    # 1. Registrar usuario
    reg_r = snaptrade_request("POST", "/api/v1/snapTrade/registerUser", {"userId": user_id})
    log.info(f"SnapTrade registerUser: {reg_r.status_code} {reg_r.text[:200]}")

    if reg_r.status_code == 200:
        user_secret = reg_r.json().get("userSecret", "")
        # Guardar userSecret en Supabase
        if user_secret and SUPABASE_KEY:
            try:
                h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                     "Content-Type": "application/json", "Prefer": "return=minimal"}
                requests.post(f"{SUPABASE_URL}/rest/v1/snaptrade_users",
                              headers=h, json={"user_id": user_id, "user_secret": user_secret},
                              timeout=10)
            except Exception as e:
                log.warning(f"Error guardando userSecret: {e}")
    elif reg_r.status_code in (409, 400) or "already exist" in reg_r.text.lower():
        # Usuario ya existe — recuperar userSecret de Supabase
        log.info(f"Usuario ya existe en SnapTrade, recuperando userSecret de Supabase...")
        user_secret = ""
        if SUPABASE_KEY:
            try:
                h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
                r = requests.get(
                    f"{SUPABASE_URL}/rest/v1/snaptrade_users?user_id=eq.{user_id}&select=user_secret",
                    headers=h, timeout=10)
                log.info(f"Supabase snaptrade_users: {r.status_code} {r.text[:100]}")
                if r.status_code == 200 and r.json():
                    user_secret = r.json()[0].get("user_secret", "")
            except Exception as e:
                log.warning(f"Error recuperando userSecret: {e}")

        if not user_secret:
            # No hay userSecret — usar resetUserSecret para obtener uno nuevo sin borrar el usuario
            log.info("userSecret no encontrado — solicitando resetUserSecret a SnapTrade...")
            reset_extra = f"userId={user_id}&userSecret=placeholder"
            reset_r = snaptrade_request("POST", "/api/v1/snapTrade/resetUserSecret",
                                        {"userId": user_id, "userSecret": "placeholder"},
                                        reset_extra)
            log.info(f"SnapTrade resetUserSecret: {reset_r.status_code} {reset_r.text[:200]}")

            if reset_r.status_code == 200:
                user_secret = reset_r.json().get("userSecret", "")
                if user_secret and SUPABASE_KEY:
                    try:
                        h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                             "Content-Type": "application/json", "Prefer": "return=minimal"}
                        requests.post(f"{SUPABASE_URL}/rest/v1/snaptrade_users",
                                      headers=h, json={"user_id": user_id, "user_secret": user_secret},
                                      timeout=10)
                        log.info("✓ Nuevo userSecret guardado en Supabase")
                    except Exception as e:
                        log.warning(f"Error guardando userSecret: {e}")
            else:
                log.error(f"resetUserSecret falló: {reset_r.status_code} {reset_r.text[:200]}")
                return jsonify({"error": "No se pudo recuperar el acceso a SnapTrade. Contacta con soporte."}), 500
    else:
        log.error(f"SnapTrade registerUser error inesperado: {reg_r.status_code} {reg_r.text}")
        return jsonify({"error": f"Error registrando usuario: {reg_r.text[:200]}"}), 500

    # 2. Generar link de conexión — userId y userSecret en query params adicionales
    extra = f"userId={user_id}&userSecret={user_secret}"
    link_r = snaptrade_request("POST", "/api/v1/snapTrade/login", None, extra)
    log.info(f"SnapTrade login: {link_r.status_code} {link_r.text[:200]}")

    if link_r.status_code == 200:
        return jsonify({"redirectURI": link_r.json().get("redirectURI", ""), "userSecret": user_secret})
    else:
        return jsonify({"error": f"Error generando link: {link_r.text[:100]}"}), 500


@app.route("/snaptrade/data", methods=["POST"])
def snaptrade_data():
    """Obtiene posiciones, historial y equity del usuario desde SnapTrade."""
    import hmac, hashlib, json as _json, datetime as dt
    from base64 import b64encode
    SNAPTRADE_CLIENT_ID    = os.environ.get("SNAPTRADE_CLIENT_ID", "")
    SNAPTRADE_CONSUMER_KEY = os.environ.get("SNAPTRADE_CONSUMER_KEY", "")
    if not SNAPTRADE_CLIENT_ID or not SNAPTRADE_CONSUMER_KEY:
        return jsonify({"error": "SnapTrade no configurado"}), 500

    body = request.get_json() or {}
    user_id     = body.get("user_id", "")
    user_secret = body.get("user_secret", "")
    if not user_id or not user_secret:
        return jsonify({"error": "user_id y user_secret requeridos"}), 400
    if not verify_supabase_user(request, user_id):
        return jsonify({"error": "No autorizado."}), 401

    def snaptrade_get(path, extra_query=""):
        ts = str(int(dt.datetime.now(timezone.utc).timestamp()))
        query = f"clientId={SNAPTRADE_CLIENT_ID}&timestamp={ts}&userId={user_id}&userSecret={user_secret}"
        if extra_query:
            query += f"&{extra_query}"
        sig_obj = {"content": None, "path": path, "query": query}
        sig_content = _json.dumps(sig_obj, separators=(",", ":"), sort_keys=True)
        sig_digest = hmac.new(
            SNAPTRADE_CONSUMER_KEY.encode(), sig_content.encode(), hashlib.sha256
        ).digest()
        signature = b64encode(sig_digest).decode()
        headers = {"Accept": "application/json", "Content-Type": "application/json",
                   "Signature": signature}
        return requests.get(f"https://api.snaptrade.com{path}?{query}",
                            headers=headers, timeout=15)

    result = {}

    # 1. Listar cuentas conectadas para obtener el accountId
    account_id = None
    try:
        r = snaptrade_get("/api/v1/accounts")
        log.info(f"SnapTrade accounts: {r.status_code} {r.text[:200]}")
        if r.status_code == 200:
            accounts = r.json()
            result["accounts"] = accounts
            if accounts:
                account_id = accounts[0].get("id")
    except Exception as e:
        log.warning(f"SnapTrade accounts error: {e}")

    if not account_id:
        log.warning("No se encontró ninguna cuenta conectada en SnapTrade")
        return jsonify(result)

    # 2. Posiciones de la cuenta
    try:
        r = snaptrade_get(f"/api/v1/accounts/{account_id}/positions")
        log.info(f"SnapTrade positions: {r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            result["positions"] = r.json()
    except Exception as e:
        log.warning(f"SnapTrade positions error: {e}")

    # 3. Balances de la cuenta
    try:
        r = snaptrade_get(f"/api/v1/accounts/{account_id}/balances")
        log.info(f"SnapTrade balances: {r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            result["balances"] = r.json()
    except Exception as e:
        log.warning(f"SnapTrade balances error: {e}")

    # 4. Órdenes recientes de la cuenta
    try:
        r = snaptrade_get(f"/api/v1/accounts/{account_id}/orders", "state=all&days=365")
        log.info(f"SnapTrade orders: {r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            result["orders"] = r.json()
    except Exception as e:
        log.warning(f"SnapTrade orders error: {e}")

    # 5. Actividades de la cuenta (depósitos/retiradas) — NUEVO (09/07/2026)
    # Sin esto, la curva de equity confundía aportaciones de capital con
    # rendimiento de trading (p.ej. una transferencia de 53K se veía como
    # una subida del +600%). start_date/end_date cubren el último año.
    try:
        end_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        start_date = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%d")
        r = snaptrade_get(
            f"/api/v1/accounts/{account_id}/activities",
            f"startDate={start_date}&endDate={end_date}"
        )
        log.info(f"SnapTrade activities: {r.status_code} {r.text[:150]}")
        if r.status_code == 200:
            result["activities"] = r.json()
    except Exception as e:
        log.warning(f"SnapTrade activities error: {e}")

    return jsonify(result)



    port = int(os.environ.get("PORT", 10000))
    log.info(f"Servidor arrancando en puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
