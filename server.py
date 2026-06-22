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
        # Soporta tanto 'condicion' (mayor/menor) como 'direccion' (above/below)
        condicion  = alerta.get("condicion") or alerta.get("direccion", "")
        # precio_objetivo puede venir como precio_objetivo o precio
        precio_obj_raw = alerta.get("precio_objetivo") or alerta.get("precio")
        if precio_obj_raw is None:
            log.warning(f"Alerta {alerta.get('id')} sin precio_objetivo, saltando")
            continue
        precio_obj = float(precio_obj_raw)
        if not condicion:
            log.warning(f"Alerta {alerta.get('id')} sin condicion/direccion, saltando")
            continue
        user_id    = alerta.get("user_id", "")
        precio_actual = get_precio_actual(ticker)
        if precio_actual is None:
            continue
        cumplida = (
            (condicion in ("mayor", "above") and precio_actual >= precio_obj) or
            (condicion in ("menor", "below") and precio_actual <= precio_obj)
        )
        if cumplida:
            log.info(f"🔔 Alerta disparada: {ticker} {condicion} {precio_obj} (actual: {precio_actual})")
            marcar_alerta_disparada(alerta["id"])
            disparadas += 1
            es_subida = condicion in ("mayor", "above")
            simbolo = "⬆️" if es_subida else "⬇️"
            titulo  = f"{simbolo} Alerta: {ticker}"
            cuerpo  = f"{ticker} ha {'superado' if es_subida else 'bajado de'} {precio_obj:.2f}$ (actual: {precio_actual:.2f}$)"
            for sub in get_subscripciones_usuario(user_id):
                enviar_push_notificacion(sub, titulo, cuerpo)
    return {"status": "ok", "alertas_revisadas": len(alertas), "disparadas": disparadas}

# ══════════════════════════════════════════════════════════════════════════════
#  4. EMAIL SEMANAL
# ══════════════════════════════════════════════════════════════════════════════

def get_email_summary() -> dict:
    """Lee el email_summary.json generado por el cron de dashboard."""
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
    """Calcula los 4 semáforos dinámicamente a partir del email_summary."""
    score    = s.get("score", 50)
    pct50    = s.get("pct_abv50", 50)
    vix      = s.get("vix", 20)
    gspc_chg = s.get("gspc_chg", 0)
    rut_chg  = s.get("rut_chg", 0)
    try:
        vix_val = float(vix)
    except (TypeError, ValueError):
        vix_val = 20

    # Tendencia: score del mercado
    if score >= 65:
        tend_dot, tend_val = "dot-green", "Alcista"
    elif score >= 45:
        tend_dot, tend_val = "dot-amber", "Neutral"
    else:
        tend_dot, tend_val = "dot-red",   "Bajista"

    # Amplitud: % sobre MA50
    if pct50 >= 60:
        amp_dot, amp_val = "dot-green", "Positiva"
    elif pct50 >= 40:
        amp_dot, amp_val = "dot-amber", "Mixta"
    else:
        amp_dot, amp_val = "dot-red",   "Débil"

    # Small caps: Russell vs S&P 500
    diff_rut = rut_chg - gspc_chg
    if diff_rut > 0.5:
        sc_dot, sc_val = "dot-green", "Fuerte"
    elif diff_rut > -0.5:
        sc_dot, sc_val = "dot-amber", "Cautela"
    else:
        sc_dot, sc_val = "dot-red",   "Débil"

    # VIX
    if vix_val < 15:
        vix_dot, vix_label = "dot-green", "Calma"
    elif vix_val < 20:
        vix_dot, vix_label = "dot-blue",  f"{vix_val:.0f} — Normal"
    elif vix_val < 25:
        vix_dot, vix_label = "dot-amber", f"{vix_val:.0f} — Precaución"
    else:
        vix_dot, vix_label = "dot-red",   f"{vix_val:.0f} — Miedo"

    return [
        {"label": "Tendencia",  "dot": tend_dot, "val": tend_val},
        {"label": "Amplitud",   "dot": amp_dot,  "val": amp_val},
        {"label": "Small caps", "dot": sc_dot,   "val": sc_val},
        {"label": "VIX",        "dot": vix_dot,  "val": vix_label},
    ]


def get_ranking_miembros() -> list:
    """Top 10 miembros por racha + dias_total desde Supabase profiles."""
    if not SUPABASE_KEY:
        return []
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/profiles?select=nombre,racha,dias_total&order=racha.desc&limit=10",
        headers=headers, timeout=15
    )
    if r.status_code == 200:
        return r.json()
    return []


def get_datos_mercado_polygon() -> dict:
    """Obtiene datos semanales de los índices principales desde Polygon."""
    POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
    if not POLYGON_KEY:
        return {}

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
    import datetime as dt_mod
    end = dt_mod.date.today()
    start = end - dt_mod.timedelta(days=10)

    for nombre, ticker, seccion in mercados_config:
        try:
            url = f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/{start}/{end}"
            r = requests.get(url, params={"apiKey": POLYGON_KEY, "sort": "asc", "limit": 10}, timeout=10)
            if r.status_code != 200:
                continue
            bars = r.json().get("results", [])
            if len(bars) < 2:
                continue
            precio_actual = bars[-1]["c"]
            precio_hace_5d = bars[-5]["c"] if len(bars) >= 5 else bars[0]["c"]
            pct_semana = (precio_actual / precio_hace_5d - 1) * 100
            resultado.append({
                "nombre": nombre, "ticker": ticker, "seccion": seccion,
                "precio": precio_actual, "pct": pct_semana
            })
        except Exception as e:
            log.warning(f"Error datos {ticker}: {e}")

    return resultado


def get_sectores_semana() -> dict:
    """Obtiene top 4 mejores y 4 peores sectores de la semana desde Polygon."""
    POLYGON_KEY = os.environ.get("POLYGON_API_KEY", "")
    if not POLYGON_KEY:
        return {"mejores": [], "peores": []}

    sectores = {
        "XLK": "Tecnología", "XLE": "Energía", "XLF": "Financiero",
        "XLV": "Salud", "XLU": "Utilities", "XLRE": "Inmobiliario",
        "XLC": "Comunicación", "XLI": "Industriales", "XLY": "Consumo discr.",
        "XLP": "Consumo básico", "XLB": "Materiales",
    }

    import datetime as dt_mod
    end = dt_mod.date.today()
    start = end - dt_mod.timedelta(days=10)
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
            p_base = bars[-5]["c"] if len(bars) >= 5 else bars[0]["c"]
            pct = (p_actual / p_base - 1) * 100
            perf.append({"nombre": nombre, "sector": ticker, "pct": pct})
        except:
            pass

    perf.sort(key=lambda x: x["pct"], reverse=True)
    return {"mejores": perf[:4], "peores": perf[-4:]}


def get_top_rs_stocks() -> list:
    """Obtiene top 6 acciones por RS del scanner (desde el JSON del dashboard si existe)."""
    # Intenta leer del JSON generado por el cron de dashboard
    import pathlib
    json_path = pathlib.Path(__file__).parent / "dashboard_data.json"
    if json_path.exists():
        try:
            with open(json_path) as f:
                data = json.load(f)
            stocks = data.get("stockPerf", {})
            ranked = sorted(
                [(tk, v) for tk, v in stocks.items() if v.get("rs") and v.get("price", 0) > 5],
                key=lambda x: x[1]["rs"], reverse=True
            )[:6]
            return [{"ticker": tk, "rs": v["rs"], "pct_1w": v.get("1W", 0)} for tk, v in ranked]
        except:
            pass
    # Fallback: lista estática
    return [
        {"ticker": "NVDA", "rs": 99, "sector": "Semiconductores", "pct_1w": 0},
        {"ticker": "META", "rs": 97, "sector": "Redes sociales",  "pct_1w": 0},
        {"ticker": "AXON", "rs": 95, "sector": "Defensa / Tech",  "pct_1w": 0},
        {"ticker": "ORCL", "rs": 93, "sector": "Software nube",   "pct_1w": 0},
        {"ticker": "CRWD", "rs": 91, "sector": "Ciberseguridad",  "pct_1w": 0},
        {"ticker": "PLTR", "rs": 89, "sector": "Big Data / IA",   "pct_1w": 0},
    ]


def generar_comentario_ia(datos_mercado: list) -> dict:
    """Genera comentarios dinámicos con Claude API basados en los datos reales."""
    ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    if not ANTHROPIC_KEY:
        return {
            "mercados": "Semana mixta en los mercados globales con movimientos diferenciados por regiones.",
            "timing": "La amplitud de mercado muestra señales constructivas. Mantener posiciones en tendencia.",
            "sentimiento": "El VIX en zona neutral. Flujos institucionales positivos hacia sectores growth.",
            "macro": "Los tipos de interés siguen siendo el factor clave a vigilar en las próximas semanas.",
        }

    resumen = "\n".join([
        f"- {d['nombre']}: {'+' if d['pct']>=0 else ''}{d['pct']:.1f}% semanal (precio: {d['precio']:.2f})"
        for d in datos_mercado
    ])

    prompt = f"""Eres Victor Galán, trader y educador financiero español. 
Genera 4 comentarios CORTOS y directos (2-3 frases cada uno) en español para el email semanal 
de La Comunidad, basados en estos datos reales de mercado:

{resumen}

Devuelve SOLO un JSON válido con exactamente estas 4 claves:
- "mercados": comentario sobre el comportamiento de índices esta semana
- "timing": comentario sobre amplitud y salud interna del mercado
- "sentimiento": comentario sobre VIX, Bitcoin y apetito de riesgo
- "macro": comentario sobre bonos, oro y macro

Sé directo, técnico y accionable. Habla en primera persona del plural (nosotros/la comunidad)."""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 600,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30
        )
        if r.status_code == 200:
            texto = r.json()["content"][0]["text"]
            # Limpiar posibles backticks
            texto = texto.replace("```json", "").replace("```", "").strip()
            return json.loads(texto)
    except Exception as e:
        log.warning(f"Error generando comentario IA: {e}")

    return {
        "mercados": "Semana con movimientos diferenciados. La tecnología sigue liderando el avance.",
        "timing": "La amplitud muestra señales constructivas. Mantener exposición en valores de calidad.",
        "sentimiento": "El VIX en zona de calma. Bitcoin activa el risk-on. Flujos institucionales positivos.",
        "macro": "Los tipos estables no añaden presión adicional. Oro consolidando cerca de máximos.",
    }


def enviar_email_semanal() -> dict:
    if not RESEND_KEY or not RESEND_FROM:
        log.error("RESEND_API_KEY o RESEND_FROM no configurados")
        return {"status": "error", "msg": "Resend no configurado"}

    alumnos = get_todos_los_emails()
    if not alumnos:
        log.warning("No hay alumnos en profiles — enviados: 0")
        return {"status": "ok", "enviados": 0}

    log.info(f"Preparando email para {len(alumnos)} alumnos...")

    # ── Fechas ────────────────────────────────────────────────────────────────
    now_madrid = datetime.now(MADRID)
    lunes      = now_madrid - timedelta(days=now_madrid.weekday())
    viernes    = lunes + timedelta(days=4)
    semana_str = f"Semana del {lunes.strftime('%d')} al {viernes.strftime('%d de %B de %Y')}"
    edicion    = now_madrid.isocalendar()[1]
    fecha_tt   = viernes.strftime("%d %b %Y").upper()

    # ── Datos ─────────────────────────────────────────────────────────────────
    log.info("Obteniendo datos de mercado...")
    datos_mercado = get_datos_mercado_polygon()
    sectores      = get_sectores_semana()
    ideas         = get_top_ideas()
    ranking       = get_ranking_miembros()
    # Leer resumen del dashboard para semáforos dinámicos y top RS reales
    email_summ    = get_email_summary()
    semaforos     = calcular_semaforos(email_summ)
    # Top RS: desde email_summary si existe, sino fallback estático
    top_rs = email_summ.get("top_rs") or get_top_rs_stocks()

    log.info("Generando comentarios con IA...")
    comentarios = generar_comentario_ia(datos_mercado)

    # ── HTML helpers ──────────────────────────────────────────────────────────
    def tt_row_mercado(d):
        pct = d["pct"]
        precio = d["precio"]
        if pct > 0.5:
            color, arrow, cls_pct = "#05c46b", "▲", "tt-pct-up"
        elif pct < -0.5:
            color, arrow, cls_pct = "#ff3f5b", "▼", "tt-pct-dn"
        else:
            color, arrow, cls_pct = "#8a96a3", "▶", "tt-pct-neu"
        bar_w = min(100, abs(pct) * 15)
        pct_str = f"+{pct:.1f}%" if pct > 0 else f"{pct:.1f}%"
        precio_fmt = f"${precio:,.0f}" if precio > 1000 else f"${precio:.2f}" if precio > 10 else f"{precio:.1f}"
        return f"""<div class="tt-row">
  <span class="tt-name">{d['nombre']}</span>
  <span class="tt-val">{precio_fmt}</span>
  <div class="tt-bar"><div class="tt-bar-fill" style="width:{bar_w:.0f}%;background:{color};"></div></div>
  <span class="tt-arrow" style="color:{color};">{arrow}</span>
  <span class="{cls_pct}">{pct_str}</span>
</div>"""

    rows_indices = "".join(tt_row_mercado(d) for d in datos_mercado if d["seccion"] == "ÍNDICES")
    rows_macro   = "".join(tt_row_mercado(d) for d in datos_mercado if d["seccion"] == "MACRO")

    def ind_card(item, up=True):
        cls = "up" if up else "dn"
        badge_cls = "bup" if up else "bdn"
        pct_str = f"+{item['pct']:.1f}%" if item['pct'] > 0 else f"{item['pct']:.1f}%"
        return f"""<div class="ind-card {cls}">
  <div><div class="ind-name">{item['nombre']}</div><div class="ind-sector">{item['sector']}</div></div>
  <span class="{badge_cls}">{pct_str}</span>
</div>"""

    mejores_html = "".join(ind_card(i, True)  for i in sectores["mejores"])
    peores_html  = "".join(ind_card(i, False) for i in sectores["peores"])

    def setup_row(s):
        rs = s.get("rs", 80)
        bar_w = rs
        pct = s.get("pct_1w", 0)
        pct_str = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
        sector = s.get("sector", "")
        return f"""<div class="setup-row">
  <span class="s-ticker">{s['ticker']}</span>
  <span class="s-sector">{sector}</span>
  <div class="s-bar-bg"><div class="s-bar-fill" style="width:{bar_w}%;"></div></div>
  <span class="s-rs">{rs}</span>
  <span class="s-arrow">▲</span>
  <span class="s-pct">{pct_str}</span>
</div>"""

    setups_html = "".join(setup_row(s) for s in top_rs)

    tv_links_html = "".join(f"""<a href="https://www.tradingview.com/chart/?symbol=NASDAQ:{s['ticker']}" class="tv-link">
  <div style="display:flex;align-items:center;gap:8px;"><span style="font-size:14px;">📈</span>
  <div><div class="tv-ticker-l">{s['ticker']}</div>
  <div class="tv-label-l">{s.get('sector','')} · RS {s.get('rs','')} · {('+' if s.get('pct_1w',0)>=0 else '') + str(round(s.get('pct_1w',0),1))}% semana</div></div></div>
  <span class="tv-btn">Ver chart →</span>
</a>""" for s in top_rs[:3])

    def idea_card(idea):
        ticker = idea.get("ticker", "")
        titulo = idea.get("titulo", "Sin título")
        votos  = idea.get("votos", 0)
        stars  = "★" * min(5, max(1, round(votos/10))) + "☆" * (5 - min(5, max(1, round(votos/10))))
        return f"""<div class="idea-card">
  <div class="idea-top"><span class="idea-ticker">{ticker}</span>
  <div><span class="idea-stars">{stars}</span><span class="idea-votes">{votos} votos</span></div></div>
  <div class="idea-desc">{titulo}</div>
  <a href="https://www.tradingview.com/chart/?symbol=NASDAQ:{ticker}" class="idea-tv-btn">📈 Ver gráfico →</a>
</div>"""

    ideas_html = "".join(idea_card(i) for i in ideas[:3]) if ideas else \
        '<p style="font-size:12px;color:#8a96a3;">No hay ideas esta semana todavía.</p>'

    def rank_row(idx, m):
        nombre = m.get("nombre", "?")
        racha  = m.get("racha", 0)
        iniciales = nombre[:2].upper()
        medalla = ["🥇","🥈","🥉"][idx] if idx < 3 else ""
        num_html = f'<span class="rank-medal">{medalla}</span>' if idx < 3 else f'<span class="rank-num">{idx+1}</span>'
        icono = "🔥" if racha > 20 else "✨" if racha > 10 else "🌱"
        return f"""<div class="rank-row">
  {num_html}<div class="rank-av">{iniciales}</div>
  <span class="rank-name">{nombre}</span>
  <span class="rank-streak">{icono} {racha} días</span>
</div>"""

    ranking_html = "".join(rank_row(i, m) for i, m in enumerate(ranking)) if ranking else \
        '<p style="font-size:12px;color:#8a96a3;">Sin datos de actividad esta semana.</p>'

    # ── HTML del email completo ───────────────────────────────────────────────
    html_email = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
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
  .dot-green{{background:#05c46b;}} .dot-amber{{background:#f59e0b;}} .dot-blue{{background:#4f6ef7;}} .dot-red{{background:#ff3f5b;}}
  .bup{{background:rgba(5,196,107,.1);color:#05c46b;display:inline-flex;font-size:11px;font-weight:600;padding:3px 8px;border-radius:99px;}}
  .bdn{{background:rgba(255,63,91,.1);color:#ff3f5b;display:inline-flex;font-size:11px;font-weight:600;padding:3px 8px;border-radius:99px;}}
  .bneu{{background:#eef0f3;color:#6b7280;display:inline-flex;font-size:11px;font-weight:600;padding:3px 8px;border-radius:99px;}}
  .tt-wrap{{background:#fdfcf8;border:1px solid #e8e4d8;border-radius:8px;padding:14px;font-family:'Courier Prime','Courier New',monospace;}}
  .tt-head{{display:flex;justify-content:space-between;border-bottom:2px solid #1a2332;padding-bottom:8px;margin-bottom:10px;}}
  .tt-head-title{{font-size:12px;font-weight:700;color:#1a2332;letter-spacing:.05em;}}
  .tt-head-sub{{font-size:10px;color:#8a96a3;}}
  .tt-section{{font-size:10px;font-weight:700;color:#8a96a3;letter-spacing:.08em;margin:10px 0 5px;border-top:1px dashed #e0dbd0;padding-top:8px;}}
  .tt-section:first-of-type{{border-top:none;padding-top:0;margin-top:0;}}
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
  .mt-pills{{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;}}
  .mt-pill{{font-size:11px;font-weight:600;padding:4px 12px;border-radius:99px;}}
  .ind-grid{{display:grid;grid-template-columns:1fr 1fr;gap:7px;}}
  .ind-card{{border:1px solid #e2e6eb;border-radius:8px;padding:9px 11px;display:flex;justify-content:space-between;align-items:center;background:#fff;}}
  .ind-card.up{{border-left:3px solid #05c46b;}}
  .ind-card.dn{{border-left:3px solid #ff3f5b;}}
  .ind-name{{font-size:12px;font-weight:600;color:#1a2332;}}
  .ind-sector{{font-size:10px;color:#8a96a3;}}
  .tv-link{{display:flex;align-items:center;justify-content:space-between;background:#f7f8fa;border:1px solid #e2e6eb;border-radius:7px;padding:8px 12px;margin-top:5px;text-decoration:none;}}
  .tv-ticker-l{{font-family:'Courier Prime','Courier New',monospace;font-weight:700;font-size:12px;color:#1a2332;}}
  .tv-label-l{{font-size:10px;color:#8a96a3;}}
  .tv-btn{{background:rgba(79,110,247,.09);color:#4f6ef7;font-size:10px;font-weight:600;padding:4px 10px;border-radius:6px;border:1px solid rgba(79,110,247,.2);white-space:nowrap;font-family:'Inter',sans-serif;}}
  .idea-card{{border:1px solid #e2e6eb;border-radius:8px;padding:12px 14px;margin-bottom:8px;background:#fff;}}
  .idea-card:last-child{{margin-bottom:0;}}
  .idea-top{{display:flex;justify-content:space-between;align-items:center;margin-bottom:5px;}}
  .idea-ticker{{font-family:'Syne',sans-serif;font-weight:800;font-size:14px;color:#1a2332;}}
  .idea-votes{{font-size:11px;color:#8a96a3;}}
  .idea-stars{{color:#f59e0b;font-size:12px;margin-right:3px;}}
  .idea-desc{{font-size:12px;color:#3d4a5c;line-height:1.65;margin-bottom:8px;text-align:justify;}}
  .idea-tv-btn{{display:inline-flex;align-items:center;gap:5px;background:rgba(79,110,247,.07);color:#4f6ef7;font-size:11px;font-weight:600;padding:5px 11px;border-radius:6px;border:1px solid rgba(79,110,247,.18);text-decoration:none;}}
  .wl-intro{{font-size:12px;color:#3d4a5c;line-height:1.7;margin-bottom:10px;text-align:justify;}}
  .wl-chips{{display:flex;flex-wrap:wrap;gap:5px;}}
  .wl-chip{{font-family:'Courier Prime','Courier New',monospace;font-weight:700;font-size:12px;color:#3d4a5c;border-bottom:1px solid #d0d8ee;padding:2px 0;margin-right:6px;}}
  .rank-row{{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f0f2f5;}}
  .rank-row:last-child{{border-bottom:none;}}
  .rank-medal{{font-size:13px;width:18px;text-align:center;flex-shrink:0;}}
  .rank-num{{font-size:11px;font-weight:700;color:#8a96a3;width:18px;text-align:center;flex-shrink:0;}}
  .rank-av{{width:24px;height:24px;border-radius:50%;background:rgba(79,110,247,.1);color:#4f6ef7;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;flex-shrink:0;border:1px solid rgba(79,110,247,.18);}}
  .rank-name{{font-weight:600;font-size:12px;color:#1a2332;flex:1;}}
  .rank-streak{{font-size:11px;color:#8a96a3;}}
  .cta{{display:block;text-align:center;background:#4f6ef7;color:#fff;padding:14px;border-radius:10px;font-family:'Syne',sans-serif;font-weight:800;font-size:14px;text-decoration:none;letter-spacing:-.01em;margin-bottom:10px;}}
  .footer{{text-align:center;font-size:11px;color:#8a96a3;padding:6px 0 4px;}}
</style>
</head>
<body style="background:#f0f2f5;">
<div class="ew">

  <div class="hdr">
    <div class="hdr-eyebrow">Victor Galán · La Comunidad</div>
    <div class="hdr-title">Resumen semanal<br>del mercado</div>
    <div class="hdr-sub">{semana_str}</div>
    <div class="hdr-pill">Edición #{edicion}</div>
  </div>

  <div class="semaforos">
    {''.join(f'<div class="sem-card"><div class="sem-dot {sem["dot"]}"></div><div class="sem-label">{sem["label"]}</div><div class="sem-val">{sem["val"]}</div></div>' for sem in semaforos)}
  </div>

  <div class="sec">
    <div class="sec-label">📊 Mercados de la semana</div>
    <div class="tt-wrap">
      <div class="tt-head">
        <span class="tt-head-title">MERCADOS · CIERRE SEMANAL</span>
        <span class="tt-head-sub">{fecha_tt}</span>
      </div>
      <div class="tt-section">ÍNDICES</div>
      {rows_indices}
      <div class="tt-section">MACRO &amp; ALTERNATIVOS</div>
      {rows_macro}
    </div>
    <div class="comment-block">
      <p>{comentarios.get('mercados','')}</p>
    </div>
  </div>

  <div class="sec">
    <div class="sec-label">⚡ Market timing</div>
    <div class="mt-block">
      <div class="mt-block-title">Amplitud de mercado</div>
      <div class="mt-block-txt">{comentarios.get('timing','')}</div>
    </div>
    <div class="mt-block">
      <div class="mt-block-title">Sentimiento &amp; Flujos</div>
      <div class="mt-block-txt">{comentarios.get('sentimiento','')}</div>
    </div>
    <div class="mt-block">
      <div class="mt-block-title">Macro de la semana</div>
      <div class="mt-block-txt">{comentarios.get('macro','')}</div>
    </div>
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
      <div class="tt-head">
        <span class="tt-head-title">LÍDERES · FUERZA RELATIVA</span>
        <span class="tt-head-sub">SEMANA {fecha_tt}</span>
      </div>
      {setups_html}
    </div>
    <div class="divider-label" style="margin-top:12px;">Ver gráficos en TradingView</div>
    {tv_links_html}
  </div>

  <div class="sec">
    <div class="sec-label">💡 Ideas más votadas de la comunidad</div>
    {ideas_html}
  </div>

  <div class="sec">
    <div class="sec-label">🏆 Top 10 miembros más activos</div>
    {ranking_html}
  </div>

  <a href="https://victorgbolsa.github.io/LaComunidad/" class="cta">Abrir el dashboard completo →</a>
  <div class="footer">© Victor Galán · La Comunidad &nbsp;·&nbsp; <a href="#" style="color:#8a96a3;">Darse de baja</a></div>
</div>
</body>
</html>"""

    # ── Envío ─────────────────────────────────────────────────────────────────
    enviados = 0
    errores  = 0
    emails_lista = [a["email"] for a in alumnos if a.get("email")]

    BATCH = 50
    for i in range(0, len(emails_lista), BATCH):
        batch = emails_lista[i:i+BATCH]
        payload = {
            "from":    RESEND_FROM,
            "to":      batch,
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



    if not SUPABASE_KEY:
        return []
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
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
