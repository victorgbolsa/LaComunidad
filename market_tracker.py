#!/usr/bin/env python3
"""
VICTOR GALAN: LA COMUNIDAD
─────────────────────────────────────────────────────────────────────────────
• 11 Sectores + 77 Industrias/Temas con drill-down (acciones + 1Y + MA)
• Benchmarks extendidos: BTC, oro, petróleo, IBEX35, DAX, CAC40...
• Amplitud real: A/D Line proxy, % sobre MA50/MA200, nuevos máx/mín,
  distribución de retornos diarios, score 0-100 estilo "Ofensivo Pleno"
• Noticias de bolsa vía yfinance RSS integrado en el HTML (fetch live)
• Earnings recientes S&P 500: batió/falló expectativas
• Panel individual de acción: precio, técnicos, RS, MA, volumen relativo
─────────────────────────────────────────────────────────────────────────────
Ejecutar:  python market_tracker.py
Requisitos: pip install yfinance pandas requests beautifulsoup4
"""

import os, sys, json, webbrowser, math, time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ══════════════════════════════════════════════════════════════════════════════
#  POLYGON.IO — fuente principal de datos (sustituye yfinance para acciones)
# ══════════════════════════════════════════════════════════════════════════════
POLYGON_KEY  = os.environ.get("POLYGON_API_KEY", "4qgTyqfpFuFbTfQPrL4mTrIA7a8NDi21")
POLYGON_BASE = "https://api.polygon.io"

# ══════════════════════════════════════════════════════════════════════════════
#  SUPABASE — para guardar estado compartido con server.py. market_tracker.py
#  corre en "cron-dashboard" y server.py en "LaComunidad" — son contenedores
#  DISTINTOS en Render, cada uno con su propio disco. Mismo SUPABASE_KEY que
#  ya usa server.py para snaptrade_users.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://othghdtplmlkrqwfcjzk.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

def pg_get(path, params=None, retries=3, timeout=15):
    """GET a Polygon con reintentos suaves para rate-limit (429)."""
    p = dict(params or {})
    p["apiKey"] = POLYGON_KEY
    for attempt in range(retries):
        try:
            r = requests.get(f"{POLYGON_BASE}{path}", params=p, timeout=timeout)
            if r.status_code == 429:
                time.sleep(6)
                continue
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            if attempt == retries - 1:
                return {}
            time.sleep(2)
    return {}

def pg_aggs_daily(ticker, days=400):
    """Equivalente a yf.download para UN ticker: barras diarias OHLCV del ultimo año+."""
    import datetime as _dt
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days)
    data = pg_get(f"/v2/aggs/ticker/{ticker}/range/1/day/{start.isoformat()}/{end.isoformat()}",
                  {"adjusted": "true", "sort": "asc", "limit": 50000})
    results = data.get("results", [])
    if not results:
        return None
    # Polygon devuelve: t=timestamp(ms), o,h,l,c,v
    return [{
        "date": _dt.datetime.utcfromtimestamp(r["t"]/1000).strftime("%Y-%m-%d"),
        "open": r.get("o"), "high": r.get("h"), "low": r.get("l"),
        "close": r.get("c"), "volume": r.get("v"),
    } for r in results]

def pg_fetch_many(tickers, max_workers=10, days=400):
    """Descarga en paralelo (con ThreadPoolExecutor) barras diarias de muchos tickers."""
    out = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(pg_aggs_daily, tk, days): tk for tk in tickers}
        done_count = 0
        for fut in as_completed(futs):
            tk = futs[fut]
            try:
                bars = fut.result()
                if bars:
                    out[tk] = bars
            except Exception:
                pass
            done_count += 1
            if done_count % 200 == 0:
                print(f"    ... {done_count}/{len(tickers)} tickers (Polygon)")
    return out

# ══════════════════════════════════════════════════════════════════════════════
#  AMPLITUD REAL DEL NYSE (03/09/2026) — BUG REAL ENCONTRADO Y CONFIRMADO:
#  el McClellan/AD Line/avanzan-retroceden de más abajo (fetch_breadth_and_
#  amplitude) usaba SOLO 11 ETFs de sector (XLK, XLF...) como aproximación
#  burda de "cuántos suben o bajan" — ni siquiera nuestro universo de ~1.700
#  acciones, muchísimo menos el NYSE completo (~2.700). Por eso nunca
#  coincidía con fuentes oficiales tipo amplitudmercado.com o Tom McClellan.
#
#  Aquí se construye de verdad: se pide a Polygon la lista real de tickers
#  que cotizan en el NYSE (endpoint de referencia, exchange=XNYS), y el
#  "Grouped Daily" (TODO el mercado americano en una sola llamada por día)
#  de los últimos ~270 días naturales (~185-190 sesiones de bolsa) — la
#  misma metodología y universo que usan las fuentes oficiales, no una
#  aproximación nuestra.
# ══════════════════════════════════════════════════════════════════════════════
NYSE_TICKERS_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nyse_tickers_cache.json")
NYSE_TICKERS_CACHE_DIAS = 7  # la lista de que cotiza en el NYSE no cambia a diario
NYSE_TICKERS_CACHE_VERSION = 2  # subir este numero invalida cualquier cache vieja (03/09/2026: se quito el filtro type=CS)

def pg_nyse_active_tickers():
    """Lista de tickers (acciones comunes, activas) cuyo exchange principal es
    el NYSE (XNYS). Se cachea en disco ~7 días — esta lista no cambia cada día,
    pedirla de nuevo en cada cron sería tirar llamadas a Polygon sin necesidad."""
    if os.path.exists(NYSE_TICKERS_CACHE_PATH):
        try:
            with open(NYSE_TICKERS_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            edad_horas = (time.time() - cache.get("ts", 0)) / 3600
            version_ok = cache.get("version") == NYSE_TICKERS_CACHE_VERSION
            if version_ok and edad_horas < NYSE_TICKERS_CACHE_DIAS * 24 and cache.get("tickers"):
                print(f"  ✓ Lista NYSE desde caché ({len(cache['tickers'])} tickers, {edad_horas:.0f}h de antigüedad)")
                return cache["tickers"]
        except Exception:
            pass

    tickers = []
    url_path = "/v3/reference/tickers"
    params = {"market": "stocks", "exchange": "XNYS", "active": "true", "limit": 1000}
    pagina = 0
    while url_path and pagina < 10:  # tope de seguridad: 10 paginas x 1000 = 10.000, mas que de sobra
        data = pg_get(url_path, params if pagina == 0 else None) if pagina == 0 else pg_get_raw_url(url_path)
        results = data.get("results", [])
        tickers.extend(r["ticker"] for r in results if r.get("ticker"))
        next_url = data.get("next_url")
        if not next_url:
            break
        url_path = next_url  # next_url ya viene con la apiKey y los params codificados
        pagina += 1

    tickers = sorted(set(tickers))
    if tickers:
        try:
            with open(NYSE_TICKERS_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "tickers": tickers, "version": NYSE_TICKERS_CACHE_VERSION}, f)
        except Exception:
            pass
    print(f"  ✓ {len(tickers)} tickers activos (acciones comunes) en el NYSE (Polygon, {pagina+1} páginas)")
    return tickers

def pg_get_raw_url(full_url, retries=3, timeout=15):
    """Igual que pg_get pero para una URL ya completa (la que da next_url de
    paginación) — esa URL ya trae sus propios query params, solo hace falta
    añadir la apiKey si no la trae."""
    sep = "&" if "?" in full_url else "?"
    url = full_url if "apiKey=" in full_url else f"{full_url}{sep}apiKey={POLYGON_KEY}"
    for attempt in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code == 429:
                time.sleep(6); continue
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            if attempt == retries - 1: return {}
            time.sleep(2)
    return {}

def pg_grouped_daily(date_str):
    """Grouped Daily: OHLC de TODO el mercado de acciones de EEUU para un día
    concreto, en una sola llamada. Devuelve {ticker: close} para ese día."""
    data = pg_get(f"/v2/aggs/grouped/locale/us/market/stocks/{date_str}", {"adjusted": "true"})
    results = data.get("results", [])
    return {r["T"]: r["c"] for r in results if r.get("T") and r.get("c") is not None}

def fetch_nyse_breadth_real(dias_atras=400, max_workers=15):
    """Construye avanzan/retroceden, % sobre MA50/MA200, nuevos máximos/mínimos
    de 52 semanas y el McClellan Oscillator REALES, usando el NYSE completo
    y Grouped Daily de Polygon — no una aproximación con 11 ETFs ni con
    nuestro universo curado de ~1.700 acciones.
    Devuelve None si algo falla gravemente (para poder caer al método viejo
    como respaldo sin romper el resto del script)."""
    try:
        nyse_set = set(pg_nyse_active_tickers())
        if len(nyse_set) < 500:  # algo fue mal, universo demasiado pequeño para fiarse
            print("  ⚠️ Lista NYSE sospechosamente pequeña, se aborta la amplitud real")
            return None

        import datetime as _dt
        hoy = _dt.date.today()
        fechas = [(hoy - _dt.timedelta(days=i)) for i in range(dias_atras)]
        fechas = [f for f in fechas if f.weekday() < 5]  # solo dias laborables (festivos: grouped daily vendra vacio y se descarta solo)
        fechas_str = sorted(f.isoformat() for f in fechas)

        print(f"  ↓ Amplitud NYSE real: Grouped Daily de {len(fechas_str)} sesiones (~{len(nyse_set)} tickers NYSE)...")
        cierres_por_fecha = {}
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(pg_grouped_daily, f): f for f in fechas_str}
            done = 0
            for fut in as_completed(futs):
                f = futs[fut]
                try:
                    resultado = fut.result()
                    if resultado:
                        cierres_por_fecha[f] = {tk: c for tk, c in resultado.items() if tk in nyse_set}
                except Exception:
                    pass
                done += 1
                if done % 50 == 0:
                    print(f"    ... {done}/{len(fechas_str)} sesiones de Grouped Daily")

        fechas_con_datos = sorted(cierres_por_fecha.keys())
        print(f"  ✓ {len(fechas_con_datos)} sesiones con datos reales (de {len(fechas_str)} pedidas — festivos/findes se descartan solos)")
        if len(fechas_con_datos) < 45:
            print("  ⚠️ Muy pocas sesiones con datos, se aborta la amplitud real (respaldo al método antiguo)")
            return None

        # Reorganizar a series por ticker: {ticker: [(fecha, cierre), ...]} ordenado
        series_por_ticker = {}
        for f in fechas_con_datos:
            for tk, c in cierres_por_fecha[f].items():
                series_por_ticker.setdefault(tk, []).append((f, c))

        # Avanzando/retrocediendo del ÚLTIMO día vs el anterior
        f_hoy, f_ayer = fechas_con_datos[-1], fechas_con_datos[-2]
        adv = dec = unch = 0
        for tk in nyse_set:
            c_hoy = cierres_por_fecha[f_hoy].get(tk)
            c_ayer = cierres_por_fecha[f_ayer].get(tk)
            if c_hoy is None or c_ayer is None or c_ayer == 0:
                continue
            if c_hoy > c_ayer: adv += 1
            elif c_hoy < c_ayer: dec += 1
            else: unch += 1
        total_comparados = adv + dec + unch

        # % sobre MA50 / MA200 y nuevos máximos/mínimos de 52 semanas (o el
        # máximo histórico disponible si aún no llegamos a 252 sesiones)
        abv50 = abv200 = con_ma50 = con_ma200 = 0
        new_highs = new_lows = 0
        new_highs_list, new_lows_list = [], []
        for tk, serie in series_por_ticker.items():
            if len(serie) < 20:
                continue
            cierres = [c for _, c in serie]
            c_actual = cierres[-1]
            if len(cierres) >= 50:
                ma50 = sum(cierres[-50:]) / 50
                con_ma50 += 1
                if c_actual > ma50: abv50 += 1
            if len(cierres) >= 200:
                ma200 = sum(cierres[-200:]) / 200
                con_ma200 += 1
                if c_actual > ma200: abv200 += 1
            ventana = cierres[-252:] if len(cierres) >= 252 else cierres
            if c_actual >= max(ventana):
                new_highs += 1
                new_highs_list.append(tk)
            if c_actual <= min(ventana):
                new_lows += 1
                new_lows_list.append(tk)

        pct50  = round(abv50/con_ma50*100, 1) if con_ma50 else 0
        pct200 = round(abv200/con_ma200*100, 1) if con_ma200 else 0

        # McClellan Oscillator real: EMA19-EMA39 del neto diario avanzan-
        # retroceden de TODO el NYSE, sesion a sesion (no de 11 ETFs)
        neto_diario = []
        for i in range(1, len(fechas_con_datos)):
            f0, f1 = fechas_con_datos[i-1], fechas_con_datos[i]
            a = d = 0
            for tk in nyse_set:
                c0 = cierres_por_fecha[f0].get(tk); c1 = cierres_por_fecha[f1].get(tk)
                if c0 is None or c1 is None or c0 == 0: continue
                if c1 > c0: a += 1
                elif c1 < c0: d += 1
            neto_diario.append({"date": fechas_con_datos[i], "net": a-d})

        mcclellan_series = []
        if len(neto_diario) >= 39:
            vals = [x["net"] for x in neto_diario]
            def _ema(vals, n):
                k = 2/(n+1); e = vals[0]; result = [e]
                for v in vals[1:]:
                    e = v*k + e*(1-k); result.append(round(e, 2))
                return result
            e19, e39 = _ema(vals, 19), _ema(vals, 39)
            mcclellan_series = [
                {"date": neto_diario[i]["date"], "val": round(e19[i]-e39[i], 2)}
                for i in range(len(neto_diario))
            ]

        print(f"  ✓ Amplitud NYSE real: {adv}▲ {dec}▼ {unch}= (de {total_comparados} comparados) · "
              f"MA50={pct50}% MA200={pct200}% · {new_highs} máx / {new_lows} mín 52w · "
              f"McClellan último={mcclellan_series[-1]['val'] if mcclellan_series else 'N/D'}")

        return {
            "advancing": adv, "declining": dec, "unchanged": unch,
            "total_sample": total_comparados,
            "pct_abv50": pct50, "pct_abv200": pct200,
            "new_highs": new_highs, "new_lows": new_lows,
            "new_highs_list": sorted(new_highs_list),
            "new_lows_list": sorted(new_lows_list),
            "mcclellan": mcclellan_series[-90:] if len(mcclellan_series) > 90 else mcclellan_series,
        }
    except Exception as e:
        print(f"  ⚠️ Error construyendo amplitud NYSE real: {e} — se usará el método antiguo como respaldo")
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  API DE www.amplitudmercado.com (03/09/2026) — datos de amplitud OFICIALES
#  (los mismos que usa Alex Salamanca en su web), con hasta 20 años de
#  histórico: NYSE, NASDAQ, encuestas de sentimiento (AAII e Investors
#  Intelligence), bonos (AD High-Yield y CEF) y macro (Fear&Greed, Put/Call,
#  VIX/VXV). Sustituye a fetch_nyse_breadth_real() como fuente de amplitud
#  cuando hay clave configurada — es la fuente "de verdad", no una
#  aproximación nuestra por muy bien construida que esté.
#
#  La API es AUTODESCRIPTIVA: cada serie trae su propia fila de cabeceras
#  (nombres de columna) antes de las filas de datos — por eso el parseo de
#  abajo lee esos nombres directamente de la respuesta en vez de tenerlos
#  fijados a mano, así que aunque alguna serie (nasdaq, encuestas, bonos)
#  tenga columnas que no hemos visto documentadas explícitamente, el
#  parseo las recoge igual con su nombre real.
#
#  IMPORTANTE — límite de 50 peticiones/día: se cachea la respuesta
#  completa en disco ~20h, así el cron puede correr varias veces al día
#  sin gastar la cuota. La API solo se llama de verdad una vez por día.
# ══════════════════════════════════════════════════════════════════════════════
AMPLITUD_API_KEY = os.environ.get("AMPLITUD_MERCADO_API_KEY", "")
AMPLITUD_API_URL = "https://script.google.com/macros/s/AKfycbz5udZFi0vVSUm9yyo8BqPWfgYVqOEMt6Km6HUP/exec"
AMPLITUD_API_CACHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "amplitud_mercado_cache.json")
AMPLITUD_API_CACHE_HORAS = 20  # bastante para 1 sola llamada real al dia, con margen si el cron corre varias veces

def _amplitud_fecha_ddmmaaaa_a_iso(fecha_str):
    """Convierte 'DDMMAAAA' (formato de la API) a 'AAAA-MM-DD' (el que usa
    todo el resto del dashboard) — para que estas series se puedan mezclar
    sin problema con las demas graficas."""
    try:
        s = str(fecha_str).strip()
        if len(s) != 8: return s
        return f"{s[4:8]}-{s[2:4]}-{s[0:2]}"
    except Exception:
        return str(fecha_str)

def _amplitud_parsear_serie(datos):
    """Convierte una serie [cabeceras, fila1, fila2, ...] en una lista de
    diccionarios {cabecera: valor} — usa los nombres de columna que la
    propia API manda en la primera fila, no nombres fijados a mano. Si la
    primera columna es una fecha en formato DDMMAAAA, se normaliza a ISO."""
    if not datos or not isinstance(datos, list) or len(datos) < 2:
        return []
    headers = datos[0]
    if not isinstance(headers, list):
        return []
    filas = datos[1:]
    resultado = []
    for fila in filas:
        if not isinstance(fila, list): continue
        d = {}
        for i, h in enumerate(headers):
            if i < len(fila):
                d[h] = fila[i]
        # Normalizar la fecha si la primera columna se llama "Fecha" (patron visto en NYSE)
        if headers and headers[0] == "Fecha" and "Fecha" in d:
            d["FechaISO"] = _amplitud_fecha_ddmmaaaa_a_iso(d["Fecha"])
        resultado.append(d)
    return resultado

def fetch_amplitud_mercado_api():
    """Descarga y parsea la API de amplitudmercado.com. Devuelve None si no
    hay clave configurada, si la clave es invalida, si se supero el limite
    diario, o si algo mas falla — en cualquiera de esos casos el dashboard
    debe caer a fetch_nyse_breadth_real() como respaldo, nunca romperse."""
    if not AMPLITUD_API_KEY:
        print("  ℹ️ AMPLITUD_MERCADO_API_KEY no configurada — se usa la amplitud construida con Polygon como fuente")
        return None

    # Cache en disco (~20h) para no gastar la cuota de 50 peticiones/dia
    if os.path.exists(AMPLITUD_API_CACHE_PATH):
        try:
            with open(AMPLITUD_API_CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
            edad_horas = (time.time() - cache.get("ts", 0)) / 3600
            if edad_horas < AMPLITUD_API_CACHE_HORAS and cache.get("datos"):
                print(f"  ✓ Amplitud (amplitudmercado.com) desde caché ({edad_horas:.1f}h de antigüedad)")
                return cache["datos"]
        except Exception:
            pass

    try:
        r = requests.get(AMPLITUD_API_URL, params={"clave": AMPLITUD_API_KEY, "metodo": "amplitud"}, timeout=30)
        if r.status_code != 200:
            print(f"  ⚠️ API amplitudmercado.com respondió {r.status_code} — se usa el respaldo de Polygon")
            return None
        body = r.json()
        if body.get("error"):
            print(f"  ⚠️ API amplitudmercado.com: {body.get('mensaje', 'error desconocido')} — se usa el respaldo de Polygon")
            return None

        raw = body.get("datosAmplitud", {})
        nyse = _amplitud_parsear_serie(raw.get("nyse"))
        nasdaq = _amplitud_parsear_serie(raw.get("nasdaq"))
        encuestas = raw.get("encuestas", {}) or {}
        aaii = _amplitud_parsear_serie(encuestas.get("aaii"))
        ii = _amplitud_parsear_serie(encuestas.get("ii"))
        macro = raw.get("macro", {}) or {}
        diarios = _amplitud_parsear_serie(macro.get("diarios"))
        bonos = _amplitud_parsear_serie(macro.get("bonos"))
        # fearGreed puede venir como un unico par [fecha, valor] (lectura de
        # hoy) o como serie [cabeceras, filas...] segun documentacion — se
        # admiten los dos formatos sin romper
        fg_raw = macro.get("fearGreed")
        fear_greed = []
        if isinstance(fg_raw, list) and fg_raw:
            if isinstance(fg_raw[0], list):
                fear_greed = _amplitud_parsear_serie(fg_raw)
            elif len(fg_raw) >= 2:
                fear_greed = [{"Fecha": fg_raw[0], "FechaISO": _amplitud_fecha_ddmmaaaa_a_iso(fg_raw[0]), "Valor": fg_raw[1]}]

        resultado = {
            "nyse": nyse, "nasdaq": nasdaq,
            "aaii": aaii, "ii": ii,
            "diarios": diarios, "bonos": bonos,
            "fearGreed": fear_greed,
        }
        total_puntos = len(nyse) + len(nasdaq) + len(aaii) + len(ii) + len(diarios) + len(bonos)
        print(f"  ✓ Amplitud (amplitudmercado.com): {len(nyse)} sesiones NYSE, {len(nasdaq)} NASDAQ, "
              f"{len(aaii)} AAII, {len(ii)} II, {len(diarios)} macro diarios, {len(bonos)} bonos "
              f"({total_puntos} puntos de datos totales)")

        try:
            with open(AMPLITUD_API_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "datos": resultado}, f)
        except Exception:
            pass
        return resultado
    except Exception as e:
        print(f"  ⚠️ Error llamando a la API de amplitudmercado.com: {e} — se usa el respaldo de Polygon")
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  EODHD — PLAN B, solo para indices internacionales que Polygon/yfinance no
#  cubren bien (IBEX, DAX, Hang Seng, etc). No se usa para nada mas. Si
#  EODHD_API_KEY no esta configurada, esta fuente queda inactiva sin afectar
#  al resto del script (Polygon sigue siendo la fuente principal siempre).
# ══════════════════════════════════════════════════════════════════════════════
EODHD_KEY  = os.environ.get("EODHD_API_KEY", "")
EODHD_BASE = "https://eodhd.com/api"

def eodhd_aggs_daily(eodhd_ticker, days=400):
    """Equivalente a pg_aggs_daily pero contra EODHD. Mismo formato de salida
    (lista de dicts date/open/high/low/close/volume) para que encaje sin
    cambios en fetch_perf() ni en nada que consuma sus resultados."""
    if not EODHD_KEY:
        return None
    import datetime as _dt
    end = _dt.date.today()
    start = end - _dt.timedelta(days=days)
    try:
        r = requests.get(
            f"{EODHD_BASE}/eod/{eodhd_ticker}",
            params={
                "api_token": EODHD_KEY, "fmt": "json",
                "period": "d", "order": "asc",
                "from": start.isoformat(), "to": end.isoformat(),
            },
            timeout=15,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, list) or not data:
            return None
        return [{
            "date":  row.get("date"),
            "open":  row.get("open"),
            "high":  row.get("high"),
            "low":   row.get("low"),
            "close": row.get("adjusted_close") or row.get("close"),
            "volume": row.get("volume"),
        } for row in data if row.get("close") is not None or row.get("adjusted_close") is not None]
    except Exception:
        return None
from datetime import datetime, timedelta

# ── Auto-install ─────────────────────────────────────────────────────────────
def ensure(pkg, imp=None):
    try: __import__(imp or pkg)
    except ImportError:
        import subprocess
        print(f"  Instalando {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure("yfinance"); ensure("pandas"); ensure("requests"); ensure("beautifulsoup4","bs4")

import yfinance as yf
import warnings, logging
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from requests import Session

# Sesion con headers de navegador real para evitar bloqueo de Yahoo Finance en servidores cloud
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
_adapter = HTTPAdapter(pool_connections=2, pool_maxsize=4, max_retries=3)
_session = Session()
_session.headers.update(_HEADERS)
_session.mount("https://", _adapter)
_session.mount("http://", _adapter)

# Inyectar sesion en yfinance para que use nuestros headers
try:
    import yfinance.utils as _yfu
    _yfu.requests = _session
except Exception:
    pass
try:
    import yfinance.base as _yfb
    _yfb.requests = _session  
except Exception:
    pass

# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

SECTOR_ETFS = {
    "Technology":             "XLK", "Healthcare":           "XLV",
    "Financials":             "XLF", "Consumer Discret.":    "XLY",
    "Consumer Staples":       "XLP", "Energy":               "XLE",
    "Industrials":            "XLI", "Materials":            "XLB",
    "Real Estate":            "XLRE","Utilities":            "XLU",
    "Communication Svcs":     "XLC",
}

# ══════════════════════════════════════════════════════════════════════════════
#  SECTOR_STOCKS (03/09/2026) — mismo criterio que INDUSTRY_DATA: el Sector
#  exacto que da Finviz para cada una de las 725 acciones, sin repetidos
#  entre sectores.
# ══════════════════════════════════════════════════════════════════════════════
SECTOR_STOCKS = {
    "Communication Svcs": ['APP', 'CHTR', 'CMCSA', 'DIS', 'ECHO', 'FOX', 'FOXA', 'FWONA', 'FWONK', 'GOOG', 'GOOGL', 'GSAT', 'LYV', 'META', 'MTCH', 'NFLX', 'NWS', 'NWSA', 'NYT', 'OMC', 'PINS', 'PSKY', 'RBLX', 'RDDT', 'ROKU', 'SIRI', 'T', 'TKO', 'TMUS', 'TTWO', 'VZ', 'WBD', 'WMG'],
    "Consumer Discret.": ['ABNB', 'ALSN', 'AMZN', 'AUR', 'AVY', 'AZO', 'BALL', 'BBY', 'BKNG', 'BURL', 'BWA', 'CART', 'CASY', 'CCK', 'CCL', 'CMG', 'CPNG', 'CVNA', 'DASH', 'DECK', 'DHI', 'DKNG', 'DKS', 'DPZ', 'DRI', 'EBAY', 'EXPE', 'F', 'FIVE', 'FLUT', 'GM', 'GPC', 'H', 'HAS', 'HD', 'HLT', 'IP', 'LEN', 'LOW', 'LVS', 'MAR', 'MCD', 'MGM', 'NKE', 'NVR', 'ORLY', 'PAG', 'PHM', 'PKG', 'QSR', 'RCL', 'RIVN', 'RL', 'ROL', 'ROST', 'SBUX', 'SCI', 'SGI', 'SN', 'TJX', 'TOL', 'TPR', 'TSCO', 'TSLA', 'TXRH', 'ULTA', 'W', 'WSM', 'YUM'],
    "Consumer Staples": ['ADM', 'BF-A', 'BF-B', 'BG', 'BJ', 'CHD', 'CL', 'CLX', 'COKE', 'COST', 'DAR', 'DG', 'DLTR', 'EL', 'GIS', 'HRL', 'HSY', 'KDP', 'KHC', 'KMB', 'KO', 'KR', 'KVUE', 'MDLZ', 'MKC', 'MNST', 'MO', 'PEP', 'PFGC', 'PG', 'PM', 'SJM', 'STZ', 'SYY', 'TGT', 'TSN', 'USFD', 'WMT'],
    "Energy": ['AM', 'APA', 'AR', 'BKR', 'COP', 'CQP', 'CVX', 'DINO', 'DTM', 'DVN', 'EOG', 'EPD', 'EQT', 'ET', 'EXE', 'FANG', 'FTI', 'HAL', 'KMI', 'LNG', 'MPC', 'MPLX', 'OKE', 'OVV', 'OXY', 'PAA', 'PAGP', 'PR', 'PSX', 'SLB', 'SUN', 'TPL', 'TRGP', 'VG', 'VLO', 'VNOM', 'WES', 'WMB', 'XOM'],
    "Financials": ['AFG', 'AFL', 'AFRM', 'AIG', 'AIZ', 'AJG', 'ALL', 'ALLY', 'AMP', 'APO', 'ARCC', 'ARES', 'AXP', 'BAC', 'BAM', 'BEN', 'BLK', 'BMNR', 'BNY', 'BPOP', 'BRK-A', 'BRK-B', 'BRO', 'BX', 'C', 'CBOE', 'CFG', 'CFR', 'CG', 'CINF', 'CM', 'CME', 'CNA', 'COF', 'COIN', 'CRBG', 'CRCL', 'EQH', 'ERIE', 'EVR', 'EWBC', 'FCNCA', 'FDS', 'FHN', 'FITB', 'FNF', 'GL', 'GS', 'HBAN', 'HIG', 'HOOD', 'IBKR', 'ICE', 'IVZ', 'JEF', 'JPM', 'KEY', 'KKR', 'L', 'LPLA', 'MA', 'MCO', 'MET', 'MKL', 'MRSH', 'MS', 'MSCI', 'MTB', 'NDAQ', 'NTRS', 'ORI', 'OWL', 'PFG', 'PGR', 'PNC', 'PNFP', 'PRU', 'PS', 'PYPL', 'RF', 'RGA', 'RJF', 'RKT', 'RYAN', 'SCHW', 'SEIC', 'SF', 'SOFI', 'SPGI', 'SSB', 'STT', 'SYF', 'TFC', 'TPG', 'TROW', 'TRU', 'TRV', 'TW', 'UMBF', 'UNM', 'USB', 'V', 'WBS', 'WFC', 'WRB', 'WTFC'],
    "Healthcare": ['A', 'ABBV', 'ABT', 'ALGN', 'ALNY', 'AMGN', 'APGE', 'ARWR', 'AXSM', 'BAX', 'BBIO', 'BDX', 'BIIB', 'BIO', 'BMRN', 'BMY', 'BSX', 'BTSG', 'CAH', 'CI', 'CNC', 'COO', 'COR', 'CORT', 'CRL', 'CVS', 'DGX', 'DHR', 'DVA', 'DXCM', 'EHC', 'ELAN', 'ELV', 'ENSG', 'EW', 'EXEL', 'GEHC', 'GH', 'GILD', 'GKOS', 'GMED', 'HALO', 'HCA', 'HSIC', 'HUM', 'IDXX', 'ILMN', 'INCY', 'INSM', 'IONS', 'IQV', 'ISRG', 'JNJ', 'KRYS', 'LH', 'LLY', 'MCK', 'MDGL', 'MDLN', 'MEDP', 'MOH', 'MRK', 'MRNA', 'MTD', 'NBIX', 'NTRA', 'PEN', 'PFE', 'PODD', 'REGN', 'RMD', 'RPRX', 'RVMD', 'RVTY', 'SMMT', 'SOLV', 'SYK', 'TECH', 'TEM', 'THC', 'TMO', 'UNH', 'UTHR', 'VEEV', 'VRTX', 'VTRS', 'WAT', 'WST', 'ZBH', 'ZTS'],
    "Industrials": ['AEIS', 'AIT', 'AME', 'APG', 'ARMK', 'ARXS', 'ATI', 'AXON', 'BA', 'BE', 'BWXT', 'CARR', 'CAT', 'CHRW', 'CLH', 'CMI', 'CP', 'CPRT', 'CR', 'CRS', 'CSL', 'CSX', 'CTAS', 'CW', 'DAL', 'DCI', 'DE', 'DOV', 'EFX', 'EME', 'EMR', 'EXPD', 'FAST', 'FDX', 'FDXF', 'FERG', 'FIX', 'FTAI', 'GD', 'GE', 'GEV', 'GFL', 'GGG', 'GNRC', 'GWW', 'HEI', 'HEI-A', 'HII', 'HON', 'HONA', 'HUBB', 'HWM', 'IESC', 'IEX', 'IR', 'ITT', 'ITW', 'J', 'JBHT', 'KNX', 'LECO', 'LHX', 'LII', 'LMT', 'LUV', 'MAIR', 'MAS', 'MLI', 'MMM', 'MOG-A', 'MTZ', 'NDSN', 'NOC', 'NSC', 'OC', 'ODFL', 'OTIS', 'PCAR', 'PH', 'PWR', 'QXO', 'RBA', 'RBC', 'RKLB', 'ROK', 'RRX', 'RSG', 'RTX', 'SNA', 'SPCX', 'STRL', 'SUNB', 'SWK', 'SYM', 'TDG', 'TXT', 'UAL', 'UHAL', 'UHAL-B', 'ULS', 'UNP', 'UPS', 'URI', 'VLTO', 'VRSK', 'VRT', 'WAB', 'WCC', 'WM', 'WMS', 'WSO', 'WTS', 'WWD', 'XPO', 'XYL'],
    "Materials": ['AA', 'ALB', 'AMRZ', 'APD', 'AU', 'CDE', 'CF', 'CRH', 'CTVA', 'DD', 'DOW', 'ECL', 'FCX', 'HL', 'IFF', 'MLM', 'NEM', 'NUE', 'PPG', 'RGLD', 'RPM', 'RS', 'SCCO', 'SHW', 'STLD', 'VMC'],
    "Real Estate": ['AGNC', 'AHR', 'AMH', 'AMT', 'BXP', 'CBRE', 'CCI', 'CPT', 'CSGP', 'DLR', 'DOC', 'EGP', 'ELS', 'EQIX', 'ESS', 'EXR', 'FRT', 'GLPI', 'HST', 'INVH', 'IRM', 'JLL', 'KIM', 'LAMR', 'MAA', 'NLY', 'O', 'OHI', 'PLD', 'PSA', 'REG', 'SBAC', 'SPG', 'SUI', 'UDR', 'VICI', 'VMRK', 'VTR', 'WELL', 'WPC', 'WY'],
    "Technology": ['AAPL', 'ADBE', 'ADI', 'ADP', 'ADSK', 'AKAM', 'ALAB', 'AMAT', 'AMD', 'AMKR', 'ANET', 'APH', 'ARW', 'ASTS', 'AVGO', 'BR', 'BSY', 'CACI', 'CBRS', 'CDNS', 'CDW', 'CGNX', 'CHYM', 'CIEN', 'COHR', 'CPAY', 'CRM', 'CRWD', 'CRWV', 'CSCO', 'CTSH', 'DDOG', 'DELL', 'DOCN', 'DOCU', 'DT', 'ENTG', 'FFIV', 'FICO', 'FIG', 'FIS', 'FISV', 'FLEX', 'FROG', 'FSLR', 'FTNT', 'FTV', 'GDDY', 'GEN', 'GFS', 'GLW', 'GPN', 'GWRE', 'HPE', 'HPQ', 'HUBS', 'IBM', 'INTC', 'INTU', 'IONQ', 'IOT', 'IT', 'JBL', 'JKHY', 'KEYS', 'KLAC', 'LDOS', 'LFUS', 'LITE', 'LRCX', 'LSCC', 'MANH', 'MCHP', 'MDB', 'MKSI', 'MPWR', 'MRVL', 'MSFT', 'MSI', 'MSTR', 'MTSI', 'MU', 'NET', 'NOW', 'NTAP', 'NTNX', 'NVDA', 'NXT', 'OKTA', 'ON', 'ONTO', 'ORCL', 'P', 'PANW', 'PAYC', 'PAYX', 'PLTR', 'PTC', 'Q', 'QCOM', 'QNT', 'RBRK', 'ROP', 'SAIL', 'SANM', 'SITM', 'SMCI', 'SMTC', 'SNDK', 'SNOW', 'SNPS', 'SNX', 'SSNC', 'STRC', 'SWKS', 'TDY', 'TEAM', 'TER', 'TOST', 'TRMB', 'TTMI', 'TWLO', 'TXN', 'TYL', 'U', 'UBER', 'UI', 'VRSN', 'WDAY', 'WDC', 'XYZ', 'ZBRA', 'ZM', 'ZS'],
    "Utilities": ['AEE', 'AEP', 'AES', 'ATO', 'AWK', 'CEG', 'CMS', 'CNP', 'D', 'DTE', 'DUK', 'DUKU', 'ED', 'EIX', 'ES', 'ETR', 'EVRG', 'EXC', 'FE', 'LNT', 'NEE', 'NI', 'NRG', 'PCG', 'PEG', 'PNW', 'PPL', 'SO', 'SRE', 'TLN', 'VST', 'WEC', 'WTRG', 'XEL'],
}

# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO_EXTRA (03/09/2026) — IMPORTANTE: separado a propósito de
#  INDUSTRY_DATA/SECTOR_STOCKS. Esos dos son solo para CLASIFICAR (que cada
#  accion caiga en su industria/sector correcto, 1 sola vez, segun Finviz —
#  725 tickers). Pero el UNIVERSO GENERAL usado en fundamentales, amplitud,
#  scanner, etc. necesita ser mas amplio (~1.343+, como antes) — si no,
#  reducir INDUSTRY_DATA/SECTOR_STOCKS a los 725 de Finviz encogia tambien
#  el universo entero sin querer (bug real, confirmado por Victor: bajo a
#  747 fundamentales cuando debian seguir siendo 1.343+). Esta lista son los
#  tickers del universo ORIGINAL (antes de la reconstruccion de hoy) que NO
#  estan entre los 725 de Finviz — se suman aparte en fetch_stock_perf() para
#  que el universo total no encoja, sin ensuciar la clasificacion limpia de
#  INDUSTRY_DATA/SECTOR_STOCKS.
# ══════════════════════════════════════════════════════════════════════════════
UNIVERSO_EXTRA = [
    "AAL", "AAOI", "AAON", "AAP", "ABB", "ABEV", "ACAD", "ACB", "ACCD", "ACDC",
    "ACE", "ACHR", "ACLS", "ACM", "ACMR", "ACNB", "ACR", "ADYEN", "AECOM", "AEM",
    "AEO", "AESE", "AEVA", "AG", "AGCO", "AGI", "AGX", "AI", "AIR", "ALG",
    "ALGT", "ALHC", "ALTD", "AMBA", "AMBP", "AMCR", "AMG", "AMPS", "AMPX", "AMR",
    "AMRS", "AMSYS", "AMTX", "AMWD", "AMWL", "ANF", "ANGI", "ANSS", "ANTO", "AON",
    "APAM", "APLD", "APOG", "APTV", "AQMS", "ARCB", "ARE", "ARIS", "ARKB", "ARNC",
    "ARQQ", "ARRY", "ARTNA", "ARVL", "ASM", "ASML", "ATKR", "ATLX", "ATMU", "ATOM",
    "ATR", "ATVI", "AUGO", "AVA", "AVAV", "AVB", "AVTR", "AWR", "AXBK", "AXS",
    "AYI", "AYRO", "AYRWF", "AZN", "AZRE", "AZUL", "BABA", "BAH", "BALY", "BBAI",
    "BBD", "BBUC", "BCEKF", "BDC", "BEAM", "BELFA", "BEP", "BEPC", "BHE", "BHP",
    "BIDU", "BILI", "BILL", "BIP", "BITB", "BITF", "BITI", "BITO", "BITS", "BJRI",
    "BK", "BKCH", "BKE", "BKU", "BLBD", "BLD", "BLDP", "BLDR", "BLMN", "BLNK",
    "BLUE", "BMBL", "BNPL", "BNTX", "BOKF", "BOOT", "BP", "BRGX", "BROS", "BRRR",
    "BTAL", "BTBT", "BTCO", "BTCS", "BTCW", "BTDR", "BTF", "BTG", "BTU", "BURBY",
    "BXSL", "BYD", "CAG", "CAKE", "CALM", "CALY", "CAN", "CAOS", "CAPL", "CAR",
    "CAVA", "CB", "CBRL", "CBSH", "CCJ", "CCS", "CE", "CECO", "CELH", "CENX",
    "CFLT", "CFRUY", "CGC", "CHCT", "CHDN", "CHKP", "CHPT", "CHWY", "CIFR", "CIG",
    "CLF", "CLNC", "CLNE", "CLOV", "CLPR", "CLSK", "CLUB", "CMC", "CMMC", "CMP",
    "CMRE", "CNI", "CNX", "COFORGE", "COHU", "COLB", "COLD", "COLL", "CONE", "COPX",
    "CORN", "CORR", "COTY", "CPA", "CPB", "CPER", "CPRI", "CRK", "CRON", "CROX",
    "CRSP", "CSAN", "CSIQ", "CSLR", "CSWC", "CTLP", "CTOS", "CTRA", "CTRM", "CU",
    "CURLF", "CURO", "CVCO", "CVI", "CVLG", "CVSB", "CVV", "CWCO", "CWEN", "CWST",
    "CWT", "CXBTF", "CYBR", "CZR", "DAN", "DAQO", "DAVE", "DBA", "DBB", "DEFI",
    "DEFN", "DFNS", "DFS", "DGII", "DIN", "DISH", "DJP", "DK", "DKL", "DNN",
    "DNNGY", "DNUT", "DO", "DOCS", "DORM", "DOYU", "DQ", "DRS", "DRV", "DSGX",
    "DSX", "DWAHY", "DY", "EA", "EAF", "EAT", "EBON", "ECG", "ECM", "ECO",
    "EDIT", "EDRY", "EDV", "EGLE", "EGO", "ELF", "ELMS", "ELYS", "EMN", "ENB",
    "ENCM", "ENPH", "ENR", "ENS", "ENVA", "ENVX", "EOAN", "EPAM", "EPI", "EQPT",
    "EQR", "EQX", "ERII", "ERO", "ESAB", "ESEA", "ESTC", "ETHE", "ETHU", "ETN",
    "ETSY", "EU", "EVGO", "EVRI", "EVTC", "EVTL", "EXAS", "EXK", "EXPO", "EXTR",
    "EZJ", "FANUY", "FATE", "FBTC", "FCEL", "FELE", "FEYE", "FFIE", "FFIN", "FILO",
    "FLGT", "FLNC", "FLR", "FLS", "FLYW", "FM", "FMC", "FNV", "FOLD", "FORM",
    "FOSL", "FOUR", "FPX", "FRD", "FRSH", "FSLY", "FSR", "FSS", "FTCI", "FUBO",
    "FUJIY", "FUN", "FWRD", "GAIN", "GAME", "GAP", "GATO", "GATX", "GBTC", "GBX",
    "GCWW", "GDEN", "GEL", "GENI", "GEVO", "GFAI", "GGB", "GHC", "GIL", "GLASF",
    "GLBS", "GLD", "GLDD", "GLEN", "GLP", "GMBL", "GMIN", "GNK", "GNSS", "GNTX",
    "GOCO", "GOEV", "GOL", "GOLD", "GOLF", "GOOD", "GOOS", "GPOR", "GRAB", "GRBK",
    "GRIN", "GRVY", "GRWG", "GS2", "GSG", "GSL", "GTBIF", "GTLB", "GTX", "GVA",
    "GWRS", "GXO", "HA", "HAFN", "HASI", "HAYW", "HBI", "HBM", "HCAT", "HCC",
    "HDB", "HDFC", "HDGE", "HEP", "HERMY", "HES", "HEXO", "HGV", "HIMS", "HIVE",
    "HLIO", "HMC", "HODL", "HOLX", "HONB", "HP", "HPNN", "HQY", "HRI", "HSHP",
    "HTLD", "HTOO", "HUBG", "HUT", "HUYA", "HYAC", "HYLN", "HYSR", "HYTN", "HYW",
    "HYZN", "I", "IAC", "IAG", "IAU", "IBDRY", "IBIT", "IBN", "IBOC", "IBP",
    "ICF", "ICICIBC", "ICUI", "IDEX", "IIJIY", "IIPR", "IMGN", "IMPV", "IMVT", "INDA",
    "INDB", "INFY", "INGR", "INVZ", "IPAR", "IPG", "IQ", "IQM", "IRBT", "IRDM",
    "IREN", "IRTC", "ITM", "ITRG", "ITUB", "IVN", "IZN", "JACK", "JAZZ", "JBLU",
    "JBSS", "JD", "JKS", "JMIA", "JNPR", "JOBY", "JRVS", "JWN", "K", "KBH",
    "KBR", "KC", "KGC", "KN", "KPIT", "KSS", "KTOS", "KYMR", "KYOCY", "LAC",
    "LAZR", "LBRDA", "LBRT", "LC", "LCID", "LEA", "LEGN", "LEU", "LFTO", "LGIH",
    "LI", "LIDR", "LIN", "LIQT", "LKQ", "LMAT", "LNTH", "LOCO", "LOGI", "LOOP",
    "LPSN", "LSI", "LSTR", "LTCN", "LTH", "LTHI", "LTIMINDTREE", "LULU", "LUMN", "LUNR",
    "LVMH", "LVMHF", "LW", "LX", "LYB", "M", "MAG", "MAIFF", "MAIN", "MARA",
    "MAT", "MATX", "MAXI", "MAXN", "MBLY", "MCRI", "MDT", "MELI", "MESA", "METC",
    "MFG", "MGEE", "MGNI", "MGRC", "MGY", "MHO", "MIDD", "MINDTREE", "MMC", "MMED",
    "MMP", "MMSI", "MNVN", "MOD", "MOMO", "MOO", "MORN", "MOS", "MOV", "MOVE",
    "MP", "MPHASIS", "MQ", "MRAAY", "MRCY", "MRO", "MRTN", "MSB", "MSEX", "MSGE",
    "MSGS", "MT", "MTDR", "MTH", "MTN", "MTRX", "MTSL", "MTUS", "MUFG", "MULN",
    "MVST", "MYRG", "NB", "NCLH", "NCR", "NCTY", "NE", "NERD", "NFE", "NG",
    "NGEX", "NGL", "NGLOY", "NICE", "NIO", "NIU", "NKLA", "NMG", "NMM", "NNE",
    "NNN", "NOVA", "NOVN", "NOVS", "NRDS", "NRGV", "NS", "NTDOY", "NTES", "NTLA",
    "NTR", "NU", "NUAN", "NUVB", "NUVEI", "NVAX", "NVCR", "NVO", "NVRI", "NVST",
    "NVTS", "NWE", "NWL", "NWN", "NWPX", "NXPI", "NXRT", "NYKAA", "OCEA", "OGE",
    "OGI", "OKLO", "OLED", "OLLI", "OLN", "OMCL", "OMH", "ONDS", "ONEM", "ONON",
    "OPAL", "OPEN", "OPFI", "OPRX", "OR", "ORA", "ORLA", "OSCR", "OSIS", "OSK",
    "OTSKY", "OTTR", "OUST", "OUTF", "OXM", "PAAS", "PACB", "PAHC", "PANL", "PARA",
    "PARR", "PATH", "PAY", "PAYO", "PAYTM", "PBF", "PBFX", "PBR", "PCTY", "PDBC",
    "PDD", "PDN", "PENN", "PERSISTENT", "PESI", "PFPT", "PGNY", "PHIN", "PHLT", "PHR",
    "PIN", "PKX", "PL", "PLAY", "PLBY", "PLNT", "PLUG", "PLXS", "PNTG", "POLICYBZR",
    "POOL", "POR", "POST", "POWI", "PRAA", "PRCT", "PRGO", "PRIM", "PRKS", "PRMW",
    "PROS", "PSIX", "PSMT", "PSNY", "PSQ", "PSTG", "PTEN", "PTON", "PUMP", "PVH",
    "PVOL", "PXD", "QBTS", "QFIN", "QLYS", "QMCO", "QS", "QTS", "QUBT", "R",
    "RAL", "RAR", "RARE", "RATE", "RCKT", "RDVY", "RDW", "RDWR", "RE", "REE",
    "RELY", "REMX", "RES", "REX", "RGEN", "RGTI", "RH", "RIDE", "RIO", "RIOT",
    "RLI", "RMBS", "RMS", "RNW", "ROAD", "ROG", "RPAR", "RPAY", "RRC", "RRGB",
    "RRR", "RSI", "RUN", "RWE", "RXMD", "RXO", "RXRX", "RYAAY", "S", "SABESP",
    "SAFE", "SAIA", "SAIC", "SAP", "SATS", "SB", "SBICARD", "SBIN", "SBLK", "SBS",
    "SBSW", "SCVL", "SDGR", "SDOW", "SE", "SEA", "SEB", "SEDG", "SEE", "SEI",
    "SFBS", "SFD", "SFL", "SGA", "SGEN", "SGMS", "SH", "SHAK", "SHIP", "SHLS",
    "SHLX", "SHOP", "SID", "SIG", "SIGI", "SIL", "SILV", "SITE", "SJW", "SKLZ",
    "SKX", "SKY", "SKYW", "SLAB", "SLV", "SM", "SMAR", "SMFG", "SMG", "SMLR",
    "SMR", "SNAP", "SNCY", "SNDR", "SNV", "SOLG", "SOLO", "SON", "SONY", "SOS",
    "SOUN", "SOXS", "SOYB", "SPCE", "SPIR", "SPT", "SPWR", "SPXS", "SQ", "SQM",
    "SQQQ", "SR", "SRPT", "SSD", "SSL", "SSRM", "STEM", "STM", "STNG", "SUPN",
    "SUZ", "SVM", "SVXY", "SWAN", "SWX", "SXC", "TACO", "TAIL", "TALK", "TATA",
    "TCEHY", "TCNNF", "TDC", "TDOC", "TDS", "TECK", "TELE", "TENB", "TEX", "TFII",
    "TFSL", "TFX", "TIRX", "TKOMY", "TLGA", "TLRY", "TM", "TME", "TMHC", "TNDM",
    "TNL", "TOPS", "TPIC", "TREE", "TREX", "TRIP", "TRMD", "TRP", "TS", "TSM",
    "TSVT", "TT", "TTD", "TTEK", "TWST", "TYGO", "UEC", "UGI", "ULCC", "UNIT",
    "UPST", "URBN", "URG", "URNJ", "URNM", "USA", "USAC", "UUUU", "UVIX", "UVXY",
    "VAC", "VAL", "VALE", "VC", "VCYT", "VERINT", "VFC", "VFF", "VIAV", "VICR",
    "VINF", "VIPS", "VIRT", "VITL", "VIXM", "VIXY", "VLDR", "VMI", "VNET", "VRA",
    "VRNT", "VRSSF", "VRTS", "VSAT", "VSEE", "VSXY", "VXX", "WB", "WBA", "WEAT",
    "WEN", "WERN", "WEX", "WHD", "WING", "WIT", "WKHS", "WOLF", "WOR", "WPM",
    "WRBY", "WS", "WSC", "WULF", "WYNN", "X", "XOS", "XPEV", "XRAY", "YETI",
    "YORW", "YY", "ZEUS", "ZEV", "ZG", "ZI", "ZIM", "ZNGA", "ZOMATO",
]

# ══════════════════════════════════════════════════════════════════════════════
#  INDUSTRY_DATA (03/09/2026) — RECONSTRUIDO desde la clasificacion oficial
#  de Finviz (Sector + Industry), enviada por Victor en 705 de 725 filas
#  (faltan las filas 301-320, pendientes de anadir cuando lleguen). Cada
#  accion pertenece a UNA SOLA industria (la que dice Finviz), no varias
#  como antes -- confirmado con auditoria: 0 tickers repetidos entre
#  industrias. El ETF de cada industria es el mismo que ya usabamos si el
#  nombre coincidia exactamente con el INDUSTRY_DATA viejo; si no, un ETF
#  proxy conocido de esa industria concreta, o si tampoco existe, el ETF
#  del sector como referencia mas amplia.
# ══════════════════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════════════════
#  INDUSTRY_DATA (03/09/2026) — RECONSTRUIDO desde la clasificacion oficial
#  de Finviz (Sector + Industry), las 725 filas completas que paso Victor.
#  Cada accion pertenece a UNA SOLA industria (la que dice Finviz), no
#  varias como antes -- 0 tickers repetidos entre industrias, verificado.
# ══════════════════════════════════════════════════════════════════════════════
INDUSTRY_DATA = {
    "Advertising Agencies": {"etf": "XLC", "holdings": ['APP', 'OMC']},
    "Aerospace & Defense": {"etf": "ITA", "holdings": ['ARXS', 'AXON', 'BA', 'BWXT', 'CW', 'FTAI', 'GD', 'GE', 'HEI', 'HEI-A', 'HII', 'HONA', 'HWM', 'LHX', 'LMT', 'MOG-A', 'NOC', 'RKLB', 'RTX', 'SPCX', 'TDG', 'TXT', 'WWD']},
    "Agricultural Inputs": {"etf": "XLB", "holdings": ['CF', 'CTVA']},
    "Airlines": {"etf": "JETS", "holdings": ['DAL', 'LUV', 'UAL']},
    "Aluminum": {"etf": "XLB", "holdings": ['AA']},
    "Apparel Manufacturing": {"etf": "XLY", "holdings": ['RL']},
    "Apparel Retail": {"etf": "XRT", "holdings": ['BURL', 'ROST', 'TJX']},
    "Asset Management": {"etf": "KCE", "holdings": ['AMP', 'APO', 'ARCC', 'ARES', 'BAM', 'BEN', 'BLK', 'BX', 'CG', 'CRBG', 'EQH', 'IVZ', 'KKR', 'NTRS', 'OWL', 'PFG', 'PS', 'RJF', 'SEIC', 'STT', 'TPG', 'TROW']},
    "Auto & Truck Dealerships": {"etf": "XLY", "holdings": ['CVNA', 'PAG']},
    "Auto Manufacturers": {"etf": "CARZ", "holdings": ['F', 'GM', 'RIVN', 'TSLA']},
    "Auto Parts": {"etf": "CARZ", "holdings": ['ALSN', 'AUR', 'AZO', 'BWA', 'GPC', 'ORLY']},
    "Banks - Diversified": {"etf": "KBE", "holdings": ['BAC', 'BNY', 'C', 'CM', 'JPM', 'WFC']},
    "Banks - Regional": {"etf": "KRE", "holdings": ['BPOP', 'CFG', 'CFR', 'EWBC', 'FCNCA', 'FHN', 'FITB', 'HBAN', 'KEY', 'MTB', 'PNC', 'PNFP', 'RF', 'SSB', 'TFC', 'UMBF', 'USB', 'WBS', 'WTFC']},
    "Beverages - Brewers": {"etf": "XLP", "holdings": ['STZ']},
    "Beverages - Non-Alcoholic": {"etf": "XLP", "holdings": ['COKE', 'KDP', 'KO', 'MNST', 'PEP']},
    "Beverages - Wineries & Distilleries": {"etf": "XLP", "holdings": ['BF-A', 'BF-B']},
    "Biotechnology": {"etf": "XBI", "holdings": ['ALNY', 'APGE', 'ARWR', 'AXSM', 'BBIO', 'BMRN', 'CORT', 'EXEL', 'HALO', 'INCY', 'INSM', 'IONS', 'KRYS', 'MDGL', 'MRNA', 'REGN', 'RPRX', 'RVMD', 'SMMT', 'TECH', 'VRTX']},
    "Building Materials": {"etf": "XLB", "holdings": ['AMRZ', 'CRH', 'MLM', 'VMC']},
    "Building Products & Equipment": {"etf": "XLI", "holdings": ['CARR', 'CSL', 'LII', 'MAIR', 'MAS', 'OC', 'WMS']},
    "Capital Markets": {"etf": "KCE", "holdings": ['BMNR', 'CRCL', 'EVR', 'GS', 'HOOD', 'IBKR', 'JEF', 'LPLA', 'MS', 'SCHW', 'SF', 'TW']},
    "Chemicals": {"etf": "XLB", "holdings": ['DOW']},
    "Communication Equipment": {"etf": "XLK", "holdings": ['ASTS', 'CIEN', 'CSCO', 'HPE', 'LITE', 'MSI', 'UI', 'ZBRA']},
    "Computer Hardware": {"etf": "XLK", "holdings": ['ANET', 'DELL', 'HPQ', 'IONQ', 'P', 'SMCI', 'SNDK', 'WDC']},
    "Confectioners": {"etf": "XLP", "holdings": ['HSY', 'MDLZ']},
    "Conglomerates": {"etf": "XLI", "holdings": ['HON', 'MMM']},
    "Consulting Services": {"etf": "XLI", "holdings": ['EFX', 'VRSK']},
    "Consumer Electronics": {"etf": "XLK", "holdings": ['AAPL']},
    "Copper": {"etf": "COPX", "holdings": ['FCX', 'SCCO']},
    "Credit Services": {"etf": "IYF", "holdings": ['AFRM', 'ALLY', 'AXP', 'COF', 'MA', 'PYPL', 'SOFI', 'SYF', 'V']},
    "Diagnostics & Research": {"etf": "IHI", "holdings": ['A', 'CRL', 'DGX', 'DHR', 'GH', 'IDXX', 'ILMN', 'IQV', 'LH', 'MEDP', 'MTD', 'NTRA', 'RVTY', 'TMO', 'WAT']},
    "Discount Stores": {"etf": "XRT", "holdings": ['BJ', 'COST', 'DG', 'DLTR', 'TGT', 'WMT']},
    "Drug Manufacturers - General": {"etf": "XPH", "holdings": ['ABBV', 'AMGN', 'BIIB', 'BMY', 'GILD', 'JNJ', 'LLY', 'MRK', 'PFE']},
    "Drug Manufacturers - Specialty & Generic": {"etf": "XPH", "holdings": ['ELAN', 'NBIX', 'UTHR', 'VTRS', 'ZTS']},
    "Electrical Equipment & Parts": {"etf": "XLI", "holdings": ['AEIS', 'BE', 'HUBB', 'VRT']},
    "Electronic Components": {"etf": "XLK", "holdings": ['APH', 'FLEX', 'GLW', 'JBL', 'LFUS', 'SANM', 'TTMI']},
    "Electronic Gaming & Multimedia": {"etf": "XLC", "holdings": ['RBLX', 'TTWO']},
    "Electronics & Computer Distribution": {"etf": "XLK", "holdings": ['ARW', 'SNX']},
    "Engineering & Construction": {"etf": "XLI", "holdings": ['APG', 'EME', 'FIX', 'IESC', 'J', 'MTZ', 'PWR', 'STRL']},
    "Entertainment": {"etf": "PBS", "holdings": ['DIS', 'FOX', 'FOXA', 'FWONA', 'FWONK', 'LYV', 'NFLX', 'NWS', 'NWSA', 'PSKY', 'ROKU', 'SIRI', 'TKO', 'WBD', 'WMG']},
    "Farm & Heavy Construction Machinery": {"etf": "XLI", "holdings": ['CAT', 'DE', 'PCAR']},
    "Farm Products": {"etf": "XLP", "holdings": ['ADM', 'BG', 'TSN']},
    "Financial Data & Stock Exchanges": {"etf": "XLF", "holdings": ['CBOE', 'CME', 'COIN', 'FDS', 'ICE', 'MCO', 'MSCI', 'NDAQ', 'SPGI', 'TRU']},
    "Food Distribution": {"etf": "XLP", "holdings": ['PFGC', 'SYY', 'USFD']},
    "Footwear & Accessories": {"etf": "XLY", "holdings": ['DECK', 'NKE']},
    "Furnishings, Fixtures & Appliances": {"etf": "XLY", "holdings": ['SGI', 'SN']},
    "Gambling": {"etf": "XLY", "holdings": ['DKNG', 'FLUT']},
    "Gold": {"etf": "GDX", "holdings": ['AU', 'CDE', 'NEM', 'RGLD']},
    "Grocery Stores": {"etf": "XLP", "holdings": ['KR']},
    "Health Information Services": {"etf": "XLV", "holdings": ['BTSG', 'TEM', 'VEEV']},
    "Healthcare Plans": {"etf": "XLV", "holdings": ['CI', 'CNC', 'CVS', 'ELV', 'HUM', 'MOH', 'UNH']},
    "Home Improvement Retail": {"etf": "XLY", "holdings": ['HD', 'LOW']},
    "Household & Personal Products": {"etf": "XLP", "holdings": ['CHD', 'CL', 'CLX', 'EL', 'KMB', 'KVUE', 'PG']},
    "Industrial Distribution": {"etf": "XLI", "holdings": ['AIT', 'FAST', 'FERG', 'GWW', 'QXO', 'WCC', 'WSO']},
    "Information Technology Services": {"etf": "XLK", "holdings": ['BR', 'CACI', 'CDW', 'CTSH', 'FIS', 'FISV', 'IBM', 'IT', 'JKHY', 'LDOS']},
    "Insurance - Diversified": {"etf": "KIE", "holdings": ['AIG', 'BRK-A', 'BRK-B', 'HIG']},
    "Insurance - Life": {"etf": "KIE", "holdings": ['AFL', 'GL', 'MET', 'PRU', 'UNM']},
    "Insurance - Property & Casualty": {"etf": "KIE", "holdings": ['AFG', 'AIZ', 'ALL', 'CINF', 'CNA', 'L', 'MKL', 'ORI', 'PGR', 'TRV', 'WRB']},
    "Insurance - Reinsurance": {"etf": "XLF", "holdings": ['RGA']},
    "Insurance - Specialty": {"etf": "XLF", "holdings": ['FNF', 'RYAN']},
    "Insurance Brokers": {"etf": "XLF", "holdings": ['AJG', 'BRO', 'ERIE', 'MRSH']},
    "Integrated Freight & Logistics": {"etf": "XLI", "holdings": ['CHRW', 'EXPD', 'FDX', 'FDXF', 'JBHT', 'UPS']},
    "Internet Content & Information": {"etf": "XLC", "holdings": ['GOOG', 'GOOGL', 'META', 'MTCH', 'PINS', 'RDDT']},
    "Internet Retail": {"etf": "IBUY", "holdings": ['AMZN', 'CART', 'CPNG', 'DASH', 'EBAY', 'W']},
    "Leisure": {"etf": "XLY", "holdings": ['HAS']},
    "Lodging": {"etf": "XLY", "holdings": ['H', 'HLT', 'MAR']},
    "Luxury Goods": {"etf": "LUXE", "holdings": ['TPR']},
    "Medical Care Facilities": {"etf": "XLV", "holdings": ['DVA', 'EHC', 'ENSG', 'HCA', 'THC']},
    "Medical Devices": {"etf": "IHI", "holdings": ['ABT', 'BIO', 'BSX', 'DXCM', 'EW', 'GEHC', 'GKOS', 'GMED', 'PEN', 'PODD', 'SYK', 'ZBH']},
    "Medical Distribution": {"etf": "XLV", "holdings": ['CAH', 'COR', 'HSIC', 'MCK']},
    "Medical Instruments & Supplies": {"etf": "XLV", "holdings": ['ALGN', 'BAX', 'BDX', 'COO', 'ISRG', 'MDLN', 'RMD', 'SOLV', 'WST']},
    "Metal Fabrication": {"etf": "XLB", "holdings": ['ATI', 'CRS', 'MLI']},
    "Mortgage Finance": {"etf": "XLF", "holdings": ['RKT']},
    "Oil & Gas E&P": {"etf": "XOP", "holdings": ['APA', 'AR', 'COP', 'DVN', 'EOG', 'EQT', 'EXE', 'FANG', 'OVV', 'OXY', 'PR', 'TPL']},
    "Oil & Gas Equipment & Services": {"etf": "XES", "holdings": ['BKR', 'FTI', 'HAL', 'SLB']},
    "Oil & Gas Integrated": {"etf": "XLE", "holdings": ['CVX', 'XOM']},
    "Oil & Gas Midstream": {"etf": "AMLP", "holdings": ['AM', 'CQP', 'DTM', 'EPD', 'ET', 'KMI', 'LNG', 'MPLX', 'OKE', 'PAA', 'PAGP', 'TRGP', 'VG', 'VNOM', 'WES', 'WMB']},
    "Oil & Gas Refining & Marketing": {"etf": "CRAK", "holdings": ['DINO', 'MPC', 'PSX', 'SUN', 'VLO']},
    "Other Precious Metals & Mining": {"etf": "XLB", "holdings": ['HL']},
    "Packaged Foods": {"etf": "XLP", "holdings": ['DAR', 'GIS', 'HRL', 'KHC', 'MKC', 'SJM']},
    "Packaging & Containers": {"etf": "XLY", "holdings": ['AVY', 'BALL', 'CCK', 'IP', 'PKG']},
    "Personal Services": {"etf": "XLY", "holdings": ['ROL', 'SCI']},
    "Pollution & Treatment Controls": {"etf": "XLI", "holdings": ['VLTO']},
    "Publishing": {"etf": "XLC", "holdings": ['NYT']},
    "REIT - Diversified": {"etf": "VNQ", "holdings": ['VICI', 'WPC']},
    "REIT - Healthcare Facilities": {"etf": "FREL", "holdings": ['AHR', 'DOC', 'OHI', 'VTR', 'WELL']},
    "REIT - Hotel & Motel": {"etf": "VNQ", "holdings": ['HST']},
    "REIT - Industrial": {"etf": "INDS", "holdings": ['EGP', 'EXR', 'PLD', 'PSA']},
    "REIT - Mortgage": {"etf": "REM", "holdings": ['AGNC', 'NLY']},
    "REIT - Office": {"etf": "FREL", "holdings": ['BXP']},
    "REIT - Residential": {"etf": "REZ", "holdings": ['AMH', 'CPT', 'ELS', 'ESS', 'INVH', 'MAA', 'SUI', 'UDR', 'VMRK']},
    "REIT - Retail": {"etf": "RTL", "holdings": ['FRT', 'KIM', 'O', 'REG', 'SPG']},
    "REIT - Specialty": {"etf": "VNQ", "holdings": ['AMT', 'CCI', 'DLR', 'EQIX', 'GLPI', 'IRM', 'LAMR', 'SBAC', 'WY']},
    "Railroads": {"etf": "RAIL", "holdings": ['CP', 'CSX', 'NSC', 'UNP', 'WAB']},
    "Real Estate Services": {"etf": "XLRE", "holdings": ['CBRE', 'CSGP', 'JLL']},
    "Rental & Leasing Services": {"etf": "XLI", "holdings": ['SUNB', 'UHAL', 'UHAL-B', 'URI']},
    "Residential Construction": {"etf": "XLY", "holdings": ['DHI', 'LEN', 'NVR', 'PHM', 'TOL']},
    "Resorts & Casinos": {"etf": "XLY", "holdings": ['LVS', 'MGM']},
    "Restaurants": {"etf": "PBJ", "holdings": ['CMG', 'DPZ', 'DRI', 'MCD', 'QSR', 'SBUX', 'TXRH', 'YUM']},
    "Scientific & Technical Instruments": {"etf": "XLK", "holdings": ['CGNX', 'COHR', 'FTV', 'KEYS', 'MKSI', 'TDY', 'TRMB']},
    "Semiconductor Equipment & Materials": {"etf": "SMH", "holdings": ['AMAT', 'AMKR', 'ENTG', 'KLAC', 'LRCX', 'ONTO', 'Q', 'TER']},
    "Semiconductors": {"etf": "SOXX", "holdings": ['ADI', 'ALAB', 'AMD', 'AVGO', 'CBRS', 'GFS', 'INTC', 'LSCC', 'MCHP', 'MPWR', 'MRVL', 'MTSI', 'MU', 'NVDA', 'ON', 'QCOM', 'SITM', 'SMTC', 'SWKS', 'TXN']},
    "Software - Application": {"etf": "IGV", "holdings": ['ADBE', 'ADP', 'ADSK', 'BSY', 'CDNS', 'CHYM', 'CRM', 'DDOG', 'DOCU', 'DT', 'FICO', 'FIG', 'FROG', 'GWRE', 'HUBS', 'INTU', 'MANH', 'MSTR', 'NOW', 'PAYC', 'PAYX', 'PTC', 'QNT', 'ROP', 'SNOW', 'SSNC', 'STRC', 'TEAM', 'TYL', 'U', 'UBER', 'WDAY', 'ZM']},
    "Software - Infrastructure": {"etf": "IGV", "holdings": ['AKAM', 'CPAY', 'CRWD', 'CRWV', 'DOCN', 'FFIV', 'FTNT', 'GDDY', 'GEN', 'GPN', 'IOT', 'MDB', 'MSFT', 'NET', 'NTAP', 'NTNX', 'OKTA', 'ORCL', 'PANW', 'PLTR', 'RBRK', 'SAIL', 'SNPS', 'TOST', 'TWLO', 'VRSN', 'XYZ', 'ZS']},
    "Solar": {"etf": "TAN", "holdings": ['FSLR', 'NXT']},
    "Specialty Business Services": {"etf": "XLI", "holdings": ['ARMK', 'CPRT', 'CTAS', 'RBA', 'ULS']},
    "Specialty Chemicals": {"etf": "XLB", "holdings": ['ALB', 'APD', 'DD', 'ECL', 'IFF', 'PPG', 'RPM', 'SHW']},
    "Specialty Industrial Machinery": {"etf": "XLI", "holdings": ['AME', 'CMI', 'CR', 'DCI', 'DOV', 'EMR', 'GEV', 'GGG', 'GNRC', 'IEX', 'IR', 'ITT', 'ITW', 'NDSN', 'OTIS', 'PH', 'ROK', 'RRX', 'SYM', 'WTS', 'XYL']},
    "Specialty Retail": {"etf": "XRT", "holdings": ['BBY', 'CASY', 'DKS', 'FIVE', 'TSCO', 'ULTA', 'WSM']},
    "Steel": {"etf": "SLX", "holdings": ['NUE', 'RS', 'STLD']},
    "Telecom Services": {"etf": "IYZ", "holdings": ['CHTR', 'CMCSA', 'ECHO', 'GSAT', 'T', 'TMUS', 'VZ']},
    "Tobacco": {"etf": "XLP", "holdings": ['MO', 'PM']},
    "Tools & Accessories": {"etf": "XLI", "holdings": ['LECO', 'RBC', 'SNA', 'SWK']},
    "Travel Services": {"etf": "XLY", "holdings": ['ABNB', 'BKNG', 'CCL', 'EXPE', 'RCL']},
    "Trucking": {"etf": "IYT", "holdings": ['KNX', 'ODFL', 'XPO']},
    "Utilities - Diversified": {"etf": "XLU", "holdings": ['AES', 'SRE']},
    "Utilities - Independent Power Producers": {"etf": "XLU", "holdings": ['CEG', 'NRG', 'TLN', 'VST']},
    "Utilities - Regulated Electric": {"etf": "XLU", "holdings": ['AEE', 'AEP', 'CMS', 'CNP', 'D', 'DTE', 'DUK', 'DUKU', 'ED', 'EIX', 'ES', 'ETR', 'EVRG', 'EXC', 'FE', 'LNT', 'NEE', 'PCG', 'PEG', 'PNW', 'PPL', 'SO', 'WEC', 'XEL']},
    "Utilities - Regulated Gas": {"etf": "XLU", "holdings": ['ATO', 'NI']},
    "Utilities - Regulated Water": {"etf": "XLU", "holdings": ['AWK', 'WTRG']},
    "Waste Management": {"etf": "EVX", "holdings": ['CLH', 'GFL', 'RSG', 'WM']},
}

# ── BENCHMARKS extendidos ────────────────────────────────────────────────────
BENCHMARK = {
    # USA — Indices nativos Polygon (fallback automatico a ETF si no disponibles)
    "S&P 500":          "I:SPX", "Nasdaq 100":    "I:NDX",
    "Russell 2000":     "I:RUT", "Dow Jones":     "I:DJI",
    "Mid Cap (S&P400)": "MDY",   "VIX":           "I:VIX",
    # Crypto (precio nativo Polygon, no ETF — evita distorsión de precio)
    "Bitcoin":          "X:BTCUSD", "Ethereum":      "X:ETHUSD",
    # Commodities (ETFs proxy, disponibles en Polygon)
    "Gold":             "GLD",   "Silver":        "SLV",
    "Oil (WTI)":        "USO",   "Natural Gas":   "UNG",
    "Copper":           "CPER",
    # Bonds / tipos
    "Treasury 20Y":     "TLT",   "High Yield":    "HYG",
    "T-Bond 10Y Yield": "IEF",   "T-Bond 2Y Yield":"SHY",
    # Europa — DAX e IBEX usan EODHD nativo via fallback; CAC y FTSE forzados a EODHD
    "DAX (Germany)":    "EWG",   "AEX (Holanda)": "EWN",
    "IBEX 35 (Esp)":    "EWP",
    "Euro Stoxx 50":    "FEZ",
    # Asia — ETFs proxy
    "Nikkei 225":       "EWJ",   "Hang Seng":     "EWH",
    "Shanghai":         "MCHI",  "India (Nifty)": "INDA",
    # FX / alternatives — ETFs proxy
    "EUR/USD":          "C:EURUSD", "US Dollar Idx": "UUP",
    "Real Estate":      "VNQ",
}

# Mapeo: si el indice nativo no devuelve datos, usar este ETF como respaldo
BENCHMARK_FALLBACK = {
    "I:SPX": "SPY", "I:NDX": "QQQ", "I:RUT": "IWM", "I:DJI": "DIA", "I:VIX": "VIXY",
}

# Plan B (EODHD): solo para los indices internacionales donde el ETF proxy de
# Polygon puede no ser ideal o donde se quiera el indice nativo real en vez
# del proxy. Se activa SOLO si EODHD_API_KEY esta configurada Y Polygon (ni
# su ETF fallback) devolvio datos. Formato ticker EODHD: CODIGO.INDX
BENCHMARK_EODHD_FALLBACK = {
    # Europa / Asia (problema original: yfinance fallaba en Render)
    "EWG": "GDAXI.INDX",      # DAX (Germany)
    "I:VIX": "VIX.INDX",      # VIX real (CBOE Volatility Index)
    "EWN": "AEX.INDX",        # AEX (Holanda)
    "EWP": "IBEX.INDX",       # IBEX 35 (España)
    "EWJ": "N225.INDX",       # Nikkei 225
    "EWH": "HSI.INDX",        # Hang Seng
    "FEZ": "STOXX50E.INDX",   # Euro Stoxx 50
    "C:EURUSD": "EURUSD.FOREX", # EUR/USD real
    "GLD": "GC.COMM",         # Oro spot (COMEX)
    "SLV": "SI.COMM",         # Plata spot (COMEX)
    # USA — indice nativo real en vez del ETF proxy (Polygon I:XXX fallaba
    # con estos en el plan basico, asi que se usan directamente como
    # fuente preferida). El VIX se deja fuera porque I:VIX si funciona bien.
    "I:SPX": "GSPC.INDX",     # S&P 500
    "I:NDX": "NDX.INDX",      # Nasdaq 100
    "I:DJI": "DJI.INDX",      # Dow Jones Industrial Average
    "I:RUT": "RUT.INDX",      # Russell 2000
}

# ── Amplitud de mercado ──────────────────────────────────────────────────────
BREADTH_TICKERS = {
    "SPY":"S&P 500 ETF","QQQ":"Nasdaq 100","IWM":"Russell 2000","DIA":"Dow Jones",
    "VIXY":"VIX ETF","HYG":"High Yield Bonds","TLT":"Treasury 20Y","SHY":"Treasury 2Y",
    "GLD":"Gold","SLV":"Silver","UUP":"US Dollar","USO":"Oil (WTI)",
    "X:BTCUSD":"Bitcoin","GDX":"Gold Miners",
    # NYSE — ^NYA es el indice NYSE Composite real (via EODHD), VTI se deja
    # como estaba por si algo mas lo usa como proxy de mercado total
    "VTI":"NYSE/Total Market Composite",
    "^NYA":"NYSE Composite (indice real)",
    "VIXM":"VIXM (Volatilidad medio plazo)",
    # Macro / Bonds CEF / TIPS / HAA
    "TIP":"TIPS ETF (Inflacion real)",
    "STIP":"TIPS Corto Plazo",
    "AGG":"Aggregate Bonds (AGG)",
    "LQD":"Corp Bonds IG",
    "EMB":"Bonos Emergentes",
    "IEF":"Yield 10Y Tesoro EEUU (proxy ETF)",
    # Sectores
    "XLK":"Tech","XLE":"Energy","XLF":"Financials","XLV":"Healthcare",
    "XLU":"Utilities","XLRE":"Real Estate","XLC":"Communication",
    "XLI":"Industrials","XLY":"Consumer Discret.","XLP":"Consumer Staples",
    "XLB":"Materials",
}

# EODHD: ^NYA no es una accion/ETF, es un indice -> Polygon no lo cubre bien
# en plan basico. Mismo patron que BENCHMARK_EODHD_FALLBACK.
BREADTH_EODHD_FALLBACK = {
    "^NYA": "NYA.INDX",   # NYSE Composite
}

# S&P 500 muestra amplia para amplitud de mercado (~200 tickers)
SP500_SAMPLE = [
    # Mega cap / Top 50
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
    "LLY","V","UNH","XOM","MA","JNJ","PG","HD","COST","MRK",
    "CVX","ABBV","CRM","BAC","ORCL","KO","PEP","TMO","AMD","NFLX",
    "DIS","ADBE","NKE","WMT","CSCO","MCD","ABT","COP","IBM","GE",
    "CAT","GS","HON","SPGI","AMGN","LOW","ISRG","DE","RTX","NOW",
    # Top 51-100
    "QCOM","PFE","TXN","BMY","NEE","UPS","INTU","T","BKNG","AXP",
    "VRTX","LMT","SYK","MDT","MDLZ","CB","ETN","C","ZTS","BSX",
    "SO","REGN","CI","MMC","ADI","WFC","MS","PGR","GILD","CME",
    "AMAT","ELV","SHW","BDX","LRCX","MO","F","GM","NOC","COF",
    "USB","DUK","AON","APD","FCX","TJX","HUM","FDX","SLB","PSA",
    # Top 101-150
    "ECL","WM","NSC","EMR","KLAC","GD","ADP","MCO","PYPL","UBER",
    "ABNB","SNOW","CRWD","DDOG","ZS","NET","PANW","MDB","TTD","SHOP",
    "SQ","AFRM","SOFI","COIN","RIVN","LCID","NIO","XPEV","LI","PLTR",
    "PATH","AI","SOUN","IONQ","RKLB","JOBY","ACHR","SMCI","CAVA","CELH",
    "DASH","DKNG","SNAP","PINS","RBLX","U","MTCH","BMBL","ZG","IAC",
    # Top 151-200
    "NEM","FCX","ALB","MOS","CF","LIN","APD","PPG","IFF","VMC",
    "MLM","NUE","STLD","CLF","CMC","PLD","AMT","EQIX","PSA","O",
    "WELL","DLR","AVB","EQR","WY","SPG","ESS","MAA","VTR","ARE",
    "NEE","SO","DUK","AEP","SRE","XEL","D","ED","EXC","ES",
    "EPD","ET","OKE","WMB","KMI","TRGP","LNG","MPC","PSX","VLO",
]
# Eliminar duplicados preservando orden
_seen = set()
SP500_SAMPLE = [x for x in SP500_SAMPLE if not (x in _seen or _seen.add(x))]


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES DE DESCARGA
# ══════════════════════════════════════════════════════════════════════════════

def fetch_perf(tickers_dict, label="", period="1y"):
    # FIX (10/07/2026): antes se construía un "name_map" ticker->nombre que
    # solo puede guardar UN nombre por ticker — si varias industrias
    # comparten el mismo ETF proxy (ej. XLI usado por Machinery, Rental,
    # Conglomerates y Electrical Equipment), todas acababan mostrando el
    # nombre de la última, generando filas "duplicadas" con nombre erróneo.
    # Ahora se itera directamente sobre (nombre, ticker) y cada industria
    # saca su propia fila con su nombre correcto, aunque comparta ETF con
    # otras — el precio/rendimiento sí es el mismo (es el mismo ETF), pero
    # el nombre ya no se pisa.
    results = []
    tks = list(dict.fromkeys(tickers_dict.values()))  # únicos, sin perder orden — solo para pedir datos una vez por ticker
    print(f"  ↓ {label} ({len(tickers_dict)} industrias/temas, {len(tks)} tickers únicos, Polygon)...")

    # Fuente preferida (Plan A real) para indices validados en EODHD:
    # Europa/Asia (IBEX, DAX, CAC40, FTSE, Nikkei, Hang Seng) + USA
    # (S&P 500, Dow Jones, Russell 2000). Es el indice nativo de verdad
    # (no un ETF proxy), asi que si hay API key se pide primero.
    # Si EODHD_API_KEY no esta configurada, este bloque no hace nada y todo
    # sigue exactamente igual que antes (Polygon como unica fuente).
    raw_bars = {}
    if EODHD_KEY:
        for tk in tks:
            if tk in BENCHMARK_EODHD_FALLBACK:
                eod_tk = BENCHMARK_EODHD_FALLBACK[tk]
                bars = eodhd_aggs_daily(eod_tk, days=400)
                if bars:
                    raw_bars[tk] = bars
                    print(f"    ✓ {tk} ← EODHD {eod_tk} (indice nativo)")

    # Polygon para todo lo demas (US, crypto, commodities, bonos) y como
    # respaldo de los indices internacionales si EODHD no devolvio nada
    tks_pendientes = [tk for tk in tks if tk not in raw_bars]
    raw_bars.update(pg_fetch_many(tks_pendientes, max_workers=8, days=400))

    # Fallback nivel 1: si un indice nativo Polygon (I:XXX) no devolvio datos, probar su ETF equivalente
    for tk in tks:
        if tk not in raw_bars and tk in BENCHMARK_FALLBACK:
            fb = BENCHMARK_FALLBACK[tk]
            bars = pg_aggs_daily(fb, days=400)
            if bars:
                raw_bars[tk] = bars
                print(f"    ↺ {tk} sin datos, usando fallback {fb}")
    # Fallback nivel 2 (EODHD como red de seguridad): por si algun indice
    # internacional no se pidio arriba (ej. sin key en el primer intento) o
    # fallo Polygon+ETF. No toca nada de US/crypto/commodities.
    if EODHD_KEY:
        for tk in tks:
            if tk not in raw_bars and tk in BENCHMARK_EODHD_FALLBACK:
                eod_tk = BENCHMARK_EODHD_FALLBACK[tk]
                bars = eodhd_aggs_daily(eod_tk, days=400)
                if bars:
                    raw_bars[tk] = bars
                    print(f"    ↺ {tk} sin datos (Polygon+ETF), usando EODHD {eod_tk}")

    for name, tk in tickers_dict.items():
        try:
            bars = raw_bars.get(tk)
            if not bars or len(bars) < 2:
                continue
            closes = [b["close"] for b in bars if b["close"] is not None]
            dates  = [b["date"] for b in bars]
            n = len(closes)
            if n < 2:
                continue
            last = float(closes[-1])
            def chg(idx):
                b = closes[idx]
                return round((last/float(b)-1)*100, 2) if b else 0.0
            results.append({
                "name":    name,
                "ticker":  tk,
                "price":   round(last, 2),
                "1D":  chg(-2),
                "1W":  chg(-6)   if n>5   else chg(0),
                "1M":  chg(-22)  if n>21  else chg(0),
                "3M":  chg(-66)  if n>65  else chg(0),
                "6M":  chg(-132) if n>131 else chg(0),
                "1Y":  chg(0),
                "52wHigh": round(float(max(closes)), 2),
                "52wLow":  round(float(min(closes)), 2),
                "distHi":  round((last/float(max(closes))-1)*100, 1),
                "priceHistory": [round(float(v),2) for v in closes[-90:]],
                "priceDates":   dates[-90:],
            })
        except: continue
    results.sort(key=lambda x: x["1D"], reverse=True)
    return results


def fetch_stock_perf():
    """Descarga datos de todas las acciones de sectores e industrias (via Polygon.io)."""
    all_tks = set()
    for d in INDUSTRY_DATA.values(): all_tks.update(d["holdings"])
    for s in SECTOR_STOCKS.values(): all_tks.update(s)
    all_tks.update(SP500_SAMPLE)
    # NUEVO (03/09/2026): sumamos el universo extra (ver comentario junto a
    # UNIVERSO_EXTRA) para que el universo general no se quede corto por
    # haber limpiado INDUSTRY_DATA/SECTOR_STOCKS a solo los 725 de Finviz.
    all_tks.update(UNIVERSO_EXTRA)
    all_tks = list(all_tks)
    print(f"  ↓ Constituyentes: {len(all_tks)} acciones únicas via Polygon (paralelo)...")

    raw_bars = pg_fetch_many(all_tks, max_workers=10, days=400)
    print(f"    ✓ Polygon devolvió datos para {len(raw_bars)}/{len(all_tks)} tickers")

    out = {}
    for tk in all_tks:
        try:
            bars = raw_bars.get(tk)
            if not bars or len(bars) < 5:
                continue
            closes = [b["close"] for b in bars if b["close"] is not None]
            vols   = [b["volume"] for b in bars if b["volume"] is not None]
            opens  = [b["open"] for b in bars]
            highs  = [b["high"] for b in bars]
            lows   = [b["low"] for b in bars]
            dates  = [b["date"] for b in bars]
            if len(closes) < 5:
                continue

            last = float(closes[-1])
            def chg(idx):
                b = closes[idx]
                return round((last/float(b)-1)*100, 2) if b else 0.0

            n = len(closes)
            ma20  = float(sum(closes[-20:]) / 20)   if n>=20  else None
            ma50  = float(sum(closes[-50:]) / 50)   if n>=50  else None
            ma200 = float(sum(closes[-200:]) / 200) if n>=200 else None

            vol_rel = None
            if len(vols) >= 20 and vols[-1] is not None:
                avg = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else sum(vols[-20:]) / 20
                vol_rel = round(float(vols[-1]) / avg, 2) if avg and avg > 0 else None

            hi52 = float(max(closes)); lo52 = float(min(closes))
            new_hi = bool(last >= hi52 * 0.99)
            new_lo = bool(last <= lo52 * 1.01)

            out[tk] = {
                "ticker":  tk,
                "price":   round(last, 2),
                "1D":  chg(-2) if n>1 else 0.0,
                "1W":  chg(-6)  if n>5  else chg(0),
                "1M":  chg(-22) if n>21 else chg(0),
                "3M":  chg(-66) if n>65 else chg(0),
                "1Y":  chg(0),
                "ma20":  round(ma20,2)  if ma20  else None,
                "ma50":  round(ma50,2)  if ma50  else None,
                "ma200": round(ma200,2) if ma200 else None,
                "abv20":  bool(last>ma20)  if ma20  else None,
                "abv50":  bool(last>ma50)  if ma50  else None,
                "abv200": bool(last>ma200) if ma200 else None,
                "52wHigh": round(hi52,2),
                "52wLow":  round(lo52,2),
                "newHi":   new_hi,
                "newLo":   new_lo,
                "volRel":  vol_rel,
                "spark": normalize_spark(closes[-30:]),
                "ohlc":  [{"t": dates[i], "o": opens[i], "h": highs[i],
                           "l": lows[i], "c": closes[i]} for i in range(max(0,n-90), n)],
            }
        except Exception:
            continue
    return out


def _build_ohlc(close_s, op_df, hi_df, lo_df, tk):
    """Construye lista OHLC para los últimos 90 días."""
    ohlc = []
    try:
        for dt in close_s.index[-90:]:
            c = float(close_s.loc[dt])
            o = float(op_df[tk].loc[dt]) if not op_df.empty and tk in op_df.columns else c
            h = float(hi_df[tk].loc[dt]) if not hi_df.empty and tk in hi_df.columns else c
            l = float(lo_df[tk].loc[dt]) if not lo_df.empty and tk in lo_df.columns else c
            ohlc.append({"t":dt.strftime("%Y-%m-%d"),"o":round(o,2),"h":round(h,2),"l":round(l,2),"c":round(c,2)})
    except: pass
    return ohlc


def normalize_spark(prices):
    """Normaliza serie de precios a 0-100 para sparkline."""
    if not prices or len(prices) < 2: return []
    mn, mx = min(prices), max(prices)
    rng = mx - mn
    if rng == 0: return [50] * len(prices)
    return [round((p-mn)/rng*100, 1) for p in prices]


def fetch_breadth_and_amplitude(stock_perf):
    """
    Calcula métricas de amplitud real usando los datos de stock_perf.
    También descarga series de tiempo de instrumentos clave.
    """
    tks = list(BREADTH_TICKERS.keys())
    print(f"  ↓ Amplitud de mercado ({len(tks)} instrumentos, Polygon)...")

    # NYSE Composite (^NYA) es un indice, no una accion/ETF -> EODHD primero
    # si hay key configurada. Mismo patron que en fetch_perf().
    raw_bars = {}
    if EODHD_KEY:
        for tk in tks:
            if tk in BREADTH_EODHD_FALLBACK:
                eod_tk = BREADTH_EODHD_FALLBACK[tk]
                bars = eodhd_aggs_daily(eod_tk, days=400)
                if bars:
                    raw_bars[tk] = bars
                    print(f"    ✓ {tk} ← EODHD {eod_tk} (indice nativo)")

    tks_pendientes = [tk for tk in tks if tk not in raw_bars]
    raw_bars.update(pg_fetch_many(tks_pendientes, max_workers=8, days=400))

    latest, series = {}, {}
    for tk in tks:
        try:
            bars = raw_bars.get(tk)
            if not bars or len(bars) < 2: continue
            closes = [b["close"] for b in bars if b["close"] is not None]
            dates  = [b["date"] for b in bars]
            n = len(closes)
            if n < 2: continue
            last, prev = float(closes[-1]), float(closes[-2])
            chg1d = round((last/prev-1)*100, 2)
            ma50  = float(sum(closes[-50:])/50)   if n>=50  else None
            ma200 = float(sum(closes[-200:])/200) if n>=200 else None
            latest[tk] = {
                "name":  BREADTH_TICKERS.get(tk, tk),
                "price": round(last,2),
                "chg":   chg1d,
                "ma50":  round(ma50,2)  if ma50  else None,
                "ma200": round(ma200,2) if ma200 else None,
                "abv50": bool(last>ma50)  if ma50  else None,
                "abv200":bool(last>ma200) if ma200 else None,
            }
            days = 300 if tk in ('SPY','TIP','QQQ') else 90
            series[tk] = {
                "dates":  dates[-days:],
                "values": [round(float(v),2) for v in closes[-days:]],
            }
        except: continue

    # ── Amplitud REAL usando TODOS los datos de stock_perf ──────────────────
    # sample_sp500 = solo SP500 (200 tickers curados a mano) — se deja
    # disponible por si algo más lo necesita, pero YA NO es la fuente
    # principal de las métricas de amplitud.
    # sample_all   = TODO el universo descargado (~1.343 acciones vía
    # Polygon) — desde el 27/08/2026 esta es la fuente para % sobre MA50/
    # MA200 y nuevos máximos/mínimos, no solo para avanzando/retrocediendo.
    # ANTES (bug real, confirmado por Victor): "% sobre MA50/MA200" y los
    # nuevos máximos/mínimos usaban solo los 200 tickers de SP500_SAMPLE,
    # mientras que avanzando/retrocediendo ya usaba las 1.343 — dando una
    # amplitud incoherente (una métrica con universo grande, la de al lado
    # con uno 6-7 veces más pequeño) sin motivo real para la diferencia.
    sample_sp500 = [v for k,v in stock_perf.items() if k in set(SP500_SAMPLE)]
    sample_all   = list(stock_perf.values())  # todas las acciones descargadas

    # % sobre medias móviles — TODO el universo, no solo SP500
    if sample_all:
        abv50  = [s for s in sample_all if s.get("abv50")  is True]
        abv200 = [s for s in sample_all if s.get("abv200") is True]
        pct50  = round(len(abv50)/len(sample_all)*100,1)
        pct200 = round(len(abv200)/len(sample_all)*100,1)
    else:
        pct50 = pct200 = 0

    # Nuevos máximos / mínimos — TODO el universo, no solo SP500
    new_highs_list = sorted([s["ticker"] for s in sample_all if s.get("newHi")],
                            key=lambda t: stock_perf.get(t,{}).get("1D",0), reverse=True)
    new_lows_list  = sorted([s["ticker"] for s in sample_all if s.get("newLo")],
                            key=lambda t: stock_perf.get(t,{}).get("1D",0))
    new_highs = len(new_highs_list)
    new_lows  = len(new_lows_list)

    # Distribución de retornos diarios — TODAS las acciones del universo
    returns_1d = [s.get("1D",0) for s in sample_all if s.get("1D") is not None]
    dist_buckets = {
        "<-10%":0, "-10a-5%":0, "-5a-2%":0, "-2a0%":0,
        "0a2%":0, "2a5%":0, "5a10%":0, ">10%":0
    }
    for r in returns_1d:
        if   r < -10: dist_buckets["<-10%"]  += 1
        elif r < -5:  dist_buckets["-10a-5%"] += 1
        elif r < -2:  dist_buckets["-5a-2%"]  += 1
        elif r <  0:  dist_buckets["-2a0%"]   += 1
        elif r <  2:  dist_buckets["0a2%"]    += 1
        elif r <  5:  dist_buckets["2a5%"]    += 1
        elif r < 10:  dist_buckets["5a10%"]   += 1
        else:         dist_buckets[">10%"]    += 1

    # Avanzando / retrocediendo — TODAS las acciones del universo
    adv  = sum(1 for s in sample_all if (s.get("1D") or 0) > 0)
    dec  = sum(1 for s in sample_all if (s.get("1D") or 0) < 0)
    unch = len(sample_all) - adv - dec

    # Alias para compatibilidad con score
    sample = sample_sp500

    # A/D Line: acumulado de (avances - descensos) últimos 90 días
    # Aproximamos con sectores ETFs diarios
    ad_line = []
    try:
        spy_s = series.get("SPY", {})
        if spy_s:
            n = len(spy_s["dates"])
            spy_vals = spy_s["values"]
            # Use sector ETF daily changes as proxy
            sector_tks = ["XLK","XLF","XLV","XLY","XLP","XLE","XLI","XLB","XLRE","XLU","XLC"]
            cumad = 0
            for i in range(1, min(n, 90)):
                up,dn = 0,0
                for stk in sector_tks:
                    sv = series.get(stk,{}).get("values",[])
                    if len(sv)>i and sv[i-1]>0:
                        chg = (sv[i]-sv[i-1])/sv[i-1]
                        if chg>0: up+=1
                        else: dn+=1
                cumad += (up-dn)
                ad_line.append({"date": spy_s["dates"][i], "val": cumad})
    except: pass

    # McClellan Oscillator proxy: EMA19 - EMA39 de avances-descensos diarios
    mcclellan_series = []
    try:
        if len(ad_line) >= 39:
            ad_vals  = [x["val"] for x in ad_line]
            ad_daily = [ad_vals[i]-ad_vals[i-1] for i in range(1, len(ad_vals))]
            def _ema(vals, n):
                k = 2/(n+1); e = vals[0]; result = [e]
                for v in vals[1:]:
                    e = v*k + e*(1-k); result.append(round(e,2))
                return result
            if len(ad_daily) >= 39:
                e19 = _ema(ad_daily, 19); e39 = _ema(ad_daily, 39)
                n   = min(len(e19), len(e39))
                mcclellan_series = [
                    {"date": ad_line[i+1]["date"], "val": round(e19[i]-e39[i],2)}
                    for i in range(n)
                ]
    except: pass

    # Curva 10Y-2Y proxy: retorno relativo TLT vs SHY
    curve_spread = []
    try:
        tlt_s = series.get("TLT",{}).get("values",[])
        shy_s = series.get("SHY",{}).get("values",[])
        dates = series.get("TLT",{}).get("dates",[])
        if tlt_s and shy_s and len(tlt_s)==len(shy_s) and len(tlt_s)>0:
            tlt0, shy0 = tlt_s[0], shy_s[0]
            for i, d in enumerate(dates):
                tlt_ret = (tlt_s[i]/tlt0 - 1) * 100
                shy_ret = (shy_s[i]/shy0 - 1) * 100
                curve_spread.append({"date": d, "val": round(tlt_ret - shy_ret, 2)})
    except: pass

    # NUEVO (03/09/2026): sustituir avanzan/retroceden, %MA50/200, nuevos
    # máx/mín y McClellan por la versión REAL del NYSE completo (Grouped
    # Daily + lista real de tickers NYSE) — reemplaza la aproximación de
    # arriba (basada en 11 ETFs de sector / nuestro universo curado), que
    # es la razón confirmada de que no coincidiera con fuentes oficiales.
    # Si algo falla (Polygon caído, plan sin acceso a Grouped Daily, etc.),
    # se cae automáticamente a los valores aproximados de arriba — nunca
    # se rompe el resto del dashboard por esto.
    _real = fetch_nyse_breadth_real()
    if _real:
        adv, dec, unch = _real["advancing"], _real["declining"], _real["unchanged"]
        pct50, pct200 = _real["pct_abv50"], _real["pct_abv200"]
        new_highs, new_lows = _real["new_highs"], _real["new_lows"]
        new_highs_list, new_lows_list = _real["new_highs_list"], _real["new_lows_list"]
        mcclellan_series = _real["mcclellan"]
        total_sample_real = _real["total_sample"]
    else:
        total_sample_real = None  # se usará len(sample_all) como antes, mas abajo

    # ── SCORE 0-100 ──────────────────────────────────────────────────────────
    score_components = []
    # % sobre MA50 (0-25 pts)
    score_components.append(min(25, pct50 * 0.25))
    # % sobre MA200 (0-20 pts)
    score_components.append(min(20, pct200 * 0.20))
    # Nuevos máximos vs mínimos (0-15 pts)
    total_nh = new_highs + new_lows
    if total_nh > 0:
        score_components.append(min(15, (new_highs/total_nh)*15))
    else: score_components.append(7)
    # VIX (bajo=bueno) (0-15 pts)
    vix = latest.get("I:VIX",{}).get("price") or latest.get("VIXY",{}).get("price", 20)
    if   isinstance(vix,(int,float)) and vix < 15: score_components.append(15)
    elif isinstance(vix,(int,float)) and vix < 20: score_components.append(12)
    elif isinstance(vix,(int,float)) and vix < 25: score_components.append(7)
    else: score_components.append(3)
    # HYG risk-on (0-10 pts)
    hyg_chg = latest.get("HYG",{}).get("chg",0)
    score_components.append(10 if hyg_chg>0 else 3)
    # McClellan: positivo=alcista (0-10 pts)
    mcc_last = mcclellan_series[-1]["val"] if mcclellan_series else 0
    if   mcc_last >  50: score_components.append(10)
    elif mcc_last >   0: score_components.append(7)
    elif mcc_last > -50: score_components.append(3)
    else: score_components.append(0)
    # Nuevos mínimos penalizan (0-5 pts, penaliza si hay muchos mínimos)
    if total_nh > 0:
        score_components.append(max(0, 5 - round(new_lows/max(new_highs,1)*5)))
    else: score_components.append(3)

    market_score = int(sum(score_components))
    score_label  = ("Defensivo" if market_score<30 else
                   "Neutral Bajista" if market_score<45 else
                   "Neutral" if market_score<55 else
                   "Neutral Alcista" if market_score<65 else
                   "Ofensivo" if market_score<80 else
                   "Ofensivo Pleno")

    sc = [latest.get(t,{}).get("chg",0) for t in
          ["XLK","XLV","XLF","XLY","XLP","XLE","XLI","XLB","XLRE","XLU","XLC"]]

    latest["__summary__"] = {
        "up_sectors":    sum(1 for c in sc if c>0),
        "down_sectors":  sum(1 for c in sc if c<0),
        "vix":           latest.get("I:VIX",{}).get("price") or latest.get("VIXY",{}).get("price","N/A"),
        "vix_chg":       latest.get("I:VIX",{}).get("chg") or latest.get("VIXY",{}).get("chg",0),
        "spy_chg":       latest.get("SPY",{}).get("chg",0),
        "spy_price":     latest.get("SPY",{}).get("price","N/A"),
        "gspc_price":    latest.get("SPY",{}).get("price",None),
        "gspc_chg":      latest.get("SPY",{}).get("chg",None),
        "hyg_chg":       hyg_chg,
        "tlt_chg":       latest.get("TLT",{}).get("chg",0),
        "uup_chg":       latest.get("UUP",{}).get("chg",0),
        "gld_chg":       latest.get("GLD",{}).get("chg",0),
        "uso_chg":       latest.get("USO",{}).get("chg",0),
        # NYSE
        "nyse_price":    latest.get("^NYA",{}).get("price","N/A"),
        "nyse_chg":      latest.get("^NYA",{}).get("chg",0),
        # Macro / Bonos / Inflación
        "tip_chg":       latest.get("TIP",{}).get("chg",0),
        "tip_price":     latest.get("TIP",{}).get("price","N/A"),
        "agg_chg":       latest.get("AGG",{}).get("chg",0),
        "lqd_chg":       latest.get("LQD",{}).get("chg",0),
        "tnx_price":     latest.get("^TNX",{}).get("price","N/A"),
        "tnx_chg":       latest.get("^TNX",{}).get("chg",0),
        "irx_price":     latest.get("^IRX",{}).get("price","N/A"),
        "irx_chg":       latest.get("^IRX",{}).get("chg",0),
        "emb_chg":       latest.get("EMB",{}).get("chg",0),
        # Amplitud real
        "pct_abv50":     pct50,
        "pct_abv200":    pct200,
        "new_highs":     new_highs,
        "new_lows":      new_lows,
        "new_highs_list": new_highs_list[:25],
        "new_lows_list":  new_lows_list[:25],
        "advancing":     adv,
        "declining":     dec,
        "unchanged":     unch,
        "total_sample":  total_sample_real if total_sample_real is not None else len(sample_all),
        "total_sp500":   len(sample_sp500),
        "dist_buckets":  dist_buckets,
        "ad_line":       ad_line[-60:] if len(ad_line)>60 else ad_line,
        "mcclellan":     mcclellan_series[-60:] if len(mcclellan_series)>60 else mcclellan_series,
        "curve_spread":  curve_spread[-60:] if len(curve_spread)>60 else curve_spread,
        "score":         market_score,
        "score_label":   score_label,
    }
    return latest, series


def fetch_stock_info(tickers_sample):
    """Descarga info fundamental en paralelo via Polygon.io (detalles + financials)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"  ↓ Fundamentales ({len(tickers_sample)} acciones, Polygon paralelo)...")
    out = {}

    def _fetch_one(tk):
        try:
            # 1) Detalles de la compañía (nombre, sector, market cap, empleados...)
            details = pg_get(f"/v3/reference/tickers/{tk}")
            d = details.get("results", {}) if details else {}
            if not d:
                return tk, None
            sic_desc = d.get("sic_description", "")
            mkt_cap  = d.get("market_cap")

            # 2) Snapshot para precio actual y variación diaria
            snap = pg_get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{tk}")
            snap_t = (snap.get("ticker", {}) or {}) if snap else {}
            day_data = snap_t.get("day", {}) or {}
            prev_day = snap_t.get("prevDay", {}) or {}
            last_price = day_data.get("c") or prev_day.get("c")

            # 3) Financials (income statement / balance sheet más reciente, anual)
            fin = pg_get(f"/vX/reference/financials", {"ticker": tk, "limit": 1, "timeframe": "annual"})
            fin_results = (fin.get("results", []) if fin else []) or []
            financials = fin_results[0].get("financials", {}) if fin_results else {}

            income   = financials.get("income_statement", {}) or {}
            balance  = financials.get("balance_sheet", {}) or {}
            cashflow = financials.get("cash_flow_statement", {}) or {}

            def _v(d_, key):
                node = d_.get(key, {})
                return node.get("value") if isinstance(node, dict) else None

            revenue   = _v(income, "revenues")
            net_inc   = _v(income, "net_income_loss")
            gross_p   = _v(income, "gross_profit")
            op_inc    = _v(income, "operating_income_loss")
            eps_basic = _v(income, "basic_earnings_per_share")
            assets    = _v(balance, "assets")
            equity    = _v(balance, "equity")
            liab      = _v(balance, "liabilities")
            fcf       = _v(cashflow, "net_cash_flow")

            pe = round(last_price / eps_basic, 2) if (last_price and eps_basic and eps_basic != 0) else None
            gross_marg = round(gross_p / revenue, 4) if (gross_p and revenue) else None
            op_marg    = round(op_inc / revenue, 4) if (op_inc and revenue) else None
            net_marg   = round(net_inc / revenue, 4) if (net_inc and revenue) else None
            roe        = round(net_inc / equity, 4) if (net_inc and equity) else None
            roa        = round(net_inc / assets, 4) if (net_inc and assets) else None
            debt_eq    = round(liab / equity, 2) if (liab and equity) else None
            ps         = round(mkt_cap / revenue, 2) if (mkt_cap and revenue) else None
            pb         = round(mkt_cap / equity, 2) if (mkt_cap and equity) else None

            return tk, {
                "name":        d.get("name", ""),
                "sector":      sic_desc,
                "industry":    sic_desc,
                "mktCap":      mkt_cap,
                "pe":          pe,
                "fwdPE":       None,
                "eps":         eps_basic,
                "fwdEps":      None,
                "revGrowth":   None,
                "epsGrowth":   None,
                "divYield":    None,
                "beta":        None,
                "analyst":     None,
                "nAnalysts":   None,
                "targetMean":  None,
                "grossMarg":   gross_marg,
                "opMarg":      op_marg,
                "netMarg":     net_marg,
                "roe":         roe,
                "roa":         roa,
                "debtEq":      debt_eq,
                "currentRatio":None,
                "revenue":     revenue,
                "ebitda":      None,
                "fcf":         fcf,
                "peg":         None,
                "pb":          pb,
                "ps":          ps,
                "employees":   d.get("total_employees"),
                "country":     d.get("locale","").upper(),
                "exchange":    d.get("primary_exchange",""),
                "website":     d.get("homepage_url",""),
                "summary":     (d.get("description","") or "")[:600],
            }
        except: return tk, None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_one, tk): tk for tk in tickers_sample}
        for future in as_completed(futures):
            try:
                tk, data = future.result()
                if data: out[tk] = data
            except: pass
    print(f"    → {len(out)} acciones con fundamentales")
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  MASSIVE — add-on "Financials & Ratios" ($29/m, activo desde julio 2026)
#  Endpoint nuevo, distinto dominio de Polygon. Ratios ya calculados (TTM,
#  EOD) en una sola llamada por ticker: PE, PB, PS, P/CF, P/FCF, div yield,
#  ROA, ROE, debt/equity, current/quick/cash ratio, EV/Sales, EV/EBITDA,
#  enterprise value, FCF. Confirmado via curl en Render shell (04/07/2026).
#  Se guarda en un diccionario aparte (ratios_data) — NO sustituye ni toca
#  fetch_stock_info() ni el dict stock_info que ya usa el resto del dashboard.
# ══════════════════════════════════════════════════════════════════════════════
MASSIVE_BASE = "https://api.massive.com"

def massive_get(path, params=None, retries=3, timeout=15):
    """GET a Massive (mismo API key que Polygon) con reintentos suaves para 429."""
    p = dict(params or {})
    p["apiKey"] = POLYGON_KEY
    for attempt in range(retries):
        try:
            r = requests.get(f"{MASSIVE_BASE}{path}", params=p, timeout=timeout)
            if r.status_code == 429:
                time.sleep(6)
                continue
            if r.status_code == 200:
                return r.json()
            return {}
        except Exception:
            if attempt == retries - 1:
                return {}
            time.sleep(2)
    return {}


def fetch_ratios(tickers_sample):
    """Descarga en paralelo los ratios TTM del add-on Financials & Ratios
    (Massive). Devuelve un dict {ticker: {...}} independiente de stock_info,
    pensado para el screener tipo Finviz (filtrar por ROE, ROA, PER, deuda...)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"  ↓ Ratios TTM ({len(tickers_sample)} acciones, Massive Financials&Ratios)...")
    out = {}

    def _fetch_one(tk):
        try:
            data = massive_get("/stocks/financials/v1/ratios", {"ticker": tk})
            results = (data.get("results") if data else None) or []
            if not results:
                return tk, None
            r = results[0]
            return tk, {
                "date":        r.get("date"),
                "price":       r.get("price"),
                "avgVolume":   r.get("average_volume"),
                "mktCap":      r.get("market_cap"),
                "eps":         r.get("earnings_per_share"),
                "pe":          r.get("price_to_earnings"),
                "pb":          r.get("price_to_book"),
                "ps":          r.get("price_to_sales"),
                "pcf":         r.get("price_to_cash_flow"),
                "pfcf":        r.get("price_to_free_cash_flow"),
                "divYield":    r.get("dividend_yield"),
                "roa":         r.get("return_on_assets"),
                "roe":         r.get("return_on_equity"),
                "debtEq":      r.get("debt_to_equity"),
                "currentRatio":r.get("current"),
                "quickRatio":  r.get("quick"),
                "cashRatio":   r.get("cash"),
                "evSales":     r.get("ev_to_sales"),
                "evEbitda":    r.get("ev_to_ebitda"),
                "ev":          r.get("enterprise_value"),
                "fcf":         r.get("free_cash_flow"),
            }
        except Exception:
            return tk, None

    # max_workers=20: el plan pagado de Massive no tiene límite de requests/min
    # (solo el tier gratuito, 5/min). Con ~1.300 tickers, 8 workers sería lento.
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(_fetch_one, tk): tk for tk in tickers_sample}
        done_count = 0
        for future in as_completed(futures):
            try:
                tk, data = future.result()
                if data: out[tk] = data
            except Exception:
                pass
            done_count += 1
            if done_count % 200 == 0:
                print(f"    ... {done_count}/{len(tickers_sample)} tickers (ratios)")
    print(f"    → {len(out)} acciones con ratios (Financials & Ratios)")
    return out


# ══════════════════════════════════════════════════════════════════════════════
#  EXTRA FUNDAMENTALES (05/07/2026) — Float, Short Interest, crecimiento YoY
#  (ventas/EPS calculado a mano desde income-statements trimestral) y tipo de
#  ticker (ADR) + empleados desde v3/reference/tickers (dominio Polygon, ya
#  incluido en tu Starter). Todo verificado contra la doc oficial de Massive
#  antes de escribir esto — no es un endpoint adivinado.
#  Se fusiona en el mismo dict que ratios_data (por ticker), no lo sustituye.
#
#  CACHÉ EN DISCO (esto es lo que soluciona los >10 min de carga): Float, ADR,
#  empleados y crecimiento YoY casi no cambian de un día para otro — Short
#  Interest ni siquiera se actualiza más que cada 2 semanas (FINRA). Así que
#  se guardan en extra_fundamentals_cache.json con fecha, y solo se refrescan
#  si han caducado (por defecto 72h). En la práctica: la primera vez tarda lo
#  mismo, pero de ahí en adelante la mayoría de runs reutilizan caché y solo
#  se hacen llamadas nuevas para tickers vencidos o nunca vistos.
# ══════════════════════════════════════════════════════════════════════════════
EXTRA_CACHE_HOURS = 72  # sube esto si quieres refrescar con menos frecuencia aún

def fetch_extra_fundamentals(tickers_sample, cache_hours=EXTRA_CACHE_HOURS):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from datetime import datetime, timezone

    cache_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extra_fundamentals_cache.json")
    cache = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    now = datetime.now(timezone.utc)
    to_fetch, reused = [], {}
    for tk in tickers_sample:
        entry = cache.get(tk)
        if entry and entry.get("_cachedAt"):
            try:
                cached_at = datetime.fromisoformat(entry["_cachedAt"])
                age_h = (now - cached_at).total_seconds() / 3600
                if age_h < cache_hours:
                    reused[tk] = {k: v for k, v in entry.items() if k != "_cachedAt"}
                    continue
            except Exception:
                pass
        to_fetch.append(tk)

    print(f"  ↓ Extra: float, short interest, crecimiento YoY, ADR — "
          f"{len(reused)} en caché (<{cache_hours}h), {len(to_fetch)} a refrescar de {len(tickers_sample)}...")
    out = dict(reused)

    def _one(tk):
        d = {}
        # Free Float — incluido en TODOS los planes de Massive, sin coste extra
        try:
            fl = massive_get("/stocks/vX/float", {"ticker": tk, "limit": 1})
            recs = (fl.get("results") or []) if fl else []
            if recs:
                d["freeFloat"]    = recs[0].get("free_float")
                d["freeFloatPct"] = recs[0].get("free_float_percent")
        except Exception:
            pass
        # Short Interest — mismo grupo "Fundamentals" que Ratios (no confirmado
        # al 100%, pero falla en silencio si no hay acceso: no rompe nada)
        try:
            si = massive_get("/stocks/v1/short-interest",
                              {"ticker": tk, "limit": 1, "sort": "settlement_date.desc"})
            recs = (si.get("results") or []) if si else []
            if recs:
                d["shortInterest"] = recs[0].get("short_interest")
                d["daysToCover"]   = recs[0].get("days_to_cover")
        except Exception:
            pass
        # Crecimiento YoY (ventas y EPS) — calculado a mano: trimestre actual
        # vs mismo trimestre año anterior (4 trimestres atrás), sobre 8 trimestres
        # descargados. Confirmado incluido en Financials & Ratios Expansion.
        try:
            inc = massive_get("/stocks/financials/v1/income-statements",
                               {"tickers": tk, "timeframe": "quarterly",
                                "limit": 8, "sort": "period_end.desc"})
            recs = (inc.get("results") or []) if inc else []
            if len(recs) >= 5:
                rev_now, rev_prev = recs[0].get("revenue"), recs[4].get("revenue")
                eps_now, eps_prev = recs[0].get("diluted_earnings_per_share"), recs[4].get("diluted_earnings_per_share")
                if rev_now is not None and rev_prev:
                    d["revGrowth"] = (rev_now - rev_prev) / abs(rev_prev)
                if eps_now is not None and eps_prev:
                    d["epsGrowth"] = (eps_now - eps_prev) / abs(eps_prev)
            if recs:
                # Gross Margin — mismo endpoint, mismo call, sin coste extra
                gp, rev = recs[0].get("gross_profit"), recs[0].get("revenue")
                if gp is not None and rev:
                    d["grossMargin"] = gp / rev
        except Exception:
            pass
        # Tipo de ticker (ADR) y empleados — dominio Polygon, ya en tu Starter
        try:
            meta = pg_get(f"/v3/reference/tickers/{tk}")
            mres = meta.get("results") if meta else None
            if mres:
                ttype = mres.get("type")
                d["tickerType"] = ttype
                d["isADR"]      = ttype in ("ADRC", "ADRP", "ADRW", "ADRR")
                d["employees"]  = mres.get("total_employees")
        except Exception:
            pass
        return tk, d

    if to_fetch:
        # max_workers=40: solo se usa para los tickers vencidos/nuevos, no
        # para el universo completo — con caché, la mayoría de runs no
        # entran aquí apenas.
        with ThreadPoolExecutor(max_workers=40) as executor:
            futures = {executor.submit(_one, tk): tk for tk in to_fetch}
            done_count = 0
            for future in as_completed(futures):
                try:
                    tk, d = future.result()
                    if d:
                        out[tk] = d
                        cache[tk] = {**d, "_cachedAt": now.isoformat()}
                except Exception:
                    pass
                done_count += 1
                if done_count % 200 == 0:
                    print(f"    ... {done_count}/{len(to_fetch)} tickers (extra, refrescando)")
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except Exception:
            pass

    print(f"    → {len(out)} acciones con datos extra "
          f"({len(reused)} de caché, {len(to_fetch)} refrescadas)")
    return out


def build_email_summary(stock_perf, top_n=8):
    """Genera (o actualiza) email_summary.json con líderes de RS REALES,
    calculados sobre el mismo universo del dashboard (~1.300 tickers).

    Antes de esto, server.py -> get_top_rs_stocks() buscaba una clave
    "top_rs" en email_summary.json que NUNCA se generaba, así que caía
    siempre al fallback hardcodeado (NVDA/META/AXON/ORCL/CRWD/PLTR) — de ahí
    que "siempre salieran los mismos". Aquí se calcula de verdad, rankeado
    por 1M — A PROPÓSITO distinto del resto del dashboard (que usa 1Y y no
    se toca) — para que el email rote más semana a semana.

    No sobreescribe el fichero entero: si ya existiera con otras claves
    (p.ej. "score" para los semáforos), se preservan y solo se actualiza
    "top_rs".
    """
    ticker_sector = {}
    for sec_name, tks in SECTOR_STOCKS.items():
        for tk in tks:
            ticker_sector.setdefault(tk, sec_name)

    # OJO: esto usa 1M a propósito, distinto del resto del dashboard (que usa
    # 1Y y NO se toca). Es solo para el email, para que el top_rs rote semana
    # a semana en vez de quedarse siempre con los mismos ganadores estructurales.
    valid = [r for r in stock_perf.values()
             if r.get("1M") is not None and (r.get("price") or 0) >= 5]
    valid.sort(key=lambda r: r.get("1M", 0))  # ascendente, para poder sacar el rank/percentil
    n = len(valid)

    top_sorted = sorted(valid, key=lambda r: r.get("1M", 0), reverse=True)[:top_n]
    top_rs = []
    for r in top_sorted:
        rank = valid.index(r)
        rs_pct = round(rank / n * 100) if n else 0
        top_rs.append({
            "ticker":  r.get("ticker"),
            "rs":      rs_pct,
            "sector":  ticker_sector.get(r.get("ticker"), "—"),
            "pct_1w":  round(r.get("1W", 0) or 0, 2),
        })

    summary_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email_summary.json")
    existing = {}
    if os.path.exists(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    existing["top_rs"] = top_rs
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    # Escritura real: Supabase (app_state), compartida entre servicios —
    # el fichero local de arriba es solo respaldo/depuración.
    if SUPABASE_KEY:
        try:
            h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
                 "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
            r = requests.post(f"{SUPABASE_URL}/rest/v1/app_state",
                               headers=h, json={"key": "email_summary", "value": existing}, timeout=15)
            print(f"✓ email_summary guardado en Supabase (app_state): {r.status_code}")
        except Exception as e:
            print(f"⚠️ Error guardando email_summary en Supabase: {e}")
    else:
        print("⚠️ SUPABASE_KEY no configurada en este servicio — el email seguirá usando el fallback hardcodeado hasta que se añada.")
    print(f"✓ email_summary.json actualizado — {len(top_rs)} líderes RS (1M, solo para el email) → {summary_path}")
    return top_rs


# ══════════════════════════════════════════════════════════════════════════════
#  SETUPS DIARIOS + SCANNER — MIGRADO A PYTHON. Traducción fiel de
#  detectSetup()/calcAtrMultiple()/smaLast() y de runScanner()/runSetup(),
#  que antes vivían en el JS del navegador (visibles con "Ver código
#  fuente"). Aquí ya no lo son — el navegador solo recibe el resultado ya
#  calculado, vía /api/setups y /api/scanner en server.py.
#  stock_perf[tk]["ohlc"] ya trae 90 días de O/H/L/C reales.
# ══════════════════════════════════════════════════════════════════════════════

def sma_last(arr, period):
    if len(arr) < period:
        return None
    return sum(arr[-period:]) / period


def calc_atr_multiple(ohlc):
    n = len(ohlc)
    if n < 51:
        return None
    closes = [c["c"] for c in ohlc]
    highs  = [c["h"] for c in ohlc]
    lows   = [c["l"] for c in ohlc]
    sma50 = sum(closes[-50:]) / 50
    tr_sum = 0.0
    for i in range(n - 14, n):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i-1]) if i > 0 else tr1
        tr3 = abs(lows[i] - closes[i-1]) if i > 0 else tr1
        tr_sum += max(tr1, tr2, tr3)
    atr14 = tr_sum / 14
    if not atr14:
        return None
    return (closes[n-1] - sma50) / atr14


SETUP_MODES = ['htf', 'hvc', 'gap', 'breakout', 'ma_support', 'ur', 'inside', 'ma_reject', 'cup_handle', 'euforia']

def detect_setup(r, mode):
    ohlc = r.get("ohlc")
    if not ohlc or len(ohlc) < 31:
        return None
    n = len(ohlc)
    last, prev = ohlc[n-1], ohlc[n-2]
    closes = [c["c"] for c in ohlc]
    highs  = [c["h"] for c in ohlc]
    lows   = [c["l"] for c in ohlc]
    gap_pct = ((last["o"]/prev["c"]-1)*100) if prev.get("c") else 0

    if mode == 'htf':
        if n < 60: return None
        c60 = closes[n-60]
        run_pct = ((last["c"]/c60-1)*100) if c60 else 0
        hi252 = r.get("52wHigh") or max(highs)
        near_high = hi252 and (last["c"] >= hi252*0.90) and (last["c"] < hi252)
        atr14 = sum(highs[i]-lows[i] for i in range(n-14, n)) / 14
        atr_pct = (atr14/last["c"]*100) if last["c"] else 0
        r20 = closes[-20:]
        r20hi, r20lo = max(r20), min(r20)
        consolidating = ((r20hi/r20lo-1)*100 < 25) if r20lo > 0 else False
        if run_pct >= 80 and near_high and atr_pct < 12 and consolidating:
            return {"detail": f"+{run_pct:.1f}% (60d) · ATR {atr_pct:.1f}% · {((1-last['c']/hi252)*100):.1f}% del máx"}
        return None

    if mode == 'hvc':
        if n < 3: return None
        c0, c1, c2 = last["c"], prev["c"], ohlc[n-3]["c"]
        if not c2: return None
        gap = ((c1/c2-1)*100)
        if gap < 7: return None
        if c0 < c1:
            return {"detail": f"Gap día anterior +{gap:.1f}% · hoy cerró por debajo (${c1:.2f})"}
        return None

    if mode == 'gap':
        if gap_pct >= 7:
            return {"detail": f"Gap apertura: +{gap_pct:.1f}%"}
        return None

    if mode == 'breakout':
        if n < 21: return None
        max20prev = max(highs[-21:-1])
        vol_rel = r.get("volRel")
        if last["h"] > max20prev and last["c"] > max20prev and vol_rel and vol_rel >= 1.3:
            return {"detail": f"Vol {vol_rel}x · ruptura ${max20prev:.2f}"}
        return None

    if mode == 'ma_support':
        if n < 50: return None
        ma10, ma20, ma50 = sma_last(closes,10), sma_last(closes,20), sma_last(closes,50)
        if not ma10 or not ma20 or not ma50: return None
        if not (ma10 > ma20 > ma50): return None
        dist_ma10 = abs(last["l"]-ma10)/ma10*100
        dist_ma20 = abs(last["l"]-ma20)/ma20*100
        if dist_ma10 < 1.2 and last["c"] > ma10 and last["c"] > last["o"]:
            return {"detail": f"Apoyo en MA10 (${ma10:.2f}) · MA10>MA20>MA50"}
        if dist_ma20 < 1.2 and last["c"] > ma20 and last["c"] > last["o"]:
            return {"detail": f"Apoyo en MA20 (${ma20:.2f}) · MA10>MA20>MA50"}
        return None

    if mode == 'ur':
        if n < 31: return None
        min30prev = min(lows[-31:-1])
        if last["l"] < min30prev and last["c"] > last["l"]:
            denom = (min30prev-last["l"])
            recovery = ((last["c"]-last["l"])/denom*100) if denom > 0 else 0
            return {"detail": f"Recuperación {recovery:.0f}% · mín ${min30prev:.2f}"}
        return None

    if mode == 'inside':
        body_hi, body_lo = max(last["o"],last["c"]), min(last["o"],last["c"])
        p_body_hi, p_body_lo = max(prev["o"],prev["c"]), min(prev["o"],prev["c"])
        if body_hi <= p_body_hi and body_lo >= p_body_lo:
            vol_rel = r.get("volRel")
            return {"detail": (f"Vol {vol_rel}x" if vol_rel else "Compresión de rango")}
        return None

    if mode == 'ma_reject':
        ma20, ma50 = r.get("ma20"), r.get("ma50")
        if ma20 and last["h"] >= ma20 and last["c"] < ma20 and last["c"] < last["o"]:
            dist = abs(last["c"]-ma20)/last["c"]*100
            if dist < 5: return {"detail": f"Rechazo MA20 (${ma20:.2f}) · dist {dist:.1f}%"}
        if ma50 and last["h"] >= ma50 and last["c"] < ma50 and last["c"] < last["o"]:
            dist = abs(last["c"]-ma50)/last["c"]*100
            if dist < 5: return {"detail": f"Rechazo MA50 (${ma50:.2f}) · dist {dist:.1f}%"}
        return None

    if mode == 'cup_handle':
        if n < 50: return None
        win = min(80, n)
        seg = closes[-win:]
        seg_highs, seg_lows = highs[-win:], lows[-win:]
        handle_len = max(5, int(win*0.15))
        cup_end = win - handle_len
        if cup_end < 20: return None
        cup_seg = seg[:cup_end]
        cup_highs_seg = seg_highs[:cup_end]
        third_len = cup_end // 3
        left_rim_idx = 0
        for i in range(1, third_len):
            if cup_highs_seg[i] > cup_highs_seg[left_rim_idx]: left_rim_idx = i
        left_rim = cup_highs_seg[left_rim_idx]
        bottom_idx = left_rim_idx
        for i in range(left_rim_idx, cup_end):
            if cup_seg[i] < cup_seg[bottom_idx]: bottom_idx = i
        cup_bottom = cup_seg[bottom_idx]
        if bottom_idx <= left_rim_idx or bottom_idx >= cup_end-3: return None
        right_rim_idx = bottom_idx
        for i in range(bottom_idx, cup_end):
            if cup_highs_seg[i] > cup_highs_seg[right_rim_idx]: right_rim_idx = i
        right_rim = cup_highs_seg[right_rim_idx]
        cup_depth_pct = ((left_rim-cup_bottom)/left_rim*100) if left_rim > 0 else 0
        if cup_depth_pct < 8: return None
        rim_diff_pct = abs(left_rim-right_rim)/left_rim*100
        if rim_diff_pct > 22: return None
        handle_lows = seg_lows[cup_end:]
        if not handle_lows: return None
        handle_low = min(handle_lows)
        handle_depth_pct = ((right_rim-handle_low)/right_rim*100) if right_rim > 0 else 0
        if handle_depth_pct < 3 or handle_depth_pct > 18: return None
        near_rim = (last["c"] >= right_rim*0.95) and (last["c"] <= right_rim*1.02)
        if not near_rim: return None
        return {"detail": f"Taza {cup_depth_pct:.1f}% · Asa {handle_depth_pct:.1f}% · rim ${right_rim:.2f}"}

    if mode == 'euforia':
        if n < 11: return None
        c10 = closes[n-11]
        run_pct = ((last["c"]/c10-1)*100) if c10 else 0
        if run_pct < 60: return None
        green_streak = 0
        for i in range(n-1, 0, -1):
            if closes[i] > closes[i-1]: green_streak += 1
            else: break
        if green_streak < 3: return None
        euforia = calc_atr_multiple(ohlc)
        if euforia is None or euforia <= 12: return None
        return {"detail": f"+{run_pct:.1f}% (10d) · {green_streak} días verdes · Euforia {euforia:.1f}"}

    return None


def build_rs_index(stock_perf):
    all_sp = [r for r in stock_perf.values() if r.get("1Y") is not None]
    all_sp.sort(key=lambda x: x.get("1Y", 0))
    n = len(all_sp)
    idx = {r["ticker"]: i for i, r in enumerate(all_sp)}
    def rs_of(tk):
        i = idx.get(tk, -1)
        return round(i/n*100) if (i >= 0 and n) else 0
    return rs_of


def build_setups_data(stock_perf):
    rs_of = build_rs_index(stock_perf)
    resultado = {}
    for mode in SETUP_MODES:
        filtered = []
        for tk, r in stock_perf.items():
            if not r.get("price") or r["price"] < 5:
                continue
            res = detect_setup(r, mode)
            if res:
                filtered.append({
                    "ticker": tk, "price": r["price"],
                    "1D": r.get("1D"), "1W": r.get("1W"), "1M": r.get("1M"),
                    "rs": rs_of(tk), "volRel": r.get("volRel"),
                    "detail": res["detail"],
                })
        filtered.sort(key=lambda x: x.get("rs", 0), reverse=True)
        resultado[mode] = filtered[:60]
    return resultado


SCANNER_MODES = ['rs', 'highs', 'vol', 'abv_all', 'lows', 'bounce', 'pre', 'euforia']

def build_scanner_data(stock_perf):
    rs_of = build_rs_index(stock_perf)

    def atr_dist(r):
        v = calc_atr_multiple(r.get("ohlc") or [])
        return round(v*10)/10 if v is not None else 0

    def signal(r, mode):
        tk = r["ticker"]
        if mode == 'highs':
            return r.get("52wHigh") and r["price"] >= r["52wHigh"]*0.97
        if mode == 'vol':
            return r.get("volRel") and r["volRel"] >= 1.5 and (r.get("1D") or 0) > 0
        if mode == 'abv_all':
            return bool(r.get("abv20") and r.get("abv50"))
        if mode == 'lows':
            return r.get("52wLow") and r["price"] <= r["52wLow"]*1.05
        if mode == 'bounce':
            return (not r.get("abv20")) and r.get("abv50") and (r.get("1D") or 0) > 1
        if mode == 'rs':
            return rs_of(tk) >= 75
        if mode == 'pre':
            return (r.get("1D") or 0) > 1 and (r.get("volRel") or 0) > 1.0
        if mode == 'euforia':
            return atr_dist(r) > 4
        return False

    resultado = {}
    for mode in SCANNER_MODES:
        filtered = []
        for tk, r in stock_perf.items():
            if not r.get("price") or r["price"] < 5:
                continue
            if not signal(r, mode):
                continue
            filtered.append({
                "ticker": tk, "price": r["price"],
                "1D": r.get("1D"), "1W": r.get("1W"), "1M": r.get("1M"),
                "3M": r.get("3M"), "6M": r.get("6M"), "1Y": r.get("1Y"),
                "rs": rs_of(tk), "volRel": r.get("volRel"),
                "atrDist": atr_dist(r),
                "abv20": r.get("abv20"), "abv50": r.get("abv50"),
                "52wHigh": r.get("52wHigh"), "52wLow": r.get("52wLow"),
            })
        if mode == 'pre':
            filtered.sort(key=lambda x: x.get("1D") or 0, reverse=True)
        elif mode == 'vol':
            filtered.sort(key=lambda x: x.get("volRel") or 0, reverse=True)
        elif mode == 'euforia':
            filtered.sort(key=lambda x: x.get("atrDist") or 0, reverse=True)
        else:
            filtered.sort(key=lambda x: x.get("rs", 0), reverse=True)
        resultado[mode] = filtered[:100]
    return resultado


def save_setups_scanner_to_supabase(stock_perf):
    print("\n▶ Calculando Setups Diarios + Scanner (servidor)...")
    from datetime import timezone
    setups_data  = build_setups_data(stock_perf)
    scanner_data = build_scanner_data(stock_perf)
    payload = {"setups": setups_data, "scanner": scanner_data,
               "generated_at": datetime.now(timezone.utc).isoformat()}
    n_setups  = sum(len(v) for v in setups_data.values())
    n_scanner = sum(len(v) for v in scanner_data.values())
    print(f"    → {n_setups} coincidencias de setups, {n_scanner} de scanner")

    if not SUPABASE_KEY:
        print("⚠️ SUPABASE_KEY no configurada en este servicio — Setups/Scanner no se actualizarán en el sitio.")
        return
    try:
        h = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
             "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
        r = requests.post(f"{SUPABASE_URL}/rest/v1/app_state",
                           headers=h, json={"key": "setups_scanner", "value": payload}, timeout=20)
        print(f"✓ setups_scanner guardado en Supabase (app_state): {r.status_code}")
    except Exception as e:
        print(f"⚠️ Error guardando setups_scanner en Supabase: {e}")


def build_stock_maps(stock_perf):
    ind_map, sec_map = {}, {}
    for ind, data in INDUSTRY_DATA.items():
        rows = sorted([dict(stock_perf[t]) for t in data["holdings"] if t in stock_perf],
                      key=lambda x: x.get("1D",0), reverse=True)
        ind_map[ind] = rows
    for sec, tks in SECTOR_STOCKS.items():
        rows = sorted([dict(stock_perf[t]) for t in tks if t in stock_perf],
                      key=lambda x: x.get("1D",0), reverse=True)
        sec_map[sec] = rows
    return ind_map, sec_map


# ══════════════════════════════════════════════════════════════════════════════
#  HTML (template con placeholders)
# ══════════════════════════════════════════════════════════════════════════════
HTML_TMPL = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#06080d">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="VG Comunidad">
<title>VICTOR GALAN: LA COMUNIDAD</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Syne:wght@700;800&display=swap');
:root{
  /* Fondos neutros — casi blancos, no negros */
  --bg:#f0f2f5;--bg2:#ffffff;--bg3:#f7f8fa;--bg4:#eef0f3;
  /* Bordes suaves */
  --b1:#e2e6eb;--b2:#d0d6de;--b3:#b8c0ca;
  /* Texto legible */
  --tx:#3d4a5c;--dim:#8a96a3;--hi:#1a2332;
  /* Acento — azul índigo moderno, no cyan eléctrico */
  --ac:#4f6ef7;--ac2:#3a57e8;
  /* Señales — verdes/rojos más suaves, no néon */
  --up:#05c46b;--dn:#ff3f5b;--warn:#f59e0b;--neu:#6b7280;
  --upb:rgba(5,196,107,.1);--dnb:rgba(255,63,91,.1);
  /* Sombras */
  --sh:0 1px 4px rgba(0,0,0,.06),0 4px 16px rgba(0,0,0,.04);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--tx);font-family:'Inter',sans-serif;font-size:13px;line-height:1.5;-webkit-font-smoothing:antialiased}

/* ── TOPBAR */
.topbar{background:var(--bg2);border-bottom:1px solid var(--b1);padding:0 20px;display:flex;align-items:center;justify-content:space-between;height:50px;position:sticky;top:0;z-index:300;box-shadow:0 1px 3px rgba(0,0,0,.06)}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:15px;color:var(--hi);display:flex;align-items:center;gap:8px;letter-spacing:-.02em}
.logo span{color:var(--ac)}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--up);animation:pulse 2.5s infinite;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.3;transform:scale(.75)}}
.topbar-r{display:flex;align-items:center;gap:8px}
.pill{padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600;letter-spacing:-.01em}
.pup{background:var(--upb);color:var(--up)}.pdn{background:var(--dnb);color:var(--dn)}
.pwarn{background:rgba(217,119,6,.09);color:var(--warn)}.pac{background:rgba(79,110,247,.08);color:var(--ac);cursor:pointer;transition:background .15s}
.pac:hover{background:rgba(79,110,247,.14)}

/* ── WRAP */
.wrap{max-width:1900px;margin:0 auto;padding:16px 20px}

/* ── BREADTH STRIP */
.bstrip{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-bottom:16px}
.bc{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:12px 14px;box-shadow:var(--sh);transition:box-shadow .15s}
.bc:hover{box-shadow:0 2px 8px rgba(0,0,0,.1)}
.bc-l{font-size:10px;color:var(--dim);font-weight:500;text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px}
.bc-v{font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:var(--hi);line-height:1.1}
.bc-c{font-size:11px;font-weight:600;margin-top:3px}

/* ── TABS */
.tabs{display:flex;border-bottom:2px solid var(--b1);margin-bottom:16px;gap:0;overflow-x:auto;scrollbar-width:none;background:var(--bg2);border-radius:10px 10px 0 0;padding:0 4px;flex:1;scroll-behavior:smooth}
.tabs::-webkit-scrollbar{display:none}
.tab{padding:12px 16px;border:none;background:none;color:var(--dim);cursor:pointer;font-family:'Inter',sans-serif;font-weight:600;font-size:12px;letter-spacing:-.01em;border-bottom:2px solid transparent;margin-bottom:-2px;white-space:nowrap;transition:all .18s}
.tab:hover{color:var(--hi);background:var(--bg3)}
.tab.active{color:var(--ac);border-bottom-color:var(--ac);background:rgba(79,110,247,.06);font-weight:700}
.tc{display:none}.tc.active{display:block}

/* ── TABS NAV ARROWS */
.tabs-wrap{margin-bottom:16px}
.tabs-wrap .tabs{margin-bottom:0;border-radius:0}
.tabs-arrow{flex-shrink:0;width:28px;border:none;background:var(--bg2);color:var(--dim);cursor:pointer;font-size:16px;font-weight:700;display:flex;align-items:center;justify-content:center;transition:color .15s,background .15s}
.tabs-arrow:hover{color:var(--ac);background:var(--bg3)}
.tabs-arrow-l{border-radius:10px 0 0 0}
.tabs-arrow-r{border-radius:0 10px 0 0}
.tabs-arrow{display:none}
.tabs-arrow.show{display:flex}

/* ── SECTION HDR */
.sh{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px}
.st{font-family:'Syne',sans-serif;font-weight:800;font-size:13px;color:var(--hi);letter-spacing:-.02em;border-left:3px solid var(--ac);padding-left:8px}
.hint{font-size:11px;color:var(--dim);font-weight:400;margin-left:8px}
.pbs{display:flex;gap:4px}
.pb{padding:5px 12px;border:1px solid var(--b1);border-radius:6px;background:var(--bg2);color:var(--dim);cursor:pointer;font-size:11px;font-weight:500;transition:all .15s;box-shadow:0 1px 2px rgba(0,0,0,.04)}
/* Top 30 industrias por rendimiento (10/07/2026) — se recalcula solo al
   ordenar por cualquier columna de periodo (1D/1W/1M/3M/6M/1Y). */
#tb-i tr.ind-top30{
  background:linear-gradient(90deg, rgba(245,158,11,.10), transparent 60%);
  border-left:3px solid var(--warn);
}
#tb-i tr.ind-top30 td:first-child .nm::before{ content:"⭐ "; }
/* Modo discreción de Mi Broker (09/07/2026) — oculta importes/posiciones por
   defecto para poder compartir pantalla sin exponer datos reales. */
.bk-discreet #broker-kpis, .bk-discreet #bk-posiciones, .bk-discreet #bk-historial,
.bk-discreet #bk-equity, .bk-discreet #bk-metricas{
  filter:blur(8px); user-select:none; pointer-events:none; transition:filter .15s;
}
/* Modo discreción de Fiscalidad (10/07/2026) — mismo patrón que Mi Broker */
.fc-discreet #fiscal-tabla, .fc-discreet #renta-contenido{
  filter:blur(8px); user-select:none; pointer-events:none; transition:filter .15s;
}
.pb.active,.pb:hover{background:rgba(79,110,247,.07);color:var(--ac);border-color:rgba(79,110,247,.3)}

/* ── FAVORITAS — boton estrella */
.fav-star{background:none;border:none;cursor:pointer;font-size:16px;color:var(--dim);padding:2px 6px;line-height:1;transition:transform .12s,color .12s}
.fav-star:hover{transform:scale(1.2);color:var(--warn)}
.fav-star.fav-active{color:var(--warn)}

/* ── HEATMAP */
.hmg{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px;margin-bottom:16px}
.hmc{border-radius:10px;padding:10px 11px;cursor:pointer;border:1px solid transparent;transition:transform .15s,box-shadow .15s;position:relative;overflow:hidden;min-height:80px}
.hmc:hover{transform:translateY(-2px);box-shadow:0 4px 16px rgba(0,0,0,.15)}
.hmc::after{content:'▶';position:absolute;bottom:6px;right:8px;font-size:7px;opacity:.3}
.hmc-n{font-weight:700;font-size:11px;margin-bottom:2px;color:#fff;line-height:1.3;text-shadow:0 1px 3px rgba(0,0,0,.3)}
.hmc-t{font-size:9px;opacity:.65;margin-bottom:6px;font-weight:500;color:#fff}
.hmc-p{font-family:'Syne',sans-serif;font-size:16px;font-weight:800;line-height:1.1;color:#fff}
.hmc-pr{font-size:9px;opacity:.65;margin-top:2px;color:#fff}

/* ── TABLE */
.tw{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;overflow:hidden;margin-bottom:16px;box-shadow:var(--sh)}
table{width:100%;border-collapse:collapse}
thead tr{background:var(--bg3);border-bottom:1px solid var(--b1)}
th{padding:9px 12px;text-align:right;font-size:10px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);cursor:pointer;white-space:nowrap;user-select:none;font-weight:600}
th:first-child,th:nth-child(2){text-align:left}
th:hover{color:var(--ac)}th.srt{color:var(--ac)}
tbody tr{border-bottom:1px solid var(--b1);transition:background .1s;cursor:pointer}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:rgba(79,110,247,.03)}
tbody tr:nth-child(even){background:rgba(0,0,0,.012)}
td{padding:9px 12px;text-align:right;white-space:nowrap;font-size:12px}
td:first-child{text-align:left}td:nth-child(2){text-align:left;color:var(--dim);font-size:11px}
.rk{display:inline-block;width:18px;height:18px;border-radius:4px;background:var(--bg3);border:1px solid var(--b1);text-align:center;line-height:18px;font-size:9px;color:var(--dim);margin-right:6px;font-weight:600}
.nm{font-weight:600;color:var(--hi)}
.up{color:var(--up)}.dn{color:var(--dn)}.neu{color:var(--neu)}

/* gauge */
.gw{display:flex;align-items:center;gap:5px;justify-content:flex-end}
.gt{width:52px;height:4px;background:var(--b1);border-radius:2px;position:relative}
.gf{position:absolute;left:0;top:0;height:100%;border-radius:2px;background:linear-gradient(90deg,var(--dn),var(--warn),var(--up))}
.gd{position:absolute;top:-4px;width:9px;height:9px;border-radius:50%;background:var(--ac);border:2px solid var(--bg2);transform:translateX(-50%);box-shadow:0 0 4px rgba(79,110,247,.4)}

/* badge */
.badge{display:inline-block;padding:2px 7px;border-radius:5px;font-size:10px;font-weight:600}
.b-up{background:var(--upb);color:var(--up)}.b-dn{background:var(--dnb);color:var(--dn)}.b-neu{background:var(--bg4);color:var(--dim)}

/* search */
.sr{display:flex;gap:9px;align-items:center;margin-bottom:12px}
.si{background:var(--bg2);border:1px solid var(--b1);border-radius:7px;padding:8px 12px;color:var(--hi);font-family:'Inter',sans-serif;font-size:12px;width:220px;outline:none;transition:border-color .2s,box-shadow .2s;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.si:focus{border-color:var(--ac);box-shadow:0 0 0 3px rgba(79,110,247,.1)}
.si::placeholder{color:var(--dim)}
.clabel{font-size:11px;color:var(--dim);font-weight:500}

/* ── MODAL */
.ov{display:none;position:fixed;inset:0;background:rgba(15,23,42,.6);z-index:500;backdrop-filter:blur(6px);align-items:flex-start;justify-content:center;padding-top:48px}
.ov.open{display:flex}
.mod{background:var(--bg2);border:1px solid var(--b1);border-radius:14px;width:min(1100px,96vw);max-height:90vh;display:flex;flex-direction:column;animation:si .2s ease;box-shadow:0 20px 60px rgba(0,0,0,.15)}
@keyframes si{from{transform:translateY(-14px);opacity:0}to{transform:translateY(0);opacity:1}}
.mh{display:flex;align-items:flex-start;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--b1);flex-shrink:0}
.mt{font-family:'Syne',sans-serif;font-weight:800;font-size:16px;color:var(--hi)}
.msub{font-size:11px;color:var(--dim);margin-top:2px}
.mright{display:flex;align-items:center;gap:8px;flex-shrink:0}
.metf{background:rgba(79,110,247,.1);color:var(--ac);padding:3px 10px;border-radius:6px;font-size:11px;font-weight:600}
.mclose{background:none;border:1px solid var(--b1);color:var(--dim);cursor:pointer;font-size:14px;padding:4px 9px;border-radius:6px;transition:all .15s}
.mclose:hover{color:var(--hi);background:var(--bg3)}
.mb{overflow-y:auto;flex:1}
.mb table{width:100%}.mb thead th{position:sticky;top:0;z-index:1;background:var(--bg3)}
.spark-cell svg{display:block}

/* ── AMPLITUD */
.score-block{background:var(--bg2);border:1px solid var(--b1);border-radius:12px;padding:20px;margin-bottom:16px;display:flex;align-items:center;gap:22px;box-shadow:var(--sh)}
.score-ring{flex-shrink:0}
.score-txt h2{font-family:'Syne',sans-serif;font-weight:800;font-size:28px;color:var(--hi);margin-bottom:4px}
.score-txt p{font-size:12px;color:var(--dim);line-height:1.6}
.amp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:8px;margin-bottom:16px}
/* NUEVO (03/09/2026): panel de amplitud "estilo Alex Salamanca" — a todo lo
   ancho, sin cuadricula, uno debajo de otro (no en grid de 2 columnas) */
.amp-panel{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:16px 18px;margin-bottom:12px}
.amp-panel-title{font-size:12px;font-weight:700;color:var(--hi);margin-bottom:10px;display:flex;justify-content:space-between;align-items:baseline}
.amp-panel-val{font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:var(--ac)}
.amp-panel-chart{height:190px;position:relative}
@media(max-width:768px){.amp-panel-chart{height:150px}}
.amp-card{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:13px 15px;box-shadow:var(--sh)}
.amp-l{font-size:10px;color:var(--dim);font-weight:600;letter-spacing:.05em;text-transform:uppercase;margin-bottom:5px}
.amp-v{font-family:'Syne',sans-serif;font-size:24px;font-weight:800;color:var(--hi);line-height:1}
.amp-sub{font-size:11px;color:var(--dim);margin-top:4px}
.risk-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:16px}
.risk-c{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:14px;text-align:center;box-shadow:var(--sh)}
.risk-l{font-size:10px;color:var(--dim);font-weight:600;letter-spacing:.05em;text-transform:uppercase;margin-bottom:6px}
.risk-a{font-size:26px;margin-bottom:4px}
.risk-v{font-size:14px;font-weight:700;color:var(--hi)}.risk-n{font-size:11px;color:var(--dim);margin-top:5px;line-height:1.4}
.charts-2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px}
.charts-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:16px}
.cw{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:14px;box-shadow:var(--sh)}
.ct{font-family:'Syne',sans-serif;font-size:12px;font-weight:700;color:var(--hi);margin-bottom:10px;letter-spacing:-.01em}

/* dist bar */
.dist-wrap{display:flex;align-items:flex-end;gap:4px;height:80px;padding-bottom:18px;position:relative}
.dist-bar{flex:1;border-radius:4px 4px 0 0;min-width:20px;position:relative;transition:opacity .2s}
.dist-bar:hover{opacity:.75}
.dist-label{position:absolute;bottom:-16px;left:50%;transform:translateX(-50%);font-size:8px;color:var(--dim);white-space:nowrap}
.dist-val{position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:9px;font-weight:700;color:var(--hi)}

/* ── BENCHMARK CHART MODAL */
.bm-ov{display:none;position:fixed;inset:0;background:rgba(15,23,42,.65);z-index:600;backdrop-filter:blur(6px);align-items:center;justify-content:center}
.bm-ov.open{display:flex}
.bm-box{background:var(--bg2);border:1px solid var(--b1);border-radius:14px;width:min(820px,95vw);max-width:95vw;padding:20px;max-height:90vh;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 20px 60px rgba(0,0,0,.15)}
.bm-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
.bm-name{font-family:'Syne',sans-serif;font-weight:800;font-size:17px;color:var(--hi)}
.bm-meta{font-size:11px;color:var(--dim);margin-top:3px}

/* ── EARNINGS TABS */
.earn-tabs{display:flex;gap:4px;margin-bottom:12px}
.earn-tab{padding:6px 14px;border:1px solid var(--b1);border-radius:7px;background:var(--bg2);color:var(--dim);cursor:pointer;font-family:'Inter',sans-serif;font-weight:600;font-size:11px;transition:all .15s}
.earn-tab.active{background:rgba(79,110,247,.07);color:var(--ac);border-color:rgba(79,110,247,.3)}
.earn-upcoming-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:7px;margin-bottom:14px}
.eu-card{background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:10px 12px;text-align:center;box-shadow:var(--sh)}
.eu-tk{font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:var(--hi)}
.eu-dt{font-size:10px;color:var(--dim);margin-top:4px}

/* ── NEWS */
.news-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:9px;margin-bottom:14px}
.news-card{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:14px 16px;cursor:pointer;transition:border-color .2s,box-shadow .2s;box-shadow:var(--sh)}
.news-card:hover{border-color:rgba(79,110,247,.3);box-shadow:0 4px 16px rgba(0,0,0,.08)}
.news-src{font-size:10px;color:var(--ac);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px;font-weight:600}
.news-title{font-size:12px;font-weight:600;color:var(--hi);line-height:1.4;margin-bottom:6px}
.news-time{font-size:10px;color:var(--dim)}

/* ── STOCK PANEL */
.stock-header{background:var(--bg2);border:1px solid var(--b1);border-radius:12px;padding:20px 22px;margin-bottom:14px;box-shadow:var(--sh)}
.stk-top-row{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:14px}
.stock-info h2{font-family:'Syne',sans-serif;font-size:28px;font-weight:800;color:var(--hi);line-height:1.1;letter-spacing:-.02em}
.stk-sector-tag{font-size:12px;color:var(--ac);margin-top:4px;margin-bottom:6px;font-weight:500}
.stock-price{font-family:'Syne',sans-serif;font-size:26px;font-weight:800}
.stk-rs-inline{display:flex;align-items:center;gap:8px;margin-top:8px}
.stk-rs-num{font-family:'Syne',sans-serif;font-size:38px;font-weight:800;line-height:1}
.stk-rs-label{font-size:11px;color:var(--dim);max-width:120px;line-height:1.4}
.stk-badges{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.stk-vol-bar{height:5px;border-radius:3px;background:var(--b1);margin-top:4px;overflow:hidden}
.stk-vol-fill{height:100%;border-radius:3px;background:var(--ac);transition:width .4s}
.stock-metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px;margin-bottom:12px}
.sm-c{background:var(--bg3);border:1px solid var(--b1);border-radius:8px;padding:9px 11px}
.sm-l{font-size:10px;color:var(--dim);margin-bottom:2px;text-transform:uppercase;letter-spacing:.04em;font-weight:500}
.sm-v{font-size:13px;font-weight:600;color:var(--hi)}
.fund-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;margin-bottom:12px}
.fg{background:var(--bg3);border:1px solid var(--b1);border-radius:8px;padding:9px 11px}
.fg-l{font-size:10px;color:var(--dim);margin-bottom:2px;text-transform:uppercase;letter-spacing:.04em;font-weight:500}
.fg-v{font-size:13px;font-weight:600;color:var(--hi)}
.fg-v.up{color:var(--up)}.fg-v.dn{color:var(--dn)}
.stock-input-row{display:flex;gap:8px;align-items:center;margin-bottom:14px}
.stk-input{background:var(--bg2);border:1px solid var(--b1);border-radius:7px;padding:8px 12px;color:var(--hi);font-family:'Inter',sans-serif;font-size:13px;width:140px;outline:none;transition:border-color .2s,box-shadow .2s;text-transform:uppercase;box-shadow:0 1px 2px rgba(0,0,0,.04)}
.stk-input:focus{border-color:var(--ac);box-shadow:0 0 0 3px rgba(79,110,247,.1)}
.stk-btn{padding:8px 18px;border-radius:7px;border:none;background:var(--ac);color:#fff;cursor:pointer;font-family:'Inter',sans-serif;font-weight:600;font-size:12px;transition:all .15s;box-shadow:0 1px 3px rgba(79,110,247,.3)}
.stk-btn:hover{background:var(--ac2);box-shadow:0 2px 8px rgba(79,110,247,.4)}
.rs-bar{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--dn),var(--warn),var(--up));position:relative;margin-top:4px}
.rs-dot{position:absolute;top:-5px;width:12px;height:12px;border-radius:50%;background:var(--ac);border:2px solid var(--bg2);transform:translateX(-50%);box-shadow:0 0 6px rgba(79,110,247,.5)}
canvas{width:100%!important}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--b2);border-radius:3px}
.foot{color:var(--dim);font-size:11px;text-align:right;padding:10px 0;border-top:1px solid var(--b1)}

/* ── RESPONSIVE MOBILE ────────────────────────────────────────────────────── */
#mobile-nav{
  display:none;position:fixed;bottom:0;left:0;right:0;z-index:500;
  background:var(--bg2);border-top:2px solid var(--b1);
  padding:4px 0 calc(4px + env(safe-area-inset-bottom));
  align-items:stretch;justify-content:space-around;gap:0
}
#mobile-nav button{
  display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3px;
  background:none;border:none;border-right:1px solid var(--b1);color:var(--dim);
  font-size:10px;cursor:pointer;padding:6px 4px;font-family:inherit;
  flex:1;transition:all .15s;letter-spacing:.02em
}
#mobile-nav button:last-child{border-right:none}
#mobile-nav button.active{color:var(--ac);background:rgba(56,189,248,.06)}
#mobile-nav button span:first-child{font-size:20px;line-height:1}

@media (max-width:900px){
  /* Topbar compacta */
  .topbar{padding:0 8px;height:38px}
  .topbar-r .pill{font-size:9px;padding:3px 8px}
  .logo{font-size:11px}
  /* Tabs: scroll horizontal sin scrollbar visible */
  .tabs{
    overflow-x:auto;-webkit-overflow-scrolling:touch;
    scrollbar-width:none;display:flex;flex-wrap:nowrap;
    border-bottom:1px solid var(--b1);gap:0
  }
  .tabs::-webkit-scrollbar{display:none}
  .tab{
    padding:9px 12px;font-size:10px;white-space:nowrap;
    flex-shrink:0;letter-spacing:.03em
  }
}

@media (max-width:768px){
  /* Topbar bstrip: solo SP500 y VIX en móvil */
  .bstrip{grid-template-columns:1fr 1fr!important}
  .bstrip .bc:nth-child(n+3){display:none!important}
  .mod{width:100vw!important;max-height:92vh!important;border-radius:14px 14px 0 0}
  .ov{padding-top:0!important;align-items:flex-end!important}
  .mb{-webkit-overflow-scrolling:touch}
  .mb table{min-width:520px}
  .mh{padding:12px 14px}
  .mt{font-size:14px}
  .bm-box{width:100vw!important;max-height:88vh!important;border-radius:14px 14px 0 0;padding:14px 12px}
  .bm-ov{align-items:flex-end!important}
  .bm-tv-container,#bm-tv-container{height:min(300px,45vh)!important}
  #bm-tv-container iframe{width:100%!important;height:100%!important}
  .wrap{padding:6px 8px;padding-bottom:76px}
  /* Topbar */
  .topbar{padding:0 8px;height:36px}
  .topbar-l{font-size:10px;letter-spacing:-.01em}
  .topbar-r{gap:4px}
  .topbar-r .pill{display:none}
  .topbar-r #spy-p,.topbar-r #ndx-p,.topbar-r #vix-p{display:inline-flex;font-size:9px;padding:2px 6px}
  /* Tabs */
  .tabs{overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;
        display:flex;flex-wrap:nowrap;padding:0;margin-bottom:10px}
  .tabs::-webkit-scrollbar{display:none}
  .tab{padding:10px 11px;font-size:10px;white-space:nowrap;flex-shrink:0}
  .tab.active{border-bottom-width:3px}
  /* Grids: 1 columna */
  .charts-2,.charts-3{grid-template-columns:1fr!important}
  .amp-grid{grid-template-columns:1fr 1fr!important}
  .risk-grid{grid-template-columns:1fr 1fr!important}
  .hmg{grid-template-columns:1fr 1fr!important}
  [style*="grid-template-columns:1fr 1fr"]{grid-template-columns:1fr!important}
  [style*="grid-template-columns:2fr 1fr"]{grid-template-columns:1fr!important}
  [style*="grid-template-columns:1fr 1fr 1fr"]{grid-template-columns:1fr!important}
  [style*="grid-template-columns:repeat(auto-fill"]{grid-template-columns:1fr 1fr!important}
  /* Tablas */
  .tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .tw table{min-width:460px}
  th,td{padding:5px 6px;font-size:10px}
  /* Cards y secciones */
  .cw{padding:10px 12px;margin-bottom:8px}
  .sh{flex-direction:column;gap:5px;align-items:flex-start}
  .sh>div{flex-wrap:wrap;gap:4px}
  .pb{padding:5px 10px;font-size:10px}
  /* Stock panel */
  .stock-header{padding:12px 13px}
  .stk-top-row{flex-direction:column!important;gap:10px}
  .stk-rs-num{font-size:26px}
  /* Briefing 2 cols → 1 */
  #briefing-cols{grid-template-columns:1fr!important}
  /* Cartera charts */
  #ct-overview [style*="grid-template-columns"]{grid-template-columns:1fr!important}
  /* Headings */
  .sh .st{font-size:10px}
  /* Bottom nav visible */
  #mobile-nav{display:flex}
  /* Chart grid: 1 columna en movil para ver cada grafico bien */
  #cg-grid{grid-template-columns:1fr!important}
  #cg-col-3,#cg-col-4{display:none}

  /* ── DIARIO MOBILE ───────────────────────────────────────────────── */
  /* Metric cards & form fields: 2 columns instead of forcing minmax that leaves gaps */
  #tab-diario [style*="grid-template-columns:repeat(auto-fit"]{
    grid-template-columns:1fr 1fr!important;
  }
  /* Calendar: smaller cells, smaller fonts so 7 cols fit without overflow */
  #dj-cal-grid{gap:3px!important}
  #dj-cal-grid>div{min-height:40px!important;padding:3px!important}
  #dj-cal-grid>div div{font-size:9px!important;line-height:1.2}
  #tab-diario [style*="grid-template-columns:repeat(7,1fr)"]{gap:3px!important}
  #tab-diario [style*="grid-template-columns:repeat(7,1fr)"]>div{font-size:9px!important}
  /* Hide desktop tables for live positions & trades, show card lists instead */
  #dj-live-positions .tw,#dj-trades-table-wrap{display:none!important}
  #dj-live-cards,#dj-trades-cards{display:flex!important}
}

@media (max-width:420px){
  body{font-size:11px}
  .wrap{padding:4px 6px;padding-bottom:76px}
  .topbar{height:34px;padding:0 6px}
  .topbar-l{font-size:9px}
  .tab{font-size:9px;padding:9px 9px}
  .amp-grid,.risk-grid,.hmg{grid-template-columns:1fr!important}
  [style*="grid-template-columns:repeat(auto-fill"]{grid-template-columns:1fr!important}
  .cw{padding:8px 10px}
  th,td{padding:4px 5px;font-size:9px}
  .stk-rs-num{font-size:22px}
  #mobile-nav button{font-size:9px;padding:5px 2px}
  #mobile-nav button span:first-child{font-size:18px}
}

/* ── LOGIN GLOBAL ─────────────────────────────────────────────────────────── */
#login-screen{
  position:fixed;inset:0;z-index:9999;background:rgba(15,23,42,.5);
  display:flex;align-items:center;justify-content:center;padding:20px;
  backdrop-filter:blur(8px);
}
#login-screen.hidden{display:none}
.login-box{
  background:var(--bg2);border:1px solid var(--b1);border-radius:16px;
  padding:36px 32px;max-width:380px;width:100%;text-align:center;
  box-shadow:0 20px 60px rgba(0,0,0,.12)
}
.login-logo{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;
  color:var(--hi);letter-spacing:-.02em;margin-bottom:2px}
.login-sub{font-size:11px;color:var(--dim);margin-bottom:28px;line-height:1.6}
.login-input{
  width:100%;padding:13px 16px;border-radius:9px;border:1px solid var(--b2);
  background:var(--bg3);color:var(--hi);font-family:inherit;font-size:14px;
  outline:none;margin-bottom:10px;box-sizing:border-box;transition:border-color .2s;
  -webkit-appearance:none
}
.login-input:focus{border-color:var(--ac)}
.login-btn{
  width:100%;padding:13px;border-radius:9px;border:none;
  background:var(--ac);color:#000;font-family:'Syne',sans-serif;
  font-weight:800;font-size:14px;cursor:pointer;transition:opacity .2s;
  -webkit-appearance:none;margin-bottom:8px
}
.login-btn:hover{opacity:.85}
.login-err{font-size:11px;color:var(--dn);margin-top:6px;min-height:18px;line-height:1.5}
.login-hint{font-size:10px;color:var(--dim);margin-top:18px;line-height:1.7}

/* ── ALIAS POPUP ─────────────────────────────────────────────────────────── */
#alias-screen{
  position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,.85);
  display:none;align-items:center;justify-content:center;padding:20px;
  backdrop-filter:blur(4px);
}
#alias-screen.show{display:flex}
.alias-box{
  background:var(--bg2);border:1px solid var(--ac);border-radius:14px;
  padding:32px 28px;max-width:360px;width:100%;text-align:center;
}
</style>
</head>
<body>

<!-- ═══ POPUP ALIAS (primera vez) ═══ -->
<div id="alias-screen">
  <div class="alias-box">
    <div style="font-size:28px;margin-bottom:10px">👋</div>
    <div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi);margin-bottom:6px">¡Bienvenido a La Comunidad!</div>
    <div style="font-size:12px;color:var(--dim);margin-bottom:20px;line-height:1.6">Elige cómo quieres que te vean los demás alumnos.<br>Puede ser tu nombre, un alias o un apodo.</div>
    <input class="login-input" id="alias-input" type="text" placeholder="Ej: Victor, Trader77, El_Halcón..."
      maxlength="30" autocomplete="off" style="text-align:center;letter-spacing:.05em">
    <button class="login-btn" id="alias-btn" style="margin-top:10px" onclick="saveAlias()">Guardar y entrar →</button>
    <div id="alias-err" style="font-size:11px;color:var(--dn);margin-top:8px;min-height:16px"></div>
  </div>
</div>

<!-- ═══ PANTALLA DE LOGIN GLOBAL ═══ -->
<div id="login-screen">
  <div class="login-box">
    <div class="login-logo">VICTOR GALAN</div>
    <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:var(--ac);margin-bottom:20px;letter-spacing:.05em">LA COMUNIDAD</div>
    <div class="login-sub">Acceso exclusivo para alumnos activos.<br>Introduce tu email y contraseña.</div>
    <input class="login-input" id="login-email" type="email" placeholder="tu@email.com"
      autocomplete="email" autocapitalize="none" spellcheck="false"
      tabindex="1"
>
    <input class="login-input" id="login-pass" type="password" placeholder="Contraseña"
      autocomplete="current-password"
      tabindex="2"
>
    <button class="login-btn" id="login-btn" tabindex="3">Entrar al dashboard →</button>
    <div class="login-err" id="login-err"></div>
    <div class="login-hint">
      ¿No tienes acceso? Contacta con Víctor.<br>
      <strong style="color:var(--ac)">@victorgalancomunidad</strong>
    </div>
  </div>
</div>

<div class="topbar">
  <div class="logo"><span class="pulse"></span>VICTOR GALAN: <span style="color:var(--ac)">LA COMUNIDAD</span></div>
  <div class="topbar-r">
    <span id="ts-l" style="color:var(--dim);font-size:10px"></span>
    <span class="pill" id="spy-p">—</span>
    <span class="pill" id="ndx-p">—</span>
    <span class="pill" id="vix-p">—</span>
    <span class="pill" style="background:rgba(245,158,11,.1);color:var(--warn);cursor:pointer" onclick="sw('briefing',document.getElementById('tab-briefing-btn'))">📋 Resumen</span>
    <span class="pill pac" onclick="sw('breadth',document.getElementById('tab-breadth-btn'))">Amplitud ▸</span>
    <span class="pill pac" onclick="sw('stocks',document.getElementById('tab-stocks-btn'))">Acciones ▸</span>
    <div id="topbar-user" style="display:flex;align-items:center;gap:4px"></div>
  </div>
</div>

<!-- DRILL-DOWN MODAL -->
<div class="ov" id="ov" onclick="closeModal(event)">
  <div class="mod">
    <div class="mh">
      <div>
        <div class="mt" id="m-title">—</div>
        <div class="msub" id="m-sub">—</div>
      </div>
      <div class="mright">
        <span class="metf" id="m-etf">—</span>
        <div class="pbs" id="m-pbs">
          <button class="pb active" onclick="setMP('1D',this)">1D</button>
          <button class="pb" onclick="setMP('1W',this)">1W</button>
          <button class="pb" onclick="setMP('1M',this)">1M</button>
          <button class="pb" onclick="setMP('3M',this)">3M</button>
          <button class="pb" onclick="setMP('1Y',this)">1Y</button>
        </div>
        <button class="pb" onclick="cgOpenFromModal()" style="font-size:10px;margin-right:4px">📊 Gráficos</button>
        <button class="mclose" onclick="closeModal()">✕</button>
      </div>
    </div>
    <div class="mb">
      <table>
        <thead><tr>
          <th style="width:28px"></th>
          <th style="text-align:left;cursor:pointer" onclick="sortModal(0)"># Acción ↕</th>
          <th style="text-align:left">Ticker</th>
          <th onclick="sortModal(2)" style="cursor:pointer">Precio ↕</th>
          <th onclick="setMP('1D',document.querySelector('#m-pbs .pb'))" style="cursor:pointer">1D ↕</th>
          <th onclick="setMPdirect('1W')" style="cursor:pointer">1W ↕</th>
          <th onclick="setMPdirect('1M')" style="cursor:pointer">1M ↕</th>
          <th onclick="setMPdirect('3M')" style="cursor:pointer">3M ↕</th>
          <th onclick="setMPdirect('1Y')" style="cursor:pointer">1Y ↕</th>
          <th>vs MA20</th><th>vs MA50</th><th>vs MA200</th>
          <th onclick="sortModal(11)" style="cursor:pointer">Vol Rel. ↕</th>
          <th>52W</th><th>Tendencia</th>
        </tr></thead>
        <tbody id="m-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- BENCHMARK CHART MODAL -->
<div class="bm-ov" id="bm-ov" onclick="closeBMModal(event)">
  <div class="bm-box">
    <div class="bm-hdr">
      <div>
        <div class="bm-name" id="bm-name">—</div>
        <div class="bm-meta" id="bm-meta">—</div>
      </div>
      <button class="mclose" onclick="closeBMModal()">✕</button>
    </div>
    <div id="bm-tv-container" style="height:min(420px,60vh);border-radius:8px;overflow:hidden"></div>
    <div style="height:min(420px,60vh);position:relative"><canvas id="bm-fallback-chart" style="display:none"></canvas></div>
  </div>
</div>

<div class="wrap">
  <div class="bstrip" id="bstrip"></div>
  <!-- CARRETE DE COTIZACIONES -->
  <div style="background:var(--card);border-bottom:1px solid var(--border);overflow:hidden;height:46px">
    <div class="tradingview-widget-container" style="height:46px">
      <div class="tradingview-widget-container__widget" style="height:46px"></div>
      <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js" async>
      {
        "symbols": [
          {"proName":"FOREXCOM:SPXUSD","title":"S&P 500"},
          {"proName":"FOREXCOM:NSXUSD","title":"Nasdaq"},
          {"proName":"FOREXCOM:DJI","title":"Dow Jones"},
          {"proName":"BME:IBC","title":"IBEX 35"},
          {"proName":"INDEX:DEU40","title":"DAX"},
          {"proName":"INDEX:SX5E","title":"Euro Stoxx"},
          {"proName":"TVC:GOLD","title":"Oro"},
          {"proName":"TVC:USOIL","title":"Petróleo"},
          {"proName":"CRYPTO:BTCUSD","title":"Bitcoin"},
          {"proName":"CRYPTO:ETHUSD","title":"Ethereum"},
          {"proName":"FX:EURUSD","title":"EUR/USD"},
          {"proName":"NASDAQ:AAPL","title":"Apple"},
          {"proName":"NASDAQ:MSFT","title":"Microsoft"},
          {"proName":"NASDAQ:NVDA","title":"Nvidia"},
          {"proName":"NASDAQ:AMZN","title":"Amazon"},
          {"proName":"NASDAQ:META","title":"Meta"},
          {"proName":"NASDAQ:GOOGL","title":"Alphabet"},
          {"proName":"NYSE:BRK.B","title":"Berkshire"},
          {"proName":"NYSE:JPM","title":"JPMorgan"},
          {"proName":"NASDAQ:TSLA","title":"Tesla"},
          {"proName":"NYSE:V","title":"Visa"},
          {"proName":"NYSE:UNH","title":"UnitedHealth"},
          {"proName":"NASDAQ:AVGO","title":"Broadcom"},
          {"proName":"NYSE:XOM","title":"ExxonMobil"},
          {"proName":"NYSE:GS","title":"Goldman Sachs"},
          {"proName":"NASDAQ:COST","title":"Costco"},
          {"proName":"NYSE:LLY","title":"Eli Lilly"},
          {"proName":"NYSE:MA","title":"Mastercard"},
          {"proName":"NASDAQ:MRVL","title":"Marvell"},
          {"proName":"NYSE:ACN","title":"Accenture"},
          {"proName":"NASDAQ:PANW","title":"Palo Alto"},
          {"proName":"NYSE:NOW","title":"ServiceNow"},
          {"proName":"NYSE:DELL","title":"Dell"},
          {"proName":"NYSE:NEM","title":"Newmont"},
          {"proName":"NYSE:FCX","title":"Freeport"},
          {"proName":"NYSE:SLB","title":"Schlumberger"},
          {"proName":"NASDAQ:REGN","title":"Regeneron"}
        ],
        "showSymbolLogo": false,
        "isTransparent": true,
        "displayMode": "regular",
        "colorTheme": "light",
        "locale": "es"
      }
      </script>
    </div>
  </div>
  <div class="tabs-wrap" style="position:relative;display:flex;align-items:stretch">
    <button class="tabs-arrow tabs-arrow-l" onclick="scrollTabs(-1)" aria-label="Desplazar pestañas a la izquierda">‹</button>
    <div class="tabs" id="tabs-scroll">
    <button class="tab" onclick="sw('briefing',this)" id="tab-briefing-btn" style="color:var(--warn);border-bottom-color:var(--warn)">📋 Resumen</button>
    <button class="tab active" onclick="sw('sectors',this)">Sectores (11)</button>
    <button class="tab" onclick="sw('industries',this)">Industrias (__NIND__)</button>
    <button class="tab" onclick="sw('breadth',this)" id="tab-breadth-btn">Amplitud</button>
    <button class="tab" onclick="sw('stocks',this)" id="tab-stocks-btn">Gráficos</button>
    <button class="tab" onclick="sw('fundamentales',this)" id="tab-fundamentales-btn">📊 Fundamentales</button>
    <button class="tab" onclick="sw('scanner',this)" id="tab-scanner-btn">🔍 Scanner</button>
    <button class="tab" onclick="sw('setups',this)" id="tab-setups-btn">🎯 Setups Diarios</button>
    <button class="tab" onclick="sw('watchlist',this)" id="tab-watchlist-btn">⭐ Watchlist</button>
    <button class="tab" onclick="sw('favoritas',this)" id="tab-favoritas-btn">🌟 Favoritas</button>
    <button class="tab" onclick="sw('cartera',this)" id="tab-cartera-btn">💼 Mi Cartera</button>
    <button class="tab" onclick="sw('broker',this)" id="tab-broker-btn">🔗 Mi Broker</button>
    <button class="tab" onclick="sw('fiscal',this)" id="tab-fiscal-btn">🧾 Fiscalidad</button>
    <button class="tab" onclick="sw('comunidad',this)" id="tab-comunidad-btn" style="color:var(--warn)">🌟 Comunidad</button>
    <button class="tab" onclick="sw('diario',this)" id="tab-diario-btn">📔 Diario</button>
    </div>
    <button class="tabs-arrow tabs-arrow-r" onclick="scrollTabs(1)" aria-label="Desplazar pestañas a la derecha">›</button>
  </div>


  <!-- ═══ BRIEFING ═══ -->
  <div id="tab-briefing" class="tc">
    <!-- Cabecera estilo periódico -->
    <div style="border-bottom:2px solid var(--ac);margin-bottom:14px;padding-bottom:10px;display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:8px">
      <div>
        <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--hi);letter-spacing:-.01em">VICTOR GALAN: LA COMUNIDAD</div>
        <div style="font-size:11px;color:var(--dim);margin-top:2px">Resumen de mercado · <span id="briefing-date"></span></div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <div id="briefing-semaphore-top" style="display:flex;gap:6px;align-items:center"></div>
        <button class="pb" onclick="_briefingBuilt=false;renderBriefing()" style="padding:5px 12px">↻ Actualizar</button>
      </div>
    </div>
    <!-- Intro headline -->
    <div id="briefing-intro" style="margin-bottom:14px"></div>
    <!-- Layout 2 columnas -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px" id="briefing-cols">
      <div id="briefing-col-left"></div>
      <div id="briefing-col-right"></div>
    </div>
  </div>

  <!-- ═══ SECTORES ═══ -->
  <div id="tab-sectors" class="tc active">
    <div class="sh">
      <span class="st">SECTORES S&P 500<span class="hint">— click para ver acciones</span></span>
      <div class="pbs" id="ps">
        <button class="pb active" onclick="sp('s','1D',this)">1D</button>
        <button class="pb" onclick="sp('s','1W',this)">1W</button>
        <button class="pb" onclick="sp('s','1M',this)">1M</button>
        <button class="pb" onclick="sp('s','3M',this)">3M</button>
        <button class="pb" onclick="sp('s','6M',this)">6M</button>
        <button class="pb" onclick="sp('s','1Y',this)">1Y</button>
      </div>
    </div>
    <div class="hmg" id="hm-s"></div>
    <div class="tw"><table><thead><tr>
      <th onclick="srt('tb-s',0)"># Sector</th><th>Ticker</th><th>Precio</th>
      <th onclick="srt('tb-s',3)">1D</th><th onclick="srt('tb-s',4)">1W</th>
      <th onclick="srt('tb-s',5)">1M</th><th onclick="srt('tb-s',6)">3M</th>
      <th onclick="srt('tb-s',7)">6M</th><th onclick="srt('tb-s',8)">1Y</th>
      <th>52W</th><th onclick="srt('tb-s',10)">vs Máx</th>
    </tr></thead><tbody id="tb-s"></tbody></table></div>
  </div>

  <!-- ═══ INDUSTRIAS ═══ -->
  <div id="tab-industries" class="tc">
    <div class="sh">
      <span class="st">INDUSTRIAS & TEMAS<span class="hint">— click para ver constituyentes</span></span>
      <div class="pbs" id="pi">
        <button class="pb active" onclick="sp('i','1D',this)">1D</button>
        <button class="pb" onclick="sp('i','1W',this)">1W</button>
        <button class="pb" onclick="sp('i','1M',this)">1M</button>
        <button class="pb" onclick="sp('i','3M',this)">3M</button>
        <button class="pb" onclick="sp('i','6M',this)">6M</button>
        <button class="pb" onclick="sp('i','1Y',this)">1Y</button>
      </div>
    </div>
    <div class="hmg" id="hm-i"></div>
    <div class="sr">
      <input class="si" type="text" placeholder="Filtrar industria, ticker, tema..." oninput="fi(this.value)">
      <span class="clabel" id="ind-cnt"></span>
    </div>
    <div class="tw"><table><thead><tr>
      <th onclick="srt('tb-i',0)"># Industria / Tema</th><th>ETF</th><th>Precio</th>
      <th onclick="srt('tb-i',3)">1D</th><th onclick="srt('tb-i',4)">1W</th>
      <th onclick="srt('tb-i',5)">1M</th><th onclick="srt('tb-i',6)">3M</th>
      <th onclick="srt('tb-i',7)">6M</th><th onclick="srt('tb-i',8)">1Y</th>
      <th>52W</th><th onclick="srt('tb-i',10)">vs Máx</th>
    </tr></thead><tbody id="tb-i"></tbody></table></div>
  </div>

  <!-- ═══ AMPLITUD ═══ -->
  <div id="tab-breadth" class="tc">
    <!-- Score block -->
    <div class="score-block">
      <div class="score-ring">
        <svg width="90" height="90" viewBox="0 0 90 90">
          <circle cx="45" cy="45" r="38" fill="none" stroke="var(--b1)" stroke-width="7"/>
          <circle cx="45" cy="45" r="38" fill="none" stroke="var(--ac)" stroke-width="7"
            stroke-dasharray="238.76" id="score-arc" stroke-dashoffset="238.76"
            stroke-linecap="round" transform="rotate(-90 45 45)"/>
          <text x="45" y="50" text-anchor="middle" font-family="Syne,sans-serif" font-size="20"
            font-weight="800" fill="var(--hi)" id="score-num">—</text>
        </svg>
      </div>
      <div class="score-txt">
        <h2 id="score-label">—</h2>
        <p id="score-desc" style="margin-bottom:8px">—</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <span id="adv-badge" class="badge b-up">—</span>
          <span id="dec-badge" class="badge b-dn">—</span>
          <span id="unch-badge" class="badge b-neu">—</span>
          <span id="nh-badge" class="badge b-up" style="cursor:pointer" onclick="toggleNHList('highs')" title="Click para ver tickers">—</span>
          <span id="nl-badge" class="badge b-dn" style="cursor:pointer" onclick="toggleNHList('lows')" title="Click para ver tickers">—</span>
        </div>
        <div id="nh-list" style="display:none;margin-top:10px;display:none;flex-wrap:wrap;gap:4px;max-height:220px;overflow-y:auto"></div>
      </div>
    </div>

    <!-- AMPLITUD OFICIAL (amplitudmercado.com API) — se oculta sola si no hay clave configurada -->
    <div id="amplitud-api-section" style="display:none">
      <div class="sh" style="margin-top:14px"><span class="st">📊 AMPLITUD DE MERCADO OFICIAL — amplitudmercado.com</span></div>
      <div style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap" id="amp-periodo-botones">
        <button class="pb amp-periodo-btn" data-periodo="1m" onclick="amplitudCambiarPeriodo('1m')">1 mes</button>
        <button class="pb amp-periodo-btn" data-periodo="6m" onclick="amplitudCambiarPeriodo('6m')">6 meses</button>
        <button class="pb amp-periodo-btn active" data-periodo="1a" onclick="amplitudCambiarPeriodo('1a')">1 año</button>
        <button class="pb amp-periodo-btn" data-periodo="5a" onclick="amplitudCambiarPeriodo('5a')">5 años</button>
        <button class="pb amp-periodo-btn" data-periodo="10a" onclick="amplitudCambiarPeriodo('10a')">10 años</button>
        <button class="pb amp-periodo-btn" data-periodo="todo" onclick="amplitudCambiarPeriodo('todo')">Todo</button>
      </div>

      <div class="sh"><span class="st">NYSE — indicadores de amplitud</span></div>
      <div class="amp-panel"><div class="amp-panel-title">Línea Avance/Descenso (NYSE) <span class="amp-panel-val" id="amp-v-adline"></span></div><div class="amp-panel-chart"><canvas id="amp-c-adline"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Línea ADn <span class="amp-panel-val" id="amp-v-adn"></span></div><div class="amp-panel-chart"><canvas id="amp-c-adn"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">RASI <span class="amp-panel-val" id="amp-v-rasi"></span></div><div class="amp-panel-chart"><canvas id="amp-c-rasi"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Oscilador McClellan <span class="amp-panel-val" id="amp-v-mcos"></span></div><div class="amp-panel-chart"><canvas id="amp-c-mcos"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Summation Index <span class="amp-panel-val" id="amp-v-summation"></span></div><div class="amp-panel-chart"><canvas id="amp-c-summation"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Suben / Bajan (diario)</div><div class="amp-panel-chart"><canvas id="amp-c-updown"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Valores sobre su media de 50 y 200 sesiones (%) <span class="amp-panel-val" id="amp-v-ma"></span></div><div class="amp-panel-chart"><canvas id="amp-c-ma"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Valores a menos 5% de máximos/mínimos (%) <span class="amp-panel-val" id="amp-v-5pct"></span></div><div class="amp-panel-chart"><canvas id="amp-c-5pct"></canvas></div></div>

      <div class="sh"><span class="st">NASDAQ — indicadores de amplitud</span></div>
      <div id="amp-nasdaq-grid"></div>

      <div class="sh"><span class="st">BONOS — el "canario en la mina" de liquidez</span></div>
      <div class="amp-panel"><div class="amp-panel-title">Línea AD Bonos High-Yield</div><div class="amp-panel-chart"><canvas id="amp-c-adhy"></canvas></div></div>
      <div class="amp-panel"><div class="amp-panel-title">Línea AD Bonos CEF</div><div class="amp-panel-chart"><canvas id="amp-c-adcef"></canvas></div></div>
      <div id="amp-bonos-extra-grid"></div>

      <div class="sh"><span class="st">SENTIMIENTO</span></div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px">
        <div class="cw" style="padding:18px;text-align:center">
          <div class="ct" style="margin-bottom:10px;text-align:left">😨 Fear &amp; Greed</div>
          <div id="amp-fg-gauge">—</div>
        </div>
        <div class="cw" style="padding:18px">
          <div class="ct" style="margin-bottom:10px">Investors Intelligence</div>
          <div id="amp-ii-content">—</div>
        </div>
        <div class="cw" style="padding:18px">
          <div class="ct" style="margin-bottom:10px">AAII</div>
          <div id="amp-aaii-content">—</div>
        </div>
      </div>
      <div id="amp-diarios-grid"></div>

      <div style="font-size:10px;color:var(--dim);margin-bottom:16px">Datos de amplitud vía <a href="https://amplitudmercado.com" target="_blank" style="color:var(--ac)">amplitudmercado.com</a> (Alex Salamanca)</div>
    </div>

    <!-- Amplitude metrics -->
    <div class="amp-grid" id="amp-grid"></div>

    <!-- Risk on/off + NYSE — 6 tarjetas en grid de 3+3, sin huecos -->
    <div class="sh" style="margin-top:2px"><span class="st">NYSE &amp; INDICADORES RISK-ON / RISK-OFF</span></div>
    <div class="risk-grid" id="risk-g"></div>

    <!-- Indicadores avanzados: 3 columnas x 2 filas -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">📊 Sentimiento AAII</div>
        <div id="aaii-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">🌊 Ciclo Kondratiev</div>
        <div id="kondratiev-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">📈 MACD S&P500</div>
        <div id="macd-content"></div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">💰 Bonos CEF — señal de flujo</div>
        <div id="cef-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">🔁 Coppock Curve — S&P mensual</div>
        <div id="coppock-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">⚖️ HAA-Simple — Asset Allocation</div>
        <div id="haa-content"></div>
      </div>
    </div>
    <!-- Fear & Greed iframe CNN -->
    <div class="cw" style="padding:12px 14px;margin-bottom:14px">
      <div class="ct" style="margin-bottom:7px;font-size:11px">😨 Fear &amp; Greed Index</div>
      <div id="fg-content"></div>
    </div>

    <!-- Distribución retornos -->
    <div class="sh"><span class="st">DISTRIBUCIÓN DE RETORNOS DIARIOS — S&P 500 muestra</span></div>
    <div class="cw" style="margin-bottom:14px">
      <div class="dist-wrap" id="dist-chart"></div>
    </div>

    <!-- Charts row 1: SPY + VIX -->
    <div class="charts-2">
      <div class="cw"><div class="ct">S&P 500 (SPY) — 90 días <span id="chg-spy" style="float:right;font-size:10px"></span></div><canvas id="c-spy" height="120"></canvas></div>
      <div class="cw"><div class="ct">VIX — Volatilidad implícita <span id="chg-vix" style="float:right;font-size:10px"></span></div><canvas id="c-vix" height="120"></canvas></div>
    </div>
    <!-- Charts row 2: HYG + TLT + UUP -->
    <div class="charts-3">
      <div class="cw"><div class="ct">High Yield (HYG) <span id="chg-hyg" style="float:right;font-size:10px"></span></div><canvas id="c-hyg" height="110"></canvas></div>
      <div class="cw"><div class="ct">Treasury 20Y (TLT) <span id="chg-tlt" style="float:right;font-size:10px"></span></div><canvas id="c-tlt" height="110"></canvas></div>
      <div class="cw"><div class="ct">US Dollar (UUP) <span id="chg-uup" style="float:right;font-size:10px"></span></div><canvas id="c-uup" height="110"></canvas></div>
    </div>
    <!-- Charts row 3: Curva 10Y-2Y (McClellan y A/D Line se movieron a la
         sección "AMPLITUD DE MERCADO OFICIAL" de arriba, con datos reales
         del NYSE completo en vez de esta aproximación) -->
    <div style="font-size:10px;color:var(--dim);margin-bottom:8px">ℹ️ El Oscilador McClellan y la Línea AD ahora están arriba, en "Amplitud de mercado oficial", con datos reales del NYSE completo.</div>
    <div class="charts-3">
      <div class="cw"><div class="ct">Curva 10Y-2Y (proxy) <span id="chg-crv" style="float:right;font-size:10px"></span></div><canvas id="c-crv" height="110"></canvas></div>
    </div>
    <!-- Charts row 4: GLD + BTC + NYSE -->
    <div class="charts-3">
      <div class="cw"><div class="ct">Oro (GLD) <span id="chg-gld" style="float:right;font-size:10px"></span></div><canvas id="c-gld" height="110"></canvas></div>
      <div class="cw"><div class="ct">Bitcoin ETF (IBIT) <span id="chg-btc" style="float:right;font-size:10px"></span></div><canvas id="c-btc" height="110"></canvas></div>
      <div class="cw"><div class="ct">NYSE Composite <span id="chg-nya" style="float:right;font-size:10px"></span></div><canvas id="c-nya" height="110"></canvas></div>
    </div>
    <!-- Macro / Bonos / Yields -->
    <div class="sh"><span class="st">MACRO — BONOS, YIELDS E INFLACIÓN</span></div>
    <div class="charts-3" style="margin-bottom:14px">
      <div class="cw">
        <div class="ct">Yield 10Y Tesoro EEUU (^TNX) <span id="tnx-chg" style="float:right;font-size:10px"></span></div>
        <canvas id="c-tnx" height="90"></canvas>
        <div style="font-size:9px;color:var(--dim);margin-top:6px">El yield 10Y es la referencia global del coste del dinero. Subidas presionan las valoraciones growth y el mercado inmobiliario.</div>
      </div>
      <div class="cw">
        <div class="ct">TIPS (Inflación real USA) <span id="tip-chg" style="float:right;font-size:10px"></span></div>
        <canvas id="c-tip" height="90"></canvas>
        <div style="font-size:9px;color:var(--dim);margin-top:6px">Los TIPS reflejan expectativas de inflación real. Si suben mientras el nominal baja, el mercado espera menor inflación futura.</div>
      </div>
      <div class="cw">
        <div class="ct">Bonos Aggregate (AGG) vs Corp (LQD) <span id="agg-chg" style="float:right;font-size:10px"></span></div>
        <canvas id="c-agg" height="90"></canvas>
        <div style="font-size:9px;color:var(--dim);margin-top:6px">AGG mide el mercado de bonos USA en general. Su precio inverso al yield. LQD sube en entornos risk-on (crédito corporativo demandado).</div>
      </div>
    </div>

    <!-- Comentario interpretativo -->
    <div class="cw" style="margin-bottom:14px;border-left:3px solid var(--ac)" id="market-comment-box">
      <div class="ct" style="display:flex;align-items:center;gap:8px">
        <span>🧠 INTERPRETACIÓN DE MERCADO</span>
        <span style="font-size:9px;color:var(--dim);font-family:Inter,sans-serif;font-weight:400">— análisis basado en amplitud, riesgo y flujo macro</span>
      </div>
      <div id="market-comment" style="font-size:11px;line-height:1.9;color:var(--tx)">—</div>
    </div>



    <div class="sh" style="margin-top:6px"><span class="st">📅 ESTACIONALIDAD &amp; 🌡️ ENTORNO DE INFLACIÓN</span></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
      <div class="cw" style="padding:13px 15px" id="seasonal-box">
        <div class="ct" style="margin-bottom:8px">📅 ¿Qué activos favorece este mes históricamente?</div>
        <div id="seasonal-content"></div>
      </div>
      <div class="cw" style="padding:13px 15px" id="inflation-box">
        <div class="ct" style="margin-bottom:8px">🌡️ Entorno de inflación — ¿Qué funciona mejor?</div>
        <div id="inflation-content"></div>
      </div>
    </div>
  </div>

  <!-- ═══ PANEL ACCIÓN ═══ -->
  <div id="tab-stocks" class="tc">
    <div class="sh"><span class="st">PANEL INDIVIDUAL DE ACCIÓN</span></div>
    <div class="stock-input-row">
      <input class="stk-input" id="stk-ticker" type="text" placeholder="NVDA" maxlength="8" onkeydown="if(event.key==='Enter')loadStock()">
      <button class="stk-btn" onclick="loadStock()">Analizar ▶</button>
      <div style="display:flex;gap:6px;flex-wrap:wrap" id="quick-tickers"></div>
    </div>
    <div id="stock-panel"></div>
  </div>


  <!-- ═══ FUNDAMENTALES / SCREENER ═══ -->
  <div id="tab-fundamentales" class="tc">
    <div class="sh">
      <span class="st">📊 FUNDAMENTALES — SCREENER</span>
      <button class="pb" onclick="cgOpen('fundamentales')" style="font-size:10px">📊 Ver gráficos</button>
    </div>
    <div style="font-size:11px;color:var(--dim);margin-bottom:10px">
      Ratios TTM (Financials &amp; Ratios, Massive) · <span id="fund-count">—</span> acciones
    </div>
    <div id="fund-filters" style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px"></div>
    <details style="margin-bottom:12px;font-size:11px;color:var(--dim)">
      <summary style="cursor:pointer;color:var(--tx);font-weight:600">ℹ️ ¿Qué significa cada ratio?</summary>
      <div id="fund-glossary" style="margin-top:8px;line-height:1.7;columns:2;column-gap:20px"></div>
    </details>
    <div class="tw">
      <table id="fund-table">
        <thead>
          <tr id="fund-thead"></tr>
        </thead>
        <tbody id="fund-tbody"></tbody>
      </table>
    </div>
  </div>

  <!-- ═══ SCANNER ═══ -->
  <div id="tab-scanner" class="tc">
    <div class="sh">
      <span class="st">🔍 SCANNER DE ACCIONES</span>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <button class="pb active" id="scan-btn-rs" onclick="runScanner('rs',this)">⭐ RS Líderes</button>
        <button class="pb" id="scan-btn-highs" onclick="runScanner('highs',this)">🔝 Cerca 52W Max</button>
        <button class="pb" id="scan-btn-vol" onclick="runScanner('vol',this)">💰 Volumen Comprador</button>
        <button class="pb" id="scan-btn-abv_all" onclick="runScanner('abv_all',this)">✅ Sobre MA20+50</button>
        <button class="pb" id="scan-btn-lows" onclick="runScanner('lows',this)">🔻 Cerca 52W Mín</button>
        <button class="pb" id="scan-btn-bounce" onclick="runScanner('bounce',this)">🔄 Rebote MA</button>
        <button class="pb" id="scan-btn-pre" onclick="runScanner('pre',this)">🌅 Premercado ↑</button>
        <button class="pb" id="scan-btn-euforia" onclick="runScanner('euforia',this)">🔥 Euforia Extrema</button>
        <span style="font-size:9px;color:var(--dim)">· click en columna para ordenar ·</span>
        <button class="pb" onclick="copyScannerTickers()" style="margin-left:auto">📋 Copiar lista</button>
      </div>
    </div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <div id="scanner-status" style="font-size:10px;color:var(--dim)">Selecciona un filtro para escanear</div>
      <button class="pb" onclick="cgOpen('scanner')" style="font-size:10px">📊 Ver gráficos</button>
    </div>
    <div class="tw"><table id="scanner-table"><thead><tr>
      <th style="width:30px"></th>
      <th style="text-align:left" onclick="sortScanner(0)"># Ticker</th>
      <th onclick="sortScanner(1)">Precio</th>
      <th onclick="sortScanner(2)">1D ↕</th>
      <th onclick="sortScanner(3)">1W ↕</th>
      <th onclick="sortScanner(4)">1M ↕</th>
      <th onclick="sortScanner(5)">1Y ↕</th>
      <th onclick="sortScanner(6)">MA20 ↕</th>
      <th onclick="sortScanner(7)">MA50 ↕</th>
      <th onclick="sortScanner(8)">ATR Ext. ↕</th>
      <th onclick="sortScanner(9)">Vol Rel. ↕</th>
      <th onclick="sortScanner(10)">RS ↕</th>
      <th onclick="sortScanner(11)">52W ↕</th>
      <th>Señal</th>
    </tr></thead><tbody id="tb-scanner"></tbody></table></div>
  </div>

  <!-- ═══ SETUPS DIARIOS ═══ -->
  <div id="tab-setups" class="tc">
    <div class="sh">
      <span class="st">🎯 SETUPS DIARIOS</span>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <button class="pb active" id="setup-btn-htf" onclick="runSetup('htf',this)">🚀 High Tight Flag</button>
        <button class="pb" id="setup-btn-hvc" onclick="runSetup('hvc',this)">💥 High Volume Close</button>
        <button class="pb" id="setup-btn-gap" onclick="runSetup('gap',this)">⚡ Gappers</button>
        <button class="pb" id="setup-btn-breakout" onclick="runSetup('breakout',this)">📈 Breakout</button>
        <button class="pb" id="setup-btn-ur" onclick="runSetup('ur',this)">🔄 Undercut &amp; Rally</button>
        <button class="pb" id="setup-btn-inside" onclick="runSetup('inside',this)">📦 Inside Bar</button>
        <button class="pb" id="setup-btn-ma_reject" onclick="runSetup('ma_reject',this)">🔻 Rechazo en Media</button>
        <button class="pb" id="setup-btn-ma_support" onclick="runSetup('ma_support',this)">📐 Apoyo en Media</button>
        <button class="pb" id="setup-btn-cup_handle" onclick="runSetup('cup_handle',this)">☕ Taza con Asa</button>
        <span style="font-size:9px;color:var(--dim)">· click en columna para ordenar ·</span>
        <button class="pb" onclick="copySetupTickers()" style="margin-left:auto">📋 Copiar lista</button>
      </div>
    </div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <div id="setup-status" style="font-size:10px;color:var(--dim)">Selecciona un setup para escanear</div>
      <button class="pb" onclick="cgOpen('setups')" style="font-size:10px">📊 Ver gráficos</button>
    </div>
    <div class="tw"><table id="setup-table"><thead><tr id="setup-thead">
      <th style="width:30px"></th>
      <th style="text-align:left" onclick="sortSetup(0)"># Ticker</th>
      <th onclick="sortSetup(1)">Precio</th>
      <th onclick="sortSetup(2)">1D ↕</th>
      <th onclick="sortSetup(3)">1W ↕</th>
      <th onclick="sortSetup(4)">1M ↕</th>
      <th onclick="sortSetup(5)">RS ↕</th>
      <th onclick="sortSetup(6)">Vol Rel. ↕</th>
      <th>Detalle</th>
    </tr></thead><tbody id="tb-setup"></tbody></table></div>
  </div>

  <!-- ═══ WATCHLIST ═══ -->
  <div id="tab-watchlist" class="tc">
    <div class="sh">
      <span class="st">⭐ WATCHLIST DIARIA</span>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="pb" onclick="buildWatchlist()">🔄 Generar Watchlist</button>
        <button class="pb" onclick="copyTickers()">📋 Copiar tickers</button>
        <span style="font-size:9px;color:var(--dim)">Top acciones por setup + industria fuerte</span>
      </div>
    </div>
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
      <div id="wl-status" style="font-size:10px;color:var(--dim);line-height:1.6"></div>
      <button class="pb" onclick="cgOpen('watchlist')" style="font-size:10px">📊 Ver gráficos</button>
    </div>
    <!-- Copy textarea hidden -->
    <textarea id="wl-copy-area" style="position:absolute;left:-9999px"></textarea>
    <div id="wl-criteria" style="background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:12px;margin-bottom:12px;font-size:10px;color:var(--dim);line-height:1.7;display:none">
      <strong style="color:var(--hi)">Criterios de selección:</strong><br>
      ✅ RS ≥ 70 (líder o por encima de media) · ✅ Sobre MA50 · ✅ Industria en tendencia (1M positivo) · 
      ✅ Volumen relativo ≥ 1.0 · ✅ Precio &gt; $10 · ✅ 1D ≥ 0 (no en caída libre)<br>
      <strong>Setups priorizados:</strong> Near 52W High · High Vol Close · Gap Up · Above All MAs
    </div>
    <div class="tw"><table id="wl-table"><thead><tr>
      <th style="text-align:left" onclick="sortWL(0)"># Ticker ↕</th>
      <th onclick="sortWL(1)">Precio ↕</th>
      <th onclick="sortWL(2)">1D ↕</th>
      <th onclick="sortWL(3)">1W ↕</th>
      <th onclick="sortWL(4)">1M ↕</th>
      <th onclick="sortWL(5)">RS ↕</th>
      <th onclick="sortWL(6)">MA50</th>
      <th onclick="sortWL(7)">Vol Rel. ↕</th>
      <th>Setup</th><th>Industria</th>
    </tr></thead><tbody id="tb-watchlist"></tbody></table></div>
  </div>

  <!-- ═══ FAVORITAS ═══ -->
  <div id="tab-favoritas" class="tc">
    <div class="sh">
      <span class="st">🌟 MIS FAVORITAS</span>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="pb" onclick="copyFavTickers()">📋 Copiar tickers</button>
        <button class="pb" onclick="cgOpen('favoritas')" style="font-size:10px">📊 Ver gráficos</button>
        <button class="pb" onclick="clearFavoritas()" style="color:var(--dn);border-color:rgba(244,63,94,.3)">🗑 Vaciar lista</button>
      </div>
    </div>
    <div style="font-size:10px;color:var(--dim);margin-bottom:12px;line-height:1.6">
      Acciones que marcaste con ☆ desde Setups Diarios, Scanner, Sectores o Industrias. Se guardan en este dispositivo.
    </div>
    <textarea id="fav-copy-area" style="position:absolute;left:-9999px"></textarea>
    <div class="tw"><table id="fav-table"><thead><tr>
      <th style="text-align:left">#</th>
      <th style="text-align:left;cursor:pointer" onclick="favSortBy('ticker')">Ticker <span id="fav-sort-ticker"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('price')">Precio <span id="fav-sort-price"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('1D')">1D <span id="fav-sort-1D"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('1W')">1W <span id="fav-sort-1W"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('1M')">1M <span id="fav-sort-1M"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('rs')">RS <span id="fav-sort-rs"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('atr')" title="Distancia a SMA50 en multiplos de ATR-14">ATR Ext. <span id="fav-sort-atr"></span></th>
      <th style="cursor:pointer" onclick="favSortBy('added')">Añadido <span id="fav-sort-added"></span></th>
      <th></th>
    </tr></thead><tbody id="tb-favoritas"></tbody></table></div>
    <div id="fav-empty" style="text-align:center;padding:40px 20px;color:var(--dim);font-size:12px;display:none">
      <div style="font-size:32px;margin-bottom:10px">☆</div>
      Aún no tienes favoritas. Pulsa la ☆ junto a cualquier ticker en Setups, Scanner o tablas de Sectores/Industrias para añadirlo aquí.
    </div>
  </div>

  <!-- MI BROKER -->
  <div id="tab-broker" class="tc">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
      <div>
        <div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">🔗 Mi Broker</div>
        <div style="font-size:10px;color:var(--dim);margin-top:2px">Conecta tu broker · Solo lectura · Datos en sesión</div>
      </div>
      <div id="broker-connect-btn-wrap">
        <button class="pb" onclick="brokerConnect()" id="broker-connect-btn"
          style="background:var(--ac);color:#fff;border:none;padding:10px 20px;font-size:13px;font-weight:700;border-radius:8px;cursor:pointer;">
          🔗 Conectar mi broker
        </button>
      </div>
    </div>

    <!-- Estado no conectado -->
    <div id="broker-disconnected">
      <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:12px;padding:40px;text-align:center;margin-top:20px">
        <div style="font-size:40px;margin-bottom:12px">🏦</div>
        <div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:var(--hi);margin-bottom:8px">Conecta tu broker</div>
        <div style="font-size:12px;color:var(--dim);max-width:400px;margin:0 auto;line-height:1.7">
          Conecta tu cuenta de Interactive Brokers, DEGIRO, Trading 212 u otros brokers para ver tus posiciones reales,
          historial de operaciones y evolución del capital — con las métricas del dashboard integradas.
        </div>
        <div style="margin-top:16px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
          <span style="font-size:11px;background:var(--bg3);padding:4px 10px;border-radius:99px;color:var(--dim)">🔒 Solo lectura</span>
          <span style="font-size:11px;background:var(--bg3);padding:4px 10px;border-radius:99px;color:var(--dim)">🚫 Sin contraseñas</span>
          <span style="font-size:11px;background:var(--bg3);padding:4px 10px;border-radius:99px;color:var(--dim)">💨 Datos en sesión</span>
        </div>
      </div>
    </div>

    <!-- Estado conectado -->
    <div id="broker-connected" style="display:none">

      <!-- KPIs -->
      <div id="broker-kpis" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-bottom:16px"></div>

      <!-- Tabs internos -->
      <div style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">
        <button class="pb active" id="bk-btn-posiciones" onclick="bkTab('posiciones',this)">Posiciones</button>
        <button class="pb" id="bk-btn-historial" onclick="bkTab('historial',this)">Historial</button>
        <button class="pb" id="bk-btn-equity" onclick="bkTab('equity',this)">Equity Curve</button>
        <button class="pb" id="bk-btn-metricas" onclick="bkTab('metricas',this)">📊 Métricas</button>
        <button class="pb" id="bk-discreet-btn" onclick="bkToggleDiscreto()" style="margin-left:auto">🙈 Mostrar</button>
        <button class="pb" style="color:var(--dn);border-color:rgba(244,63,94,.3)"
          onclick="brokerDisconnect()">Desconectar</button>
      </div>

      <!-- POSICIONES -->
      <div id="bk-posiciones">
        <div id="bk-pos-table"></div>
      </div>

      <!-- HISTORIAL -->
      <div id="bk-historial" style="display:none">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
          <label style="font-size:12px;color:var(--dim);font-weight:600">Año:</label>
          <select id="bk-hist-anio-select" onchange="bkFiltrarAnioHistorial()" style="padding:6px 10px;font-size:12px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)"></select>
        </div>
        <div id="bk-hist-table"></div>
      </div>

      <!-- EQUITY CURVE -->
      <div id="bk-equity" style="display:none">
        <div class="cw" style="padding:14px">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:8px">
            <div class="ct" style="margin-bottom:0">📈 Evolución del capital — reconstruida desde órdenes reales</div>
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
              <select id="bk-periodo-anio" onchange="bkFiltrarPeriodoMetricas()" style="padding:5px 8px;font-size:11px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)"></select>
              <select id="bk-periodo-rango" onchange="bkFiltrarPeriodoMetricas()" style="padding:5px 8px;font-size:11px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)">
                <option value="anio">Año completo</option>
                <option value="q1">1er trimestre</option>
                <option value="q2">2º trimestre</option>
                <option value="q3">3er trimestre</option>
                <option value="q4">4º trimestre</option>
                <option value="m1">Enero</option><option value="m2">Febrero</option><option value="m3">Marzo</option>
                <option value="m4">Abril</option><option value="m5">Mayo</option><option value="m6">Junio</option>
                <option value="m7">Julio</option><option value="m8">Agosto</option><option value="m9">Septiembre</option>
                <option value="m10">Octubre</option><option value="m11">Noviembre</option><option value="m12">Diciembre</option>
              </select>
              <select id="bk-benchmark-select" onchange="bkFiltrarPeriodoMetricas()" style="padding:5px 8px;font-size:11px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)">
                <option value="">Sin comparación</option>
                <option value="SPY">vs S&P 500</option>
                <option value="QQQ">vs Nasdaq 100</option>
              </select>
              <button class="pb" onclick="bkResetZoom()" style="font-size:10px;padding:4px 8px" title="Quitar zoom del gráfico (también puedes arrastrar para seleccionar zona, o rueda del ratón)">🔍 Quitar zoom</button>
            </div>
          </div>
          <div style="display:flex;gap:16px;align-items:baseline;margin-bottom:8px;font-size:11px;color:var(--dim)">
            Rendimiento real sobre capital total aportado (del periodo mostrado):
            <span id="bk-rendimiento-real" style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--tx)">—</span>
          </div>
          <div id="bk-equity-aviso" style="display:none;font-size:11px;color:var(--warn);background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.25);border-radius:6px;padding:8px 10px;margin-bottom:10px"></div>
          <div style="font-size:10px;color:var(--dim);margin-bottom:6px">🔍 Rueda del ratón para zoom · arrastra para desplazarte · arrastra con Shift para seleccionar una zona</div>
          <div style="position:relative;height:280px"><canvas id="bk-equity-canvas"></canvas></div>
        </div>
        <div class="cw" style="padding:14px;margin-top:8px">
          <div class="ct" style="margin-bottom:10px">📊 Métricas de rendimiento</div>
          <div id="bk-metricas-inline"></div>
        </div>
      </div>

      <!-- MÉTRICAS -->
      <div id="bk-metricas" style="display:none">
        <div id="bk-metricas-content"></div>
      </div>

    </div>
  </div>

  <!-- MI BROKER JS -->
  <script>
  var brokerLoaded = false;
  var BK_USER_SECRET = null;
  var BK_DATA = null;

  // NUEVO (09/07/2026): bug real encontrado en el log — d.balances trae
  // varias divisas (EUR, USD, CAD, AUD...) y el código las sumaba todas tal
  // cual, tratando 92.083€ como si fueran 92.083$. Esta función convierte
  // cada saldo a USD correctamente antes de sumar. Se calcula el tipo de
  // cambio EUR/USD EN EL MOMENTO de llamarla (no al cargar la página), igual
  // que se corrigió en Fiscalidad, para leer el dato real del Resumen.
  function balancesToUSD(balances){
    if(!Array.isArray(balances)) return 0;
    var eurUsd = 1.10; // fallback si D.benchmarks no está disponible
    if(typeof D !== 'undefined' && D.benchmarks){
      var eurData = D.benchmarks.find(function(b){ return b.ticker==='C:EURUSD' || b.name==='EUR/USD'; });
      if(eurData && eurData.price) eurUsd = parseFloat(eurData.price);
    }
    var totalUSD = 0;
    balances.forEach(function(b){
      var amount = parseFloat(b.cash || 0);
      var code = (b.currency && b.currency.code) || 'USD';
      if(code === 'USD') totalUSD += amount;
      else if(code === 'EUR') totalUSD += amount * eurUsd;
      // Otras divisas (CAD, AUD...): sin tipo de cambio fiable disponible
      // aquí — se ignoran en vez de sumarlas mal. En tu caso son ~0€, así
      // que no afecta al resultado, pero si algún día tienes saldo real en
      // otra divisa, avísame y añadimos su conversión específica.
    });
    return totalUSD;
  }

  // NUEVO (09/07/2026): lógica de recuperación compartida entre initBroker()
  // y fiscalCargar() — antes, si entrabas en Fiscalidad antes de que
  // terminara la recuperación en segundo plano (o sin pasar antes por Mi
  // Broker), te quedabas viendo "Conecta tu broker primero" para siempre,
  // aunque sí estuvieras conectado. Ahora Fiscalidad puede intentar
  // recuperar la conexión ella misma, en vez de rendirse a la primera.
  async function tryRecoverBroker(){
    if(BK_USER_SECRET) return true;
    if(!GLOBAL_USER) return false;
    var token = await getAuthToken();
    if(!token) return false;
    try{
      var r = await fetch('https://lacomunidad.onrender.com/snaptrade/connect', {
        method: 'POST',
        headers: {'Content-Type':'application/json', 'Authorization':'Bearer '+token},
        body: JSON.stringify({user_id: GLOBAL_USER.id})
      });
      var d = await r.json();
      if(d.error || !d.userSecret) return false;
      BK_USER_SECRET = d.userSecret;
      return true;
    }catch(e){ return false; }
  }

  async function initBroker(){
    // Si hay sesión guardada en memoria (ya cargado en esta misma navegación), usarla
    if(BK_USER_SECRET && BK_DATA){
      brokerMostrarDatos(BK_DATA);
      return;
    }
    var ok = await tryRecoverBroker();
    if(ok) brokerCargarDatos(); // carga datos automáticamente, sin popup
  }

  async function brokerConnect(){
    if(!GLOBAL_USER){ alert('Debes estar logueado para conectar tu broker.'); return; }
    var btn = document.getElementById('broker-connect-btn');
    btn.textContent = 'Conectando...'; btn.disabled = true;
    var token = await getAuthToken();
    if(!token){ alert('Tu sesión ha caducado, vuelve a iniciar sesión.'); btn.textContent='🔗 Conectar mi broker'; btn.disabled=false; return; }

    fetch('https://lacomunidad.onrender.com/snaptrade/connect', {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'Authorization':'Bearer '+token},
      body: JSON.stringify({user_id: GLOBAL_USER.id})
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d.error){ alert('Error: ' + d.error); btn.textContent='🔗 Conectar mi broker'; btn.disabled=false; return; }
      BK_USER_SECRET = d.userSecret;
      // Abrir el flujo OAuth de SnapTrade
      window.open(d.redirectURI, 'snaptrade', 'width=600,height=700');
      // Mostrar botón para que el usuario confirme cuando haya terminado
      btn.textContent = '✓ Ya conecté mi broker — cargar datos';
      btn.disabled = false;
      btn.style.background = '#f59e0b';
      btn.onclick = function(){ brokerCargarDatos(); };
    })
    .catch(function(e){
      alert('Error de conexión: ' + e.message);
      btn.textContent='🔗 Conectar mi broker'; btn.disabled=false;
    });
  }

  async function brokerCargarDatos(){
    var btn = document.getElementById('broker-connect-btn');
    btn.textContent = 'Cargando datos...'; btn.disabled = true;
    var token = await getAuthToken();
    if(!token){ alert('Tu sesión ha caducado, vuelve a iniciar sesión.'); btn.textContent='🔗 Conectar mi broker'; btn.disabled=false; return; }

    fetch('https://lacomunidad.onrender.com/snaptrade/data', {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'Authorization':'Bearer '+token},
      body: JSON.stringify({user_id: GLOBAL_USER.id, user_secret: BK_USER_SECRET})
    })
    .then(function(r){ return r.json(); })
    .then(function(d){
      if(d.error){ alert('Error cargando datos: ' + d.error); btn.textContent='🔗 Conectar mi broker'; btn.disabled=false; return; }
      BK_DATA = d;
      brokerMostrarDatos(d);
      btn.textContent='✓ Broker conectado'; btn.style.background='var(--up)';
    })
    .catch(function(e){
      alert('Error: ' + e.message);
      btn.textContent='🔗 Conectar mi broker'; btn.disabled=false;
    });
  }

  function bkSetDiscreto(on){
    var el = document.getElementById('broker-connected');
    var btn = document.getElementById('bk-discreet-btn');
    if(!el) return;
    if(on){
      el.classList.add('bk-discreet');
      if(btn) btn.textContent = '🙈 Mostrar';
    } else {
      el.classList.remove('bk-discreet');
      if(btn) btn.textContent = '🙉 Ocultar';
    }
  }
  function bkToggleDiscreto(){
    var el = document.getElementById('broker-connected');
    var isOn = el && el.classList.contains('bk-discreet');
    bkSetDiscreto(!isOn);
  }

  function brokerMostrarDatos(d){
    document.getElementById('broker-disconnected').style.display = 'none';
    document.getElementById('broker-connected').style.display = 'block';

    // Modo discreción SIEMPRE por defecto (10/07/2026): capado de inicio
    // cada vez, sin recordar elecciones anteriores — máxima privacidad.
    bkSetDiscreto(true);

    // Posiciones (nuevo formato: array plano desde /accounts/{id}/positions)
    var posiciones = Array.isArray(d.positions) ? d.positions : [];

    // KPIs (usando balances reales cuando estén disponibles)
    var totalVal = posiciones.reduce(function(s,p){
      var price = parseFloat((p.price!=null?p.price:(p.symbol&&p.symbol.last_price))||0);
      var units = parseFloat(p.units||p.fractional_units||0);
      return s + (price * units);
    }, 0);
    var totalCost = posiciones.reduce(function(s,p){
      var avg = parseFloat(p.average_purchase_price||p.price||0);
      var units = parseFloat(p.units||p.fractional_units||0);
      return s + (avg * units);
    }, 0);
    var totalPnL = totalVal - totalCost;
    var totalPnLPct = totalCost > 0 ? (totalPnL/totalCost*100) : 0;

    // Liquidez real (ya convertida a USD correctamente, ver balancesToUSD)
    var cashUSD = balancesToUSD(d.balances);
    var capitalTotal = totalVal + cashUSD;

    document.getElementById('broker-kpis').innerHTML = [
      bkKpi('Acciones (posiciones)', '$' + totalVal.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}), 'var(--ac)'),
      bkKpi('Liquidez', '$' + cashUSD.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}), 'var(--hi)'),
      bkKpi('Capital total', '$' + capitalTotal.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}), 'var(--ac2)'),
      bkKpi('P&L no realizado', (totalPnL>=0?'+':'') + totalPnL.toLocaleString('es-ES', {minimumFractionDigits:2, maximumFractionDigits:2}) + '$', totalPnL>=0?'var(--up)':'var(--dn)'),
      bkKpi('Rentabilidad (posiciones)', (totalPnLPct>=0?'+':'') + totalPnLPct.toFixed(2)+'%', totalPnLPct>=0?'var(--up)':'var(--dn)'),
      bkKpi('Posiciones', posiciones.length + ' activas', 'var(--hi)'),
    ].join('');

    // Tabla de posiciones con métricas del dashboard
    var posHtml = '<table style="width:100%;border-collapse:collapse;font-size:12px">';
    posHtml += '<thead><tr style="border-bottom:2px solid var(--b1)">';
    ['Ticker','Unidades','P.Medio','Precio','Valor','P&L','P&L%','RS','ATR Ext.','vs MA50','Tendencia'].forEach(function(h){
      posHtml += '<th style="text-align:left;padding:6px 8px;font-size:10px;color:var(--dim);font-weight:600">' + h + '</th>';
    });
    posHtml += '</tr></thead><tbody>';

    posiciones.forEach(function(p){
      var symObj = (p.symbol && p.symbol.symbol) ? p.symbol.symbol : (p.symbol || {});
      var tk = symObj.symbol || p.ticker || '';
      // Mismo criterio que en Fiscalidad — ver esa nota para el detalle
      var tipoCodigo = ((symObj.type && symObj.type.code) || '').toLowerCase();
      var tipoDesc = ((symObj.type && symObj.type.description) || '').toLowerCase();
      var esETF = tipoCodigo.indexOf('et')===0 || tipoCodigo==='etf' ||
                  tipoDesc.indexOf('etf')>=0 || tipoDesc.indexOf('exchange traded')>=0 ||
                  tipoDesc.indexOf('fund')>=0;
      var units = parseFloat(p.units || p.fractional_units || 0);
      var avgCost = parseFloat(p.average_purchase_price) || parseFloat(p.price) || 0;
      var price = parseFloat(p.price || (p.symbol && p.symbol.last_price) || 0);
      var valor = price * units;
      var pnl = (price - avgCost) * units;
      var pnlPct = avgCost > 0 ? ((price - avgCost) / avgCost * 100) : 0;
      var pnlColor = pnl >= 0 ? 'var(--up)' : 'var(--dn)';

      // Métricas del dashboard
      var dash = (D && D.stockPerf && D.stockPerf[tk]) || null;
      var rs = dash ? (dash.rs || '-') : '-';
      var atrExt = dash ? (dash.atrMult ? dash.atrMult.toFixed(1)+'x' : '-') : '-';
      var ma50ok = dash ? (dash.price > dash.ma50 ? '✅' : '❌') : '-';
      var tend = '-';
      if(dash && dash.price && dash.ma10 && dash.ma20 && dash.ma50){
        tend = (dash.price > dash.ma10 && dash.ma10 > dash.ma20 && dash.ma20 > dash.ma50) ? '✅ Alcista' : '⚠️ Mixta';
      }

      var rsColor = typeof rs === 'number' ? (rs>=90?'var(--up)':rs>=70?'var(--warn)':'var(--dn)') : 'var(--dim)';

      posHtml += '<tr style="border-bottom:1px solid var(--b1)">';
      posHtml += '<td style="padding:6px 8px;font-weight:700;color:var(--ac)">' + tk + (esETF?' <span style="font-size:9px;color:var(--hi);background:var(--bg3);border:1px solid var(--b2);border-radius:3px;padding:0 4px">ETF</span>':'') + '</td>';
      posHtml += '<td style="padding:6px 8px">' + units.toFixed(2) + '</td>';
      posHtml += '<td style="padding:6px 8px">$' + avgCost.toFixed(2) + '</td>';
      posHtml += '<td style="padding:6px 8px;font-weight:600">$' + price.toFixed(2) + '</td>';
      posHtml += '<td style="padding:6px 8px">$' + valor.toFixed(2) + '</td>';
      posHtml += '<td style="padding:6px 8px;color:' + pnlColor + '">' + (pnl>=0?'+':'') + pnl.toFixed(2) + '$</td>';
      posHtml += '<td style="padding:6px 8px;color:' + pnlColor + ';font-weight:700">' + (pnlPct>=0?'+':'') + pnlPct.toFixed(2) + '%</td>';
      posHtml += '<td style="padding:6px 8px;color:' + rsColor + ';font-weight:700">' + rs + '</td>';
      posHtml += '<td style="padding:6px 8px">' + atrExt + '</td>';
      posHtml += '<td style="padding:6px 8px;text-align:center">' + ma50ok + '</td>';
      posHtml += '<td style="padding:6px 8px;font-size:11px">' + tend + '</td>';
      posHtml += '</tr>';
    });
    posHtml += '</tbody></table>';
    if(posiciones.length === 0){
      posHtml = '<div style="text-align:center;padding:40px;color:var(--dim);font-size:12px">Sin posiciones disponibles todavía.<br>IBKR puede tardar 1-2 días en sincronizar tras la conexión inicial.</div>';
    }
    document.getElementById('bk-pos-table').innerHTML = posHtml;

    // Historial de operaciones — NUEVO (13/08/2026): antes solo leía
    // "orders" (tope de 21 en tu caso, confirmado por SnapTrade). Ahora
    // fusiona "activities" (hasta 1.777 reales, ya paginado) con "orders"
    // como respaldo — mismo patrón que ya usa el cálculo de Renta, para no
    // tener dos fuentes de verdad distintas en la misma pantalla.
    var listaActivities = Array.isArray(d.activities) ? d.activities : (d.activities && d.activities.data) || [];
    var trades = [];
    var clavesYaVistas = {};
    listaActivities.forEach(function(a){
      var tipo = (a.type||'').toUpperCase();
      if(tipo !== 'BUY' && tipo !== 'SELL') return; // solo compras/ventas, no depósitos/dividendos aquí
      var tk = (a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '';
      var fecha = (a.trade_date || a.settlement_date || '').slice(0,10);
      var qty = Math.abs(parseFloat(a.units || 0));
      var price = parseFloat(a.price || 0);
      if(!tk || !fecha || !qty || !price) return;
      var clave = tk+'|'+tipo+'|'+fecha+'|'+qty.toFixed(4);
      clavesYaVistas[clave] = true;
      trades.push({fecha: fecha, ticker: tk, tipo: tipo, qty: qty, price: price, origen: 'activities'});
    });
    var orders = Array.isArray(d.orders) ? d.orders.slice() : [];
    orders.forEach(function(o){
      var tk = (o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '';
      var qty = parseFloat(o.total_quantity || o.filled_quantity || 0);
      var price = parseFloat(o.execution_price || o.limit_price || 0);
      var action = (o.action || '').toUpperCase();
      var fecha = (o.time_executed || o.time_placed || o.time_updated || '').slice(0,10);
      if(!tk || !qty || !price || !fecha) return;
      var claveBase = (action.indexOf('BUY')>=0 ? 'BUY' : action.indexOf('SELL')>=0 ? 'SELL' : action);
      var clave = tk+'|'+claveBase+'|'+fecha+'|'+qty.toFixed(4);
      if(clavesYaVistas[clave]) return; // ya está en activities, no duplicar
      trades.push({fecha: fecha, ticker: tk, tipo: action, qty: qty, price: price, origen: 'orders', estado: o.status});
    });
    trades.sort(function(a,b){ return b.fecha.localeCompare(a.fecha); });

    // NUEVO (14/08/2026): guardar TODOS los trades sin filtrar, y rellenar
    // el desplegable de año — mismo patrón que ya usa Renta.
    BK_TODOS_LOS_TRADES = trades;
    var selectAnio = document.getElementById('bk-hist-anio-select');
    if(selectAnio){
      var anios = Array.from(new Set(trades.map(function(t){ return t.fecha.slice(0,4); }))).sort().reverse();
      var valorPrevio = selectAnio.value;
      selectAnio.innerHTML = '<option value="">Todos</option>' + anios.map(function(a){ return '<option value="'+a+'">'+a+'</option>'; }).join('');
      if(Array.from(selectAnio.options).some(function(o){ return o.value===valorPrevio; })) selectAnio.value = valorPrevio;
    }
    bkFiltrarAnioHistorial();
    bkContinuarConEquity(d, posiciones, orders);
  }

  var BK_TODOS_LOS_TRADES = [];
  function bkFiltrarAnioHistorial(){
    var selectAnio = document.getElementById('bk-hist-anio-select');
    var anio = selectAnio ? selectAnio.value : '';
    var trades = anio ? BK_TODOS_LOS_TRADES.filter(function(t){ return t.fecha.slice(0,4) === anio; }) : BK_TODOS_LOS_TRADES;

    var histHtml = '<div style="font-size:10px;color:var(--dim);margin-bottom:6px">'+trades.length+' operaciones'+(anio?(' en '+anio):'')+' · '+(trades.length?('desde '+trades[trades.length-1].fecha+' hasta '+trades[0].fecha):'—')+'</div>';
    histHtml += '<table style="width:100%;border-collapse:collapse;font-size:12px">';
    histHtml += '<thead><tr style="border-bottom:2px solid var(--b1)">';
    ['Fecha','Ticker','Tipo','Estado','Unidades','Precio'].forEach(function(h){
      histHtml += '<th style="text-align:left;padding:6px 8px;font-size:10px;color:var(--dim);font-weight:600">'+h+'</th>';
    });
    histHtml += '</tr></thead><tbody>';
    trades.forEach(function(t){
      var tipoColor = t.tipo.indexOf('BUY')>=0 ? 'var(--up)' : t.tipo.indexOf('SELL')>=0 ? 'var(--dn)' : 'var(--dim)';
      var estado = t.origen === 'activities' ? 'Ejecutada' : (t.estado || '-');
      histHtml += '<tr style="border-bottom:1px solid var(--b1)">';
      histHtml += '<td style="padding:6px 8px;color:var(--dim)">'+t.fecha+'</td>';
      histHtml += '<td style="padding:6px 8px;font-weight:700;color:var(--ac)">'+t.ticker+'</td>';
      histHtml += '<td style="padding:6px 8px;color:'+tipoColor+';font-weight:600">'+t.tipo+'</td>';
      histHtml += '<td style="padding:6px 8px">'+estado+'</td>';
      histHtml += '<td style="padding:6px 8px">'+t.qty.toFixed(2)+'</td>';
      histHtml += '<td style="padding:6px 8px">$'+t.price.toFixed(2)+'</td>';
      histHtml += '</tr>';
    });
    histHtml += '</tbody></table>';
    if(trades.length === 0){
      histHtml = '<div style="text-align:center;padding:40px;color:var(--dim);font-size:12px">Sin historial de operaciones'+(anio?(' en '+anio):'')+' disponible.'+(BK_TODOS_LOS_TRADES.length===0?'<br>IBKR puede tardar 1-2 días en sincronizar tras la conexión inicial.':'')+'</div>';
    }
    document.getElementById('bk-hist-table').innerHTML = histHtml;
  }

  function bkContinuarConEquity(d, posiciones, orders){
    // Equity curve reconstruida desde órdenes reales + depósitos/retiradas.
    // NUEVO (13/08/2026): los precios históricos ahora se piden a un
    // endpoint APARTE (bkFetchPriceHistory) para que, si Polygon va lento,
    // solo se resienta la curva — el resto de la pantalla (posiciones,
    // historial) ya se ha pintado antes de llegar aquí, sin esperar nada.
    bkFetchPriceHistory(orders, d.activities || []).then(function(priceHistory){
      bkConstruirEquity(posiciones, orders, d.balances || [], d.activities || [], priceHistory);
    });
  }

  async function bkFetchPriceHistory(orders, activities){
    try{
      var tickers = {};
      var fechaMin = null;
      (orders||[]).forEach(function(o){
        var tk = (o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '';
        if(tk && tk.length<=6) tickers[tk] = true;
        var f = (o.time_executed || o.time_placed || '').slice(0,10);
        if(f && (!fechaMin || f < fechaMin)) fechaMin = f;
      });
      // NUEVO (13/08/2026): activities ahora llega hasta 2024 (antes solo
      // orders, mucho más corto) — sin esto, la curva se quedaba plana en
      // los tramos viejos por no tener ni el ticker ni la fecha para pedir
      // su precio histórico.
      var listaActivities = Array.isArray(activities) ? activities : (activities && activities.data) || [];
      listaActivities.forEach(function(a){
        var tipo = (a.type||'').toUpperCase();
        if(tipo !== 'BUY' && tipo !== 'SELL') return;
        var tk = (a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '';
        if(tk && tk.length<=6) tickers[tk] = true;
        var f = (a.trade_date || a.settlement_date || '').slice(0,10);
        if(f && (!fechaMin || f < fechaMin)) fechaMin = f;
      });
      var listaTickers = Object.keys(tickers);
      // NUEVO (26/08/2026): añadimos SIEMPRE SPY (S&P 500) y QQQ (Nasdaq
      // 100) a la petición — así su histórico de precios ya está disponible
      // para poder comparar la curva contra un índice, sin tener que pedir
      // nada aparte cuando el usuario elija comparar.
      if(listaTickers.indexOf('SPY')<0) listaTickers.push('SPY');
      if(listaTickers.indexOf('QQQ')<0) listaTickers.push('QQQ');
      if(listaTickers.length === 0 || !fechaMin) return {};
      var token = await getAuthToken();
      if(!token) return {};
      var resp = await fetch('https://lacomunidad.onrender.com/snaptrade/price-history', {
        method: 'POST',
        headers: {'Content-Type':'application/json', 'Authorization':'Bearer '+token},
        body: JSON.stringify({user_id: GLOBAL_USER.id, tickers: listaTickers, start_date: fechaMin})
      });
      var data = await resp.json();
      // NUEVO (09/08/2026): esta misma llamada ya trae el histórico diario
      // EUR/USD (la usa también Renta) — lo cacheamos aquí de paso, así si
      // el alumno visita Mi Broker antes que Fiscalidad, Renta no tiene que
      // volver a pedirlo para ese rango de fechas.
      if(data.eurUsdHistory) Object.keys(data.eurUsdHistory).forEach(function(f){ EURUSD_HISTORICO[f] = data.eurUsdHistory[f]; });
      return data.priceHistory || {};
    }catch(e){
      console.warn('No se pudieron cargar precios históricos para la curva:', e);
      return {}; // la curva sigue funcionando, solo sin precios reales día a día — degradado, no roto
    }
  }

  // NUEVO (26/08/2026): guardamos la curva completa (fechas/valores/cashflows)
  // para poder recalcular las métricas por año/trimestre/mes sin tener que
  // reconstruir la curva entera cada vez que cambias el periodo.
  var BK_EQUITY_DATES = [];
  var BK_EQUITY_VALUES = [];
  var BK_EQUITY_CASHFLOWS = [];
  var BK_EQUITY_ORDERS = [];
  var BK_EQUITY_POSICIONES = [];
  var BK_METRICAS_PERIODO = {anio: null, rango: null};
  var BK_PRICE_HISTORY = {}; // guardado para poder calcular la comparación contra SPY/QQQ al filtrar por periodo
  var BK_BENCHMARK_ACTUAL = ''; // '', 'SPY' o 'QQQ' — qué comparación está activa ahora mismo

  function bkConstruirEquity(posiciones, orders, balances, activities, priceHistory){
    BK_PRICE_HISTORY = priceHistory || {}; // NUEVO (26/08/2026): para poder calcular la comparación contra SPY/QQQ luego
    // Cash real desde balances — convertido correctamente por divisa (antes
    // sumaba EUR y USD como si fueran lo mismo, ver balancesToUSD)
    var cashReal = Math.max(0, balancesToUSD(balances));
    // Construir cartera día a día desde las órdenes
    if(!orders || orders.length === 0){
      document.getElementById('bk-equity-canvas').parentElement.innerHTML =
        '<div style="text-align:center;padding:40px;color:var(--dim);font-size:12px">Sin órdenes suficientes para construir la curva de equity.</div>';
      return;
    }



    // "metiste dinero" con "ganaste dinero" en la curva. Se filtran solo los
    // tipos de aportación/retirada de capital (no trades, esos ya vienen de
    // `orders`). Nombres de campo cubiertos de forma defensiva porque no
    // hemos podido verificar el formato exacto de SnapTrade en producción
    // todavía — si algo no encaja, revisa los logs de Render ("SnapTrade
    // activities: ...") y ajustamos los nombres de campo.
    var DEPOSIT_TYPES = ['CONTRIBUTION','DEPOSIT','TRANSFER_IN','EXTERNAL_ASSET_TRANSFER_IN','CASH_TRANSFER_IN'];
    var WITHDRAWAL_TYPES = ['WITHDRAWAL','TRANSFER_OUT','EXTERNAL_ASSET_TRANSFER_OUT','CASH_TRANSFER_OUT'];
    var cashFlows = []; // {date, amount} — positivo = aportación, negativo = retirada
    var totalAportado = 0;
    if(Array.isArray(activities)){
      activities.forEach(function(a){
        var tipo = (a.type || a.activity_type || '').toUpperCase();
        var fecha = (a.trade_date || a.settlement_date || a.date || '').slice(0,10);
        var monto = parseFloat(a.amount || a.net_amount || 0);
        if(!fecha || !monto) return;
        if(DEPOSIT_TYPES.indexOf(tipo)>=0){
          cashFlows.push({date:fecha, amount: Math.abs(monto)});
          totalAportado += Math.abs(monto);
        } else if(WITHDRAWAL_TYPES.indexOf(tipo)>=0){
          cashFlows.push({date:fecha, amount: -Math.abs(monto)});
          totalAportado -= Math.abs(monto);
        }
      });
    }

    // Ordenar órdenes por fecha
    var sorted = orders.filter(function(o){ return o.status==='EXECUTED' || o.status==='FILLED'; })
      .sort(function(a,b){
        return new Date(a.time_placed||a.time_executed||0) - new Date(b.time_placed||b.time_executed||0);
      });

    if(sorted.length === 0){
      sorted = orders.sort(function(a,b){
        return new Date(a.time_placed||a.time_executed||0) - new Date(b.time_placed||b.time_executed||0);
      });
    }

    // NUEVO (13/08/2026): reconstrucción DÍA A DÍA con precios reales de
    // mercado (priceHistory, pedido en el servidor solo para los tickers de
    // tu propio historial) — antes solo había un punto por cada día que
    // operabas, valorado al coste de compra en vez del precio real, lo que
    // daba una curva a saltos feos. Ahora hay un punto por cada día natural
    // desde tu primera operación hasta hoy, valorado a precio de mercado.
    var portfolio = {}; // tk -> unidades
    var cash = 0;
    var equityPoints = [];
    var ultimoPrecioConocido = {}; // tk -> último precio real visto (relleno hacia adelante en findes/festivos)

    // NUEVO (27/08/2026) — BUG REAL ENCONTRADO: esto usaba solo "orders"
    // para las compras/ventas día a día — y "orders" tiene el tope de ~90
    // días CONFIRMADO por SnapTrade, sin forma de saltárselo. Por eso la
    // curva se quedaba plana (sin ningún movimiento de cartera) para
    // cualquier fecha más antigua que esa ventana, aunque tuviéramos el
    // historial completo en "activities" (la misma fuente que ya usa
    // Renta y el Modelo 720, con cobertura de años). Se cambia a
    // "activities" como fuente principal — mismo alias de ticker
    // (SQ→XYZ) y mismo orden por timestamp completo que ya validamos ahí.
    var TICKER_ALIASES_EQ = { 'SQ': 'XYZ' };
    function normalizarTickerEq(tk){ return TICKER_ALIASES_EQ[tk] || tk; }
    var listaActivitiesEq = Array.isArray(activities) ? activities : (activities && activities.data) || [];
    var eventosOrden = [];
    var vistosEq = {};
    listaActivitiesEq.forEach(function(a){
      var tipo = (a.type||'').toUpperCase();
      if(tipo !== 'BUY' && tipo !== 'SELL') return;
      var tk = normalizarTickerEq((a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '');
      var fechaHoraFull = a.trade_date || a.settlement_date || '';
      var fecha = fechaHoraFull.slice(0,10);
      var qty = Math.abs(parseFloat(a.units || 0));
      var price = parseFloat(a.price || 0);
      if(!tk || !fecha || !qty || !price) return;
      var clave = tk+'|'+tipo+'|'+fecha+'|'+qty.toFixed(4);
      vistosEq[clave] = true;
      eventosOrden.push({tipo:'orden', tk:tk, action:tipo, qty:qty, price:price, fecha:fecha, fechaHora: fechaHoraFull||fecha});
    });
    // Respaldo con "orders" por si algún trade no está en activities (mismo
    // patrón que ya usa Renta) — solo añade lo que no esté ya cubierto.
    sorted.forEach(function(o){
      var tk = normalizarTickerEq((o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '');
      var qty = parseFloat(o.total_quantity || o.filled_quantity || 0);
      var price = parseFloat(o.execution_price || o.limit_price || 0);
      var action = (o.action || '').toUpperCase().indexOf('SELL')>=0 ? 'SELL' : 'BUY';
      var fechaHoraFull = o.time_executed || o.time_placed || '';
      var fecha = fechaHoraFull.slice(0,10);
      if(!tk || !qty || !price || !fecha) return;
      var clave = tk+'|'+action+'|'+fecha+'|'+qty.toFixed(4);
      if(vistosEq[clave]) return;
      eventosOrden.push({tipo:'orden', tk:tk, action:action, qty:qty, price:price, fecha:fecha, fechaHora: fechaHoraFull||fecha});
    });

    var eventos = eventosOrden.map(function(e){ return {tipo:'orden', data:e, fecha:e.fecha, fechaHora:e.fechaHora}; })
      .concat(cashFlows.map(function(cf){ return {tipo:'cashflow', data:cf, fecha:cf.date, fechaHora:cf.date}; }));
    eventos.sort(function(a,b){ return (a.fechaHora||a.fecha||'').localeCompare(b.fechaHora||b.fecha||''); });

    if(eventos.length === 0){
      document.getElementById('bk-equity-canvas').parentElement.innerHTML =
        '<div style="text-align:center;padding:40px;color:var(--dim);font-size:12px">Sin eventos suficientes para construir la curva de equity.</div>';
      return;
    }

    var fechaInicio = eventos[0].fecha;
    var fechaFin = new Date().toISOString().slice(0,10);
    var idxEvento = 0;
    var cursor = new Date(fechaInicio+'T00:00:00Z');
    var fin = new Date(fechaFin+'T00:00:00Z');

    while(cursor <= fin){
      var fechaStr = cursor.toISOString().slice(0,10);

      // Aplicar todos los eventos de este día ANTES de valorar la cartera
      while(idxEvento < eventos.length && eventos[idxEvento].fecha === fechaStr){
        var ev = eventos[idxEvento];
        if(ev.tipo === 'cashflow'){
          cash += ev.data.amount;
        } else {
          var e = ev.data;
          var tk = e.tk, qty = e.qty, price = e.price, action = e.action;
          if(tk && qty && price){
            if(!portfolio[tk]) portfolio[tk] = 0;
            // NUEVO (27/08/2026): ya no se topa en 0 — mismo motivo que en
            // el Modelo 720 (una venta en corto sin etiquetar dejaba la
            // posición clavada en 0 en vez de poder bajar, y la recompra
            // posterior se sumaba encima de ese cero falso).
            if(action === 'BUY'){ portfolio[tk] += qty; cash -= price*qty; }
            else if(action === 'SELL'){ portfolio[tk] = portfolio[tk]-qty; cash += price*qty; }
          }
        }
        idxEvento++;
      }

      // Valorar la cartera de ese día con precio real, con relleno hacia
      // adelante cuando ese día concreto no tiene precio (fin de semana,
      // festivo, o Polygon no tenía dato ese día en concreto).
      var totalVal = 0;
      Object.keys(portfolio).forEach(function(tk){
        var units = portfolio[tk];
        if(units === 0) return;
        var hist = priceHistory && priceHistory[tk];
        var precioHoy = hist ? hist[fechaStr] : undefined;
        if(precioHoy !== undefined) ultimoPrecioConocido[tk] = precioHoy;
        var precioUsado = ultimoPrecioConocido[tk];
        if(precioUsado === undefined){
          var dash = D && D.stockPerf && D.stockPerf[tk];
          precioUsado = dash ? dash.price : 0;
        }
        // NUEVO (27/08/2026): unidades negativas (posición corta) ya
        // restan valor de mercado en vez de ignorarse — antes cualquier
        // "units <= 0" se saltaba directamente, borrando el efecto de los
        // cortos en el valor de la cartera.
        totalVal += precioUsado * units;
      });

      equityPoints.push({date: fechaStr, value: totalVal + cash});
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }

    // El último punto (hoy) se sustituye por el valor REAL exacto de
    // balances/posiciones actuales — más preciso que "último precio
    // conocido", porque es el dato en vivo del broker en este momento.
    if(posiciones.length > 0){
      var currentVal = posiciones.reduce(function(s,p){
        var price = parseFloat(p.price || 0);
        var units = parseFloat(p.units || p.fractional_units || 0);
        return s + (price * units);
      }, 0) + cashReal;
      if(equityPoints.length > 0) equityPoints[equityPoints.length-1].value = currentVal;
      else equityPoints.push({date: fechaFin, value: currentVal});

      // Rendimiento real sobre el capital total aportado (no solo lo
      // invertido) — si metiste 100K y solo 20K están invertidos, el % se
      // calcula sobre el total aportado.
      var elKpi = document.getElementById('bk-rendimiento-real');
      if(elKpi && totalAportado > 0){
        var pct = ((currentVal - totalAportado) / totalAportado) * 100;
        elKpi.textContent = (pct>=0?'+':'')+pct.toFixed(1)+'%';
        elKpi.style.color = pct>=0 ? 'var(--up)' : 'var(--dn)';
      } else if(elKpi){
        elKpi.textContent = '—';
      }

      // Aviso cuando hay liquidez real pero NINGÚN depósito/aportación
      // detectado en el historial — ese dinero ya estaba en la cuenta
      // antes de la ventana de datos visible, no es una ganancia repentina.
      var avisoEl = document.getElementById('bk-equity-aviso');
      if(avisoEl){
        if(cashFlows.length === 0 && cashReal > 1000){
          avisoEl.style.display = 'block';
          avisoEl.innerHTML = '⚠️ No se ha detectado ningún depósito/aportación en el historial disponible, pero sí hay '
            + cashReal.toLocaleString('es-ES',{maximumFractionDigits:0}) + '$ de liquidez real. '
            + 'Ese dinero probablemente ya estaba en la cuenta antes de lo que el broker nos deja ver — por eso la curva '
            + 'puede dar un salto al principio: no es una ganancia repentina, es liquidez que no se puede fechar retroactivamente con los datos disponibles.';
        } else {
          avisoEl.style.display = 'none';
        }
      }
    }

    // Deduplicar por fecha (quedarse con el último valor del día)
    var byDate = {};
    equityPoints.forEach(function(pt){ byDate[pt.date] = pt.value; });
    var dates = Object.keys(byDate).sort();
    var values = dates.map(function(d){ return byDate[d]; });

    // NUEVO (26/08/2026): se guarda todo para el selector de periodo/
    // comparación, y se dibuja a través de bkFiltrarPeriodoMetricas — así
    // el primer dibujado respeta lo que haya seleccionado en los
    // desplegables (por defecto "todo el histórico" y "sin comparación",
    // el mismo comportamiento de siempre).
    BK_EQUITY_DATES = dates;
    BK_EQUITY_VALUES = values;
    BK_EQUITY_CASHFLOWS = cashFlows;
    BK_EQUITY_ORDERS = orders;
    BK_EQUITY_POSICIONES = posiciones;
    bkActualizarSelectorPeriodoMetricas();
    bkFiltrarPeriodoMetricas(); // dibuja el gráfico + calcula métricas, respetando los desplegables
  }
    // NUEVO (26/08/2026): dibuja la curva de equity — extraído a función
  // aparte para poder reutilizarlo cuando cambias de periodo (año/trimestre/
  // mes) sin duplicar todo el código del gráfico.
  //
  // Estilo "tipo Interactive Brokers": cada TRAMO de la línea (y el relleno
  // debajo) se pinta en verde si ese tramo subió respecto al punto anterior,
  // y en rojo si bajó — usando la opción "segment" de Chart.js, en vez de un
  // único color fijo para toda la curva.
  //
  // Zoom: rueda del ratón para acercar/alejar, arrastrar para desplazarte,
  // arrastrar con Shift para seleccionar una zona — vía chartjs-plugin-zoom.
  function bkDibujarEquityChart(dates, values, benchmarkSerie, benchmarkLabel){
    var ctx = document.getElementById('bk-equity-canvas').getContext('2d');
    if(window.bkEquityChart) window.bkEquityChart.destroy();

    var VERDE = 'rgb(16,185,129)', ROJO = 'rgb(244,63,94)';
    var VERDE_FILL = 'rgba(16,185,129,0.10)', ROJO_FILL = 'rgba(244,63,94,0.10)';

    var datasets = [{
      label:'Capital',
      data: values,
      borderWidth:2.5,
      pointRadius: dates.length < 30 ? 4 : 0,
      pointHoverRadius: 5,
      tension:0.15,
      fill: true,
      order: 1,
      segment: {
        borderColor: function(c){ return (c.p1.parsed.y >= c.p0.parsed.y) ? VERDE : ROJO; },
        backgroundColor: function(c){ return (c.p1.parsed.y >= c.p0.parsed.y) ? VERDE_FILL : ROJO_FILL; }
      },
      pointBackgroundColor: function(c){
        if(c.dataIndex === 0) return VERDE;
        var v = c.dataset.data[c.dataIndex], prev = c.dataset.data[c.dataIndex-1];
        return v >= prev ? VERDE : ROJO;
      }
    }];
    // NUEVO (26/08/2026): línea de comparación — "qué habría pasado con este
    // mismo dinero, metido en las mismas fechas, en el índice elegido en vez
    // de en tus operaciones". Línea discontinua gris, sin relleno, para no
    // competir visualmente con la curva real verde/roja.
    if(benchmarkSerie){
      datasets.push({
        label: benchmarkLabel || 'Índice',
        data: benchmarkSerie,
        borderColor: 'rgba(148,163,184,0.9)',
        backgroundColor: 'transparent',
        borderWidth: 1.8,
        borderDash: [5,4],
        pointRadius: 0,
        pointHoverRadius: 3,
        tension: 0.15,
        fill: false,
        order: 2
      });
    }

    window.bkEquityChart = new Chart(ctx, {
      type:'line',
      data:{
        labels: dates,
        datasets: datasets
      },
      options:{
        responsive:true, maintainAspectRatio:false,
        interaction:{mode:'index', intersect:false},
        plugins:{
          legend:{display: !!benchmarkSerie, position:'top', align:'end', labels:{color:'var(--dim)', boxWidth:14, font:{size:10}}},
          tooltip:{
            callbacks:{
              label:function(ctx){
                return ' '+ctx.dataset.label+': $'+ctx.parsed.y.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2});
              }
            }
          },
          zoom:{
            pan:{enabled:true, mode:'x'},
            zoom:{
              wheel:{enabled:true},
              pinch:{enabled:true},
              drag:{enabled:true, modifierKey:'shift', backgroundColor:'rgba(79,110,247,0.15)'},
              mode:'x'
            },
            limits:{x:{minRange:3}}
          }
        },
        scales:{
          x:{ticks:{color:'var(--dim)',font:{size:10},maxTicksLimit:8},grid:{display:false}},
          y:{ticks:{color:'var(--dim)',font:{size:10},callback:function(v){return '$'+v.toLocaleString('en-US',{maximumFractionDigits:0});}},grid:{color:'rgba(128,128,128,0.1)'}}
        }
      }
    });
  }

  // NUEVO (26/08/2026): calcula "qué habría pasado si este mismo dinero,
  // metido en las MISMAS fechas y por los MISMOS importes, hubiera ido a
  // un índice (SPY/QQQ) en vez de a tus operaciones reales" — en vez de
  // simplemente pintar el índice al lado (que engañaría igual que hacía el
  // bug del Retorno Total, mezclando "cuándo metiste el dinero" con
  // "cuánto ganaste"). Arranca en el MISMO valor que la curva real el
  // primer día del tramo mostrado, y aplica las mismas aportaciones/
  // retiradas el mismo día, al precio real del índice ese día.
  function bkCalcularSerieBenchmark(ticker, dates, values, cashFlows){
    var hist = (BK_PRICE_HISTORY && BK_PRICE_HISTORY[ticker]) || {};
    var fechasHist = Object.keys(hist).sort();
    if(!dates.length || !fechasHist.length) return null;

    // Precio del índice el primer día del tramo (o el más cercano hacia atrás)
    var primerPrecio = null;
    for(var i=0;i<fechasHist.length;i++){
      if(fechasHist[i] <= dates[0]) primerPrecio = hist[fechasHist[i]]; else break;
    }
    if(primerPrecio === null) primerPrecio = hist[fechasHist[0]];
    if(!primerPrecio) return null;

    var porFecha = {};
    (cashFlows||[]).forEach(function(cf){ porFecha[cf.date] = (porFecha[cf.date]||0) + cf.amount; });

    var shares = values[0] / primerPrecio; // mismo valor de partida que la curva real
    var ultimoPrecio = primerPrecio;
    var serie = [];
    dates.forEach(function(f, i){
      if(hist[f] !== undefined) ultimoPrecio = hist[f]; // si no cotizó ese día (finde/festivo), se usa el último conocido
      if(i > 0 && porFecha[f]) shares += porFecha[f] / ultimoPrecio;
      serie.push(shares * ultimoPrecio);
    });
    return serie;
  }

  function bkResetZoom(){
    if(window.bkEquityChart && window.bkEquityChart.resetZoom) window.bkEquityChart.resetZoom();
  }

  // NUEVO (26/08/2026): selector de año/periodo para la curva y las
  // métricas — mismo patrón que ya usamos en Renta. Rellena el desplegable
  // de años con los que de verdad aparecen en la curva reconstruida.
  function bkActualizarSelectorPeriodoMetricas(){
    var selAnio = document.getElementById('bk-periodo-anio');
    if(!selAnio || !BK_EQUITY_DATES.length) return;
    var anios = Array.from(new Set(BK_EQUITY_DATES.map(function(d){ return d.slice(0,4); }))).sort().reverse();
    var valorPrevio = BK_METRICAS_PERIODO.anio;
    selAnio.innerHTML = '<option value="">Todo el histórico</option>' + anios.map(function(a){ return '<option value="'+a+'">'+a+'</option>'; }).join('');
    BK_METRICAS_PERIODO.anio = (valorPrevio && anios.indexOf(valorPrevio)>=0) ? valorPrevio : '';
    selAnio.value = BK_METRICAS_PERIODO.anio;
  }

  function bkRangoDePeriodo(valor){
    if(!valor || valor === 'anio') return null;
    if(valor.charAt(0) === 'q'){ var q = parseInt(valor.slice(1),10); return {mesInicio:(q-1)*3+1, mesFin:q*3}; }
    if(valor.charAt(0) === 'm'){ var m = parseInt(valor.slice(1),10); return {mesInicio:m, mesFin:m}; }
    return null;
  }

  // Recalcula y redibuja TODO (gráfico + métricas + KPI de rendimiento real)
  // para el año/periodo elegido — filtrando la curva ya construida, sin
  // volver a pedir nada al servidor.
  function bkFiltrarPeriodoMetricas(){
    if(!BK_EQUITY_DATES.length) return;
    var anio = document.getElementById('bk-periodo-anio').value;
    var rangoVal = document.getElementById('bk-periodo-rango').value;
    var rango = bkRangoDePeriodo(rangoVal);
    BK_METRICAS_PERIODO = {anio: anio, rango: rangoVal};

    var idxFiltrados = [];
    BK_EQUITY_DATES.forEach(function(d, i){
      if(anio && d.slice(0,4) !== anio) return;
      if(rango){
        var mes = parseInt(d.slice(5,7),10);
        if(mes < rango.mesInicio || mes > rango.mesFin) return;
      }
      idxFiltrados.push(i);
    });
    if(idxFiltrados.length < 2){
      document.getElementById('bk-metricas-inline').innerHTML =
        '<div style="text-align:center;padding:20px;color:var(--dim);font-size:12px">Sin suficientes días en este periodo para calcular métricas.</div>';
      document.getElementById('bk-metricas-content').innerHTML = document.getElementById('bk-metricas-inline').innerHTML;
      return;
    }
    var datesF = idxFiltrados.map(function(i){ return BK_EQUITY_DATES[i]; });
    var valuesF = idxFiltrados.map(function(i){ return BK_EQUITY_VALUES[i]; });

    var benchmarkTk = document.getElementById('bk-benchmark-select') ? document.getElementById('bk-benchmark-select').value : '';
    BK_BENCHMARK_ACTUAL = benchmarkTk;
    var benchmarkSerie = benchmarkTk ? bkCalcularSerieBenchmark(benchmarkTk, datesF, valuesF, BK_EQUITY_CASHFLOWS) : null;
    var benchmarkLabel = benchmarkTk === 'SPY' ? 'S&P 500' : benchmarkTk === 'QQQ' ? 'Nasdaq 100' : '';

    bkDibujarEquityChart(datesF, valuesF, benchmarkSerie, benchmarkLabel);
    bkMetricasDesdeValues(valuesF, datesF, BK_EQUITY_POSICIONES, BK_EQUITY_ORDERS, BK_EQUITY_CASHFLOWS);
  }

  // NUEVO (27/08/2026) — BUG REAL ENCONTRADO Y CONFIRMADO (Victor lo vio en
  // pantalla): el arreglo de ayer usaba el capital aportado DESDE SIEMPRE
  // hasta el final del tramo — así que "año completo" y "un mes cualquiera"
  // daban el MISMO % en cuanto ese mes fuera el más reciente con datos (los
  // dos terminan en la misma fecha, y ninguno restaba las aportaciones
  // anteriores al propio tramo). Ahora se usa como base el valor de INICIO
  // del tramo mostrado (que ya arrastra todo lo anterior) más solo las
  // aportaciones que se hicieran DENTRO de ese tramo concreto.
  function bkCapitalAportadoEnRango(cashFlows, fechaInicio, fechaFin){
    // Ojo: fechaInicio se excluye a propósito — el valor de "inicio" del
    // tramo (values[0]) YA incluye cualquier aportación de ese mismo día
    // (los eventos se aplican antes de registrar el valor del día), así
    // que contarla también aquí la duplicaría.
    return (cashFlows||[]).filter(function(cf){ return cf.date > fechaInicio && cf.date <= fechaFin; })
      .reduce(function(s,cf){ return s + cf.amount; }, 0);
  }

  function bkMetricasDesdeValues(values, dates, posiciones, orders, cashFlows){
    if(values.length < 2){
      document.getElementById('bk-metricas-inline').innerHTML =
        '<div style="text-align:center;padding:20px;color:var(--dim);font-size:12px">Pocas operaciones para calcular métricas. Añade más historial.</div>';
      document.getElementById('bk-metricas-content').innerHTML =
        document.getElementById('bk-metricas-inline').innerHTML;
      return;
    }

    var inicio = values[0], fin = values[values.length-1];
    // El "Retorno total" del tramo mostrado: se parte del valor que YA
    // tenías al empezar ese tramo (arrastra todo lo anterior) y se le suma
    // solo lo aportado DENTRO del propio tramo — así un mes concreto da un
    // % distinto al del año completo, como debe ser.
    var contribDuranteTramo = bkCapitalAportadoEnRango(cashFlows, dates[0], dates[dates.length-1]);
    var baseTramo = inicio + contribDuranteTramo;
    var totalReturn = baseTramo > 0 ? (fin - baseTramo) / baseTramo * 100 : 0;
    var nDays = Math.max(1, (new Date(dates[dates.length-1]) - new Date(dates[0])) / 86400000);
    var years = nDays / 365;
    var cagr = baseTramo > 0 && years > 0 ? (Math.pow(fin/baseTramo, 1/years) - 1) * 100 : 0;

    // Drawdown
    var peak = values[0], maxDD = 0, maxDDStart = 0, maxDDEnd = 0;
    values.forEach(function(v, i){
      if(v > peak){ peak = v; }
      var dd = peak > 0 ? (v - peak) / peak * 100 : 0;
      if(dd < maxDD){ maxDD = dd; maxDDEnd = i; }
    });

    // Retornos diarios (entre puntos disponibles)
    var returns = [];
    for(var i=1; i<values.length; i++){
      if(values[i-1] > 0) returns.push((values[i] - values[i-1]) / values[i-1]);
    }

    var n = returns.length;
    var mean = n > 0 ? returns.reduce(function(s,r){return s+r;},0) / n : 0;
    var variance = n > 0 ? returns.reduce(function(s,r){return s+Math.pow(r-mean,2);},0) / n : 0;
    var stdDev = Math.sqrt(variance);
    var RF_daily = 0.04 / 252;
    var sharpe = stdDev > 0 ? (mean - RF_daily) / stdDev * Math.sqrt(252) : 0;

    var downRets = returns.filter(function(r){return r < RF_daily;});
    var downVar = downRets.length > 0 ? downRets.reduce(function(s,r){return s+Math.pow(r-RF_daily,2);},0)/downRets.length : 0;
    var sortino = downVar > 0 ? (mean - RF_daily) / Math.sqrt(downVar) * Math.sqrt(252) : 0;

    var calmar = maxDD < 0 ? cagr / Math.abs(maxDD) : 0;

    // Win/loss desde órdenes
    var trades = orders.filter(function(o){
      return (o.status==='EXECUTED'||o.status==='FILLED') && (o.action||'').toUpperCase()==='SELL';
    });
    var winTrades = 0, lossTrades = 0;
    trades.forEach(function(o){
      var tk = (o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '';
      var sellPrice = parseFloat(o.execution_price || 0);
      // Buscar precio medio de compra desde posiciones actuales o usar price
      var dash = D && D.stockPerf && D.stockPerf[tk];
      var buyRef = dash ? (dash.price || sellPrice) : sellPrice;
      if(sellPrice > buyRef) winTrades++; else lossTrades++;
    });
    var totalTrades = winTrades + lossTrades;
    var winRate = totalTrades > 0 ? winTrades / totalTrades * 100 : 0;

    // Posición actual más grande
    var biggestPos = posiciones.slice().sort(function(a,b){
      return (parseFloat(b.price||0)*parseFloat(b.units||0)) - (parseFloat(a.price||0)*parseFloat(a.units||0));
    })[0];
    var biggestTk = biggestPos ? ((biggestPos.symbol&&biggestPos.symbol.symbol&&biggestPos.symbol.symbol.symbol)||'') : '-';
    var biggestVal = biggestPos ? parseFloat(biggestPos.price||0)*parseFloat(biggestPos.units||0) : 0;

    function col(v, good, warn){ return v >= good ? 'var(--up)' : v >= warn ? 'var(--warn)' : 'var(--dn)'; }
    function colDD(v){ return v > -10 ? 'var(--up)' : v > -20 ? 'var(--warn)' : 'var(--dn)'; }

    var metricas = [
      {l:'Retorno total',    v:(totalReturn>=0?'+':'')+totalReturn.toFixed(2)+'%', c:col(totalReturn,10,0),    d:'Sobre el capital realmente aportado (depósitos - retiradas), no sobre el primer punto de la curva.'},
      {l:'CAGR',             v:(cagr>=0?'+':'')+cagr.toFixed(2)+'%',              c:col(cagr,10,5),            d:'Rentabilidad anualizada compuesta.'},
      {l:'Sharpe ratio',     v:sharpe.toFixed(2),                                  c:col(sharpe,1,0.5),         d:'Retorno ajustado por riesgo. >1 bueno, >2 excelente.'},
      {l:'Sortino ratio',    v:sortino.toFixed(2),                                 c:col(sortino,1,0.5),        d:'Como Sharpe pero solo penaliza caídas.'},
      {l:'Calmar ratio',     v:calmar.toFixed(2),                                  c:col(calmar,0.5,0.2),       d:'CAGR / Max Drawdown. >0.5 sostenible.'},
      {l:'Max Drawdown',     v:maxDD.toFixed(2)+'%',                               c:colDD(maxDD),              d:'Peor caída pico-valle del período.'},
      {l:'Win Rate',         v:winRate.toFixed(1)+'%',                             c:col(winRate,55,40),        d:'% de operaciones cerradas con ganancia.'},
      {l:'Posiciones act.',  v:posiciones.length+'',                               c:'var(--hi)',               d:'Número de posiciones abiertas ahora mismo.'},
      {l:'Mayor posición',   v:biggestTk+' $'+biggestVal.toFixed(0),              c:'var(--ac)',               d:'La posición de mayor valor en cartera.'},
      {l:'Días en mercado',  v:Math.round(nDays)+'d',                              c:'var(--dim)',              d:'Días desde la primera orden registrada.'},
    ];

    var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px">';
    metricas.forEach(function(m){
      html += '<div class="bc" style="border-top:3px solid '+m.c+';padding:10px 12px">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:4px;text-transform:uppercase;letter-spacing:.04em">'+m.l+'</div>'
        +'<div style="font-family:Syne,sans-serif;font-weight:800;font-size:18px;color:'+m.c+'">'+m.v+'</div>'
        +'<div style="font-size:10px;color:var(--dim);margin-top:4px;line-height:1.4">'+m.d+'</div>'
        +'</div>';
    });
    html += '</div>';

    document.getElementById('bk-metricas-inline').innerHTML = html;
    document.getElementById('bk-metricas-content').innerHTML = html;
  }

  function bkKpi(label, value, color){
    return '<div class="cw" style="padding:10px;text-align:center">'
      +'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">'+label+'</div>'
      +'<div style="font-family:Syne,sans-serif;font-weight:800;font-size:16px;color:'+color+'">'+value+'</div>'
      +'</div>';
  }

  function bkTab(name, btn){
    ['posiciones','historial','equity','metricas'].forEach(function(t){
      document.getElementById('bk-'+t).style.display = t===name?'block':'none';
      var b = document.getElementById('bk-btn-'+t);
      if(b) b.classList.toggle('active', t===name);
    });
    if(name==='metricas' && BK_DATA) bkCalcularMetricas(BK_DATA);
  }

  function bkCalcularMetricas(d){
    var posiciones = Array.isArray(d.positions) ? d.positions : [];
    var orders = Array.isArray(d.orders) ? d.orders : [];
    if(orders.length === 0){
      document.getElementById('bk-metricas-content').innerHTML =
        '<div style="text-align:center;padding:40px;color:var(--dim);font-size:12px">Sin órdenes disponibles para calcular métricas.</div>';
      return;
    }
    // Reutilizar lo ya calculado en equity
    var cached = document.getElementById('bk-metricas-inline');
    if(cached && cached.innerHTML){
      document.getElementById('bk-metricas-content').innerHTML = cached.innerHTML;
    } else {
      bkFetchPriceHistory(orders, d.activities || []).then(function(priceHistory){
        bkConstruirEquity(posiciones, orders, d.balances || [], d.activities || [], priceHistory);
      });
    }
  }

  function brokerDisconnect(){
    BK_USER_SECRET = null;
    BK_DATA = null;
    document.getElementById('broker-disconnected').style.display = 'block';
    document.getElementById('broker-connected').style.display = 'none';
    var btn = document.getElementById('broker-connect-btn');
    btn.textContent = '🔗 Conectar mi broker';
    btn.style.background = 'var(--ac)';
    btn.disabled = false;
  }
  </script>

  <!-- FISCALIDAD -->
  <div id="tab-fiscal" class="tc">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
      <div>
        <div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">🧾 Fiscalidad</div>
        <div style="font-size:10px;color:var(--dim);margin-top:2px">Modelo 720 · Posiciones a 31/12 · Solo orientativo — revisa con tu asesor fiscal</div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="pb" onclick="fiscalCargar()" id="fiscal-load-btn"
          style="background:var(--ac);color:#fff;border:none;padding:8px 16px;font-size:12px;font-weight:700;border-radius:8px;cursor:pointer">
          📥 Cargar posiciones del broker
        </button>
        <button class="pb" onclick="fiscalExportarCSV()" id="fiscal-csv-btn" style="display:none">
          ⬇️ Exportar CSV (Modelo 720)
        </button>
        <button class="pb" onclick="fiscalGenerar720()" id="fiscal-720-btn" style="display:none;background:var(--hi);color:#fff;border:none">
          📄 Generar fichero .720 (AEAT)
        </button>
        <button class="pb" onclick="fcToggleDiscreto()" id="fc-discreet-btn" style="display:none">
          🙈 Mostrar
        </button>
      </div>
    </div>

    <!-- Datos del declarante — imprescindibles para el fichero .720, no se guardan en ningún sitio -->
    <div id="fiscal-declarante" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px">
      <input type="text" id="fiscal-nif" placeholder="Tu NIF (ej. 12345678A)" maxlength="9"
        style="padding:7px 10px;font-size:12px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx);width:180px">
      <input type="text" id="fiscal-nombre" placeholder="Apellido1 Apellido2 Nombre"
        style="padding:7px 10px;font-size:12px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx);flex:1;min-width:220px">
    </div>

    <!-- Aviso legal -->
    <div style="background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:12px 14px;margin-bottom:16px;font-size:11px;color:var(--dim);line-height:1.6">
      ⚠️ <strong style="color:var(--warn)">Aviso importante:</strong> Esta herramienta es meramente orientativa para ayudarte a preparar la información del Modelo 720.
      Los datos deben ser <strong>revisados y validados por un asesor fiscal cualificado</strong> antes de su presentación.
      El Modelo 720 tiene obligación de presentación cuando el valor total de bienes en el extranjero supera los <strong>50.000€</strong>.
    </div>

    <!-- Sub-pestañas internas: Modelo 720 vs Renta -->
    <div style="display:flex;gap:6px;margin-bottom:14px">
      <button class="pb active" id="fc-subtab-720-btn" onclick="fcSubTab('720',this)">📄 Modelo 720</button>
      <button class="pb" id="fc-subtab-renta-btn" onclick="fcSubTab('renta',this)">📊 Renta (Plusvalías)</button>
    </div>

    <div id="fc-sub-720">
    <!-- Sin broker conectado -->
    <div id="fiscal-no-broker" style="background:var(--bg2);border:1px solid var(--b1);border-radius:12px;padding:40px;text-align:center">
      <div style="font-size:40px;margin-bottom:12px">🔗</div>
      <div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:var(--hi);margin-bottom:8px">Conecta tu broker primero</div>
      <div style="font-size:12px;color:var(--dim);max-width:380px;margin:0 auto;line-height:1.7">
        Para generar el borrador del Modelo 720 necesitas conectar tu broker en la pestaña
        <strong>Mi Broker</strong> y luego volver aquí a cargar las posiciones.
      </div>
      <button onclick="sw('broker',document.getElementById('tab-broker-btn'))"
        class="pb" style="margin-top:16px;background:var(--ac);color:#fff;border:none;padding:8px 18px;font-weight:700;border-radius:8px;cursor:pointer">
        Ir a Mi Broker →
      </button>
    </div>

    <!-- Tabla de posiciones para 720 -->
    <div id="fiscal-tabla" style="display:none">

      <!-- Resumen -->
      <div id="fiscal-kpis" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:16px"></div>

      <!-- Selector de fecha -->
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;font-size:12px">
        <span style="color:var(--dim);font-weight:600">Fecha de referencia:</span>
        <select id="fiscal-fecha" onchange="fiscalFiltrarFecha()" style="background:var(--bg2);border:1px solid var(--b1);color:var(--hi);padding:4px 8px;border-radius:6px;font-size:12px">
          <option value="actual">Posiciones actuales</option>
          <option value="31dic">31 de diciembre (Modelo 720)</option>
        </select>
        <span id="fiscal-fecha-label" style="color:var(--dim);font-size:11px"></span>
      </div>

      <!-- Tabla 720 -->
      <div style="overflow-x:auto">
        <table id="fiscal-table-data" style="width:100%;border-collapse:collapse;font-size:12px">
          <thead>
            <tr style="border-bottom:2px solid var(--b1);background:var(--bg2)">
              <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">TICKER</th>
              <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">ENTIDAD</th>
              <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">ISIN</th>
              <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">PAÍS</th>
              <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">UNIDADES</th>
              <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">PRECIO (€)</th>
              <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">VALOR TOTAL (€)</th>
              <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">VALOR ADQUIS. (€)</th>
              <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">P&L (€)</th>
              <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">BROKER</th>
            </tr>
          </thead>
          <tbody id="fiscal-tbody"></tbody>
          <tfoot id="fiscal-tfoot"></tfoot>
        </table>
      </div>

      <div style="margin-top:12px;font-size:11px;color:var(--dim);line-height:1.6">
        💡 <strong>Nota sobre el Modelo 720:</strong> Debes declarar valores, acciones, fondos y derechos en entidades financieras extranjeras
        con valor conjunto superior a 50.000€ a 31 de diciembre de cada año. El tipo de cambio aplicable es el oficial del BCE a 31/12.
        Esta tabla usa el tipo de cambio actual como aproximación.
      </div>
    </div>
    </div><!-- /fc-sub-720 -->

    <!-- ═══ RENTA (PLUSVALÍAS) ═══ -->
    <div id="fc-sub-renta" style="display:none">
      <div style="background:rgba(245,158,11,.08);border:1px solid rgba(245,158,11,.3);border-radius:8px;padding:12px 14px;margin-bottom:16px;font-size:11px;color:var(--dim);line-height:1.6">
        ⚠️ <strong style="color:var(--warn)">Aviso importante:</strong> Cálculo de plusvalías/minusvalías <strong>realizadas</strong> (ventas ejecutadas), método FIFO
        (primera compra, primera venta), <strong>ya con comisiones descontadas</strong> (Hacienda exige que el cálculo vaya "ajustado con gastos y
        comisiones", no solo precio × unidades), y con comprobación automática de la <strong>regla de los 2 meses</strong> (art. 33.5 LIRPF: una pérdida no es
        deducible si recompras el mismo valor en los 2 meses antes o después de la venta — marcado como "⚠ no deducible" en la tabla).
        <strong>Limitaciones actuales:</strong> (1) solo cubre el historial que el broker tiene sincronizado —
        si conectaste la cuenta hace poco, no verás operaciones anteriores a esa fecha; (2) los dividendos muestran el importe íntegro, pero
        <strong>todavía no capturamos la retención en origen</strong> (necesaria para la deducción por doble imposición internacional, casilla aparte) —
        pendiente de verificar en cuanto aparezca un dividendo real en el historial. <strong>Esto es un apoyo para preparar la Renta, no un cálculo fiscal definitivo — revísalo con tu asesor.</strong>
      </div>

      <div id="renta-no-datos" style="background:var(--bg2);border:1px solid var(--b1);border-radius:12px;padding:40px;text-align:center">
        <div style="font-size:40px;margin-bottom:12px">📊</div>
        <div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:var(--hi);margin-bottom:8px">Carga las posiciones del broker primero</div>
        <div style="font-size:12px;color:var(--dim)">Ve a la pestaña "Modelo 720" de aquí arriba y dale a "Cargar posiciones del broker" — con eso ya tenemos el historial de operaciones para calcular esto también.</div>
      </div>

      <div id="renta-contenido" style="display:none">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:12px;flex-wrap:wrap">
          <label style="font-size:12px;color:var(--dim);font-weight:600">Ejercicio fiscal:</label>
          <select id="renta-anio-select" onchange="rentaFiltrarAnio()" style="padding:6px 10px;font-size:12px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)"></select>
          <label style="font-size:12px;color:var(--dim);font-weight:600;margin-left:8px">Periodo:</label>
          <select id="renta-periodo-select" onchange="rentaFiltrarPeriodo()" style="padding:6px 10px;font-size:12px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)">
            <option value="anio">Año completo</option>
            <option value="q1">1er trimestre (ene-mar)</option>
            <option value="q2">2º trimestre (abr-jun)</option>
            <option value="q3">3er trimestre (jul-sep)</option>
            <option value="q4">4º trimestre (oct-dic)</option>
            <option value="m1">Enero</option>
            <option value="m2">Febrero</option>
            <option value="m3">Marzo</option>
            <option value="m4">Abril</option>
            <option value="m5">Mayo</option>
            <option value="m6">Junio</option>
            <option value="m7">Julio</option>
            <option value="m8">Agosto</option>
            <option value="m9">Septiembre</option>
            <option value="m10">Octubre</option>
            <option value="m11">Noviembre</option>
            <option value="m12">Diciembre</option>
          </select>
          <span style="font-size:10px;color:var(--dim)">Las ganancias/pérdidas se declaran en el año en que se VENDE, no en el que se compró.</span>
        </div>
        <div id="renta-cobertura" style="font-size:12px;font-weight:700;padding:8px 12px;border-radius:6px;margin-bottom:12px"></div>
        <div id="renta-descartes" style="font-size:12px;font-weight:700;padding:8px 12px;border-radius:6px;margin-bottom:12px;display:none"></div>
        <div id="renta-bruto-total" style="text-align:center;padding:20px;border-radius:12px;background:var(--bg2);border:2px solid var(--b1);margin-bottom:16px"></div>
        <div id="renta-kpis" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:8px"></div>
        <div id="renta-bruto-contraste" style="font-size:11px;color:var(--dim);margin-bottom:12px"></div>
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap">
          <label style="font-size:12px;color:var(--dim);font-weight:600">Estado fiscal:</label>
          <select id="renta-filtro-estado" onchange="rentaAplicarFiltros()" style="padding:6px 10px;font-size:12px;border-radius:6px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)">
            <option value="todas">Todas las operaciones</option>
            <option value="ganancia">Solo ganancias</option>
            <option value="perdida">Solo pérdidas</option>
            <option value="no_deducible">Solo no deducibles (regla 2 meses)</option>
            <option value="diferida">Solo con pérdida diferida aplicada</option>
          </select>
          <button class="pb" onclick="rentaLimpiarFiltros()" style="font-size:11px;padding:6px 10px">✖ Quitar filtros</button>
          <span id="renta-filtro-contador" style="font-size:11px;color:var(--dim)"></span>
        </div>
        <div style="overflow-x:auto">
          <table id="renta-table" style="width:100%;border-collapse:collapse;font-size:12px">
            <thead>
              <tr style="border-bottom:1px solid var(--b1);background:var(--bg2)">
                <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">TICKER</th>
                <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">FECHA COMPRA</th>
                <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">FECHA VENTA</th>
                <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">UNIDADES</th>
                <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">PRECIO COMPRA</th>
                <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">PRECIO VENTA</th>
                <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">COMISIONES</th>
                <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">GANANCIA/PÉRDIDA ($)</th>
                <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">GANANCIA/PÉRDIDA (€)</th>
              </tr>
              <tr style="border-bottom:2px solid var(--b1);background:var(--bg2)" id="renta-fila-filtros">
                <th style="padding:4px 8px"><input type="text" id="renta-f-ticker" placeholder="filtrar…" oninput="rentaAplicarFiltros()" style="width:100%;box-sizing:border-box;font-size:11px;padding:4px 6px;border-radius:4px;border:1px solid var(--b2);background:var(--bg);color:var(--tx)"></th>
                <th style="padding:4px 8px"><input type="text" id="renta-f-fc" placeholder="AAAA-MM…" oninput="rentaAplicarFiltros()" style="width:100%;box-sizing:border-box;font-size:11px;padding:4px 6px;border-radius:4px;border:1px solid var(--b2);background:var(--bg);color:var(--tx)"></th>
                <th style="padding:4px 8px"><input type="text" id="renta-f-fv" placeholder="AAAA-MM…" oninput="rentaAplicarFiltros()" style="width:100%;box-sizing:border-box;font-size:11px;padding:4px 6px;border-radius:4px;border:1px solid var(--b2);background:var(--bg);color:var(--tx)"></th>
                <th style="padding:4px 8px"></th>
                <th style="padding:4px 8px"></th>
                <th style="padding:4px 8px"></th>
                <th style="padding:4px 8px"></th>
                <th style="padding:4px 8px"></th>
                <th style="padding:4px 8px;display:flex;gap:3px">
                  <input type="number" id="renta-f-gan-min" placeholder="mín €" oninput="rentaAplicarFiltros()" style="width:50%;box-sizing:border-box;font-size:11px;padding:4px 6px;border-radius:4px;border:1px solid var(--b2);background:var(--bg);color:var(--tx)">
                  <input type="number" id="renta-f-gan-max" placeholder="máx €" oninput="rentaAplicarFiltros()" style="width:50%;box-sizing:border-box;font-size:11px;padding:4px 6px;border-radius:4px;border:1px solid var(--b2);background:var(--bg);color:var(--tx)">
                </th>
              </tr>
            </thead>
            <tbody id="renta-tbody"></tbody>
            <tfoot id="renta-tfoot"></tfoot>
          </table>
        </div>
        <div style="margin-top:10px;display:flex;gap:8px">
          <button class="pb" onclick="rentaExportarCSV()">⬇️ Exportar CSV</button>
        </div>

        <!-- Dividendos -->
        <div style="margin-top:24px">
          <div class="ct" style="margin-bottom:10px">💰 Dividendos cobrados (rendimientos del capital mobiliario)</div>
          <div id="dividendos-vacio" style="display:none;font-size:12px;color:var(--dim);padding:16px;text-align:center;background:var(--bg2);border-radius:8px">
            Sin dividendos en el historial disponible (normal si la cuenta lleva poco tiempo conectada, o si las posiciones no reparten dividendo).
          </div>
          <div id="dividendos-contenido" style="display:none">
            <div id="dividendos-kpis" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:8px;margin-bottom:12px"></div>
            <div style="overflow-x:auto">
              <table style="width:100%;border-collapse:collapse;font-size:12px">
                <thead><tr style="border-bottom:2px solid var(--b1);background:var(--bg2)">
                  <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">TICKER</th>
                  <th style="text-align:left;padding:8px;font-size:10px;color:var(--dim);font-weight:700">FECHA</th>
                  <th style="text-align:right;padding:8px;font-size:10px;color:var(--dim);font-weight:700">IMPORTE</th>
                </tr></thead>
                <tbody id="dividendos-tbody"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div><!-- /fc-sub-renta -->
  </div><!-- /tab-fiscal -->


  <script>
  var FISCAL_DATA = null;
  var FISCAL_CASH_EUR = null;
  var FISCAL_FECHAS = {}; // ticker -> fecha de la primera compra (AAAAMMDD), desde el historial real
  var FISCAL_TICKER_META = {}; // ticker -> {nombre,isin,figi,esETF,pais,codigoPais} — para reconstrucción histórica
  var FISCAL_ORDERS = [];
  var FISCAL_ACTIVITIES = [];
  var FISCAL_PRICE_HISTORY = {};
  var FISCAL_MODO_FECHA = 'actual'; // 'actual' o un año tipo '2024'
  var EURUSD_RATE = 1.10; // Fallback — solo se usa si D.benchmarks no está disponible

  // FIX (09/07/2026): esto antes se ejecutaba nada más cargar la página, ANTES
  // de que existiera `D` (que se define en un <script> posterior) — así que
  // el "if" nunca era cierto y EURUSD_RATE se quedaba siempre en el fallback
  // 1.10, inventado, nunca el tipo de cambio real. Ahora es una función que
  // se llama en el momento de usar los datos (fiscalMostrarDatos), cuando D
  // ya existe seguro.
  function actualizarEurUsdRate(){
    if(typeof D !== 'undefined' && D.benchmarks){
      var eurData = D.benchmarks.find(function(b){ return b.ticker==='C:EURUSD' || b.name==='EUR/USD'; });
      if(eurData && eurData.price) EURUSD_RATE = parseFloat(eurData.price);
    }
  }

  // ── HISTÓRICO EUR/USD POR FECHA (09/08/2026) ────────────────────────────
  // NUEVO: hasta ahora Renta (y la curva de equity de Mi Broker) sumaban
  // directamente en dólares, o como mucho usaban el cambio de HOY
  // (EURUSD_RATE) — válido para "cuánto vale mi cartera ahora", pero
  // inválido para sumar operaciones repartidas a lo largo del año, porque
  // el cambio se movió bastante durante 2025. Aquí se pide a Polygon (vía
  // /snaptrade/price-history, que ya reconstruye la curva con datos
  // reales) el cierre diario de EUR/USD desde la fecha más antigua que
  // necesitemos, y se cachea en memoria.
  var EURUSD_HISTORICO = {}; // 'AAAA-MM-DD' -> cierre EUR/USD ese día

  async function fetchEurUsdHistorico(fechaMin){
    if(!fechaMin) return {};
    try{
      var token = await getAuthToken();
      if(!token) return {};
      var resp = await fetch('https://lacomunidad.onrender.com/snaptrade/price-history', {
        method: 'POST',
        headers: {'Content-Type':'application/json', 'Authorization':'Bearer '+token},
        body: JSON.stringify({user_id: GLOBAL_USER.id, tickers: [], start_date: fechaMin})
      });
      var data = await resp.json();
      var hist = data.eurUsdHistory || {};
      Object.keys(hist).forEach(function(f){ EURUSD_HISTORICO[f] = hist[f]; });
      return hist;
    }catch(e){
      console.warn('No se pudo cargar el histórico EUR/USD — se usará el cambio actual como respaldo:', e);
      return {};
    }
  }

  // Cambio EUR/USD de una fecha concreta. Si ese día exacto no cotizó (fin
  // de semana/festivo de mercado forex), retrocede hasta 7 días buscando el
  // último cierre disponible. Si no hay nada cacheado (Polygon falló o aún
  // no se ha cargado), cae al cambio actual — degradado, no roto.
  function eurUsdEnFecha(fecha){
    if(!fecha) return EURUSD_RATE;
    if(EURUSD_HISTORICO[fecha]) return EURUSD_HISTORICO[fecha];
    var d = new Date(fecha+'T00:00:00Z');
    for(var i=0;i<7;i++){
      d.setUTCDate(d.getUTCDate()-1);
      var f = d.toISOString().slice(0,10);
      if(EURUSD_HISTORICO[f]) return EURUSD_HISTORICO[f];
    }
    return EURUSD_RATE;
  }

  // Convierte un importe en USD a EUR. Prioridad: el fx_rate NATIVO que
  // SnapTrade da por operación (el que usó IBKR de verdad para liquidar esa
  // operación en concreto — se multiplica, viene en convención "EUR por
  // USD"). Si no viene (p.ej. trades que llegan por "orders" en vez de
  // "activities"), cae al histórico diario de Polygon por fecha (se
  // divide, viene en convención "USD por EUR", como EURUSD_RATE).
  function usdAEur(montoUsd, fxNativo, fecha){
    if(fxNativo) return montoUsd * fxNativo;
    return montoUsd / eurUsdEnFecha(fecha);
  }

  // ── Sub-pestañas Fiscalidad: Modelo 720 / Renta ────────────────────────────
  function fcSubTab(name, btn){
    document.getElementById('fc-sub-720').style.display  = name==='720'  ? 'block' : 'none';
    document.getElementById('fc-sub-renta').style.display = name==='renta' ? 'block' : 'none';
    document.getElementById('fc-subtab-720-btn').classList.toggle('active', name==='720');
    document.getElementById('fc-subtab-renta-btn').classList.toggle('active', name==='renta');
  }

  // ── RENTA (Plusvalías) — FIFO sobre el historial de órdenes ────────────────
  // NUEVO (10/07/2026): calcula ganancias/pérdidas REALIZADAS (ventas ya
  // ejecutadas) emparejando cada venta con las compras más antiguas
  // todavía abiertas de ese ticker (FIFO — primera compra, primera venta,
  // que es el método que exige Hacienda para acciones). Limitaciones ya
  // avisadas en la propia pestaña: sin dividendos, sin regla de los 2 meses,
  // y solo cubre el historial que el broker tiene sincronizado.
  var RENTA_DATA = null;
  var RENTA_COBERTURA = {count:0, desde:null, hasta:null}; // qué rango de fechas se ha capturado de verdad
  var RENTA_DESCARTES = []; // ventas que no se pudieron emparejar con ninguna compra — visibilidad del hueco, en vez de que desaparezcan en silencio
  var RENTA_CORTOS_IMPLICITOS = []; // ventas/compras que abrieron una posición corta "implícita" (llegó como SELL/BUY normal, no como SELL_SHORT/BUY_TO_COVER)
  var RENTA_POSICION_RECONSTRUIDA = {}; // ticker -> unidades netas que implica TODO el historial de compras/ventas (independiente del emparejamiento FIFO)
  var RENTA_TICKERS_REVISAR = {}; // ticker -> true si la posición reconstruida no coincide con la posición REAL que reporta el bróker ahora mismo (señal de historial incompleto para ese ticker en concreto)

  function calcularRentaFIFO(orders, activities){
    RENTA_DESCARTES = []; // se resetea en cada cálculo, no acumula entre recargas
    RENTA_CORTOS_IMPLICITOS = [];
    // NUEVO (14/08/2026): normaliza el tipo de operación — CONFIRMADO en tu
    // log real que "orders" puede traer 'SELL_SHORT' (venta en corto), no
    // solo 'BUY'/'SELL' a secas. Antes esto se comparaba con === 'SELL'
    // exacto, así que ni se deduplicaba bien contra activities NI se
    // procesaba en el cálculo — se quedaba "flotando" sin más. Ahora se
    // reconoce explícitamente y se calcula como posición corta de verdad
    // (abres vendiendo, ganas si luego recompras más barato).
    function normalizarAccion(a){
      a = (a||'').toUpperCase();
      if(a.indexOf('SELL_SHORT')>=0 || a==='SELLSHORT') return 'SELL_SHORT';
      if(a.indexOf('BUY_TO_COVER')>=0 || a==='BUYTOCOVER' || (a.indexOf('COVER')>=0 && a.indexOf('BUY')>=0)) return 'BUY_TO_COVER';
      if(a.indexOf('BUY')>=0) return 'BUY';
      if(a.indexOf('SELL')>=0) return 'SELL';
      return a;
    }
    // NUEVO (09/08/2026) — BUG REAL ENCONTRADO: confirmado con datos reales
    // que un cambio de ticker corporativo (Block Inc: SQ → XYZ, en 2025)
    // rompe el emparejamiento FIFO porque se compara el símbolo exacto —
    // una compra registrada como "SQ" nunca casa con una venta posterior
    // registrada como "XYZ", aunque sean las mismas acciones. Se normaliza
    // aquí al ticker actual. Si aparece otro cambio de ticker en el futuro
    // (pasa de vez en cuando: rebrandings, cambios tras fusiones...), se
    // añade una línea más a este mapa.
    var TICKER_ALIASES = { 'SQ': 'XYZ' };
    function normalizarTicker(tk){
      return TICKER_ALIASES[tk] || tk;
    }
    // NUEVO (11/07/2026): "orders" tiene un tope de 90 días CONFIRMADO por
    // el propio soporte de SnapTrade, sin forma de saltárselo — para el
    // año fiscal completo (Modelo 720/Renta) eso se queda corto casi
    // siempre. "activities" se pide con un año completo de rango y además
    // ya trae la comisión nativa (antes había que cruzarlo a mano con
    // orders para sacarla). Se usa como fuente PRINCIPAL; orders se
    // mezcla solo como respaldo por si algún trade no aparece en activities.
    var listaActivities = Array.isArray(activities) ? activities : (activities && activities.data) || [];
    var trades = [];
    listaActivities.forEach(function(a){
      var tipo = normalizarAccion(a.type);
      if(tipo !== 'BUY' && tipo !== 'SELL' && tipo !== 'SELL_SHORT' && tipo !== 'BUY_TO_COVER') return;
      var tk = normalizarTicker((a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '');
      var fechaHoraFull = a.trade_date || a.settlement_date || '';
      var fecha = fechaHoraFull.slice(0,10);
      var qty = Math.abs(parseFloat(a.units || 0));
      var price = parseFloat(a.price || 0);
      if(!tk || !fecha || !qty || !price) return;
      trades.push({
        ticker: tk, action: tipo, fecha: fecha,
        // NUEVO (09/08/2026) — BUG REAL ENCONTRADO: "activities" NO llega
        // en orden cronológico estricto (confirmado con datos reales — hay
        // días con una venta ANTES que su compra correspondiente en el
        // array, aunque la compra sea intradía más temprana). Antes solo
        // guardábamos la fecha sin hora y ordenábamos por ese string — en
        // un empate de fecha, el sort (estable) dejaba el orden original
        // del array, así que la venta se procesaba antes que su compra del
        // mismo día, no encontraba lote abierto, y esa venta se perdía
        // entera y en silencio (mismo camino que "venta sin compra
        // previa"). Guardamos también el timestamp completo para ordenar
        // por él y no solo por el día.
        fechaHora: fechaHoraFull || fecha,
        qty: qty, price: price,
        fee: Math.abs(parseFloat(a.fee || 0)),
        // NUEVO (09/08/2026): SnapTrade trae el fx_rate REAL que usó IBKR
        // para liquidar esta operación en concreto — confirmado contra tu
        // informe oficial (coincide casi al céntimo). Es mucho mejor que
        // aproximar con el cierre diario de Polygon, así que se usa como
        // fuente principal; el histórico de Polygon queda como respaldo
        // solo para cuando este campo no venga (p.ej. trades que llegan
        // por "orders" en vez de "activities", que no lo trae).
        fx: parseFloat(a.fx_rate || 0) || null,
        clave: tk+'|'+tipo+'|'+fecha+'|'+qty.toFixed(4)
      });
    });
    // Respaldo: añadir órdenes que NO tengan ya una entrada equivalente en
    // activities (mismo ticker+acción+fecha+cantidad) — cubre el caso raro
    // de que orders tenga algo que activities no capturó.
    var clavesYaVistas = {};
    trades.forEach(function(t){ clavesYaVistas[t.clave] = true; });
    if(Array.isArray(orders)){
      orders.filter(function(o){ return (o.status==='EXECUTED'||o.status==='FILLED'); })
        .forEach(function(o){
          var tk = normalizarTicker((o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '');
          var qty = parseFloat(o.total_quantity || o.filled_quantity || 0);
          var price = parseFloat(o.execution_price || o.limit_price || 0);
          var action = normalizarAccion(o.action);
          var fechaHoraFull = o.time_executed || o.time_placed || '';
          var fecha = fechaHoraFull.slice(0,10);
          if(!tk || !qty || !price || !fecha) return;
          if(action !== 'BUY' && action !== 'SELL' && action !== 'SELL_SHORT' && action !== 'BUY_TO_COVER') return;
          var clave = tk+'|'+action+'|'+fecha+'|'+qty.toFixed(4);
          if(clavesYaVistas[clave]) return; // ya está en activities, no duplicar
          trades.push({ticker:tk, action:action, fecha:fecha, fechaHora: fechaHoraFull || fecha, qty:qty, price:price, fee:0, clave:clave});
        });
    }

    // NUEVO: guardamos la cobertura real (fecha más antigua/reciente y
    // nº de trades) para mostrarla en la pestaña — así el usuario ve con
    // sus propios ojos qué periodo se ha capturado, en vez de asumir que
    // está completo a ciegas.
    RENTA_COBERTURA = {count: trades.length, desde: null, hasta: null};
    trades.forEach(function(t){
      if(!RENTA_COBERTURA.desde || t.fecha < RENTA_COBERTURA.desde) RENTA_COBERTURA.desde = t.fecha;
      if(!RENTA_COBERTURA.hasta || t.fecha > RENTA_COBERTURA.hasta) RENTA_COBERTURA.hasta = t.fecha;
    });

    // NUEVO (09/08/2026): posición neta que implica TODO el historial de
    // compras/ventas de cada ticker — independiente de cómo se hayan
    // emparejado los lotes. Sirve para comparar contra la posición REAL
    // que reporta el bróker ahora mismo (rentaValidarPosiciones): si no
    // coinciden, es la prueba de que a ese ticker en concreto le falta (o
    // le sobra) alguna operación en el historial que trae SnapTrade — un
    // problema de datos, no de cálculo, y afecta solo a ese ticker.
    RENTA_POSICION_RECONSTRUIDA = {};
    trades.forEach(function(t){
      if(!(t.ticker in RENTA_POSICION_RECONSTRUIDA)) RENTA_POSICION_RECONSTRUIDA[t.ticker] = 0;
      if(t.action === 'BUY' || t.action === 'BUY_TO_COVER') RENTA_POSICION_RECONSTRUIDA[t.ticker] += t.qty;
      else RENTA_POSICION_RECONSTRUIDA[t.ticker] -= t.qty;
    });

    // Orden cronológico ascendente — imprescindible para que FIFO funcione
    // bien. NUEVO (09/08/2026): se ordena por el TIMESTAMP COMPLETO
    // (fechaHora), no solo por la fecha — ver nota arriba sobre el bug de
    // ventas procesadas antes que su compra del mismo día.
    trades.sort(function(a,b){ return (a.fechaHora||a.fecha).localeCompare(b.fechaHora||b.fecha); });

    var lotes = {}; // ticker -> array de {qty, price, date} compras LARGAS abiertas (más antigua primero)
    var lotesCorto = {}; // ticker -> array de {qty, price, date} ventas EN CORTO abiertas
    var cierres = []; // ventas ya emparejadas con su(s) compra(s)

    trades.forEach(function(o){
      var tk = o.ticker;
      var qty = o.qty;
      var price = o.price;
      var action = o.action;
      var fecha = o.fecha;
      // Comisión ya viene nativa de activities — prorrateada por unidad para
      // poder repartirla bien cuando una venta se empareja con varios lotes.
      var feeTotal = o.fee;
      var feePorUnidad = qty > 0 ? feeTotal / qty : 0;
      if(!lotes[tk]) lotes[tk] = [];
      if(!lotesCorto[tk]) lotesCorto[tk] = [];

      // NUEVO (09/08/2026) — BUG REAL ENCONTRADO: confirmado con datos
      // reales (BMNRn, RGTIn, NFLX) que IBKR/SnapTrade a veces manda una
      // venta en corto real como "SELL" normal (no como "SELL_SHORT") —
      // vende primero sin tener acciones, y cubre más tarde con una "BUY"
      // normal (no "BUY_TO_COVER"). Antes de esto, una SELL sin lote largo
      // suficiente simplemente se descartaba entera (se perdía el
      // resultado real de la operación). Ahora BUY y SELL primero
      // intentan casar contra la cola CONTRARIA (BUY cubre cortos
      // abiertos, SELL cierra largos abiertos) y, si sobra cantidad
      // después de agotar esa cola, la sobra ABRE una posición nueva en
      // sentido contrario — igual que haría el propio bróker — en vez de
      // desaparecer.
      // NUEVO (09/08/2026): ventana de seguridad para la cobertura
      // "implícita" — solo se da por buena una compra como cobertura de un
      // corto que no llegó etiquetado como tal si pasa poco tiempo entre
      // la venta y la recompra (igual que el patrón real confirmado:
      // BMNRn mismo día, RGTIn al día siguiente, NFLX en la misma semana).
      // Si ha pasado más de esta ventana, es más probable que sea una
      // posición antigua de antes de conectar el broker que se vende sin
      // más, no un corto real — en ese caso NO se empareja (para no
      // inventar un cierre falso mezclando dos operaciones sin relación) y
      // la compra abre una posición larga nueva normal.
      var VENTANA_COBERTURA_IMPLICITA_MS = 60 * 24 * 60 * 60 * 1000; // 60 días
      if(action === 'BUY'){
        var restanteBuy = qty;
        // 1) Cubrir primero cualquier corto abierto de antes (aunque haya
        // llegado como "BUY" normal y no como "BUY_TO_COVER") — solo si el
        // lote más antiguo NO es "implícito" (viene de un SELL_SHORT real,
        // sin límite de tiempo) o, siendo implícito, cae dentro de la
        // ventana de seguridad.
        while(restanteBuy > 0.0001 && lotesCorto[tk] && lotesCorto[tk].length > 0
              && (!lotesCorto[tk][0].implicito || Math.abs(new Date(fecha)-new Date(lotesCorto[tk][0].date)) <= VENTANA_COBERTURA_IMPLICITA_MS)){
          var loteCortoB = lotesCorto[tk][0];
          var qtyCerradaB = Math.min(restanteBuy, loteCortoB.qty);
          var comisionAperturaB = (loteCortoB.feePorUnidad || 0) * qtyCerradaB;
          var comisionCierreB = feePorUnidad * qtyCerradaB;
          var gananciaUSDb = (loteCortoB.price - price) * qtyCerradaB - comisionAperturaB - comisionCierreB;
          // NUEVO (09/08/2026) — BUG REAL ENCONTRADO Y CONFIRMADO AL CÉNTIMO
          // contra el "Informe de actividad" de IBKR: NO se convierte cada
          // pata a euros por separado (coste con el cambio de compra,
          // ingreso con el de venta) — eso multiplicaba artificialmente el
          // "ruido" de cambio de divisa. IBKR calcula la ganancia/pérdida
          // ENTERA en la divisa nativa (dólares) primero, y solo al final
          // convierte ese resultado neto a euros con el cambio del día en
          // que se CIERRA la posición (aquí, la compra que cubre el corto).
          // Verificado: GH -231,60$ × 0,83654 (fx de la venta) = -193,74€,
          // exacto contra el informe oficial.
          var gananciaB = usdAEur(gananciaUSDb, o.fx, fecha);
          cierres.push({
            ticker: tk, fechaCompra: loteCortoB.date, fechaVenta: fecha, unidades: qtyCerradaB,
            precioCompra: price, precioVenta: loteCortoB.price,
            comisiones: comisionAperturaB + comisionCierreB,
            gananciaUSD: gananciaUSDb,
            ganancia: gananciaB, esCorto: true,
            idCierre: tk+'|'+(o.fechaHora||fecha) // agrupa los cierres que vienen de la MISMA operación de cierre
          });
          loteCortoB.qty -= qtyCerradaB;
          restanteBuy -= qtyCerradaB;
          if(loteCortoB.qty <= 0.0001) lotesCorto[tk].shift();
        }
        // 2) Lo que sobre (o todo, si no había ningún corto abierto) abre
        // una posición larga normal, como antes.
        if(restanteBuy > 0.0001){
          lotes[tk].push({qty: restanteBuy, price: price, date: fecha, feePorUnidad: feePorUnidad, fx: o.fx});
        }      } else if(action === 'SELL'){
        var restante = qty;
        while(restante > 0.0001 && lotes[tk] && lotes[tk].length > 0){
          var lote = lotes[tk][0];
          var qtyCerrada = Math.min(restante, lote.qty);
          var comisionCompra = (lote.feePorUnidad || 0) * qtyCerrada;
          var comisionVenta  = feePorUnidad * qtyCerrada;
          var gananciaUSDv = (price - lote.price) * qtyCerrada - comisionCompra - comisionVenta;
          // NUEVO (09/08/2026) — BUG REAL ENCONTRADO Y CONFIRMADO AL CÉNTIMO
          // contra el "Informe de actividad" de IBKR: NO se convierte cada
          // pata a euros por separado — eso multiplicaba el ruido de cambio
          // de divisa e inflaba artificialmente ganancias y pérdidas. IBKR
          // calcula la ganancia/pérdida ENTERA en dólares primero, y solo
          // al final convierte ese resultado neto a euros, con el cambio
          // del día en que se CIERRA la posición (la venta, aquí). Ejemplo
          // real verificado: GH -231,60$ × 0,83654 (fx de esta venta) =
          // -193,74€, exacto contra el informe oficial de IBKR.
          var gananciaV = usdAEur(gananciaUSDv, o.fx, fecha);
          cierres.push({
            ticker: tk,
            fechaCompra: lote.date,
            fechaVenta: fecha,
            unidades: qtyCerrada,
            precioCompra: lote.price,
            precioVenta: price,
            comisiones: comisionCompra + comisionVenta,
            gananciaUSD: gananciaUSDv,
            ganancia: gananciaV,
            idCierre: tk+'|'+(o.fechaHora||fecha)
          });
          lote.qty -= qtyCerrada;
          restante -= qtyCerrada;
          if(lote.qty <= 0.0001) lotes[tk].shift();
        }
        // NUEVO (09/08/2026): lo que sobre tras agotar los lotes largos
        // abre una posición CORTA nueva (venta sin tener las acciones) en
        // vez de descartarse — cubre el caso real confirmado (BMNRn,
        // RGTIn, NFLX) de cortos que llegan como "SELL" normal. Se anota
        // en RENTA_CORTOS_IMPLICITOS para poder revisarlo (por si algún
        // ticker no debería ir nunca en corto, y esto en realidad es una
        // posición antigua de antes de conectar el broker).
        if(restante > 0.0001){
          lotesCorto[tk].push({qty: restante, price: price, date: fecha, feePorUnidad: feePorUnidad, fx: o.fx, implicito: true});
          RENTA_CORTOS_IMPLICITOS.push({ticker: tk, fecha: fecha, unidades: restante, tipo: 'apertura corto (SELL)'});
        }
      } else if(action === 'SELL_SHORT'){
        // Abre (o amplía) una posición corta — vendes sin tener las
        // acciones, apostando a que baje el precio.
        lotesCorto[tk].push({qty: qty, price: price, date: fecha, feePorUnidad: feePorUnidad, fx: o.fx});
      } else if(action === 'BUY_TO_COVER'){
        // Cierra la posición corta — la ganancia es al revés que en largo:
        // ganas si RECOMPRAS más barato de lo que vendiste en corto.
        var restanteCorto = qty;
        while(restanteCorto > 0.0001 && lotesCorto[tk] && lotesCorto[tk].length > 0){
          var loteCorto = lotesCorto[tk][0];
          var qtyCerrada = Math.min(restanteCorto, loteCorto.qty);
          var comisionApertura = (loteCorto.feePorUnidad || 0) * qtyCerrada;
          var comisionCierre = feePorUnidad * qtyCerrada;
          var gananciaUSDc = (loteCorto.price - price) * qtyCerrada - comisionApertura - comisionCierre;
          // NUEVO (09/08/2026): mismo criterio que en BUY/SELL — la
          // ganancia se calcula entera en dólares y se convierte a euros
          // una sola vez, con el cambio de la operación que CIERRA (aquí,
          // la recompra que cubre el corto), no con el cambio de cada pata
          // por separado. Confirmado al céntimo contra IBKR.
          var gananciaC = usdAEur(gananciaUSDc, o.fx, fecha);
          cierres.push({
            ticker: tk,
            fechaCompra: loteCorto.date, // fecha de apertura del corto (venta)
            fechaVenta: fecha,           // fecha de cierre (recompra)
            unidades: qtyCerrada,
            precioCompra: price,          // en corto, el "coste" es lo que pagas al RECOMPRAR
            precioVenta: loteCorto.price, // y el "ingreso" es lo que cobraste al VENDER en corto
            comisiones: comisionApertura + comisionCierre,
            gananciaUSD: gananciaUSDc,
            ganancia: gananciaC,
            esCorto: true,
            idCierre: tk+'|'+(o.fechaHora||fecha)
          });
          loteCorto.qty -= qtyCerrada;
          restanteCorto -= qtyCerrada;
          if(loteCorto.qty <= 0.0001) lotesCorto[tk].shift();
        }
        // NUEVO (09/08/2026): igual que en BUY, lo que sobre abre una
        // posición LARGA nueva en vez de descartarse.
        if(restanteCorto > 0.0001){
          lotes[tk].push({qty: restanteCorto, price: price, date: fecha, feePorUnidad: feePorUnidad, fx: o.fx});
          RENTA_CORTOS_IMPLICITOS.push({ticker: tk, fecha: fecha, unidades: restanteCorto, tipo: 'apertura largo (BUY_TO_COVER)'});
        }
      }
    });
    cierres.sort(function(a,b){ return a.fechaVenta.localeCompare(b.fechaVenta); });

    // REGLA DE LOS 2 MESES (art. 33.5 LIRPF, valores cotizados): una pérdida
    // NO es deducible si recompras el MISMO valor en los 2 meses ANTES o
    // DESPUÉS de la venta. Lo comprobamos con las fechas reales de todas
    // las órdenes (no solo las de ese lote) — si hay una BUY del mismo
    // ticker dentro de esa ventana, se marca como no deducible por ahora.
    var todasLasCompras = {}; // ticker -> array de fechas (YYYY-MM-DD) de BUY ejecutadas
    trades.forEach(function(t){
      if(t.action !== 'BUY') return;
      var tk = t.ticker;
      var fecha = t.fecha;
      if(!tk || !fecha) return;
      if(!todasLasCompras[tk]) todasLasCompras[tk] = [];
      todasLasCompras[tk].push(fecha);
    });
    // NUEVO (09/08/2026) — BUG REAL ENCONTRADO Y CONFIRMADO (caso GH): cuando
    // una sola venta liquida VARIOS lotes de golpe (comprados en fechas
    // distintas, ej. varias compras el día 20 y 21, vendidas todas juntas el
    // día 28), cada cierre comparaba las fechas de compra de los DEMÁS
    // lotes como si fueran una "recompra" sospechosa — pero no lo son, son
    // trozos de la MISMA liquidación simultánea, no una recompra después de
    // una pérdida. Agrupamos por "idCierre" (misma operación de venta) para
    // excluir también esas fechas hermanas, no solo la propia.
    var comprasHermanasPorCierre = {}; // idCierre -> Set de fechas de compra de los lotes hermanos
    cierres.forEach(function(c){
      if(!comprasHermanasPorCierre[c.idCierre]) comprasHermanasPorCierre[c.idCierre] = {};
      comprasHermanasPorCierre[c.idCierre][c.fechaCompra] = true;
    });
    var DOS_MESES_MS = 62 * 24 * 60 * 60 * 1000; // 62 días como aproximación segura de "2 meses"
    cierres.forEach(function(c){
      c.deducible = true;
      if(c.ganancia >= 0) return; // la regla solo afecta a pérdidas
      var fechaVentaMs = new Date(c.fechaVenta).getTime();
      var compras = todasLasCompras[c.ticker] || [];
      var hermanas = comprasHermanasPorCierre[c.idCierre] || {};
      // NUEVO (25/08/2026) — BUG REAL ENCONTRADO Y CONFIRMADO: en un cierre
      // CORTO, "fechaCompra" guarda la fecha de APERTURA del corto (una
      // venta, no una compra) — así que nunca coincide con nada de
      // "compras" (solo fechas de BUY), y la exclusión de "no cuentes tu
      // propia compra" no hacía nada. Pero la recompra que SÍ cierra el
      // corto tiene fecha = fechaVenta, y esa sí es un BUY real — se
      // comparaba consigo misma a distancia CERO, cayendo siempre dentro
      // de la ventana. Resultado: todo corto con pérdida salía "no
      // deducible" sin excepción, tuviera o no una recompra real cerca.
      // Se excluye también fechaVenta cuando es un cierre corto.
      var recompraEnVentana = compras.some(function(fc){
        if(fc === c.fechaCompra) return false;
        if(c.esCorto && fc === c.fechaVenta) return false;
        if(hermanas[fc]) return false;
        var diff = Math.abs(new Date(fc).getTime() - fechaVentaMs);
        return diff <= DOS_MESES_MS;
      });
      if(recompraEnVentana) c.deducible = false;
    });

    // ── DIFERIMIENTO DE PÉRDIDAS NO DEDUCIBLES (art. 33.5.f LIRPF) ─────────
    // NUEVO (09/08/2026): hasta ahora una pérdida "no deducible" simplemente
    // desaparecía del NETO FISCAL para siempre. Eso está mal — la ley no la
    // elimina, la POSPONE: se suma al coste de adquisición de la recompra que
    // activó la regla, y aflora (reduce la ganancia, o aumenta la pérdida)
    // cuando esa recompra concreta se vuelva a vender fuera de cualquier otra
    // ventana de 2 meses. Aquí localizamos, para cada pérdida no deducible,
    // la recompra más cercana en el tiempo (antes o después de la venta —
    // igual que ya hace la detección de arriba) y trasladamos el importe a
    // la(s) venta(s) futuras que liquiden esas acciones concretas, a
    // prorrata de las unidades si esa recompra se vende en varios tramos. Si
    // la recompra sigue abierta (todavía no se ha vuelto a vender en el
    // histórico disponible), la pérdida queda diferida sin aplicar — correcto,
    // porque tampoco se ha realizado fiscalmente todavía.
    var comprasPorTickerFecha = {}; // "ticker|fecha" -> unidades totales compradas ese día
    trades.forEach(function(t){
      if(t.action !== 'BUY') return;
      var k = t.ticker+'|'+t.fecha;
      comprasPorTickerFecha[k] = (comprasPorTickerFecha[k]||0) + t.qty;
    });

    var poolDiferido = {}; // "ticker|fechaRecompra" -> importe total de pérdida pospuesta
    cierres.forEach(function(c){
      if(c.deducible) return; // solo nos interesan las marcadas no deducibles
      var fechaVentaMs = new Date(c.fechaVenta).getTime();
      var compras = todasLasCompras[c.ticker] || [];
      var hermanasDif = comprasHermanasPorCierre[c.idCierre] || {};
      var mejorFecha = null, mejorDiff = Infinity;
      compras.forEach(function(fc){
        if(fc === c.fechaCompra) return;
        if(c.esCorto && fc === c.fechaVenta) return; // mismo motivo que en la detección de arriba
        if(hermanasDif[fc]) return; // mismo motivo que en la detección de arriba
        var diff = Math.abs(new Date(fc).getTime() - fechaVentaMs);
        if(diff <= DOS_MESES_MS && diff < mejorDiff){ mejorDiff = diff; mejorFecha = fc; }
      });
      if(!mejorFecha) return; // por seguridad, no debería pasar si ya está marcada no deducible
      var key = c.ticker+'|'+mejorFecha;
      poolDiferido[key] = (poolDiferido[key]||0) + Math.abs(c.ganancia);
      c.recompraFecha = mejorFecha; // trazabilidad/depuración
    });

    // Repartimos cada bolsa de pérdida diferida entre las ventas futuras que
    // liquiden esa recompra concreta, a prorrata de las unidades vendidas.
    Object.keys(poolDiferido).forEach(function(key){
      var separador = key.lastIndexOf('|');
      var tk = key.slice(0, separador), fechaRecompra = key.slice(separador+1);
      var totalUnidadesCompradas = comprasPorTickerFecha[key] || 0;
      if(totalUnidadesCompradas <= 0) return;
      var importeTotal = poolDiferido[key];
      cierres.forEach(function(c){
        if(c.ticker !== tk || c.fechaCompra !== fechaRecompra) return;
        var prorrateo = c.unidades / totalUnidadesCompradas;
        var importeAplicado = importeTotal * prorrateo;
        c.ganancia -= importeAplicado; // sube el coste efectivo de esa recompra concreta
        c.perdidaDiferidaAplicada = (c.perdidaDiferidaAplicada||0) + importeAplicado;
      });
    });

    return cierres;
  }

  // NUEVO (09/08/2026): compara, ticker por ticker, la posición que implica
  // TODO nuestro historial reconstruido contra la posición REAL que reporta
  // el bróker ahora mismo (mismo array "positions" que ya se pide siempre en
  // /snaptrade/data — no hace falta ninguna llamada nueva ni que el alumno
  // suba nada). Si no coinciden (más allá de una fracción de acción), es la
  // prueba de que a ESE ticker en concreto le falta o le sobra alguna
  // operación en el historial de SnapTrade — un problema de datos de ese
  // ticker, no del cálculo. Funciona igual para cualquier alumno, sin que
  // nadie tenga que aportar su propio informe del bróker.
  function rentaValidarPosiciones(posicionesReales){
    RENTA_TICKERS_REVISAR = {};
    var TOLERANCIA_UNIDADES = 0.5; // margen por acciones fraccionarias
    var unidadesReales = {};
    (Array.isArray(posicionesReales) ? posicionesReales : []).forEach(function(p){
      var symObj = (p.symbol && p.symbol.symbol) ? p.symbol.symbol : (p.symbol || {});
      var tk = symObj.symbol || p.ticker || '';
      if(!tk) return;
      unidadesReales[tk] = (unidadesReales[tk]||0) + parseFloat(p.units || p.fractional_units || 0);
    });
    var todosLosTickers = Array.from(new Set(Object.keys(RENTA_POSICION_RECONSTRUIDA).concat(Object.keys(unidadesReales))));
    todosLosTickers.forEach(function(tk){
      var reconstruida = RENTA_POSICION_RECONSTRUIDA[tk] || 0;
      var real = unidadesReales[tk] || 0;
      if(Math.abs(reconstruida - real) > TOLERANCIA_UNIDADES){
        RENTA_TICKERS_REVISAR[tk] = {reconstruida: reconstruida, real: real};
      }
    });
  }

  var RENTA_TODOS_LOS_CIERRES = []; // sin filtrar por año — la fuente de verdad
  var RENTA_ANIO_ACTUAL = null;

  function renderRenta(cierresCompletos){
    RENTA_TODOS_LOS_CIERRES = cierresCompletos;
    document.getElementById('renta-no-datos').style.display = 'none';
    document.getElementById('renta-contenido').style.display = 'block';

    // NUEVO (13/08/2026): selector de ejercicio fiscal. Las ganancias se
    // declaran en el año de la VENTA (fechaVenta), no de la compra — así lo
    // exige Hacienda. Sin esto, se mezclaban 2024+2025+2026 en un solo
    // número, dando cifras que no cuadraban con ningún año concreto.
    var anios = Array.from(new Set(cierresCompletos.map(function(c){ return c.fechaVenta.slice(0,4); }))).sort().reverse();
    var selectEl = document.getElementById('renta-anio-select');
    if(selectEl){
      var anioPrevio = RENTA_ANIO_ACTUAL;
      selectEl.innerHTML = anios.map(function(a){ return '<option value="'+a+'">'+a+'</option>'; }).join('');
      RENTA_ANIO_ACTUAL = (anioPrevio && anios.indexOf(anioPrevio)>=0) ? anioPrevio : (anios[0] || null);
      selectEl.value = RENTA_ANIO_ACTUAL || '';
    }
    rentaFiltrarAnio();
  }

  // NUEVO (26/08/2026): filtro por trimestre/mes, combinado con el año ya
  // seleccionado — para quien quiera ver un periodo más corto que el año
  // completo (ej. "cuánto llevo ganado/perdido este trimestre").
  function rentaObtenerRangoPeriodo(){
    var periodoEl = document.getElementById('renta-periodo-select');
    var periodo = periodoEl ? periodoEl.value : 'anio';
    if(!periodo || periodo === 'anio') return null;
    if(periodo.charAt(0) === 'q'){
      var q = parseInt(periodo.slice(1), 10);
      return {mesInicio: (q-1)*3+1, mesFin: q*3, etiqueta: 'T'+q};
    }
    if(periodo.charAt(0) === 'm'){
      var m = parseInt(periodo.slice(1), 10);
      var nombresMes = ['','enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
      return {mesInicio: m, mesFin: m, etiqueta: nombresMes[m]};
    }
    return null;
  }

  function rentaFiltrarAnio(){
    var selectEl = document.getElementById('renta-anio-select');
    var anio = selectEl ? selectEl.value : null;
    RENTA_ANIO_ACTUAL = anio;
    rentaAplicarFiltroAnioYPeriodo();
    rentaFiltrarDividendosPorAnio();
  }

  function rentaFiltrarPeriodo(){
    rentaAplicarFiltroAnioYPeriodo();
  }

  function rentaAplicarFiltroAnioYPeriodo(){
    var anio = RENTA_ANIO_ACTUAL;
    var cierres = anio ? RENTA_TODOS_LOS_CIERRES.filter(function(c){ return c.fechaVenta.slice(0,4) === anio; }) : RENTA_TODOS_LOS_CIERRES.slice();
    var rango = rentaObtenerRangoPeriodo();
    if(rango){
      cierres = cierres.filter(function(c){
        var mes = parseInt(c.fechaVenta.slice(5,7), 10);
        return mes >= rango.mesInicio && mes <= rango.mesFin;
      });
    }
    rentaRenderConAnio(cierres, anio, rango);
  }

  function rentaRenderConAnio(cierres, anio, rangoPeriodo){
    RENTA_DATA = cierres;

    // NUEVO (11/07/2026): mostrar SIEMPRE qué rango de fechas se ha
    // capturado de verdad — nada de asumir que está completo. Si el rango
    // no cubre desde el 1 de enero del año en curso, avisa en naranja.
    var covEl = document.getElementById('renta-cobertura');
    if(covEl){
      var hoy = new Date();
      var inicioAnio = hoy.getFullYear() + '-01-01';
      var cubreAnioCompleto = RENTA_COBERTURA.desde && RENTA_COBERTURA.desde <= inicioAnio;
      if(RENTA_COBERTURA.count === 0){
        covEl.style.display = 'none';
      } else if(cubreAnioCompleto){
        covEl.style.display = 'block';
        covEl.style.background = 'rgba(5,196,107,.08)'; covEl.style.color = 'var(--up)';
        covEl.innerHTML = '✓ Cobertura total: ' + RENTA_COBERTURA.desde + ' → ' + RENTA_COBERTURA.hasta + ' (' + RENTA_COBERTURA.count + ' operaciones) — mostrando ejercicio ' + (anio||'—') + '.';
      } else {
        covEl.style.display = 'block';
        covEl.style.background = 'rgba(245,158,11,.10)'; covEl.style.color = 'var(--warn)';
        covEl.innerHTML = '⚠️ Cobertura total: ' + RENTA_COBERTURA.desde + ' → ' + RENTA_COBERTURA.hasta + ' (' + RENTA_COBERTURA.count + ' operaciones) — <strong>NO llega hasta el 1 de enero</strong>. '
          + 'El broker no siempre entrega el histórico completo del año (a veces solo el último tramo). Revisa si te faltan operaciones anteriores a ' + RENTA_COBERTURA.desde + '.';
      }
    }

    // NUEVO (09/08/2026): resumen de ventas/compras que abrieron una
    // posición CORTA o LARGA "implícita" — llegaron como SELL/BUY normal
    // sin lote contrario suficiente que cerrar, así que (en vez de
    // descartarse como antes) se ha asumido que es una operación en corto
    // real que el feed no etiquetó como tal (confirmado con datos reales:
    // BMNRn, RGTIn, NFLX). Se muestra para que puedas revisar si algún
    // ticker de la lista NO tiene sentido que vaya en corto (en cuyo caso
    // sería más bien una posición antigua de antes de conectar el broker,
    // y convendría avisarme). Se añade también, en la misma caja, cuántos
    // tickers llevan el badge "🔍 revisar cifra" (posición reconstruida
    // que no coincide con la posición real del bróker).
    var cortosEl = document.getElementById('renta-descartes');
    if(cortosEl){
      var tickersRevisar = Object.keys(RENTA_TICKERS_REVISAR);
      if(RENTA_CORTOS_IMPLICITOS.length === 0 && tickersRevisar.length === 0){
        cortosEl.style.display = 'none';
      } else {
        var partes = [];
        if(tickersRevisar.length){
          partes.push('🔍 <strong>' + tickersRevisar.length + ' ticker(s) con "revisar cifra"</strong> (' + tickersRevisar.slice(0,8).join(', ') + (tickersRevisar.length>8?'…':'') + ') — la posición que implica el historial no coincide con lo que tienes de verdad en el bróker. Probablemente falte alguna operación de ese ticker en el historial; la cifra de esos tickers puede no ser exacta.');
        }
        if(RENTA_CORTOS_IMPLICITOS.length){
          var tickersCortos = Array.from(new Set(RENTA_CORTOS_IMPLICITOS.map(function(d){ return d.ticker; })));
          partes.push('ℹ️ ' + RENTA_CORTOS_IMPLICITOS.length + ' operación(es) tratadas como apertura de corto/largo implícita (' + tickersCortos.slice(0,8).join(', ') + (tickersCortos.length>8?'…':'') + ').');
        }
        cortosEl.style.display = 'block';
        cortosEl.style.background = tickersRevisar.length ? 'rgba(245,158,11,.10)' : 'rgba(59,130,246,.10)';
        cortosEl.style.color = tickersRevisar.length ? 'var(--warn)' : 'var(--ac)';
        cortosEl.innerHTML = partes.join('<br>');
      }
    }

    var ganancias = cierres.filter(function(c){ return c.ganancia >= 0; }).reduce(function(s,c){ return s+c.ganancia; }, 0);
    var perdidasDeducibles    = cierres.filter(function(c){ return c.ganancia < 0 && c.deducible; }).reduce(function(s,c){ return s+c.ganancia; }, 0);
    var perdidasNoDeducibles  = cierres.filter(function(c){ return c.ganancia < 0 && !c.deducible; }).reduce(function(s,c){ return s+c.ganancia; }, 0);
    var neto = ganancias + perdidasDeducibles; // el neto fiscal NO incluye las pérdidas bloqueadas por la regla de los 2 meses
    // NUEVO (25/08/2026): bruto de CONTRASTE — la suma de TODAS las
    // operaciones tal cual pasaron, sin aplicar la regla de los 2 meses.
    // NO es una cifra fiscal (para eso está el NETO FISCAL de arriba, que
    // ya excluye correctamente lo no deducible) — es solo para poder
    // comparar de un vistazo contra el informe de tu bróker, que tampoco
    // aplica esta regla española. Se reconstruye deshaciendo el efecto del
    // diferimiento (ganancia + lo que se le haya restado por absorber una
    // pérdida diferida) para no arrastrar el doble conteo que tiene sumar
    // las tres tarjetas de arriba a pelo.
    var brutoContraste = cierres.reduce(function(s,c){ return s + c.ganancia + (c.perdidaDiferidaAplicada||0); }, 0);

    // NUEVO (26/08/2026): el número grande de arriba de todo — el
    // "Total ganancias/pérdidas" simple, tal cual lo mostraría el bróker,
    // sin ningún ajuste fiscal español. Es lo primero que se ve, para que
    // cualquiera (incluidos los alumnos que no conocen la regla de los 2
    // meses) entienda de un vistazo el resultado real, antes de bajar a
    // las tarjetas con el detalle fiscal.
    var totalEl = document.getElementById('renta-bruto-total');
    if(totalEl){
      var etiquetaPeriodo = rangoPeriodo ? (' — ' + rangoPeriodo.etiqueta) : '';
      totalEl.innerHTML = '<div style="font-size:12px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">Total ganancias/pérdidas (como en tu bróker)'+etiquetaPeriodo+'</div>'
        + '<div style="font-family:Syne,sans-serif;font-size:36px;font-weight:800;color:'+(brutoContraste>=0?'var(--up)':'var(--dn)')+'">'
        + (brutoContraste>=0?'+':'') + brutoContraste.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}) + '€</div>'
        + '<div style="font-size:11px;color:var(--dim);margin-top:6px">Para la declaración de la Renta hay que aplicar la regla española de los 2 meses — mira el "Resultado neto fiscal" en las tarjetas de abajo.</div>';
    }

    document.getElementById('renta-kpis').innerHTML = [
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--up)"><div class="bc-l">Ganancias realizadas</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--up)">+'+ganancias.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--dn)"><div class="bc-l">Pérdidas deducibles</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--dn)">'+perdidasDeducibles.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--warn)"><div class="bc-l">Pérdidas NO deducibles (regla 2 meses)</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--warn)">'+perdidasNoDeducibles.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid '+(neto>=0?'var(--up)':'var(--dn)')+'"><div class="bc-l">Resultado neto fiscal</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+(neto>=0?'var(--up)':'var(--dn)')+'">'+(neto>=0?'+':'')+neto.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--dim)"><div class="bc-l">Ventas cerradas</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">'+cierres.length+'</div></div>',
    ].join('');

    var brutoEl = document.getElementById('renta-bruto-contraste');
    if(brutoEl){
      brutoEl.innerHTML = 'Estas 4 tarjetas son el desglose fiscal español (regla de los 2 meses) — el número grande de arriba es el total real sin ajustar.';
    }

    document.getElementById('renta-tbody').innerHTML = cierres.map(function(c){
      var color = c.ganancia >= 0 ? 'var(--up)' : 'var(--dn)';
      var colorUSD = c.gananciaUSD >= 0 ? 'var(--up)' : 'var(--dn)';
      var avisoRegla = (!c.deducible) ? ' <span title="Recompraste el mismo valor dentro de los 2 meses — esta pérdida no es deducible este ejercicio (regla de los 2 meses). Se pospone al coste de la recompra y aflorará cuando esas acciones se vendan definitivamente." style="font-size:9px;color:var(--warn);border:1px solid var(--warn);border-radius:3px;padding:0 4px;cursor:help">⚠ no deducible</span>' : '';
      var avisoDiferida = (c.perdidaDiferidaAplicada) ? ' <span title="Esta venta incluye una pérdida diferida de una recompra anterior (regla de los 2 meses): -'+c.perdidaDiferidaAplicada.toFixed(2)+'€ ya restados de la ganancia." style="font-size:9px;color:var(--dim);border:1px solid var(--dim);border-radius:3px;padding:0 4px;cursor:help">📥 incl. pérdida diferida</span>' : '';
      var infoRevisar = RENTA_TICKERS_REVISAR[c.ticker];
      var avisoRevisar = infoRevisar ? ' <span title="La posición que implica todo el historial de '+c.ticker+' ('+infoRevisar.reconstruida.toFixed(2)+' uds.) no coincide con lo que tienes de verdad en el bróker ahora mismo ('+infoRevisar.real.toFixed(2)+' uds.) — probablemente falta alguna operación de este ticker en el historial. Esta cifra puede no ser exacta." style="font-size:9px;color:var(--ac);border:1px solid var(--ac);border-radius:3px;padding:0 4px;cursor:help">🔍 revisar cifra</span>' : '';
      return '<tr style="border-bottom:1px solid var(--b1)"'
        +' data-ticker="'+c.ticker.toLowerCase()+'"'
        +' data-fc="'+c.fechaCompra+'" data-fv="'+c.fechaVenta+'"'
        +' data-gan="'+c.ganancia.toFixed(4)+'"'
        +' data-deducible="'+(c.deducible?'1':'0')+'"'
        +' data-diferida="'+(c.perdidaDiferidaAplicada?'1':'0')+'">'
        +'<td style="padding:6px 8px;font-weight:700;color:var(--ac)">'+c.ticker+avisoRegla+avisoDiferida+avisoRevisar+'</td>'
        +'<td style="padding:6px 8px;font-size:11px">'+c.fechaCompra+'</td>'
        +'<td style="padding:6px 8px;font-size:11px">'+c.fechaVenta+'</td>'
        +'<td style="padding:6px 8px;text-align:right">'+c.unidades.toFixed(4)+'</td>'
        +'<td style="padding:6px 8px;text-align:right">'+c.precioCompra.toFixed(2)+'$</td>'
        +'<td style="padding:6px 8px;text-align:right">'+c.precioVenta.toFixed(2)+'$</td>'
        +'<td style="padding:6px 8px;text-align:right;color:var(--dim)">-'+(c.comisiones||0).toFixed(2)+'$</td>'
        +'<td style="padding:6px 8px;text-align:right;color:'+colorUSD+'">'+(c.gananciaUSD>=0?'+':'')+c.gananciaUSD.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'$</td>'
        +'<td style="padding:6px 8px;text-align:right;color:'+color+';font-weight:600">'+(c.ganancia>=0?'+':'')+c.ganancia.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
        +'</tr>';
    }).join('') || '<tr><td colspan="9" style="text-align:center;color:var(--dim);padding:20px">Sin ventas cerradas en el historial disponible</td></tr>';

    document.getElementById('renta-tfoot').innerHTML = cierres.length ? (
      '<tr style="border-top:2px solid var(--b1);font-weight:700;background:var(--bg2)">'
      +'<td colspan="8" style="padding:8px">NETO FISCAL del ejercicio, en € (ya descuenta comisiones, convierte cada pata al cambio EUR/USD de su propia fecha, y excluye pérdidas no deducibles)</td>'
      +'<td style="padding:8px;text-align:right;color:'+(neto>=0?'var(--up)':'var(--dn)')+'">'+(neto>=0?'+':'')+neto.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
      +'</tr>'
      +'<tr id="renta-fila-total-filtrado" style="border-top:1px dashed var(--b2);font-weight:700">'
      +'<td colspan="8" style="padding:8px;color:var(--dim)" id="renta-total-filtrado-label">TOTAL (filas visibles con los filtros de arriba)</td>'
      +'<td style="padding:8px;text-align:right" id="renta-total-filtrado-valor"></td>'
      +'</tr>'
    ) : '';

    // Los filtros se limpian al cambiar de año/renderizar de nuevo, y se
    // recalcula el total de lo que quede visible.
    rentaLimpiarFiltros();
  }

  // ── FILTROS DE LA TABLA DE RENTA ────────────────────────────────────────
  // NUEVO: filtro rápido por columna (texto libre en ticker/fechas, rango
  // en ganancia/pérdida) + un desplegable de estado fiscal, todo client-side
  // sobre las filas ya pintadas. La fila "TOTAL (filtrado)" se recalcula
  // sobre lo que quede visible, así sirve para sumar rápido un subconjunto
  // (p.ej. solo un ticker, o solo un rango de fechas) sin tener que exportar
  // a CSV y sumarlo aparte.
  function rentaAplicarFiltros(){
    var fTicker = (document.getElementById('renta-f-ticker').value || '').toLowerCase().trim();
    var fFc = (document.getElementById('renta-f-fc').value || '').toLowerCase().trim();
    var fFv = (document.getElementById('renta-f-fv').value || '').toLowerCase().trim();
    var ganMinRaw = document.getElementById('renta-f-gan-min').value;
    var ganMaxRaw = document.getElementById('renta-f-gan-max').value;
    var ganMin = ganMinRaw !== '' ? parseFloat(ganMinRaw) : null;
    var ganMax = ganMaxRaw !== '' ? parseFloat(ganMaxRaw) : null;
    var estado = document.getElementById('renta-filtro-estado').value;

    var filas = document.querySelectorAll('#renta-tbody tr[data-ticker]');
    var visibles = 0, sumaGan = 0;
    filas.forEach(function(tr){
      var ok = true;
      if(fTicker && tr.getAttribute('data-ticker').indexOf(fTicker) === -1) ok = false;
      if(ok && fFc && tr.getAttribute('data-fc').indexOf(fFc) === -1) ok = false;
      if(ok && fFv && tr.getAttribute('data-fv').indexOf(fFv) === -1) ok = false;
      var gan = parseFloat(tr.getAttribute('data-gan'));
      if(ok && ganMin !== null && gan < ganMin) ok = false;
      if(ok && ganMax !== null && gan > ganMax) ok = false;
      var esDeducible = tr.getAttribute('data-deducible') === '1';
      var tieneDiferida = tr.getAttribute('data-diferida') === '1';
      if(ok && estado === 'ganancia' && gan < 0) ok = false;
      if(ok && estado === 'perdida' && gan >= 0) ok = false;
      if(ok && estado === 'no_deducible' && esDeducible) ok = false;
      if(ok && estado === 'diferida' && !tieneDiferida) ok = false;
      tr.style.display = ok ? '' : 'none';
      if(ok){ visibles++; sumaGan += gan; }
    });

    var contador = document.getElementById('renta-filtro-contador');
    if(contador) contador.textContent = visibles + ' de ' + filas.length + ' operaciones visibles';

    var valorEl = document.getElementById('renta-total-filtrado-valor');
    var labelEl = document.getElementById('renta-total-filtrado-label');
    if(valorEl){
      valorEl.style.color = sumaGan >= 0 ? 'var(--up)' : 'var(--dn)';
      valorEl.textContent = (sumaGan>=0?'+':'') + sumaGan.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}) + '€';
    }
    if(labelEl){
      labelEl.textContent = 'TOTAL de las ' + visibles + ' filas visibles, en € (suma bruta, sin aplicar la regla de los 2 meses — es solo la suma de lo que ves filtrado)';
    }
  }

  function rentaLimpiarFiltros(){
    ['renta-f-ticker','renta-f-fc','renta-f-fv','renta-f-gan-min','renta-f-gan-max'].forEach(function(id){
      var el = document.getElementById(id);
      if(el) el.value = '';
    });
    var estadoEl = document.getElementById('renta-filtro-estado');
    if(estadoEl) estadoEl.value = 'todas';
    rentaAplicarFiltros();
  }

  // ── DIVIDENDOS ──────────────────────────────────────────────────────────
  // CONFIRMADO en la documentación oficial de SnapTrade: el campo "type" de
  // cada actividad incluye "DIVIDEND" (efectivo), "STOCK_DIVIDEND" (en
  // acciones) y "REI" (reinversión automática de dividendos).
  var DIVIDEND_TYPES = ['DIVIDEND', 'STOCK_DIVIDEND', 'REI'];
  var RENTA_TODAS_LAS_ACTIVITIES = []; // para poder re-filtrar dividendos al cambiar de año
  function renderDividendos(activities){
    RENTA_TODAS_LAS_ACTIVITIES = Array.isArray(activities) ? activities : (activities && activities.data) || [];
    rentaFiltrarDividendosPorAnio();
  }
  function rentaFiltrarDividendosPorAnio(){
    var anio = RENTA_ANIO_ACTUAL;
    var lista = anio
      ? RENTA_TODAS_LAS_ACTIVITIES.filter(function(a){ return (a.trade_date||a.settlement_date||'').slice(0,4) === anio; })
      : RENTA_TODAS_LAS_ACTIVITIES;
    var dividendos = lista.filter(function(a){
      return DIVIDEND_TYPES.indexOf((a.type||'').toUpperCase()) >= 0;
    });

    if(dividendos.length === 0){
      document.getElementById('dividendos-vacio').style.display = 'block';
      document.getElementById('dividendos-contenido').style.display = 'none';
      return;
    }
    document.getElementById('dividendos-vacio').style.display = 'none';
    document.getElementById('dividendos-contenido').style.display = 'block';

    var total = dividendos.reduce(function(s,a){ return s + Math.abs(parseFloat(a.amount||0)); }, 0);
    var porTicker = {};
    dividendos.forEach(function(a){
      var tk = (a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '—';
      porTicker[tk] = (porTicker[tk]||0) + Math.abs(parseFloat(a.amount||0));
    });
    var tickerTop = Object.keys(porTicker).sort(function(a,b){ return porTicker[b]-porTicker[a]; })[0] || '—';

    document.getElementById('dividendos-kpis').innerHTML = [
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--up)"><div class="bc-l">Total dividendos cobrados</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--up)">+'+total.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'$</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--dim)"><div class="bc-l">Nº de pagos</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">'+dividendos.length+'</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--ac)"><div class="bc-l">Mayor pagador</div><div style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:var(--ac)">'+tickerTop+'</div></div>',
    ].join('');

    document.getElementById('dividendos-tbody').innerHTML = dividendos
      .sort(function(a,b){ return (b.trade_date||b.settlement_date||'').localeCompare(a.trade_date||a.settlement_date||''); })
      .map(function(a){
        var tk = (a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '—';
        var fecha = (a.trade_date || a.settlement_date || '').slice(0,10);
        var importe = Math.abs(parseFloat(a.amount||0));
        return '<tr style="border-bottom:1px solid var(--b1)">'
          +'<td style="padding:6px 8px;font-weight:700;color:var(--ac)">'+tk+'</td>'
          +'<td style="padding:6px 8px;font-size:11px">'+fecha+'</td>'
          +'<td style="padding:6px 8px;text-align:right;color:var(--up);font-weight:600">+'+importe.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'$</td>'
          +'</tr>';
      }).join('');
  }

  function rentaExportarCSV(){
    if(!RENTA_DATA || RENTA_DATA.length===0){ alert('No hay datos para exportar.'); return; }
    var rows = [['Ticker','Fecha Compra','Fecha Venta','Unidades','Precio Compra ($)','Precio Venta ($)','Comisiones ($)','Ganancia/Pérdida ($)','Ganancia/Pérdida (€)','Deducible (regla 2 meses)','Pérdida diferida aplicada (€)']];
    RENTA_DATA.forEach(function(c){
      rows.push([c.ticker,c.fechaCompra,c.fechaVenta,c.unidades.toFixed(4),c.precioCompra.toFixed(2),c.precioVenta.toFixed(2),(c.comisiones||0).toFixed(2),(c.gananciaUSD||0).toFixed(2),c.ganancia.toFixed(2),c.deducible?'Sí':'No',(c.perdidaDiferidaAplicada||0).toFixed(2)]);
    });
    var csv = rows.map(function(r){ return r.join(';'); }).join('\n');
    var blob = new Blob(['\ufeff'+csv], {type:'text/csv;charset=utf-8;'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'renta_plusvalias.csv'; a.click();
    URL.revokeObjectURL(url);
  }

  async function fiscalCargar(){
    // Verificar si hay broker conectado (reusar datos de Mi Broker si existen)
    if(!BK_USER_SECRET){
      var btn0 = document.getElementById('fiscal-load-btn');
      btn0.textContent = 'Conectando...'; btn0.disabled = true;
      var recovered = await tryRecoverBroker();
      btn0.textContent = '📥 Cargar posiciones del broker'; btn0.disabled = false;
      if(!recovered){
        alert('Primero conecta tu broker en la pestaña Mi Broker.');
        return;
      }
    }
    var btn = document.getElementById('fiscal-load-btn');
    btn.textContent = 'Cargando...'; btn.disabled = true;

    if(BK_DATA){
      // Ya tenemos datos del broker en memoria
      fiscalMostrarDatos(BK_DATA);
      btn.textContent = '✓ Posiciones cargadas'; btn.disabled = false;
    } else {
      var token = await getAuthToken();
      if(!token){ alert('Tu sesión ha caducado, vuelve a iniciar sesión.'); btn.textContent='📥 Cargar posiciones del broker'; btn.disabled=false; return; }
      // Cargar desde SnapTrade
      fetch('https://lacomunidad.onrender.com/snaptrade/data', {
        method:'POST', headers:{'Content-Type':'application/json', 'Authorization':'Bearer '+token},
        body: JSON.stringify({user_id: GLOBAL_USER.id, user_secret: BK_USER_SECRET})
      })
      .then(function(r){ return r.json(); })
      .then(function(d){
        BK_DATA = d;
        fiscalMostrarDatos(d);
        btn.textContent = '✓ Posiciones cargadas'; btn.disabled = false;
      })
      .catch(function(e){
        alert('Error cargando datos: ' + e.message);
        btn.textContent = '📥 Cargar posiciones del broker'; btn.disabled = false;
      });
    }
  }

  function fcSetDiscreto(on){
    var el = document.getElementById('tab-fiscal');
    var btn = document.getElementById('fc-discreet-btn');
    if(!el) return;
    if(on){
      el.classList.add('fc-discreet');
      if(btn) btn.textContent = '🙈 Mostrar';
    } else {
      el.classList.remove('fc-discreet');
      if(btn) btn.textContent = '🙉 Ocultar';
    }
  }
  function fcToggleDiscreto(){
    var el = document.getElementById('tab-fiscal');
    var isOn = el && el.classList.contains('fc-discreet');
    fcSetDiscreto(!isOn);
  }

  async function fiscalMostrarDatos(d){
    actualizarEurUsdRate(); // ahora sí lee el EUR/USD real del Resumen, D ya existe aquí
    document.getElementById('fiscal-no-broker').style.display = 'none';
    document.getElementById('fiscal-tabla').style.display = 'block';
    document.getElementById('fiscal-csv-btn').style.display = '';
    document.getElementById('fiscal-720-btn').style.display = '';
    document.getElementById('fc-discreet-btn').style.display = '';
    // Modo discreción SIEMPRE por defecto, igual que Mi Broker — máxima privacidad.
    fcSetDiscreto(true);

    // NUEVO (09/08/2026): antes de calcular Renta hace falta el histórico
    // EUR/USD desde la operación más antigua — si no, cada cierre caería al
    // cambio de HOY como respaldo (degradado, no roto, pero mejor tenerlo
    // real). Se calcula la fecha mínima igual que ya hace la curva de
    // equity (bkFetchPriceHistory) para no duplicar lógica de más.
    var fechaMinFX = null;
    (d.orders||[]).forEach(function(o){
      var f = (o.time_executed || o.time_placed || '').slice(0,10);
      if(f && (!fechaMinFX || f < fechaMinFX)) fechaMinFX = f;
    });
    var listaActivitiesFX = Array.isArray(d.activities) ? d.activities : (d.activities && d.activities.data) || [];
    listaActivitiesFX.forEach(function(a){
      var f = (a.trade_date || a.settlement_date || '').slice(0,10);
      if(f && (!fechaMinFX || f < fechaMinFX)) fechaMinFX = f;
    });
    if(fechaMinFX) await fetchEurUsdHistorico(fechaMinFX);

    // NUEVO (10/07/2026): dividendos — CONFIRMADO en la documentación oficial
    // de SnapTrade que el campo "type" de activities incluye "DIVIDEND",
    // "STOCK_DIVIDEND" y "REI" (reinversión). Se usa el mismo d.activities
    // que ya pedimos para la liquidez, sin llamada nueva.
    // NOTA: se llama ANTES que renderRenta a propósito — renderRenta dispara
    // el primer filtrado por año, que también refresca dividendos, así que
    // RENTA_TODAS_LAS_ACTIVITIES tiene que estar ya rellena en ese momento.
    renderDividendos(d.activities);

    // NUEVO (10/07/2026): calcular Renta (plusvalías FIFO) con el mismo
    // d.orders que ya tenemos aquí — no hace falta una llamada nueva.
    var cierres = calcularRentaFIFO(d.orders, d.activities);
    // NUEVO (09/08/2026): comparar la posición reconstruida contra la
    // posición REAL que reporta el bróker ahora mismo — antes de pintar la
    // tabla, para que el aviso "revisar cifra" ya salga en el primer
    // renderizado.
    rentaValidarPosiciones(d.positions);
    renderRenta(cierres);

    // NUEVO (10/07/2026): fecha de incorporación real, sacada del historial
    // de órdenes (mismo campo que ya funciona en Mi Broker) — se usa la
    // fecha de la PRIMERA compra ejecutada de cada ticker. No es tan preciso
    // como una fecha por lote (eso SnapTrade no lo da, tax_lots venía
    // vacío), pero es mucho mejor que dejarlo en blanco, y es un dato real,
    // no inventado.
    // NUEVO (11/07/2026): cambiado de "orders" (tope de 90 días confirmado
    // por SnapTrade) a "activities" (rango de un año pedido, mejor
    // cobertura real) — misma lógica: fecha de la PRIMERA compra de cada
    // ticker. No es tan preciso como una fecha por lote (SnapTrade no la
    // da, tax_lots venía vacío), pero es mucho mejor que dejarlo en blanco.
    FISCAL_FECHAS = {};
    var actList = Array.isArray(d.activities) ? d.activities : (d.activities && d.activities.data) || [];
    actList
      .filter(function(a){ return (a.type||'').toUpperCase()==='BUY'; })
      .forEach(function(a){
        var tk = (a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '';
        var fecha = (a.trade_date || a.settlement_date || '').slice(0,10).replace(/-/g,'');
        if(!tk || !fecha) return;
        if(!FISCAL_FECHAS[tk] || fecha < FISCAL_FECHAS[tk]) FISCAL_FECHAS[tk] = fecha;
      });
    // Respaldo con orders por si algo no aparece en activities
    if(Array.isArray(d.orders)){
      d.orders
        .filter(function(o){ return (o.action||'').toUpperCase()==='BUY' && (o.status==='EXECUTED'||o.status==='FILLED'); })
        .forEach(function(o){
          var tk = (o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '';
          var fecha = (o.time_executed || o.time_placed || '').slice(0,10).replace(/-/g,'');
          if(!tk || !fecha) return;
          if(!FISCAL_FECHAS[tk] || fecha < FISCAL_FECHAS[tk]) FISCAL_FECHAS[tk] = fecha;
        });
    }

    // FIX (09/07/2026): el servidor devuelve d.positions como array PLANO
    // (igual que usa Mi Broker, que sí funciona) — nunca hay una clave
    // "holdings" en la respuesta, por eso siempre salía todo a 0€.
    var positions = Array.isArray(d.positions) ? d.positions : [];
    var posiciones = [];
    positions.forEach(function(p){
      var symObj = (p.symbol && p.symbol.symbol) ? p.symbol.symbol : (p.symbol || {});
      var tk = symObj.symbol || p.ticker || '';
      var nombre = symObj.description || symObj.name || tk;
      // ISIN — nombre de campo no verificado al 100% en producción todavía;
      // se intenta en varios sitios posibles y se deja en blanco si no
      // aparece (mejor vacío que un dato inventado en un documento fiscal).
      // CONFIRMADO (log real 09/07/2026): SnapTrade NO trae ISIN en ningún
      // campo — solo figi_code (identificador de Bloomberg). Se guarda el
      // FIGI como referencia; convertir a ISIN real requeriría una consulta
      // aparte a OpenFIGI (pendiente de decidir si se monta).
      var isin = '';
      var figi = symObj.figi_code || (symObj.figi_instrument && symObj.figi_instrument.figi_code) || '';
      // NUEVO (10/07/2026) — CONFIRMADO por 6 fuentes (incl. consulta
      // vinculante DGT V1013-25/2025): los ETFs van con Clave tipo de bien
      // "I" (Instituciones de Inversión Colectiva), NO "V", y con subclave
      // en blanco. Se detecta usando el campo "type" que da SnapTrade
      // (visto en tu log real: "cs" = Common Stock para acciones). El
      // código exacto para ETF no está confirmado todavía porque no ha
      // aparecido ninguno en tus logs — se cubre de forma defensiva por
      // código y por descripción; si un ETF no se detecta bien, avísame con
      // el log real y lo ajusto al código exacto.
      var tipoCodigo = ((symObj.type && symObj.type.code) || '').toLowerCase();
      var tipoDesc = ((symObj.type && symObj.type.description) || '').toLowerCase();
      var esETF = tipoCodigo.indexOf('et')===0 || tipoCodigo==='etf' ||
                  tipoDesc.indexOf('etf')>=0 || tipoDesc.indexOf('exchange traded')>=0 ||
                  tipoDesc.indexOf('fund')>=0;
      var units = parseFloat(p.units || p.fractional_units || 0);
      var price = parseFloat(p.price!=null ? p.price : (symObj.last_price||0));
      var avgCost = parseFloat(p.average_purchase_price) || price;
      var valorUSD = price * units;
      var valorEUR = valorUSD / EURUSD_RATE;
      var adquisUSD = avgCost * units;
      var adquisEUR = adquisUSD / EURUSD_RATE;
      var pnlEUR = valorEUR - adquisEUR;
      // País basado en el exchange (simplificado)
      var exchange = (symObj.exchange && symObj.exchange.code) || 'US';
      var pais = exchange.includes('NYSE')||exchange.includes('NASDAQ')||exchange==='US' ? 'Estados Unidos' :
                 exchange.includes('LON')||exchange.includes('LSE') ? 'Reino Unido' :
                 exchange.includes('XETR')||exchange.includes('FRA') ? 'Alemania' :
                 exchange.includes('BME')||exchange.includes('MAD') ? 'España' :
                 exchange.includes('EPA')||exchange.includes('PAR') ? 'Francia' : 'Internacional';
      var codigoPais = pais==='Estados Unidos'?'US':pais==='Reino Unido'?'GB':pais==='Alemania'?'DE':pais==='España'?'ES':pais==='Francia'?'FR':'US';
      posiciones.push({
        ticker: tk, nombre: nombre, isin: isin, figi: figi, esETF: esETF, units: units, price: price, avgCost: avgCost,
        valorEUR: valorEUR, adquisEUR: adquisEUR, pnlEUR: pnlEUR,
        broker: 'IBKR', pais: pais, codigoPais: codigoPais
      });
    });

    FISCAL_DATA = posiciones;

    // NUEVO (14/08/2026): reconstrucción histórica de posiciones por año,
    // para el Modelo 720 de ejercicios anteriores — reutiliza la misma
    // lógica que ya usamos para la curva de capital (día a día, desde
    // orders+activities), pero solo necesita la "foto" de un día concreto
    // (31/12 de cada año), no el histórico completo punto a punto.
    FISCAL_TICKER_META = {};
    posiciones.forEach(function(p){
      FISCAL_TICKER_META[p.ticker] = {nombre:p.nombre, isin:p.isin, figi:p.figi, esETF:p.esETF, pais:p.pais, codigoPais:p.codigoPais};
    });
    FISCAL_ORDERS = Array.isArray(d.orders) ? d.orders : [];
    FISCAL_ACTIVITIES = d.activities;
    // Precios históricos — mismo endpoint que ya usa Mi Broker, reutilizado
    // aquí para poder valorar posiciones de años anteriores.
    bkFetchPriceHistory(FISCAL_ORDERS, FISCAL_ACTIVITIES).then(function(priceHistory){
      FISCAL_PRICE_HISTORY = priceHistory;
      fiscalActualizarSelectorAnios();
    });

    // NUEVO (09/07/2026): la liquidez (Bloque 1: Cuentas) se evalúa por
    // SEPARADO del Bloque 2 (Valores) — así lo confirma la Agencia
    // Tributaria: son 3 bloques independientes, cada uno con su propio
    // umbral de 50.000€, no se suman entre sí. Antes esto se ignoraba del
    // todo, lo cual podía hacerte pensar que no había obligación cuando sí
    // la había (bloque de cuentas superado aunque valores no llegue a 50k).
    // Mismo aviso que con otros campos: el nombre "cash" en balances no está
    // 100% verificado en producción todavía — revisa el log si sale a 0
    // teniendo liquidez real.
    // Bug real encontrado en el log: balances trae varias divisas (EUR, USD,
    // CAD, AUD) y se sumaban directamente sin convertir — 92.083€ se sumaban
    // como si fueran 92.083$. balancesToUSD ya convierte bien; para
    // Fiscalidad (que trabaja en €) se pasa después a euros con el tipo real.
    var cashUSD = balancesToUSD(d.balances);
    var cashEUR = cashUSD / EURUSD_RATE;
    FISCAL_CASH_EUR = cashEUR;

    // KPIs
    var totalValorEUR = posiciones.reduce(function(s,p){return s+p.valorEUR;},0);
    var totalAdquisEUR = posiciones.reduce(function(s,p){return s+p.adquisEUR;},0);
    var totalPnlEUR = posiciones.reduce(function(s,p){return s+p.pnlEUR;},0);
    var supera50kValores = totalValorEUR >= 50000;
    var supera50kCuentas = cashEUR >= 50000;

    document.getElementById('fiscal-kpis').innerHTML = [
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--ac)"><div class="bc-l">Valor Valores/Acciones (€)</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--ac)">'+totalValorEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid var(--dim)"><div class="bc-l">Liquidez / Cuentas (€)</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">'+cashEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid '+(totalPnlEUR>=0?'var(--up)':'var(--dn)')+'"><div class="bc-l">P&L Valores (€)</div><div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+(totalPnlEUR>=0?'var(--up)':'var(--dn)')+'">'+(totalPnlEUR>=0?'+':'')+totalPnlEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</div></div>',
      '<div class="bc" style="padding:10px 12px;border-top:3px solid '+((supera50kValores||supera50kCuentas)?'var(--dn)':'var(--up)')+'"><div class="bc-l">Obligación 720</div>'
        +'<div style="font-size:11px;font-weight:700;color:'+(supera50kValores?'var(--dn)':'var(--up)')+'">Bloque Valores: '+(supera50kValores?'SÍ':'NO')+'</div>'
        +'<div style="font-size:11px;font-weight:700;color:'+(supera50kCuentas?'var(--dn)':'var(--up)')+'">Bloque Cuentas: '+(supera50kCuentas?'SÍ':'NO')+'</div>'
        +'<div style="font-size:10px;color:var(--dim);margin-top:2px">Cada bloque es independiente (AEAT) · Cambio: 1€ = '+EURUSD_RATE.toFixed(4)+'$</div></div>',
    ].join('');

    fiscalRenderTabla(posiciones);
  }

  function fiscalRenderTabla(posiciones){
    var tbody = document.getElementById('fiscal-tbody');
    tbody.innerHTML = posiciones.map(function(p){
      var pnlColor = p.pnlEUR >= 0 ? 'var(--up)' : 'var(--dn)';
      return '<tr style="border-bottom:1px solid var(--b1)">'
        +'<td style="padding:6px 8px;font-weight:700;color:var(--ac)">'+p.ticker+(p.esETF?' <span style="font-size:9px;color:var(--hi);background:var(--bg3);border:1px solid var(--b2);border-radius:3px;padding:0 4px">ETF</span>':'')+'</td>'
        +'<td style="padding:6px 8px;font-size:11px">'+(p.nombre||'—')+'</td>'
        +'<td style="padding:6px 8px;font-size:11px;font-family:monospace">'+(p.isin||(p.figi?('FIGI: '+p.figi):'<span style="color:var(--dim)">—</span>'))+'</td>'
        +'<td style="padding:6px 8px;color:var(--dim);font-size:11px">'+p.pais+'</td>'
        +'<td style="padding:6px 8px;text-align:right">'+p.units.toFixed(4)+'</td>'
        +'<td style="padding:6px 8px;text-align:right">'+p.price.toFixed(4)+'€</td>'
        +'<td style="padding:6px 8px;text-align:right;font-weight:600">'+p.valorEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
        +'<td style="padding:6px 8px;text-align:right">'+p.adquisEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
        +'<td style="padding:6px 8px;text-align:right;color:'+pnlColor+';font-weight:600">'+(p.pnlEUR>=0?'+':'')+p.pnlEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
        +'<td style="padding:6px 8px;font-size:11px;color:var(--dim)">'+p.broker+'</td>'
        +'</tr>';
    }).join('');

    var totalValorEUR = posiciones.reduce(function(s,p){return s+p.valorEUR;},0);
    var totalAdquisEUR = posiciones.reduce(function(s,p){return s+p.adquisEUR;},0);
    var totalPnlEUR = posiciones.reduce(function(s,p){return s+p.pnlEUR;},0);
    document.getElementById('fiscal-tfoot').innerHTML =
      '<tr style="border-top:2px solid var(--b1);font-weight:700;background:var(--bg2)">'
      +'<td colspan="6" style="padding:8px">TOTAL</td>'
      +'<td style="padding:8px;text-align:right">'+totalValorEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
      +'<td style="padding:8px;text-align:right">'+totalAdquisEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
      +'<td style="padding:8px;text-align:right;color:'+(totalPnlEUR>=0?'var(--up)':'var(--dn)')+'">'+(totalPnlEUR>=0?'+':'')+totalPnlEUR.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})+'€</td>'
      +'<td></td></tr>';
  }

  // NUEVO (14/08/2026): reconstruye qué tenías EXACTAMENTE en una fecha
  // pasada (ej. 31/12/2024) — fusiona orders+activities en trades (mismo
  // patrón que Renta/Historial), aplica solo los que caen en o antes de
  // esa fecha, y valora con el precio real de mercado más cercano
  // (relleno hacia atrás si no hay dato exacto ese día).
  function reconstruirPosicionesEnFecha(fechaObjetivo){
    var listaActivities = Array.isArray(FISCAL_ACTIVITIES) ? FISCAL_ACTIVITIES : (FISCAL_ACTIVITIES && FISCAL_ACTIVITIES.data) || [];
    var trades = [];
    var clavesYaVistas = {};
    // NUEVO (26/08/2026) — BUG REAL ENCONTRADO: esta función es un cálculo
    // aparte del de Renta (calcularRentaFIFO) y no tenía ninguno de los
    // arreglos de hoy — confirmado con datos reales que esto dejaba
    // posiciones "fantasma" en el Modelo 720 (ej. PLTR con 60 acciones
    // fantasma cuando la posición real está en 0, y "SQ" con 50 acciones
    // fantasma porque las vendiste ya renombradas como "XYZ"). Se portan
    // aquí los dos mismos arreglos: alias de ticker y orden por el
    // timestamp completo, no solo por el día.
    var TICKER_ALIASES_720 = { 'SQ': 'XYZ' };
    function normalizarTicker720(tk){ return TICKER_ALIASES_720[tk] || tk; }
    listaActivities.forEach(function(a){
      var tipo = (a.type||'').toUpperCase();
      if(tipo !== 'BUY' && tipo !== 'SELL') return;
      var tk = normalizarTicker720((a.symbol && a.symbol.symbol) || (a.symbol && a.symbol.raw_symbol) || '');
      var fechaHoraFull = a.trade_date || a.settlement_date || '';
      var fecha = fechaHoraFull.slice(0,10);
      var qty = Math.abs(parseFloat(a.units || 0));
      var price = parseFloat(a.price || 0);
      if(!tk || !fecha || !qty) return;
      var clave = tk+'|'+tipo+'|'+fecha+'|'+qty.toFixed(4);
      clavesYaVistas[clave] = true;
      trades.push({fecha:fecha, fechaHora: fechaHoraFull || fecha, ticker:tk, action:tipo, qty:qty, price:price});
    });
    (FISCAL_ORDERS||[]).forEach(function(o){
      var tk = normalizarTicker720((o.universal_symbol && o.universal_symbol.symbol) || o.symbol || '');
      var qty = parseFloat(o.total_quantity || o.filled_quantity || 0);
      var price = parseFloat(o.execution_price || o.limit_price || 0);
      var action = (o.action || '').toUpperCase();
      var fechaHoraFull = o.time_executed || o.time_placed || '';
      var fecha = fechaHoraFull.slice(0,10);
      if(!tk || !qty || !fecha) return;
      var claveBase = (action.indexOf('BUY')>=0 ? 'BUY' : action.indexOf('SELL')>=0 ? 'SELL' : action);
      var clave = tk+'|'+claveBase+'|'+fecha+'|'+qty.toFixed(4);
      if(clavesYaVistas[clave]) return;
      trades.push({fecha:fecha, fechaHora: fechaHoraFull || fecha, ticker:tk, action:claveBase, qty:qty, price:price});
    });
    trades.sort(function(a,b){ return a.fechaHora.localeCompare(b.fechaHora); });

    var lotes = {}; // tk -> {units, costoTotal} — coste medio, no FIFO (aproximación razonable para el 720, que no exige FIFO)
    trades.forEach(function(t){
      if(t.fecha > fechaObjetivo) return;
      if(!lotes[t.ticker]) lotes[t.ticker] = {units:0, costoTotal:0};
      if(t.action === 'BUY'){
        lotes[t.ticker].units += t.qty;
        lotes[t.ticker].costoTotal += t.qty * t.price;
      } else if(t.action === 'SELL'){
        // NUEVO (26/08/2026) — BUG REAL ENCONTRADO: antes esto topaba en 0
        // con Math.max(0, ...) — si una venta era en realidad un corto sin
        // etiquetar (mismo caso confirmado en Renta: BMNRn, RGTIn, NFLX,
        // DKNG, AEO...), la posición se quedaba clavada en 0 en vez de
        // poder bajar, y la recompra que cerraba el corto se sumaba
        // encima de ese 0 falso — dejando una posición "fantasma" en el
        // Modelo 720 que en realidad ya estaba cerrada del todo. Ahora se
        // deja bajar de 0 sin topar, para que una recompra posterior
        // vuelva a dejarlo exactamente en el neto real.
        var avgCost = lotes[t.ticker].units>0 ? lotes[t.ticker].costoTotal/lotes[t.ticker].units : 0;
        lotes[t.ticker].units = lotes[t.ticker].units - t.qty;
        lotes[t.ticker].costoTotal = avgCost * lotes[t.ticker].units;
      }
    });

    var resultado = [];
    Object.keys(lotes).forEach(function(tk){
      var lote = lotes[tk];
      if(lote.units <= 0.0001) return;
      var hist = FISCAL_PRICE_HISTORY[tk] || {};
      var fechasDisponibles = Object.keys(hist).filter(function(f){ return f <= fechaObjetivo; }).sort();
      var price = fechasDisponibles.length ? hist[fechasDisponibles[fechasDisponibles.length-1]] : (lote.costoTotal/lote.units);
      var avgCost = lote.units>0 ? lote.costoTotal/lote.units : price;
      var meta = FISCAL_TICKER_META[tk] || {nombre:tk, isin:'', figi:'', esETF:false, pais:'Estados Unidos', codigoPais:'US'};
      var valorEUR = (price * lote.units) / EURUSD_RATE;
      var adquisEUR = (avgCost * lote.units) / EURUSD_RATE;
      resultado.push({
        ticker: tk, nombre: meta.nombre, isin: meta.isin, figi: meta.figi, esETF: meta.esETF,
        units: lote.units, price: price, avgCost: avgCost,
        valorEUR: valorEUR, adquisEUR: adquisEUR, pnlEUR: valorEUR - adquisEUR,
        broker: 'IBKR', pais: meta.pais, codigoPais: meta.codigoPais
      });
    });
    return resultado;
  }

  // Rellena el desplegable con los años reales que hay en el historial
  // (además de "Posiciones actuales") — antes esto era un valor fijo
  // "31 de diciembre" que no hacía nada de verdad.
  function fiscalActualizarSelectorAnios(){
    var selectEl = document.getElementById('fiscal-fecha');
    if(!selectEl) return;
    var anios = {};
    var listaActivities = Array.isArray(FISCAL_ACTIVITIES) ? FISCAL_ACTIVITIES : (FISCAL_ACTIVITIES && FISCAL_ACTIVITIES.data) || [];
    listaActivities.forEach(function(a){
      var f = (a.trade_date || a.settlement_date || '').slice(0,4);
      if(f) anios[f] = true;
    });
    (FISCAL_ORDERS||[]).forEach(function(o){
      var f = (o.time_executed || o.time_placed || '').slice(0,4);
      if(f) anios[f] = true;
    });
    var anioActual = new Date().getFullYear().toString();
    var listaAnios = Object.keys(anios).filter(function(a){ return a < anioActual; }).sort().reverse();
    var valorPrevio = selectEl.value;
    selectEl.innerHTML = '<option value="actual">Posiciones actuales</option>'
      + listaAnios.map(function(a){ return '<option value="'+a+'">31 de diciembre '+a+' (Modelo 720 '+a+')</option>'; }).join('');
    if(Array.from(selectEl.options).some(function(o){ return o.value===valorPrevio; })) selectEl.value = valorPrevio;
  }

  function fiscalFiltrarFecha(){
    if(!FISCAL_DATA) return;
    var sel = document.getElementById('fiscal-fecha').value;
    FISCAL_MODO_FECHA = sel;
    if(sel === 'actual'){
      fiscalRenderTabla(FISCAL_DATA);
      document.getElementById('fiscal-fecha-label').textContent = '';
    } else {
      // sel es un año, ej. "2024" — reconstruir posiciones a 31/12 de ese año
      var fechaObjetivo = sel + '-12-31';
      var historico = reconstruirPosicionesEnFecha(fechaObjetivo);
      fiscalRenderTabla(historico);
      document.getElementById('fiscal-fecha-label').textContent =
        '(' + historico.length + ' posiciones reconstruidas a 31/12/' + sel + ' — precio de mercado real, aviso: coste medio, no FIFO exacto)';
    }
  }

  // Devuelve los datos que corresponden al modo activo del selector — para
  // que Exportar CSV y Generar .720 usen SIEMPRE lo mismo que se ve en
  // pantalla, sea "actual" o un año pasado.
  function fiscalDatosActivos(){
    if(FISCAL_MODO_FECHA === 'actual' || !FISCAL_MODO_FECHA) return FISCAL_DATA;
    return reconstruirPosicionesEnFecha(FISCAL_MODO_FECHA + '-12-31');
  }

  function fiscalExportarCSV(){
    var datos = fiscalDatosActivos();
    if(!datos || datos.length === 0){ alert('No hay datos para exportar.'); return; }
    var rows = [['Ticker','Entidad','ISIN','Código País','Unidades','Precio (€)','Valor Total (€)','Valor Adquisición (€)','P&L (€)','Broker']];
    datos.forEach(function(p){
      rows.push([p.ticker, p.nombre||'', p.isin||'', p.codigoPais||'', p.units.toFixed(4), p.price.toFixed(4),
        p.valorEUR.toFixed(2), p.adquisEUR.toFixed(2), p.pnlEUR.toFixed(2), p.broker]);
    });
    rows.push([]);
    rows.push(['Bloque Cuentas (liquidez)','','','','','','','','','']);
    rows.push(['Liquidez total (€)', FISCAL_CASH_EUR!=null ? FISCAL_CASH_EUR.toFixed(2) : '0.00']);
    var csv = rows.map(function(r){ return r.join(';'); }).join('\n');
    var blob = new Blob(['\ufeff'+csv], {type:'text/csv;charset=utf-8;'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = 'modelo720_lacomunidad.csv'; a.click();
    URL.revokeObjectURL(url);
  }

  // ══════════════════════════════════════════════════════════════════════
  //  GENERADOR FICHERO .720 (09/07/2026) — formato oficial exacto de la
  //  Orden HAP/72/2013 (Anexo: Diseños físicos y lógicos), verificado campo
  //  a campo contra el documento oficial de la AEAT antes de escribir esto.
  //
  //  IMPORTANTE — lo que SÍ y lo que NO incluye:
  //  ✓ Registro tipo 1 (declarante) y tipo 2 (uno por posición, Bloque V)
  //  ✓ Sin ISIN se usa Clave de identificación=2 y "Z"+país (lo permite el
  //    propio formulario de la AEAT para valores extranjeros sin ISIN)
  //  ✗ NO incluye el Bloque C (liquidez/cuentas) — para eso Hacienda exige
  //    IBAN/BIC/código de cuenta que SnapTrade no proporciona en absoluto;
  //    inventar esos datos sería peor que no incluirlos. Prepararlo aparte
  //    con el extracto real del broker.
  //  ✗ FECHA DE INCORPORACIÓN (obligatoria por posición) se deja en blanco
  //    — SnapTrade no da fecha de adquisición por lote (tax_lots venía
  //    vacío en tu cuenta real). Hay que rellenarla a mano por cada valor.
  //  Esto es un BORRADOR MUY AVANZADO, no un fichero listo para subir sin
  //  revisión — exactamente como hablamos.
  // ══════════════════════════════════════════════════════════════════════
  function pad720(str, len, side, fillChar){
    str = (str==null?'':String(str)).toUpperCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g,'') // sin tildes
      .replace(/[^A-Z0-9 .]/g, ''); // sin caracteres especiales
    if(str.length > len) str = str.slice(0, len);
    var fill = fillChar.repeat(len - str.length);
    return side === 'left' ? fill + str : str + fill;
  }
  function padNum720(num, totalLen, decimals){
    // Campo numérico sin coma: parte entera + parte decimal, todo a ceros por la izquierda
    var n = Math.abs(parseFloat(num) || 0);
    var factor = Math.pow(10, decimals);
    var enteroDecimal = Math.round(n * factor).toString();
    return enteroDecimal.padStart(totalLen, '0');
  }
  function nifPad720(nif){
    nif = (nif||'').toUpperCase().replace(/[^A-Z0-9]/g,'');
    if(nif.length >= 9) return nif.slice(-9);
    // Rellenar a la izquierda del número (no de la letra final) con ceros
    var letra = nif.slice(-1);
    var numero = nif.slice(0,-1);
    return numero.padStart(8,'0') + letra;
  }

  function fiscalGenerar720(){
    var datos = fiscalDatosActivos();
    if(!datos || datos.length === 0){ alert('Primero carga las posiciones del broker.'); return; }
    var nif = document.getElementById('fiscal-nif').value.trim();
    var nombre = document.getElementById('fiscal-nombre').value.trim();
    if(!nif || !nombre){
      alert('Rellena tu NIF y Apellidos/Nombre arriba antes de generar el fichero — son obligatorios en el registro de declarante.');
      return;
    }
    var nifP = nifPad720(nif);
    // NUEVO (14/08/2026): si hay un año histórico seleccionado en el
    // desplegable, el ejercicio del fichero es ESE año, no siempre
    // "año actual - 1" a ciegas — para poder generar el 720 de años
    // anteriores de verdad, no solo el más reciente.
    var anio = (FISCAL_MODO_FECHA && FISCAL_MODO_FECHA !== 'actual')
      ? FISCAL_MODO_FECHA
      : (new Date().getFullYear() - 1).toString();

    var registros2 = [];
    datos.forEach(function(p){
      var claveId = p.isin ? '1' : '2';
      var identifValores = p.isin ? pad720(p.isin, 12, 'left', ' ')
                                   : pad720('Z'+(p.codigoPais||'US'), 12, 'left', ' ');
      var r2 =
        '2' +                                          // 1: tipo registro
        '720' +                                         // 2-4: modelo
        anio +                                           // 5-8: ejercicio
        nifP +                                           // 9-17: NIF declarante
        nifP +                                           // 18-26: NIF declarado (= declarante)
        pad720('', 9, 'left', ' ') +                     // 27-35: NIF representante legal (blanco)
        pad720(nombre, 40, 'left', ' ') +                // 36-75: apellidos y nombre declarado
        '1' +                                            // 76: clave condición declarante = Titular
        pad720('', 25, 'left', ' ') +                    // 77-101: tipo titularidad (solo si clave=8)
        (p.esETF ? 'I' : 'V') +                            // 102: I=ETF/IIC, V=acción individual (CONFIRMADO: distinto tratamiento AEAT)
        (p.esETF ? ' ' : '1') +                            // 103: subclave — EN BLANCO si es "I" (obligatorio así), "1" si es "V"
        pad720('', 25, 'left', ' ') +                     // 104-128: tipo derecho real inmueble (n/a)
        pad720(p.codigoPais||'US', 2, 'left', ' ') +      // 129-130: código país
        claveId +                                          // 131: clave identificación (1=ISIN, 2=sin ISIN)
        identifValores +                                   // 132-143: ISIN o "Z"+país
        ' ' +                                              // 144: clave identif. cuenta (n/a para V)
        pad720('', 11, 'left', ' ') +                      // 145-155: código BIC (n/a para V)
        pad720('', 34, 'left', ' ') +                      // 156-189: código cuenta (n/a para V)
        pad720(p.nombre||p.ticker, 41, 'left', ' ') +      // 190-230: identificación de la entidad
        pad720('', 20, 'left', ' ') +                      // 231-250: NIF entidad país residencia (sin verificar)
        pad720('', 164, 'left', ' ') +                     // 251-414: domicilio entidad (sin verificar, revisar a mano)
        (FISCAL_FECHAS[p.ticker] || pad720('', 8, 'left', '0')) + // 415-422: fecha incorporación (real, desde el historial de órdenes — o en blanco si el ticker no tiene compra registrada, p.ej. si la posición ya existía antes de conectar el broker)
        'A' +                                              // 423: origen del bien = primera declaración
        pad720('', 8, 'left', '0') +                       // 424-431: fecha extinción (n/a)
        (p.pnlEUR<0?'N':' ') +                             // 432: signo valoración 1
        padNum720(p.valorEUR, 14, 2) +                     // 433-446: valoración 1 (valor a 31/12)
        ' ' +                                              // 447: signo valoración 2
        padNum720(0, 14, 2) +                              // 448-461: valoración 2 (n/a, primera declaración)
        'A' +                                              // 462: representación valores = anotaciones en cuenta
        padNum720(p.units, 12, 2) +                        // 463-474: número de valores
        ' ' +                                              // 475: clave tipo inmueble (n/a)
        padNum720(100, 5, 2) +                             // 476-480: % participación = 100%
        pad720('', 20, 'left', ' ');                       // 481-500: blancos
      registros2.push(r2);
    });

    var numRegistros = registros2.length;
    var sumaVal1 = datos.reduce(function(s,p){ return s + Math.abs(p.valorEUR); }, 0);

    var r1 =
      '1' +
      '720' +
      anio +
      nifP +
      pad720(nombre, 40, 'left', ' ') +
      'T' +
      pad720('', 9, 'left', '0') +          // teléfono (vacío)
      pad720(nombre, 40, 'left', ' ') +     // persona con quien relacionarse
      pad720('720'+String(numRegistros).padStart(10,'0'), 13, 'left', '0') +
      '  ' +                                 // declaración complementaria/sustitutiva (n/a)
      pad720('', 13, 'left', '0') +          // número declaración anterior (n/a)
      String(numRegistros).padStart(9,'0') +
      (sumaVal1<0?'N':' ') + padNum720(sumaVal1, 17, 2) +
      ' ' + padNum720(0, 17, 2) +
      pad720('', 320, 'left', ' ');

    var contenido = [r1].concat(registros2).join('\r\n');

    // Comprobación de longitud — cada línea DEBE tener exactamente 500 caracteres
    var lineasMalas = [r1].concat(registros2).map(function(l,i){ return {i:i, len:l.length}; })
      .filter(function(x){ return x.len !== 500; });
    if(lineasMalas.length > 0){
      console.error('Longitud incorrecta en líneas:', lineasMalas);
      alert('Aviso: alguna línea del fichero no tiene exactamente 500 caracteres (revisa la consola). No lo subas a la AEAT sin comprobarlo primero.');
    }

    var blob = new Blob([contenido], {type:'text/plain;charset=iso-8859-1;'});
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url; a.download = nifP + '.720'; a.click();
    URL.revokeObjectURL(url);

    var sinFecha = datos.filter(function(p){ return !FISCAL_FECHAS[p.ticker]; }).map(function(p){ return p.ticker; });
    var etfs = datos.filter(function(p){ return p.esETF; }).map(function(p){ return p.ticker; });
    alert('Fichero .720 generado — IMPORTANTE:\n\n'
      + '• NO incluye el Bloque C (liquidez) — no tenemos IBAN/BIC del broker.\n'
      + '• FECHA DE INCORPORACIÓN: rellenada con la fecha real de la primera compra ejecutada de cada valor (sacada del historial de órdenes).'
      + (sinFecha.length ? (' Sin esa fecha (revisar a mano): ' + sinFecha.join(', ') + '.') : ' Todas las posiciones tenían fecha.') + '\n'
      + '• El domicilio de cada entidad va en blanco.\n'
      + '• Donde no había ISIN se usó la clave "sin ISIN" (Z+país), que el propio formulario de la AEAT permite.\n'
      + (etfs.length ? ('• Detectados como ETF (clave "I", subclave en blanco): ' + etfs.join(', ') + '. Verifica que esté bien detectado.\n') : '• No se detectó ningún ETF — todo se trató como acción individual (clave "V"). Si tienes algún ETF, revisa que se haya detectado bien.\n')
      + '\nEsto es un borrador muy avanzado, no un fichero listo para presentar sin revisión.');
  }
  </script>

  <!-- CARTERA -->
  <div id="tab-cartera" class="tc">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:10px">
      <div>
        <div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">💼 Mi Cartera</div>
        <div style="font-size:10px;color:var(--dim);margin-top:2px">Seguimiento de posiciones · Métricas profesionales · Datos guardados localmente</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="pb active" id="ct-btn-overview"   onclick="ctTab('overview',this)">Overview</button>
        <button class="pb"        id="ct-btn-add"        onclick="ctTab('add',this)">+ Añadir transacción</button>
        <button class="pb"        id="ct-btn-positions"  onclick="ctTab('positions',this)">Posiciones</button>
        <button class="pb"        id="ct-btn-riesgo"     onclick="ctTab('riesgo',this)">Riesgo & Métricas</button>
        <button class="pb" onclick="clearCartera()" style="color:var(--dn);border-color:rgba(244,63,94,.3)">🗑 Limpiar</button>
      </div>
    </div>

    <!-- Portfolio selector (up to 4) -->
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:16px" id="ct-portfolio-tabs"></div>

    <!-- OVERVIEW -->
    <div id="ct-overview">
      <!-- KPI strip -->
      <div id="ct-kpis" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-bottom:14px"></div>
      <!-- Period returns row -->
      <div id="ct-periods" style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:14px"></div>
      <!-- Main chart: perf + drawdown combined + donut -->
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-bottom:10px">
        <div class="cw" style="padding:10px">
          <div class="ct" style="margin-bottom:4px;display:flex;justify-content:space-between">
            <span>📈 Rentabilidad cartera vs S&P 500</span>
            <span style="font-size:10px;color:var(--dim)"><span style="color:#38bdf8">■</span> Cartera &nbsp;<span style="color:#64748b">┅</span> S&P500</span>
          </div>
          <div style="position:relative;height:180px"><canvas id="ct-perf-canvas" height="180"></canvas></div>
          <div class="ct" style="margin-top:8px;margin-bottom:4px;display:flex;justify-content:space-between">
            <span>📉 Drawdown histórico</span>
            <span id="ct-dd-label" style="font-size:10px;color:var(--dn)"></span>
          </div>
          <div style="position:relative;height:100px"><canvas id="ct-dd-canvas" height="100"></canvas></div>
        </div>
        <div class="cw" style="padding:10px">
          <div class="ct" style="margin-bottom:6px">🧩 Distribución por ticker</div>
          <div style="position:relative;height:180px"><canvas id="ct-donut-canvas" height="180"></canvas></div>
          <div id="ct-donut-legend" style="margin-top:8px;font-size:10px;color:var(--dim)"></div>
        </div>
      </div>
      <!-- Sector breakdown -->
      <div class="cw" style="padding:10px;margin-bottom:10px">
        <div class="ct" style="margin-bottom:8px">🏢 Distribución por sector</div>
        <div id="ct-sector-bars" style="display:flex;flex-direction:column;gap:6px"></div>
      </div>
      <!-- Monthly returns table -->
      <div class="cw" style="padding:10px;margin-bottom:10px">
        <div class="ct" style="margin-bottom:8px">📅 Rentabilidad mensual — estilo Amibroker</div>
        <div id="ct-monthly-table" class="tw" style="overflow-x:auto"></div>
      </div>
      <!-- Correlation vs SPX -->
      <div class="cw" style="padding:10px;margin-bottom:10px">
        <div class="ct" style="margin-bottom:8px">🔗 Correlación y Beta vs S&P 500</div>
        <div id="ct-corr-content"></div>
      </div>
    </div>

    <!-- ADD TRANSACTION -->
    <div id="ct-add" style="display:none">
      <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:18px 20px;margin-bottom:14px">
        <div style="display:flex;gap:10px;margin-bottom:14px">
          <button class="pb active" id="ct-side-buy" onclick="ctSetSide('buy',this)" style="padding:6px 18px;font-size:12px">📈 Compra</button>
          <button class="pb" id="ct-side-sell" onclick="ctSetSide('sell',this)" style="padding:6px 18px;font-size:12px">📉 Venta</button>
          <input type="hidden" id="ct-side" value="buy">
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Ticker</label>
            <input id="ct-ticker" class="si" style="width:90px;text-transform:uppercase" placeholder="NVDA" maxlength="8">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Precio $ (opcional)</label>
            <input id="ct-price" class="si" type="number" style="width:110px" placeholder="500.00" step="any" oninput="ctCalcQty()">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Capital invertido $</label>
            <input id="ct-capital" class="si" type="number" style="width:120px" placeholder="5000" step="any" oninput="ctCalcQty()">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Acciones (auto)</label>
            <input id="ct-qty" class="si" type="number" style="width:90px" placeholder="10" min="0.001" step="any" oninput="ctCalcCapital()">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Stop loss $</label>
            <input id="ct-stop" class="si" type="number" style="width:100px" placeholder="450.00" step="any">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Fecha</label>
            <input id="ct-date" class="si" type="date" style="width:140px">
          </div>
          <button class="pb active" style="height:36px;padding:0 18px;font-size:12px;background:rgba(56,189,248,.1);border-color:var(--ac);color:var(--ac)" onclick="ctAddTx()">+ Registrar</button>
        </div>
        <div id="ct-add-msg" style="font-size:11px;color:var(--dim);margin-top:8px"></div>
        <div id="ct-add-err" style="font-size:11px;color:var(--dn);margin-top:6px;display:none"></div>
      </div>
      <!-- Transaction history -->
      <div class="tw"><table><thead><tr>
        <th style="text-align:left">Ticker</th><th>Tipo</th><th>Acciones</th>
        <th>Precio</th><th>Stop</th><th>Riesgo/acc</th><th>Riesgo total</th><th>Fecha</th><th></th>
      </tr></thead><tbody id="ct-tx-body"></tbody></table></div>
    </div>

    <!-- POSITIONS -->
    <div id="ct-positions" style="display:none">
      <div class="tw"><table><thead><tr>
        <th style="text-align:left">Ticker</th>
        <th>Acciones</th><th>P. Medio</th><th>P. Actual*</th>
        <th>Valor</th><th>P&L $</th><th>P&L %</th><th>% Cartera</th><th>Stop</th><th>Riesgo abierto</th>
      </tr></thead><tbody id="ct-pos-body"></tbody></table></div>
      <div style="font-size:10px;color:var(--dim)">* Precio actual tomado de D.stockPerf si disponible, si no se usa precio de entrada.</div>
    </div>

    <!-- RIESGO & METRICAS -->
    <div id="ct-riesgo" style="display:none">
      <div id="ct-metrics-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:16px"></div>
      <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:14px 16px;margin-bottom:12px">
        <div class="ct" style="margin-bottom:8px">Distribución de retornos diarios</div>
        <div style="position:relative;height:160px"><canvas id="ct-ret-canvas" height="160"></canvas></div>
      </div>
    </div>
  </div>

  <!-- ═══ COMUNIDAD ═══ -->
  <div id="tab-comunidad" class="tc">
    <!-- No auth overlay needed - already logged in globally -->

    <!-- Main comunidad content (shown when logged in) -->
    <div id="com-content" style="display:none">
      <!-- User header + racha -->
      <div style="display:grid;grid-template-columns:1fr auto;gap:12px;align-items:center;margin-bottom:16px">
        <div>
          <div id="com-welcome" style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:var(--hi)"></div>
          <div id="com-racha-txt" style="font-size:11px;color:var(--dim);margin-top:2px"></div>
        </div>
        <div style="text-align:center;background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:10px 16px;cursor:pointer" onclick="comLogout()">
          <div style="font-size:22px" id="com-streak-emoji">🔥</div>
          <div id="com-streak-num" style="font-family:Syne,sans-serif;font-size:20px;font-weight:800;color:var(--warn)">0</div>
          <div style="font-size:9px;color:var(--dim)">días seguidos</div>
        </div>
      </div>

      <!-- Sub-tabs -->
      <div style="display:flex;gap:6px;margin-bottom:14px;overflow-x:auto;padding-bottom:2px">
        <button class="pb active" id="com-btn-ideas" onclick="comTab('ideas',this)">💡 Ideas</button>
        <button class="pb" id="com-btn-ranking" onclick="comTab('ranking',this)">🏆 Ranking</button>
      </div>

      <!-- IDEAS -->
      <div id="com-ideas">
        <!-- Post new idea -->
        <div class="cw" style="padding:14px 16px;margin-bottom:14px">
          <div class="ct" style="margin-bottom:10px">💡 Comparte tu idea de inversión</div>
          <div style="display:flex;gap:8px;margin-bottom:8px;flex-wrap:wrap">
            <input id="com-idea-ticker" class="si" placeholder="Ticker (ej: NVDA)" style="width:120px;text-transform:uppercase" maxlength="8">
            <select id="com-idea-dir" class="si" style="width:110px">
              <option value="long">📈 Alcista</option>
              <option value="short">📉 Bajista</option>
            </select>
          </div>
          <textarea id="com-idea-text" class="si" placeholder="¿Por qué te gusta? Máximo 200 caracteres..." maxlength="200"
            style="width:100%;height:72px;resize:vertical;padding:8px 10px;font-family:inherit;font-size:11px;line-height:1.6"></textarea>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px">
            <div id="com-idea-chars" style="font-size:10px;color:var(--dim)">0/200</div>
            <button class="pb active" style="padding:6px 18px;font-size:12px" onclick="comPostIdea()">Publicar idea →</button>
          </div>
          <div id="com-idea-err" style="font-size:11px;color:var(--dn);margin-top:6px;min-height:14px"></div>
        </div>
        <!-- Sort bar -->
        <div style="display:flex;gap:6px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
          <span style="font-size:10px;color:var(--dim)">Ordenar:</span>
          <button class="pb active" id="sort-stars-btn" onclick="comSortIdeas('stars',this)" style="font-size:10px;padding:4px 10px">⭐ Mejor valoradas</button>
          <button class="pb" id="sort-date-btn" onclick="comSortIdeas('date',this)" style="font-size:10px;padding:4px 10px">🕐 Más recientes</button>
          <button class="pb" id="sort-votes-btn" onclick="comSortIdeas('votes',this)" style="font-size:10px;padding:4px 10px">🗳️ Más votadas</button>
        </div>
        <!-- Ideas list -->
        <div id="com-ideas-list"></div>
        <div id="com-ideas-loading" style="text-align:center;padding:20px;color:var(--dim);font-size:11px">Cargando ideas...</div>
      </div>

      <!-- RANKING -->
      <div id="com-ranking" style="display:none">
        <div class="cw" style="padding:14px 16px;margin-bottom:12px">
          <div class="ct" style="margin-bottom:12px">🏆 Ranking de racha — días consecutivos</div>
          <div id="com-ranking-list"></div>
          <div id="com-ranking-loading" style="text-align:center;padding:16px;color:var(--dim);font-size:11px">Cargando ranking...</div>
        </div>
        <div class="cw" style="padding:14px 16px">
          <div class="ct" style="margin-bottom:12px">📅 Ranking de constancia — días totales</div>
          <div id="com-ranking-total-list"></div>
        </div>
      </div>
    </div>
  </div>

  <!-- ═══ DIARIO DE TRADING ═══ -->
  <div id="tab-diario" class="tc">

    <!-- Metrics row -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-bottom:10px">
      <div class="bc"><div class="bc-l">Resultado del mes</div><div class="bc-v" id="dj-month-total">—</div></div>
      <div class="bc"><div class="bc-l">Operaciones</div><div class="bc-v" id="dj-month-trades">—</div></div>
      <div class="bc"><div class="bc-l">% Aciertos</div><div class="bc-v" id="dj-month-winrate">—</div></div>
      <div class="bc"><div class="bc-l">R medio</div><div class="bc-v" id="dj-month-avgr">—</div></div>
      <div class="bc"><div class="bc-l">Mejor / Peor día</div><div class="bc-v" id="dj-month-bestworst" style="font-size:13px">—</div></div>
    </div>

    <!-- Stats row 2: Net P&L / Profit Factor / Avg Win-Loss -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:16px">
      <div class="bc">
        <div class="bc-l">Net P&amp;L (mes)</div>
        <div class="bc-v" id="dj-stat-netpl">—</div>
      </div>
      <div class="bc">
        <div class="bc-l">Profit Factor</div>
        <div class="bc-v" id="dj-stat-pf">—</div>
        <div style="font-size:9px;color:var(--dim);margin-top:2px">Ganancias / Pérdidas</div>
      </div>
      <div class="bc">
        <div class="bc-l">Avg Win / Loss</div>
        <div class="bc-v" id="dj-stat-avgwl" style="font-size:14px">—</div>
        <div id="dj-stat-avgwl-bar" style="display:flex;height:5px;border-radius:3px;overflow:hidden;margin-top:6px;background:var(--bg3)"></div>
      </div>
    </div>

    <!-- P&L cumulative chart -->
    <div class="cw" style="margin-bottom:14px">
      <div class="ct">📈 P&amp;L acumulado</div>
      <div style="position:relative;height:180px"><canvas id="dj-pl-canvas" height="180"></canvas></div>
    </div>

    <!-- Calendar -->
    <div class="cw" style="margin-bottom:14px">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;flex-wrap:wrap;gap:8px">
        <div style="display:flex;align-items:center;gap:8px">
          <button class="pb" onclick="djChangeMonth(-1)">←</button>
          <span class="ct" id="dj-month-label" style="margin-bottom:0;min-width:140px;text-align:center"></span>
          <button class="pb" onclick="djChangeMonth(1)">→</button>
        </div>
        <button class="stk-btn" onclick="djOpenForm()">+ Nueva operación</button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px;margin-bottom:4px">
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Dom</div>
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Lun</div>
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Mar</div>
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Mié</div>
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Jue</div>
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Vie</div>
        <div style="font-size:10px;color:var(--dim);text-align:center;padding:2px 0">Sáb</div>
      </div>
      <div id="dj-cal-grid" style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px"></div>
      <div style="display:flex;gap:14px;margin-top:12px;font-size:10px;color:var(--dim)">
        <div style="display:flex;align-items:center;gap:5px"><div style="width:10px;height:10px;border-radius:3px;background:rgba(5,196,107,.5)"></div>Día positivo</div>
        <div style="display:flex;align-items:center;gap:5px"><div style="width:10px;height:10px;border-radius:3px;background:rgba(255,63,91,.5)"></div>Día negativo</div>
      </div>
    </div>

    <!-- Day detail -->
    <div class="cw" id="dj-day-detail" style="display:none;margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span class="ct" id="dj-detail-date" style="margin-bottom:0"></span>
        <span style="font-family:Syne,sans-serif;font-weight:800;font-size:17px" id="dj-detail-pl"></span>
      </div>
      <div id="dj-detail-trades" style="display:flex;flex-direction:column;gap:6px"></div>
    </div>

    <!-- OPERACIONES VIVAS -->
    <div class="cw" style="margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
        <span class="ct" style="margin-bottom:0">📡 Operaciones vivas</span>
        <button class="pb" onclick="djRenderLivePositions()" style="font-size:10px;padding:3px 8px">↻ Refrescar</button>
      </div>
      <div id="dj-live-positions"></div>
      <div id="dj-live-cards" style="display:none;flex-direction:column;gap:8px"></div>
    </div>

    <!-- REGISTRO COMPLETO -->
    <div class="cw" style="margin-bottom:14px">
      <div class="ct">📋 Registro de operaciones</div>
      <div id="dj-trades-table-wrap" class="tw"><table>
        <thead><tr>
          <th style="text-align:left">Ticker</th>
          <th>Setup</th>
          <th>Entrada</th>
          <th>Salida</th>
          <th>Días</th>
          <th>P. Entrada</th>
          <th>Stop</th>
          <th>P. Salida</th>
          <th>Acciones</th>
          <th>% B/P</th>
          <th>$ B/P</th>
          <th>R</th>
          <th></th>
        </tr></thead>
        <tbody id="dj-trades-table"></tbody>
      </table></div>
      <div id="dj-trades-cards" style="display:none;flex-direction:column;gap:8px"></div>
    </div>

    <!-- New trade form (hidden by default) -->
    <div class="cw" id="dj-form" style="display:none;margin-bottom:14px">
      <div class="ct" id="dj-form-title">Nueva operación</div>
      <input type="hidden" id="dj-edit-id" value="">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin-bottom:10px">
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Ticker</div><input class="si" id="dj-ticker" style="width:100%;text-transform:uppercase" oninput="this.value=this.value.toUpperCase()"></div>
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Setup</div><input class="si" id="dj-setup" style="width:100%" placeholder="Ej: HTF, Breakout..."></div>
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Fecha entrada</div><input class="si" type="date" id="dj-fecha-entrada" style="width:100%"></div>
        <div id="dj-fecha-salida-wrap"><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Fecha salida</div><input class="si" type="date" id="dj-fecha-salida" style="width:100%"></div>
      </div>
      <div style="margin-bottom:10px">
        <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:12px;color:var(--tx)">
          <input type="checkbox" id="dj-abierta" onchange="djToggleAbierta()" style="width:16px;height:16px;cursor:pointer">
          Operación todavía abierta (sin vender)
        </label>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px;margin-bottom:10px">
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Precio entrada</div><input class="si" type="number" step="0.01" id="dj-precio-entrada" style="width:100%"></div>
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Stop inicial</div><input class="si" type="number" step="0.01" id="dj-stop" style="width:100%"></div>
        <div id="dj-precio-salida-wrap"><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Precio salida</div><input class="si" type="number" step="0.01" id="dj-precio-salida" style="width:100%"></div>
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Nº acciones</div><input class="si" type="number" step="1" id="dj-acciones" style="width:100%"></div>
        <div><div style="font-size:10px;color:var(--dim);margin-bottom:4px">Comisiones ($)</div><input class="si" type="number" step="0.01" id="dj-comisiones" style="width:100%" value="0"></div>
      </div>
      <div style="margin-bottom:10px">
        <div style="font-size:10px;color:var(--dim);margin-bottom:4px">Notas</div>
        <input class="si" id="dj-notas" style="width:100%" maxlength="200" placeholder="Comentario sobre la operación / lección aprendida...">
      </div>
      <div id="dj-preview" style="font-size:12px;color:var(--dim);margin-bottom:10px;padding:8px 10px;background:var(--bg3);border-radius:6px"></div>
      <div style="display:flex;gap:8px">
        <button class="stk-btn" onclick="djSaveTrade()" id="dj-save-btn">Guardar operación</button>
        <button class="pb" onclick="djCloseForm()">Cancelar</button>
      </div>
      <div id="dj-form-msg" style="font-size:11px;margin-top:8px"></div>
    </div>

  </div>

  <!-- ═══ CHART GRID (Finviz-style) ═══ -->
  <div id="cg-overlay" style="display:none;position:fixed;inset:0;background:var(--bg);z-index:900;overflow-y:scroll;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:var(--b2) transparent">
    <div style="display:flex;align-items:center;gap:10px;padding:10px 14px;background:var(--bg2);border-bottom:1px solid var(--b1);position:sticky;top:0;z-index:1">
      <span style="font-family:Syne,sans-serif;font-weight:800;font-size:14px;color:var(--hi)" id="cg-title">📊 Gráficos</span>
      <span style="font-size:11px;color:var(--dim)" id="cg-count"></span>
      <div style="margin-left:auto;display:flex;gap:6px;align-items:center">
        <span style="font-size:10px;color:var(--dim)">Columnas:</span>
        <button class="pb" id="cg-col-1" onclick="cgSetCols(1,this)">1</button>
        <button class="pb active" id="cg-col-2" onclick="cgSetCols(2,this)">2</button>
        <button class="pb" id="cg-col-3" onclick="cgSetCols(3,this)">3</button>
        <button class="pb" id="cg-col-4" onclick="cgSetCols(4,this)">4</button>
        <button class="pb" style="color:var(--dn)" onclick="cgClose()">✕ Cerrar</button>
      </div>
    </div>
    <div id="cg-grid" style="display:grid;grid-template-columns:1fr 1fr;gap:10px;padding:12px 32px 40px 12px"></div>
  </div>

  <p class="foot">La Comunidad · Victor Galán · __TS__ · No es asesoramiento financiero</p>
</div>

<!-- Mobile bottom navigation -->
<nav id="mobile-nav" role="navigation" aria-label="Navegación móvil">
  <button onclick="sw('briefing',document.getElementById('tab-briefing-btn'));mobileNav(this)" class="active">
    <span>📋</span><span>Resumen</span>
  </button>
  <button onclick="sw('sectors',document.getElementById('tab-sectors-btn') || this);mobileNav(this)">
    <span>📊</span><span>Sectores</span>
  </button>
  <button onclick="sw('breadth',document.getElementById('tab-breadth-btn'));mobileNav(this)">
    <span>📡</span><span>Amplitud</span>
  </button>
  <button onclick="sw('stocks',document.getElementById('tab-stocks-btn'));mobileNav(this)">
    <span>🔍</span><span>Acción</span>
  </button>
  <button onclick="sw('cartera',document.getElementById('tab-cartera-btn'));mobileNav(this)">
    <span>💼</span><span>Cartera</span>
  </button>
</nav>

<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
<script>
// ── SUPABASE CONFIG (must be first) ──────────────────────────────────────────
var SUPABASE_URL='https://othghdtplmlkrqwfcjzk.supabase.co';
var SUPABASE_KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im90aGdoZHRwbG1sa3Jxd2ZjanprIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODA2Njk1NzEsImV4cCI6MjA5NjI0NTU3MX0.ziQgteX2SxAHUd0XfUiwoSdRjyZUMbwdgw-FIaARuYs';
var SB=null;
function sbClient(){
  if(SB) return SB;
  if(!window.supabase){console.warn('Supabase SDK not loaded');return null;}
  SB=window.supabase.createClient(SUPABASE_URL,SUPABASE_KEY);
  return SB;
}
// NUEVO (08/07/2026): el backend ahora exige el token de sesión de Supabase
// en las llamadas a /snaptrade/* para verificar que quien pide los datos de
// un user_id es de verdad esa persona logueada (antes no se comprobaba nada).
async function getAuthToken(){
  var sb=sbClient(); if(!sb) return null;
  try{
    var {data}=await sb.auth.getSession();
    return (data&&data.session) ? data.session.access_token : null;
  }catch(e){ return null; }
}
// Initialise immediately so it is ready before anything else runs
// login listeners attached in main DOMContentLoaded below
// ─────────────────────────────────────────────────────────────────────────────
const D=__DATA__;

// ── Estado ──────────────────────────────────────────────────────────────────
let PD={s:'1D',i:'1D'}, SS={}, MP='1D', MST=[], cblt=false, carteraLoaded=false, fundamentalesLoaded=false;
let FUND_FILTERS={};

// ── Init ────────────────────────────────────────────────────────────────────
// ── GLOBAL AUTH ──────────────────────────────────────────────────────────────
var GLOBAL_USER = null;
var GLOBAL_PROFILE = null;

function globalLogin(){
  var btn=document.getElementById('login-btn');
  var errEl=document.getElementById('login-err');
  var email=(document.getElementById('login-email').value||'').trim();
  var pass=document.getElementById('login-pass').value;

  if(!email||!pass){
    errEl.textContent='Introduce email y contraseña.';
    return;
  }

  // Disable button immediately
  btn.textContent='Verificando...';
  btn.disabled=true;
  btn.style.opacity='0.7';
  errEl.textContent='';

  // Check Supabase is loaded
  var sb=null;
  try{ sb=sbClient(); } catch(ex){ errEl.textContent='Error SDK: '+ex.message; btn.textContent='Entrar →'; btn.disabled=false; btn.style.opacity='1'; return; }
  if(!sb){ errEl.textContent='Error: Supabase no cargado. Refresca la página.'; btn.textContent='Entrar →'; btn.disabled=false; btn.style.opacity='1'; return; }

  // Login via promise (not async/await to avoid any transpiler issues)
  sb.auth.signInWithPassword({email:email, password:pass}).then(function(result){
    if(result.error){
      var msg=result.error.message;
      if(msg.indexOf('Invalid login')>=0) msg='Email o contraseña incorrectos.';
      else if(msg.indexOf('not confirmed')>=0) msg='Confirma tu email primero.';
      errEl.textContent=msg;
      btn.textContent='Entrar al dashboard →';
      btn.disabled=false;
      btn.style.opacity='1';
      return;
    }
    GLOBAL_USER=result.data.user;
    try{ localStorage.setItem('vgc_last_login',String(Date.now())); }catch(ex){}
    btn.textContent='✓ Correcto';
    btn.style.background='#10b981';
    // Load profile then show dashboard
    globalLoadProfile().then(function(){
      return globalUpdateStreak();
    }).then(function(){
      document.getElementById('login-screen').classList.add('hidden');
      initDashboard();
    }).catch(function(ex){
      // Profile failed but still let them in
      document.getElementById('login-screen').classList.add('hidden');
      initDashboard();
    });
  }).catch(function(ex){
    errEl.textContent='Error de red: '+ex.message;
    btn.textContent='Entrar al dashboard →';
    btn.disabled=false;
    btn.style.opacity='1';
  });
}



function globalLoadProfile(){
  var sb=sbClient();
  if(!sb||!GLOBAL_USER) return Promise.resolve();
  return sb.from('profiles').select('*').eq('id',GLOBAL_USER.id).single().then(function(r){
    if(r.data){
      GLOBAL_PROFILE=r.data;
    } else {
      var nombre=GLOBAL_USER.user_metadata&&GLOBAL_USER.user_metadata.nombre
        ? GLOBAL_USER.user_metadata.nombre
        : GLOBAL_USER.email.split('@')[0];
      GLOBAL_PROFILE={id:GLOBAL_USER.id,email:GLOBAL_USER.email,nombre:nombre,racha:0,dias_total:0};
      return sb.from('profiles').upsert(GLOBAL_PROFILE);
    }
  }).catch(function(){ GLOBAL_PROFILE={nombre:GLOBAL_USER.email.split('@')[0],racha:0,dias_total:0}; });
}


function globalUpdateStreak(){
  var sb=sbClient();
  if(!sb||!GLOBAL_USER||!GLOBAL_PROFILE) return Promise.resolve();
  var today=new Date().toISOString().slice(0,10);
  var ultima=GLOBAL_PROFILE.ultima_visita;
  if(ultima===today) return Promise.resolve();
  var yesterday=new Date(Date.now()-864e5).toISOString().slice(0,10);
  var racha=(ultima===yesterday)?(GLOBAL_PROFILE.racha||0)+1:1;
  var total=(GLOBAL_PROFILE.dias_total||0)+1;
  GLOBAL_PROFILE.racha=racha;
  GLOBAL_PROFILE.dias_total=total;
  GLOBAL_PROFILE.ultima_visita=today;
  return sb.from('profiles').update({racha:racha,dias_total:total,ultima_visita:today}).eq('id',GLOBAL_USER.id).then(function(){}).catch(function(){});
}


function globalLogout(){
  var sb=sbClient();
  if(sb) sb.auth.signOut().catch(function(){});
  try{ localStorage.removeItem('vgc_last_login'); }catch(e){}
  GLOBAL_USER=null; GLOBAL_PROFILE=null;
  document.getElementById('login-screen').classList.remove('hidden');
}

function checkGlobalSession(){
  var sb=null;
  try{ sb=sbClient(); }catch(ex){}
  if(!sb){
    // No Supabase - show login screen
    document.getElementById('login-screen').classList.remove('hidden');
    return;
  }
  sb.auth.getSession().then(function(result){
    var session=result.data&&result.data.session;
    if(!session||!session.user){
      document.getElementById('login-screen').classList.remove('hidden');
      return;
    }
    // Check 30-day expiry
    var lastLogin=0;
    try{ lastLogin=parseInt(localStorage.getItem('vgc_last_login')||'0'); }catch(ex){}
    if(Date.now()-lastLogin > 30*24*60*60*1000){
      sb.auth.signOut();
      try{ localStorage.removeItem('vgc_last_login'); }catch(ex){}
      document.getElementById('login-screen').classList.remove('hidden');
      document.getElementById('login-err').textContent='Sesión caducada (30 días). Vuelve a entrar.';
      return;
    }
    GLOBAL_USER=session.user;
    globalLoadProfile().then(function(){
      return globalUpdateStreak();
    }).then(function(){
      document.getElementById('login-screen').classList.add('hidden');
      initDashboard();
    }).catch(function(){
      document.getElementById('login-screen').classList.add('hidden');
      initDashboard();
    });
  }).catch(function(){
    document.getElementById('login-screen').classList.remove('hidden');
  });
}

function saveAlias(){
  var val=(document.getElementById('alias-input').value||'').trim();
  var errEl=document.getElementById('alias-err');
  if(!val||val.length<2){ errEl.textContent='Mínimo 2 caracteres.'; return; }
  var btn=document.getElementById('alias-btn');
  btn.textContent='Guardando...'; btn.disabled=true;
  var sb=sbClient();
  sb.from('profiles').update({nombre:val}).eq('id',GLOBAL_USER.id).then(function(){
    GLOBAL_PROFILE.nombre=val;
    document.getElementById('alias-screen').classList.remove('show');
    finishDashboard();
  }).catch(function(){
    errEl.textContent='Error guardando. Inténtalo de nuevo.';
    btn.textContent='Guardar y entrar →'; btn.disabled=false;
  });
}

function initDashboard(){
  // Check if user needs to set an alias (nombre is email-derived or missing)
  var nombre=GLOBAL_PROFILE&&GLOBAL_PROFILE.nombre;
  var needsAlias=!nombre||nombre===''||nombre.indexOf('@')>=0||nombre.indexOf('.')>=0;
  if(needsAlias){
    // Show alias popup first
    document.getElementById('alias-screen').classList.add('show');
    setTimeout(function(){
      var inp=document.getElementById('alias-input');
      if(inp) inp.focus();
    },300);
    return;
  }
  finishDashboard();
}

function finishDashboard(){
  // Show user name + logout in topbar
  if(GLOBAL_PROFILE){
    var nombre=GLOBAL_PROFILE.nombre||'Alumno';
    var racha=GLOBAL_PROFILE.racha||0;
    var emoji=racha>=30?'🏆':racha>=14?'⚡':racha>=7?'🔥':racha>=3?'✨':'🌱';
    var userEl=document.getElementById('topbar-user');
    if(userEl) userEl.innerHTML=
      '<span style="font-size:11px;color:var(--ac)">'+emoji+' '+nombre+'</span>'
      +'<span style="font-size:10px;color:var(--dim);margin-left:4px">'+racha+'d</span>'
      +'<button onclick="globalLogout()" style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:2px 8px;cursor:pointer;font-size:9px;margin-left:6px">Salir</button>';
  }
  mainInit();
}

document.addEventListener('DOMContentLoaded',function(){
  // 1. Init Supabase
  sbClient();

  // 2. Attach login form events
  var loginBtn=document.getElementById('login-btn');
  var emailInput=document.getElementById('login-email');
  var passInput=document.getElementById('login-pass');

  if(loginBtn) loginBtn.addEventListener('click',function(){
    globalLogin();
  });
  if(emailInput) emailInput.addEventListener('keydown',function(e){
    if(e.key==='Enter'||e.key==='Tab'){
      e.preventDefault();
      if(passInput) passInput.focus();
    }
  });
  if(passInput) passInput.addEventListener('keydown',function(e){
    if(e.key==='Enter') globalLogin();
  });

  // 3. Check existing session
  try{ checkGlobalSession(); }
  catch(e){ console.error('checkGlobalSession error:',e); }
});

// The real dashboard init (called after login)
function mainInit(){
  const su=D.breadthSummary;
  document.getElementById('ts-l').textContent=D.ts;
  if(typeof updateFavCount==='function') updateFavCount();
  const sc=su.spy_chg>=0;
  const spyP=document.getElementById('spy-p');
  spyP.className='pill '+(sc?'pup':'pdn');
  var spyChg=su.gspc_chg!==null&&su.gspc_chg!==undefined?su.gspc_chg:su.spy_chg;
  spyP.textContent='S&P '+(spyChg>=0?'+':'')+spyChg+'%';
  const vx=su.vix,vw=typeof vx==='number'&&vx>20; // vix real de I:VIX via EODHD
  const vixP=document.getElementById('vix-p');
  vixP.className='pill '+(vw?'pwarn':'pup');
  vixP.textContent='VIX '+vx;
  // Nasdaq 100 — buscar en benchmarks (no esta en breadthSummary)
  const ndxBm=(D.benchmarks||[]).find(function(b){return b.name==='Nasdaq 100'||b.ticker==='I:NDX'||b.ticker==='QQQ';});
  const ndxP=document.getElementById('ndx-p');
  if(ndxBm && ndxP){
    const ndxChg=ndxBm['1D']||0;
    ndxP.className='pill '+(ndxChg>=0?'pup':'pdn');
    ndxP.textContent='Nasdaq '+(ndxChg>=0?'+':'')+ndxChg+'%';
  }
  renderBstrip();
  renderHM('s'); renderHM('i');
  renderTbl('tb-s',D.sectors,true,'sector');
  renderTbl('tb-i',D.industries,true,'industry');
  highlightTop30Industrias(3); // resaltado inicial por 1D, antes de que el usuario ordene nada
  renderBmTbl();
  document.getElementById('ind-cnt').textContent=D.industries.length+' industrias';
  // Quick tickers
  // Quick tickers filled from stockPerf keys for discovery
  const qTks=['NVDA','AAPL','MSFT','AMZN','META','TSLA','GOOGL','JPM','NVDA','JPM'];
  qTks.slice(0,8).forEach(t=>{
    const b=document.createElement('button');
    b.className='pb';b.textContent=t;
    b.onclick=()=>{document.getElementById('stk-ticker').value=t;loadStock();};
    document.getElementById('quick-tickers').appendChild(b);
  });
  // Add hint
  const hint=document.createElement('span');
  hint.style.cssText='font-size:9px;color:var(--dim);align-self:center';
  hint.textContent='(escribe cualquier ticker del universo)';
  document.getElementById('quick-tickers').appendChild(hint);
};

// ── Breadth strip ────────────────────────────────────────────────────────────
function renderBstrip(){
  const s=D.breadthSummary;
  const bm=D.benchmarks||[];
  const findBm=tk=>bm.find(b=>b.ticker===tk);
  const ndx=findBm('I:NDX')||findBm('QQQ'), ibex=findBm('EWP')||findBm('I:IBEX'), btc=findBm('X:BTCUSD');
  const spx=findBm('I:SPX')||findBm('SPY');
  const items=[
    {l:'S&P 500 (^GSPC)',
      v:spx?spx.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):(s.gspc_price?s.gspc_price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'$'+s.spy_price),
      c:spx?spx['1D']:(s.gspc_chg!==null&&s.gspc_chg!==undefined?s.gspc_chg:s.spy_chg)},
    {l:'VIX',v:s.vix,c:s.vix_chg},
    {l:'Nasdaq 100',v:ndx?ndx.price.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—',c:ndx?ndx['1D']:null},
    {l:'IBEX 35',v:ibex?ibex.price.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2}):'—',c:ibex?ibex['1D']:null},
    {l:'Bitcoin',v:btc?('$'+btc.price.toLocaleString('en-US',{maximumFractionDigits:0})):'—',c:btc?btc['1D']:null},
  ];
  document.getElementById('bstrip').innerHTML=items.map(it=>{
    const cc=it.c!==null&&it.c!==undefined?`<div class="bc-c ${it.c>=0?'up':'dn'}">${it.c>=0?'+':''}${it.c}%</div>`:'';
    const uu=it.u?`<div style="font-size:9px;color:var(--dim)">${it.u}</div>`:'';
    return `<div class="bc"><div class="bc-l">${it.l}</div><div class="bc-v">${it.v}</div>${cc}${uu}</div>`;
  }).join('');
}

// ── Heatmap ──────────────────────────────────────────────────────────────────
function renderHM(type){
  const arr=[...(type==='s'?D.sectors:D.industries)];
  const p=PD[type]; const el=document.getElementById('hm-'+type);
  // Sort heatmap tiles by current period (best performers first)
  arr.sort((a,b)=>(b[p]||0)-(a[p]||0));
  const mx=Math.max(...arr.map(r=>Math.abs(r[p]||0)),0.01);
  el.innerHTML=arr.map(r=>{
    const pct=r[p]||0,t=Math.min(Math.abs(pct)/mx,1);
    // Background: pastel at low intensity, saturated at high
    // Background: rango compacto .5-.92 — siempre visible, nunca demasiado pálido
    const bg=pct>=0?`rgba(5,196,107,${.5+t*.42})`:`rgba(255,63,91,${.5+t*.42})`;
    // Texto nombre/ticker: siempre blanco con sombra
    // Texto porcentaje: oscuro sobre fondos claros (t<0.6), blanco sobre fondos intensos (t>0.6)
    const pctColor=t<0.6
      ? (pct>=0?'#0a5c35':'#8b0000')   // verde oscuro / rojo oscuro sobre fondo claro
      : '#ffffff';                       // blanco puro sobre fondo intenso
    const tp=type==='s'?'sector':'industry';
    const nm=r.name.replace(/'/g,"\'");
    return `<div class="hmc" style="background:${bg}" title="${r.name}: ${pct>0?'+':''}${pct}% (${p})"
      onclick="openDD('${tp}','${nm}')">
      <div class="hmc-n">${r.name}</div>
      <div class="hmc-t">${r.ticker}</div>
      <div class="hmc-p" style="color:${pctColor}">${pct>0?'+':''}${pct}%</div>
      <div class="hmc-pr">$${r.price}</div>
    </div>`;
  }).join('');
}
// ── Table ────────────────────────────────────────────────────────────────────
function fmt(v,pct=true){
  if(v===null||v===undefined)return'<span class="neu">—</span>';
  const c=v>0.1?'up':v<-0.1?'dn':'neu';
  return `<span class="${c}">${v>0?'+':''}${v}${pct?'%':''}</span>`;
}
function gauge(lo,hi,p){
  const pct=Math.max(0,Math.min(100,((p-lo)/(hi-lo))*100));
  return `<div class="gw"><span style="font-size:9px;color:var(--dim)">${Math.round(pct)}%</span>
    <div class="gt"><div class="gf" style="width:${pct}%"></div><div class="gd" style="left:${pct}%"></div></div></div>`;
}
function sparkSVG(pts,upColor='#10b981',dnColor='#f43f5e'){
  if(!pts||pts.length<2)return'—';
  const w=60,h=20;
  const mn=Math.min(...pts),mx=Math.max(...pts);
  const rng=mx-mn||1;
  const xs=pts.map((_,i)=>i/(pts.length-1)*w);
  const ys=pts.map(p=>h-(p-mn)/rng*(h-2)-1);
  const d='M'+xs.map((x,i)=>`${x},${ys[i]}`).join('L');
  const clr=pts[pts.length-1]>=pts[0]?upColor:dnColor;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><path d="${d}" fill="none" stroke="${clr}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function abvBadge(flag,lbl){
  if(flag===null||flag===undefined)return'<span class="neu">—</span>';
  return `<span class="badge ${flag?'b-up':'b-dn'}">${flag?'▲':'▼'} ${lbl}</span>`;
}

function renderTbl(id,arr,clickable,type){
  document.getElementById(id).innerHTML=arr.map((r,i)=>{
    const dc=r.distHi>=-5?'up':r.distHi>=-15?'neu':'dn';
    const ck=clickable?`onclick="openDD('${type}','${r.name.replace(/'/g,"\\'")}')"`:'' ;
    return `<tr ${ck}>
      <td><span class="rk">${i+1}</span><span class="nm">${r.name}</span></td>
      <td>${r.ticker}</td><td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td>
      <td>${fmt(r['3M'])}</td><td>${fmt(r['6M']??null)}</td><td>${fmt(r['1Y'])}</td>
      <td>${gauge(r['52wLow'],r['52wHigh'],r.price)}</td>
      <td><span class="${dc}">${r.distHi}%</span></td>
    </tr>`;
  }).join('');
}

// ── BENCHMARK TABLE with click-to-chart ──────────────────────────────────────
let _bmChart=null;
function renderBmTbl(){
  document.getElementById('tb-b').innerHTML=D.benchmarks.map((r,i)=>{
    const dc=r.distHi>=-5?'up':r.distHi>=-15?'neu':'dn';
    return `<tr onclick="openBMChartByIdx(${i})" style="cursor:pointer">
      <td><span class="rk">${i+1}</span><span class="nm">${r.name}</span></td>
      <td>${r.ticker}</td><td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td>
      <td>${fmt(r['3M'])}</td><td>${fmt(r['6M']??null)}</td><td>${fmt(r['1Y'])}</td>
      <td>${gauge(r['52wLow'],r['52wHigh'],r.price)}</td>
      <td><span class="${dc}">${r.distHi}%</span></td>
    </tr>`;
  }).join('');
}
function openBMChartByIdx(i){
  const r=D.benchmarks[i];
  if(!r)return;
  // Build synthetic OHLC from priceHistory if no ohlc available
  const ohlc=(r.ohlc&&r.ohlc.length)?r.ohlc:(r.priceHistory||[]).map((c,j,a)=>({t:(r.priceDates||[])[j]||'',o:c,h:c,l:c,c:c}));
  openCandleModal(r.name+' ('+r.ticker+')', 'ETF/proxy · 90 días', ohlc);
}
function openCandleModal(title, meta, ohlc, ticker){
  document.getElementById('bm-name').textContent=title;
  document.getElementById('bm-ov').classList.add('open');
  document.body.style.overflow='hidden';
  var tk=ticker||(title.match(/\(([^)]+)\)/)||[])[1]||title.split(' ')[0];
  var container=document.getElementById('bm-tv-container');
  // NUEVO (03/09/2026): tickers tipo "RGTIn", "BMNRn", "CARn" (CFD, no son
  // símbolos normales de bolsa — confirmado hoy mismo en Renta/720) no los
  // reconoce TradingView, y su propio widget muestra "gráfico no existe"
  // dentro del iframe — no es texto nuestro, no lo podíamos interceptar.
  // En vez de intentarlo a ciegas y que se vea mal, si el ticker no tiene
  // pinta de símbolo normal (mayúsculas, como mucho un sufijo de clase de
  // acción tipo BRK-B), no se intenta TradingView — se usa el gráfico
  // propio con los datos OHLC que ya tenemos, si los hay.
  var pareceTickerNormal = /^[A-Z]{1,6}([.\-][A-Z]{1,2})?$/.test(tk||'');
  if(pareceTickerNormal && container){
    document.getElementById('bm-meta').textContent=meta+' · Powered by TradingView';
    container.style.display='';
    document.getElementById('bm-fallback-chart').style.display='none';
    container.innerHTML='';
    var script=document.createElement('script');
    script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async=true;
    script.innerHTML=JSON.stringify({
      "autosize":true,"symbol":tk,"interval":"D",
      "timezone":"Europe/Madrid","theme":"light","style":"1","locale":"es",
      "backgroundColor":"rgba(255,255,255,1)","gridColor":"rgba(242,243,245,1)",
      "hide_top_toolbar":false,"hide_legend":false,"save_image":false,
      "support_host":"https://www.tradingview.com",
      "studies":["STD;MA"]
    });
    container.appendChild(script);
  } else {
    // Símbolo sospechoso (CFD u otro no estándar) — gráfico propio con lo
    // que tengamos, sin intentar TradingView.
    document.getElementById('bm-meta').textContent=meta+' · Símbolo no estándar — gráfico propio';
    if(container) container.style.display='none';
    var fb=document.getElementById('bm-fallback-chart');
    if(fb){
      fb.style.display='';
      if(window.bmFallbackChart) window.bmFallbackChart.destroy();
      if(ohlc && ohlc.length){
        var ctx=fb.getContext('2d');
        window.bmFallbackChart=new Chart(ctx,{type:'line',data:{
          labels:ohlc.map(function(b){return b.t;}),
          datasets:[{data:ohlc.map(function(b){return b.c;}),borderColor:'rgb(56,189,248)',borderWidth:1.5,pointRadius:0,fill:true,backgroundColor:'rgba(56,189,248,0.06)',tension:0.2}]
        },options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},
          scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8}},y:{ticks:{color:'#3a4860',font:{size:9}}}}}});
      } else {
        fb.getContext('2d').clearRect(0,0,fb.width,fb.height);
      }
    }
  }
}
function closeBMModal(e){
  if(e&&e.target!==document.getElementById('bm-ov'))return;
  document.getElementById('bm-ov').classList.remove('open');
  document.body.style.overflow='';
}
function openETFCandle(name,ticker,ohlc,chg){
  // ohlc may be empty for sector ETFs not in fetch_perf ohlc — build from priceHistory
  let data=ohlc;
  if(!data||!data.length){
    // try sector/industry data
    const bm=D.benchmarks.find(b=>b.ticker===ticker);
    if(bm&&bm.ohlc&&bm.ohlc.length){data=bm.ohlc;}
    else if(bm&&bm.priceHistory&&bm.priceHistory.length){
      data=bm.priceHistory.map((c,i)=>({t:(bm.priceDates||[])[i]||'',o:c,h:c,l:c,c:c}));
    }
  }
  openCandleModal(name+' ('+ticker+')', chg+' · ETF proxy', data&&data.length?data:[], ticker);
}

// ── DRILL DOWN ───────────────────────────────────────────────────────────────
function cgOpenFromModal(){
  var tickers=MST.map(function(r){return r.ticker;});
  var title=document.getElementById('m-title').textContent||'Holdings';
  closeModal();
  document.getElementById('cg-title').textContent='📊 '+title;
  document.getElementById('cg-count').textContent=tickers.length+' tickers';
  cgBuild(tickers);
  document.getElementById('cg-overlay').style.display='block';
  document.body.style.overflow='hidden';
}

function openDD(type,name){
  const stocks=(type==='sector'?D.sectorStocks:D.industryStocks)[name]||[];
  const etf=type==='sector'
    ?(D.sectors.find(s=>s.name===name)||{}).ticker
    :(D.industryMeta[name]||(D.industries.find(s=>s.name===name)||{}).ticker);
  document.getElementById('m-title').textContent=name;
  document.getElementById('m-sub').textContent=type==='sector'?'Sector S&P 500':'Industria / Tema';
  document.getElementById('m-etf').textContent='ETF: '+(etf||'—');
  MST=stocks; renderModTbl();
  document.getElementById('ov').classList.add('open');
  document.body.style.overflow='hidden';
}
function renderModTbl(){
  const sorted=[...MST].sort((a,b)=>(b[MP]||0)-(a[MP]||0));
  const tb=document.getElementById('m-tbody');
  if(!sorted.length){
    tb.innerHTML=`<tr><td colspan="14" style="text-align:center;padding:22px;color:var(--dim)">Sin datos. Ejecuta el script para descargar constituyentes.</td></tr>`;
    return;
  }
  tb.innerHTML=sorted.map((r,i)=>{
    const vr=r.volRel;
    const vrStr=vr?`<span class="${vr>1.5?'up':vr<0.5?'dn':'neu'}">${vr}x</span>`:'—';
    return `<tr style="cursor:pointer" onclick="openStockCandle('${r.ticker}')"
      title="Click para ver gráfico de velas de ${r.ticker}">
      <td onclick="event.stopPropagation()">${favStarBtn(r.ticker)}</td>
      <td><span class="rk">${i+1}</span><span class="nm">${r.ticker}</span></td>
      <td style="color:var(--dim)">${r.ticker}</td>
      <td>$${r.price||'—'}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td><td>${fmt(r['3M'])}</td><td>${fmt(r['1Y'])}</td>
      <td>${abvBadge(r.abv20,'MA20')}</td>
      <td>${abvBadge(r.abv50,'MA50')}</td>
      <td>${abvBadge(r.abv200,'MA200')}</td>
      <td>${vrStr}</td>
      <td>${gauge(r['52wLow']||0,r['52wHigh']||100,r.price)}</td>
      <td class="spark-cell">${sparkSVG(r.spark||[])}</td>
    </tr>`;
  }).join('');
}
function setMP(p,btn){
  MP=p;
  document.querySelectorAll('#m-pbs .pb').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active'); renderModTbl();
}
function setMPdirect(p){
  // Sort by period p without needing the button element
  MP=p;
  document.querySelectorAll('#m-pbs .pb').forEach(b=>{
    b.classList.toggle('active', b.textContent.trim()===p);
  });
  renderModTbl();
}
let _modalSort={col:-1,asc:-1};
function sortModal(col){
  const colFns=[
    r=>r.ticker,null,r=>r.price||0,
    r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r['3M']||0,r=>r['1Y']||0,
    r=>r.abv20?1:0,r=>r.abv50?1:0,r=>r.abv200?1:0,r=>r.volRel||0
  ];
  if(_modalSort.col===col) _modalSort.asc*=-1; else {_modalSort.col=col;_modalSort.asc=-1;}
  const fn=colFns[col];
  if(!fn)return;
  MST=[...MST].sort((a,b)=>(fn(b)-fn(a))*_modalSort.asc);
  renderModTbl();
}
function openStockCandle(tk){
  const sp=D.stockPerf||{};
  const r=sp[tk];
  if(!r||!r.ohlc||!r.ohlc.length){
    // fallback: open Panel Accion
    document.getElementById('stk-ticker').value=tk;
    closeModal();
    sw('stocks',document.getElementById('tab-stocks-btn'));
    loadStock();
    return;
  }
  const chg=r['1D']!==undefined?(r['1D']>0?'+':'')+r['1D']+'%':'';
  openCandleModal(tk+' — $'+r.price, chg+' · RS por encima de MA20/50/200', r.ohlc, tk);
}
function closeModal(e){
  if(e&&e.target!==document.getElementById('ov'))return;
  document.getElementById('ov').classList.remove('open');
  document.body.style.overflow='';
}

// ── BREADTH TAB ───────────────────────────────────────────────────────────────
function renderBreadthTab(){
  if(cblt)return; cblt=true;
  const su=D.breadthSummary;

  // Score ring
  const score=su.score||0;
  const circ=238.76;
  const offset=circ-(circ*score/100);
  document.getElementById('score-arc').setAttribute('stroke-dashoffset',offset);
  document.getElementById('score-num').textContent=score;
  document.getElementById('score-label').textContent=su.score_label||'—';
  document.getElementById('score-desc').textContent=
    `Basado en: % sobre MA50/200, nuevos máximos/mínimos, VIX, High Yield, McClellan`;
  document.getElementById('adv-badge').textContent=`▲ ${su.advancing} avanzando`;
  document.getElementById('dec-badge').textContent=`▼ ${su.declining} retrocediendo`;
  document.getElementById('unch-badge').textContent=`= ${su.unchanged} sin cambio`;
  document.getElementById('nh-badge').textContent=`★ ${su.new_highs} máximos (ver)`;
  document.getElementById('nl-badge').textContent=`✗ ${su.new_lows} mínimos (ver)`;

  // Amplitude metrics
  document.getElementById('amp-grid').innerHTML=[
    {l:'% sobre MA50',   v:su.pct_abv50+'%',  sub:`${Math.round(su.total_sample*su.pct_abv50/100)} de ${su.total_sample} acciones`},
    {l:'% sobre MA200',  v:su.pct_abv200+'%', sub:`${Math.round(su.total_sample*su.pct_abv200/100)} de ${su.total_sample} acciones`},
    {l:'Nuevos Máx 52W', v:su.new_highs,       sub:'click en badge para ver tickers'},
    {l:'Nuevos Mín 52W', v:su.new_lows,        sub:'click en badge para ver tickers'},
    {l:'AD Ratio',       v:su.advancing&&su.declining?Math.round(su.advancing/Math.max(su.declining,1)*10)/10+'x':'—', sub:`${su.advancing}▲ vs ${su.declining}▼ (${su.total_sample} acciones)`},
    {l:'Score Mercado',  v:su.score+'/100',     sub:su.score_label},
  ].map(it=>`<div class="amp-card"><div class="amp-l">${it.l}</div><div class="amp-v">${it.v}</div><div class="amp-sub">${it.sub}</div></div>`).join('');

  // NYSE + Risk-ON/Risk-OFF — 6 tarjetas (3+3), sin huecos
  const btcBm=(D.benchmarks||[]).find(b=>b.ticker==='X:BTCUSD');
  document.getElementById('risk-g').innerHTML=[
    {l:'NYSE Composite',v:su.nyse_price!=='N/A'?'$'+su.nyse_price:'—',c:su.nyse_chg>=0?'up':'dn',a:su.nyse_chg>=0?'▲':'▼',v2:(su.nyse_chg>=0?'+':'')+su.nyse_chg+'%',n:'Indice de mercado amplio NYSE'},
    {l:'High Yield (HYG)',c:su.hyg_chg>=0?'up':'dn',a:su.hyg_chg>=0?'▲':'▼',v2:(su.hyg_chg>=0?'+':'')+su.hyg_chg+'%',n:'Risk-ON si sube'},
    {l:'Tesoros 20Y (TLT)',c:su.tlt_chg>=0?'up':'dn',a:su.tlt_chg>=0?'▲':'▼',v2:(su.tlt_chg>=0?'+':'')+su.tlt_chg+'%',n:'Refugio si sube'},
    {l:'Dólar USD (UUP)',c:su.uup_chg>=0?'dn':'up',a:su.uup_chg>=0?'▲':'▼',v2:(su.uup_chg>=0?'+':'')+su.uup_chg+'%',n:'Presión RV si sube'},
    {l:'Oro (GLD)',c:su.gld_chg>=0?'up':'neu',a:su.gld_chg>=0?'▲':'▼',v2:(su.gld_chg>=0?'+':'')+su.gld_chg+'%',n:'Inflación/miedo'},
    {l:'Bitcoin',c:btcBm&&btcBm['1D']>=0?'up':'dn',a:btcBm&&btcBm['1D']>=0?'▲':'▼',v2:btcBm?(btcBm['1D']>=0?'+':'')+btcBm['1D']+'%':'—',n:'Risk-ON / apetito especulativo'},
  ].map(r=>`<div class="risk-c"><div class="risk-l">${r.l}</div><div class="risk-a ${r.c}">${r.a}</div><div class="risk-v ${r.c}">${r.v2}</div><div class="risk-n">${r.n}</div></div>`).join('');

  // Charts
  const ser=D.breadthSeries;
  const mkC=(id,tk,col,label)=>{
    const d=ser[tk];
    var contenedor = document.getElementById(id) ? document.getElementById(id).closest('.cw') : null;
    if(!d||!d.values.length){
      // NUEVO (03/09/2026): antes se dejaba el canvas vacío (quedaba mal,
      // como el panel de VIX en blanco) — ahora, si de verdad no hay
      // datos para ese indicador, se oculta la tarjeta entera en vez de
      // mostrar un hueco sin gráfico ni explicación.
      if(contenedor) contenedor.style.display='none';
      return;
    }
    if(contenedor) contenedor.style.display='';
    const ctx=document.getElementById(id); if(!ctx)return;
    new Chart(ctx,{type:'line',data:{labels:d.dates,datasets:[{
      data:d.values,borderColor:col,borderWidth:1.5,pointRadius:0,
      fill:true,backgroundColor:col.replace('rgb','rgba').replace(')',',0.06)'),tension:0.3
    }]},options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{mode:'index',intersect:false,callbacks:{label:c=>'$'+c.parsed.y.toFixed(2)}}},
      scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:7},grid:{color:'#1c2436'}},
        y:{ticks:{color:'#3a4860',font:{size:9},callback:v=>'$'+v},grid:{color:'#1c2436'}}}}});
  };
  // Fill daily change badges on chart titles
  const chgFill=(id,val)=>{const el=document.getElementById(id);if(!el||val===undefined)return;const c=parseFloat(val);if(isNaN(c))return;el.innerHTML=`<span class="${c>=0?'up':'dn'}">${c>=0?'+':''}${c}% hoy</span>`;};
  const bl=D.breadthLatest||{};
  chgFill('chg-spy',bl['SPY']?.chg);chgFill('chg-vix',bl['VIXY']?.chg);
  chgFill('chg-hyg',bl['HYG']?.chg);chgFill('chg-tlt',bl['TLT']?.chg);
  chgFill('chg-uup',bl['UUP']?.chg);chgFill('chg-gld',bl['GLD']?.chg);
  chgFill('chg-btc',bl['X:BTCUSD']?.chg);chgFill('chg-nya',bl['VTI']?.chg);
  mkC('c-spy','SPY','rgb(56,189,248)');
  // NUEVO (03/09/2026) — BUG REAL ENCONTRADO: esto buscaba la serie bajo
  // la clave 'I:VIX' si esa clave existía en D.benchmarks (una lista
  // aparte) — pero fetch_breadth_and_amplitude() SIEMPRE guarda el VIX
  // bajo la clave 'VIXY' (así está en BREADTH_TICKERS, nunca 'I:VIX').
  // Como buscaba una clave que breadthSeries nunca tiene, el gráfico
  // salía en blanco aunque el dato SÍ estuviera disponible. Se usa
  // 'VIXY' directamente, sin la comprobación cruzada que causaba el fallo.
  mkC('c-vix','VIXY','rgb(244,63,94)');
  mkC('c-hyg','HYG','rgb(16,185,129)');
  mkC('c-tlt','TLT','rgb(245,158,11)');
  mkC('c-uup','UUP','rgb(167,139,250)');
  mkC('c-gld','GLD','rgb(251,191,36)');
  mkC('c-btc','X:BTCUSD','rgb(249,115,22)');
  mkC('c-nya','VTI','rgb(100,200,255)');
  mkC('c-tip','TIP','rgb(52,211,153)');
  mkC('c-agg','AGG','rgb(99,179,237)');
  mkC('c-tnx','IEF','rgb(251,191,36)');
  // Daily change labels para macro
  const tipChg=su.tip_chg||0;const tnxChg=su.tnx_chg||0;const aggChg=su.agg_chg||0;
  if(document.getElementById('tip-chg')) document.getElementById('tip-chg').innerHTML=`<span class="${tipChg>=0?'up':'dn'}">${tipChg>=0?'+':''}${tipChg}% hoy</span>`;
  if(document.getElementById('tnx-chg')) document.getElementById('tnx-chg').innerHTML=`<span class="${tnxChg>=0?'dn':'up'}">${tnxChg>=0?'+':''}${tnxChg}% hoy</span>`;
  if(document.getElementById('agg-chg')) document.getElementById('agg-chg').innerHTML=`<span class="${aggChg>=0?'up':'dn'}">${aggChg>=0?'+':''}${aggChg}% hoy</span>`;

  // ── INTERPRETACIÓN SUBJETIVA DE MERCADO ──────────────────────────────────
  const mc=document.getElementById('market-comment');
  if(mc){
    const score=su.score||0;
    const spy=su.spy_chg||0;
    const vix=su.vix||20;
    const pct50=su.pct_abv50||0;
    const pct200=su.pct_abv200||0;
    const nh=su.new_highs||0;
    const nl=su.new_lows||0;
    const hyg=su.hyg_chg||0;
    const uup=su.uup_chg||0;
    const tlt=su.tlt_chg||0;
    const tip=su.tip_chg||0;
    const agg=su.agg_chg||0;
    const tnx=parseFloat(su.tnx_price)||0;
    const mccLast=su.mcclellan&&su.mcclellan.length?su.mcclellan[su.mcclellan.length-1].val:0;
    const adLast=su.ad_line&&su.ad_line.length?su.ad_line[su.ad_line.length-1].val:0;
    const moodStr=score>=75?'Ofensivo':score>=60?'Neutral Alcista':score>=45?'Neutral':score>=30?'Neutral Bajista':'Defensivo';
    const trendColor=score>=60?'var(--up)':score>=45?'var(--warn)':'var(--dn)';
    const lines=[];

    // ── Bloque 1: diagnóstico general ─────────────────────────────────────
    const breadthOk=pct50>55&&pct200>45;
    const nhNlOk=nh>nl;
    const riskOn=hyg>0&&tlt<0;
    const riskOff=hyg<0&&tlt>0;
    let diag='';
    if(score>=65&&breadthOk&&nhNlOk){
      diag=`El mercado muestra una estructura técnica <strong style="color:var(--up)">sólida y tendencial</strong>. `+
        `El ${pct50}% de los valores cotiza sobre su MA50 y el ${pct200}% sobre MA200 — la mayoría de carteras diversificadas están generando alpha. `+
        `Con ${nh} nuevos máximos frente a ${nl} mínimos, la amplitud confirma que la subida es <em>participada</em>, no solo de megacaps.`;
    } else if(score>=45){
      const weak=pct50<50?'La amplitud muestra dudas — solo el '+pct50+'% supera la MA50':'El porcentaje sobre MA50 es aceptable ('+pct50+'%)';
      diag=`Mercado en zona de <strong style="color:var(--warn)">transición y vigilancia</strong>. ${weak}. `+
        `La batalla entre compradores y vendedores es evidente: ${nh} nuevos máximos vs ${nl} mínimos. `+
        `En este entorno conviene priorizar valores con RS alto y reducir exposición a los rezagados.`;
    } else {
      diag=`⚠️ La estructura técnica está <strong style="color:var(--dn)">deteriorada</strong>. `+
        `Solo el ${pct50}% supera la MA50 y el ${pct200}% la MA200 — muchas carteras están bajo agua. `+
        `Los ${nl} nuevos mínimos dominan sobre ${nh} máximos. Es momento de gestión de riesgo, no de añadir exposición.`;
    }
    lines.push({color:trendColor,icon:'📊',title:`Score ${score}/100 — ${moodStr}`,body:diag});

    // ── Bloque 2: flujo de capital (risk on/off) ───────────────────────────
    if(riskOn){
      lines.push({color:'var(--up)',icon:'🟢',title:'Flujo Risk-ON',body:
        `El High Yield sube mientras los treasuries ceden — dinero fluyendo hacia activos de riesgo. `+
        `Este es el patrón clásico de "risk-on": los bonos basura se demandan porque los inversores confían en que las empresas pagarán. `+
        (hyg>0.3?`Con HYG +${hyg}%, la señal es especialmente contundente. Sectores cíclicos y growth deberían beneficiarse.`:
        `La señal es moderada pero constructiva. Sectores tech y consumo discrecional en foco.`)});
    } else if(riskOff){
      lines.push({color:'var(--dn)',icon:'🔴',title:'Flujo Risk-OFF',body:
        `HYG cae (${hyg}%) mientras TLT sube (${tlt>0?'+':''}${tlt}%) — huida hacia la calidad. `+
        `Los inversores prefieren la seguridad de los treasuries a tomar riesgo en crédito corporativo. `+
        `En este entorno, Utilities, Healthcare y bonos cortos actúan como refugio. Reducir beta de cartera.`});
    } else {
      lines.push({color:'var(--warn)',icon:'🟡',title:'Flujo neutro — sin señal clara',body:
        `HYG y TLT se mueven sin dirección definitiva. El mercado está en modo "esperar y ver", `+
        `típico antes de un dato macro relevante (Fed, IPC, empleo) o en fase de consolidación lateral. `+
        `Buena oportunidad para revisar stops y reducir posiciones especulativas.`});
    }

    // ── Bloque 3: tipos e inflación (macro) ───────────────────────────────
    if(tnx>0){
      const tnxView=tnx>4.5?`El yield 10Y en <strong>${tnx}%</strong> es terreno restrictivo — la Fed mantiene presión sobre la economía. `+
        `Las empresas growth con múltiplos altos sufren más en este entorno ya que la tasa de descuento es elevada. `+
        `Ojo especial a valoraciones del Nasdaq y real estate.`:
        tnx>4?`Yield 10Y en <strong>${tnx}%</strong> — nivel elevado pero ya descontado por el mercado en parte. `+
        `La curva 10Y-2Y es clave: si el spread se estrecha, cuidado con bancarios y financieras.`:
        `Yield 10Y en <strong>${tnx}%</strong> — nivel manejable. Los bonos siguen siendo competitivos vs renta variable.`;
      const tipView=tip>0?`Los TIPS (+${tip}% hoy) reflejan que los breakevens de inflación suben — el mercado empieza a descontar mayor inflación futura. Vigilar oro y commodities como cobertura.`:
        tip<0?`Los TIPS ceden (${tip}%) — expectativas de inflación a la baja, favorable para el múltiplo de los activos growth.`:'';
      lines.push({color:'var(--ac)',icon:'📉',title:'Tipos e inflación',body:tnxView+(tipView?' '+tipView:'')});
    }

    // ── Bloque 4: McClellan + A/D internos ────────────────────────────────
    if(mccLast!==0||adLast!==0){
      const mccStr=mccLast>100?`McClellan muy positivo (+${mccLast.toFixed(0)}) — impulso alcista de amplitud fuerte. Históricamente este nivel precede a continuaciones de tendencia`:
        mccLast>30?`McClellan positivo (+${mccLast.toFixed(0)}) — la mayoría de valores participan en la subida`:
        mccLast<-100?`⚠️ McClellan muy negativo (${mccLast.toFixed(0)}) — señal de capitulación o inicio de rebote técnico`:
        mccLast<-30?`McClellan negativo (${mccLast.toFixed(0)}) — distribución interna, las subidas no están siendo confirmadas`:
        `McClellan en zona neutra (${mccLast.toFixed(0)}) — sin señal de momentum definida`;
      lines.push({color:mccLast>0?'var(--up)':'var(--dn)',icon:'🔬',title:'Análisis interno (McClellan + A/D)',body:
        mccStr+`. La línea A/D acumulada ${adLast>0?'en terreno positivo, confirmando la tendencia alcista':'en terreno negativo, divergencia bajista a vigilar'}.`});
    }

    // ── Bloque 5: dólar y emergentes ──────────────────────────────────────
    if(Math.abs(uup)>0.2){
      lines.push({color:uup>0?'var(--warn)':'var(--up)',icon:'💵',title:`Dólar ${uup>0?'fuerte':'débil'} (UUP ${uup>0?'+':''}${uup}%)`,body:
        uup>0.3?`Un dólar fuerte genera vientos en contra para materias primas y emergentes. Las multinacionales americanas con ingresos en el exterior también sufren en su repatriación. Sector a vigilar: XLB (materiales) y EEM.`:
        uup<-0.3?`La debilidad del dólar es un catalizador positivo para commodities (oro, petróleo, cobre) y mercados emergentes. Momento para revisar exposición a EM y materias primas.`:
        `Movimiento del dólar moderado — sin impacto relevante por ahora.`});
    }

    mc.innerHTML=lines.map(l=>
      `<div style="margin-bottom:10px;padding:10px 14px;background:var(--bg3);border-left:4px solid ${l.color};border-radius:6px">
        <div style="font-size:12px;font-weight:700;color:${l.color};margin-bottom:5px">${l.icon} ${l.title}</div>
        <div style="font-size:11px;color:var(--tx);line-height:1.8">${l.body}</div>
      </div>`).join('');
  }

  // A/D Line
  if(su.ad_line&&su.ad_line.length>0){
    const ctx=document.getElementById('c-adl');
    if(ctx) new Chart(ctx,{type:'line',data:{
      labels:su.ad_line.map(x=>x.date),
      datasets:[{data:su.ad_line.map(x=>x.val),borderColor:'rgb(52,211,153)',borderWidth:1.5,
        pointRadius:0,fill:true,backgroundColor:'rgba(52,211,153,0.06)',tension:0.3}]
    },options:{responsive:true,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},
      scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:7},grid:{color:'#1c2436'}},
        y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'}}}}});
  }

  // McClellan Oscillator
  const mcc=su.mcclellan||[];
  if(mcc.length>0){
    const ctx=document.getElementById('c-mcc');
    if(ctx){
      const mccColors=mcc.map(x=>x.val>=0?'rgba(16,185,129,.75)':'rgba(244,63,94,.75)');
      new Chart(ctx,{type:'bar',data:{
        labels:mcc.map(x=>x.date),
        datasets:[{data:mcc.map(x=>x.val),backgroundColor:mccColors,borderRadius:2}]
      },options:{responsive:true,plugins:{legend:{display:false},
        tooltip:{mode:'index',intersect:false,callbacks:{label:c=>c.parsed.y.toFixed(2)}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'}},
          y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'}}}}});
    }
  }

  // Curva 10Y-2Y proxy
  const crv=su.curve_spread||[];
  if(crv.length>0){
    const ctx=document.getElementById('c-crv');
    if(ctx){
      const crvPos=crv.map(x=>x.val>=0?x.val:0);
      const crvNeg=crv.map(x=>x.val<0?x.val:0);
      new Chart(ctx,{type:'bar',data:{
        labels:crv.map(x=>x.date),
        datasets:[
          {data:crvPos,backgroundColor:'rgba(16,185,129,.55)',borderRadius:1},
          {data:crvNeg,backgroundColor:'rgba(244,63,94,.55)',borderRadius:1},
        ]
      },options:{responsive:true,plugins:{legend:{display:false},
        tooltip:{mode:'index',intersect:false,callbacks:{label:c=>c.parsed.y.toFixed(2)+'%'}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'},stacked:true},
          y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'},stacked:true}}}});
    }
  }

  // Distribution bars
  const dist=su.dist_buckets||{};
  const dkeys=Object.keys(dist);
  const dvals=Object.values(dist);
  const dmx=Math.max(...dvals,1);
  const colors={'<-10%':'#f43f5e','-10a-5%':'#f97316','-5a-2%':'#eab308','-2a0%':'#6b7280',
    '0a2%':'#22c55e','2a5%':'#10b981','5a10%':'#06b6d4','>10%':'#38bdf8'};
  document.getElementById('dist-chart').innerHTML=dkeys.map((k,i)=>{
    const pct=Math.round(dvals[i]/dmx*100);
    return `<div class="dist-bar" style="height:${Math.max(pct,4)}%;background:${colors[k]||'var(--ac)'}">
      <span class="dist-val">${dvals[i]}</span>
      <span class="dist-label">${k}</span>
    </div>`;
  }).join('');

  // ── MACD S&P500 — Signal line semanal SPY (MACD 12/23/9) ───────────────────
  (function(){
    var el=document.getElementById('macd-content');
    if(!el) return;
    // Use SPY daily series — 300 days gives ~60 weekly closes
    var spySeries=(D.breadthSeries&&D.breadthSeries['SPY']&&D.breadthSeries['SPY'].values)||
                  (D.breadthSeries&&D.breadthSeries['^GSPC']&&D.breadthSeries['^GSPC'].values)||[];
    var dates=(D.breadthSeries&&D.breadthSeries['SPY']&&D.breadthSeries['SPY'].dates)||
              (D.breadthSeries&&D.breadthSeries['^GSPC']&&D.breadthSeries['^GSPC'].dates)||[];
    if(spySeries.length<25){ el.innerHTML='<div style="color:var(--dim);font-size:11px">Sin datos de SPY.</div>'; return; }
    // Build weekly closes from daily
    var weekly=[];
    if(dates.length===spySeries.length){
      for(var i=0;i<spySeries.length;i++){
        var dt=new Date(dates[i]);
        var nextDt=i+1<dates.length?new Date(dates[i+1]):null;
        var isLast=!nextDt||(nextDt-dt)>3*86400000;
        if(isLast) weekly.push(spySeries[i]);
      }
    }
    // If weekly conversion failed or not enough, use daily directly (rescale periods)
    var useWeekly=weekly.length>=20;
    var data=useWeekly?weekly:spySeries;
    // Scale periods: weekly uses 12/23/9, daily uses 60/120/45 (approx equivalent)
    var fast=useWeekly?12:60, slow=useWeekly?23:120, sig=useWeekly?9:45;
    function ema(arr,n){ var k=2/(n+1),e=arr[0]; for(var i=1;i<arr.length;i++) e=arr[i]*k+e*(1-k); return e; }
    var macdArr=[];
    for(var i=slow;i<data.length;i++) macdArr.push(ema(data.slice(0,i+1),fast)-ema(data.slice(0,i+1),slow));
    var sigArr=[];
    for(var i=sig;i<macdArr.length;i++) sigArr.push(ema(macdArr.slice(0,i+1),sig));
    if(sigArr.length<2){ el.innerHTML='<div style="color:var(--dim);font-size:11px">Calculando... (necesita más historial)</div>'; return; }
    var sigLine=sigArr[sigArr.length-1]||0;
    var active=sigLine>0;
    var color=active?'var(--up)':'var(--dn)';
    var spark=sigArr.slice(-25);
    var maxAbs=Math.max.apply(null,spark.map(Math.abs).concat([0.01]));
    el.innerHTML=''
      +'<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">'
        +'<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
          +'<div style="width:52px;height:52px;border-radius:50%;background:'+(active?'rgba(5,196,107,.15)':'rgba(255,63,91,.12)')+';border:2px solid '+color+';display:flex;align-items:center;justify-content:center;flex-shrink:0">'
            +'<span style="font-size:22px">'+(active?'🟢':'🔴')+'</span>'
          +'</div>'
          +'<div style="font-size:9px;color:var(--dim)">'+(active?'ACTIVO':'NO ACTIVO')+'</div>'
        +'</div>'
        +'<div>'
          +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+'">'+(active?'SEÑAL ALCISTA':'SEÑAL BAJISTA')+'</div>'
          +'<div style="font-size:11px;color:var(--dim);margin-top:3px">Signal(9): <strong style="color:'+color+'">'+(sigLine>=0?'+':'')+sigLine.toFixed(3)+'</strong></div>'
          +'<div style="font-size:10px;color:var(--dim)">MACD(12,23,9) semanal · SPY</div>'
        +'</div>'
      +'</div>'
      +'<div style="display:flex;align-items:center;gap:1px;height:36px;margin-bottom:10px;background:var(--bg3);border-radius:6px;padding:4px 8px;position:relative">'
      +'<div style="position:absolute;left:0;right:0;top:50%;height:1px;background:var(--b2)"></div>'
      +spark.map(function(v){
        var pct=Math.min(100,Math.abs(v)/maxAbs*45);
        return '<div style="flex:1;position:relative;height:100%;display:flex;align-items:'+(v>=0?'flex-end':'flex-start')+'">'
          +'<div style="width:100%;background:'+(v>=0?'var(--up)':'var(--dn)')+';height:'+pct+'%;border-radius:1px;opacity:.8;min-height:2px"></div>'
          +'</div>';
      }).join('')+'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:8px 11px;background:var(--bg3);border-radius:6px">'
        +(active?'Signal Line > 0 — MACD semanal activo. Momentum alcista confirmado en SPY.':'Signal Line < 0 — MACD inactivo. Sin señal alcista. Esperar cruce por encima de 0.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">Activo cuando Signal(9) de MACD(12,23) semanal sobre SPY > 0. Idéntico a tu Pine script.</div>';
  })();
  // ── BONOS CEF — señal de flujo de capital ────────────────────────────────────
  (function(){
    var el=document.getElementById('cef-content');
    if(!el) return;
    // CEF bonds proxy: TLT + LQD + AGG movements as capital flow signal
    var tlt=parseFloat(su.tlt_chg||0);
    var agg=parseFloat(su.agg_chg||0);
    var lqd=parseFloat(su.lqd_chg||0);
    var tnx=parseFloat(su.tnx_price||4.5);
    // CEF bond funds typically trade at premium/discount to NAV
    // Rising bond prices = falling yields = favorable for CEF bonds
    var cefSignal=(tlt+agg+(lqd||0))/3;
    var signalOk=cefSignal>0&&tnx<4.8;
    var color=signalOk?'var(--up)':cefSignal<-0.3?'var(--dn)':'var(--warn)';
    var label=signalOk?'✅ FLUJO POSITIVO':cefSignal<-0.3?'❌ FLUJO NEGATIVO':'🟡 NEUTRO';
    el.innerHTML=''
      +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+';margin-bottom:7px">'+label+'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px">'
        +'TLT: <span class="'+(tlt>=0?'up':'dn')+'">'+(tlt>=0?'+':'')+tlt.toFixed(2)+'%</span> &nbsp;'
        +'AGG: <span class="'+(agg>=0?'up':'dn')+'">'+(agg>=0?'+':'')+agg.toFixed(2)+'%</span> &nbsp;'
        +'Yield10Y: <strong>'+tnx.toFixed(2)+'%</strong>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:7px 10px;background:var(--bg3);border-radius:5px">'
        +(signalOk
          ?'Los bonos suben — los CEF de renta fija cotizan con menor descuento o en prima. Entorno favorable para bonos de alto cupón (closed-end funds de RF).'
          :cefSignal<-0.3
          ?'Bonos bajo presión — los CEF de renta fija pueden ampliar su descuento al NAV. Moment de precaución en RF.'
          :'Señal mixta en bonos. Los CEF de RF en zona de transición. Monitorizar yield 10Y.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">CEF = Closed-End Funds (Fondos cerrados de renta fija). Señal basada en TLT/AGG/Yield 10Y.</div>';
  })();

  // ── COPPOCK CURVE — indicador mensual de largo plazo ─────────────────────────
  (function(){
    var el=document.getElementById('coppock-content');
    if(!el) return;
    var spy=D.benchmarks?D.benchmarks.find(function(b){ return b.ticker==='^GSPC'||b.ticker==='SPY'; }):null;
    // Coppock = WMA(10) of (ROC(14 months) + ROC(11 months))
    // Proxy: use available return data
    var roc14=spy?parseFloat(spy['1Y']||0):0;  // ~12m proxy
    var roc11=spy?parseFloat(spy['3M']||0)*4:0; // ~11m proxy (3M annualized)
    var rawCoppock=roc14*0.6+roc11*0.4;
    // WMA smoothing proxy: combine with shorter term
    var m1=spy?parseFloat(spy['1M']||0):0;
    var coppock=(rawCoppock*0.7+m1*3*0.3);
    var rising=coppock>0&&m1>0;
    var activated=coppock>0;
    var color=activated?'var(--up)':'var(--dn)';
    el.innerHTML=''
      +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+';margin-bottom:7px">'
        +(activated?'✅ POSITIVO':'❌ NEGATIVO')+(rising?' ↑':' ↓')
      +'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px">'
        +'Valor proxy: <strong style="color:'+color+'">'+(coppock>=0?'+':'')+coppock.toFixed(1)+'</strong>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:7px 10px;background:var(--bg3);border-radius:5px">'
        +(activated&&rising
          ?'Coppock positivo y subiendo — señal alcista de largo plazo. Edwin Coppock diseñó este indicador como señal de compra en mercados bajistas. Históricamente muy preciso en mercados mensuales.'
          :activated&&!rising
          ?'Coppock positivo pero girando — momentum de largo plazo se modera. Mantener posiciones pero reducir nuevas compras agresivas.'
          :'Coppock negativo — el modelo mensual no confirma tendencia alcista de largo plazo. Esperar cruce sobre cero.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">Coppock Curve original: WMA10 de (ROC14m + ROC11m). Señal válida solo en gráfico mensual.</div>';
  })();

  // ── HAA — ROC TIP (21/63/126/252 días), media > 0 = ACTIVO ─────────────────
  (function(){
    var el=document.getElementById('haa-content');
    if(!el) return;
    var tipSeries=(D.breadthSeries&&D.breadthSeries['TIP']&&D.breadthSeries['TIP'].values)||[];
    if(tipSeries.length<30){ el.innerHTML='<div style="color:var(--dim);font-size:11px">Datos insuficientes de TIP.</div>'; return; }
    function roc(arr,period){ var last=arr[arr.length-1]; var prev=arr.length>period?arr[arr.length-1-period]:arr[0]; return prev>0?100*(last/prev-1):0; }
    var p=tipSeries;
    var r21=roc(p,Math.min(21,p.length-1));
    var r63=roc(p,Math.min(63,p.length-1));
    var r126=roc(p,Math.min(126,p.length-1));
    var r252=roc(p,Math.min(252,p.length-1));
    var media=(r21+r63+r126+r252)/4;
    var active=media>0;
    var color=active?'var(--up)':'var(--dn)';
    var spark=[];
    for(var i=Math.min(252,p.length-1);i<p.length;i++){
      var sl=p.slice(0,i+1);
      spark.push((roc(sl,Math.min(21,sl.length-1))+roc(sl,Math.min(63,sl.length-1))+roc(sl,Math.min(126,sl.length-1))+roc(sl,Math.min(252,sl.length-1)))/4);
    }
    spark=spark.slice(-30);
    var maxAbs=Math.max.apply(null,spark.map(Math.abs).concat([0.01]));
    el.innerHTML=''
      +'<div style="display:flex;align-items:center;gap:14px;margin-bottom:12px">'
        +'<div style="display:flex;flex-direction:column;align-items:center;gap:4px">'
          +'<div style="width:52px;height:52px;border-radius:50%;background:'+(active?'rgba(5,196,107,.15)':'rgba(255,63,91,.12)')+';border:2px solid '+color+';display:flex;align-items:center;justify-content:center;flex-shrink:0">'
            +'<span style="font-size:22px">'+(active?'🟢':'🔴')+'</span>'
          +'</div>'
          +'<div style="font-size:9px;color:var(--dim)">'+(active?'ACTIVO':'NO ACTIVO')+'</div>'
        +'</div>'
        +'<div>'
          +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+'">'+(active?'MODO OFENSIVO':'MODO DEFENSIVO')+'</div>'
          +'<div style="font-size:11px;color:var(--dim);margin-top:3px">Media ROC TIP: <strong style="color:'+color+'">'+(media>=0?'+':'')+media.toFixed(3)+'%</strong></div>'
          +'<div style="font-size:10px;color:var(--dim)">ROC(21/63/126/252d) sobre TIP</div>'
        +'</div>'
      +'</div>'
      +'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:5px;margin-bottom:10px">'
      +[['21d',r21],['63d',r63],['126d',r126],['252d',r252]].map(function(r){
        var c=r[1]>=0?'var(--up)':'var(--dn)';
        return '<div style="background:var(--bg3);border-radius:7px;padding:8px;text-align:center">'
          +'<div style="font-size:9px;color:var(--dim);margin-bottom:3px">ROC '+r[0]+'</div>'
          +'<div style="font-size:12px;font-weight:700;color:'+c+'">'+(r[1]>=0?'+':'')+r[1].toFixed(2)+'%</div>'
          +'</div>';
      }).join('')+'</div>'
      +'<div style="display:flex;align-items:center;gap:1px;height:36px;margin-bottom:10px;background:var(--bg3);border-radius:6px;padding:4px 8px;position:relative">'
      +'<div style="position:absolute;left:0;right:0;top:50%;height:1px;background:var(--b2)"></div>'
      +spark.map(function(v){
        var pct=Math.min(100,Math.abs(v)/maxAbs*45);
        return '<div style="flex:1;position:relative;height:100%;display:flex;align-items:'+(v>=0?'flex-end':'flex-start')+'">'
          +'<div style="width:100%;background:'+(v>=0?'var(--up)':'var(--dn)')+';height:'+pct+'%;border-radius:1px;opacity:.8;min-height:2px"></div>'
          +'</div>';
      }).join('')+'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:8px 11px;background:var(--bg3);border-radius:6px">'
        +(active?'TIP ROC media > 0 — inflación real positiva. Modo OFENSIVO: mantener renta variable.':'TIP ROC media < 0 — deflación o inflación negativa. Modo DEFENSIVO: reducir riesgo.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">HAA: ROC(TIP, 21/63/126/252d), media > 0 = activo. Idéntico a tu indicador Pine.</div>';
  })();
  (function(){
    var el=document.getElementById('fg-content');
    if(!el) return;
    var vix=parseFloat(su.vix)||20;
    var pct50=su.pct_abv50||50;
    var nh=su.new_highs||0, nl=su.new_lows||0;
    var hyg=parseFloat(su.hyg_chg||0);
    var tlt=parseFloat(su.tlt_chg||0);
    // Get GSPC series for momentum
    var gspcSeries=D.breadthSeries&&D.breadthSeries['SPY']?D.breadthSeries['SPY'].values:[];
    var gspcLast=gspcSeries.length>0?gspcSeries[gspcSeries.length-1]:0;
    // MA125 for momentum comparison (CNN uses 125-day MA)
    var ma125=gspcSeries.length>=125?gspcSeries.slice(-125).reduce(function(a,b){return a+b;},0)/125:
              gspcSeries.length>0?gspcSeries.reduce(function(a,b){return a+b;},0)/gspcSeries.length:gspcLast;
    // VIX: CNN compares to 50-day average. Score: higher VIX vs avg = more fear
    // VIX 12 = extreme greed, VIX 20 = neutral, VIX 30 = fear, VIX 40+ = extreme fear
    var vixNorm=Math.max(0,Math.min(100, 100-(vix-12)/(40-12)*100));
    // Market Momentum: price vs MA125
    var momScore=ma125>0?Math.max(0,Math.min(100, 50+(gspcLast/ma125-1)*500)):50;
    // Breadth: % above MA50, centered at 50%
    var breadthScore=Math.max(0,Math.min(100, pct50));
    // NH/NL ratio
    var nhnlScore=nh+nl>0?Math.max(0,Math.min(100,nh/(nh+nl)*100)):50;
    // Safe haven demand: TLT rising = fear (bonds up = flight to safety)
    var safeScore=Math.max(0,Math.min(100, tlt>0.5?20:tlt>0.2?35:tlt>0?45:tlt>-0.2?55:tlt>-0.5?65:80));
    // Junk bond demand: HYG rising = greed
    var junkScore=Math.max(0,Math.min(100, hyg>0.3?75:hyg>0?60:hyg>-0.3?45:30));
    // Weighted score (closer to CNN weighting)
    var score=Math.round(vixNorm*0.25+momScore*0.25+breadthScore*0.2+nhnlScore*0.15+safeScore*0.1+junkScore*0.05);
    score=Math.max(0,Math.min(100,score));
    var label=score>=80?'Codicia Extrema':score>=60?'Codicia':score>=40?'Neutral':score>=20?'Miedo':'Miedo Extremo';
    var color=score>=75?'#ef4444':score>=55?'#f97316':score>=40?'#eab308':score>=25?'#84cc16':'#22c55e';
    var advice=score>=80?'Exceso de optimismo — señal contrarian bajista. Revisar exposición especulativa.':
      score>=60?'Codicia moderada. Rally puede continuar con menor margen de seguridad.':
      score>=40?'Zona neutral. Sin sesgo contrarian claro. Seguir análisis técnico.':
      score>=20?'Miedo: históricamente buen momento para añadir en acciones de calidad con RS alto.':
      'Miedo Extremo — señal contrarian alcista muy potente. Mejores oportunidades históricas de compra.';
    var gaugeGrad='conic-gradient('+color+' 0% '+score+'%, var(--bg3) '+score+'% 100%)';
    el.innerHTML=''
      +'<div style="display:flex;gap:14px;align-items:center;margin-bottom:10px">'
        +'<div style="position:relative;width:80px;height:80px;border-radius:50%;background:'+gaugeGrad+';display:flex;align-items:center;justify-content:center;flex-shrink:0">'
          +'<div style="position:absolute;inset:8px;border-radius:50%;background:var(--bg2);display:flex;align-items:center;justify-content:center;flex-direction:column">'
            +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+'">'+score+'</div>'
          +'</div>'
        +'</div>'
        +'<div><div style="font-size:15px;font-weight:700;color:'+color+';margin-bottom:4px">'+label+'</div>'
          +'<div style="font-size:9px;color:var(--dim)">'
            +'VIX: '+vixNorm.toFixed(0)+' · Momentum: '+momScore.toFixed(0)+' · Amplitud: '+breadthScore.toFixed(0)
          +'</div>'
        +'</div>'
      +'</div>'
      +'<div style="height:6px;border-radius:3px;background:linear-gradient(90deg,#22c55e,#84cc16,#eab308,#f97316,#ef4444);margin-bottom:5px;position:relative">'
        +'<div style="position:absolute;top:-4px;left:calc('+score+'% - 7px);width:14px;height:14px;border-radius:50%;background:var(--hi);border:2px solid var(--bg);box-shadow:0 0 5px rgba(0,0,0,.3)"></div>'
      +'</div>'
      +'<div style="display:flex;justify-content:space-between;font-size:8px;color:var(--dim);margin-bottom:9px"><span>0 Miedo Extremo</span><span>100 Codicia Extrema</span></div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.65;padding:8px 10px;background:var(--bg3);border-radius:6px">'+advice+'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:6px">Calculado con 6 componentes: VIX · Momentum S&P500 vs MA125 · Amplitud · NH/NL · Bonos · HYG. Valor de referencia CNN: markets.money.cnn.com</div>';
  })();
  // ── AAII SENTIMENT PROXY ─────────────────────────────────────────────────────
  (function(){
    var el=document.getElementById('aaii-content');
    if(!el) return;
    var vix=parseFloat(su.vix)||20;
    var pct50=su.pct_abv50||50;
    var mcc=su.mcclellan&&su.mcclellan.length?su.mcclellan[su.mcclellan.length-1].val:0;
    // Proxy bull/bear/neutral derived from market internals
    var bullBase=38+(pct50-50)*0.4+(mcc/6)+(vix<18?5:vix>25?-8:0);
    var bearBase=30-(pct50-50)*0.3+(vix>25?10:vix<15?-5:0)-(mcc>50?5:mcc<-50?5:0);
    var bull=Math.max(15,Math.min(65,Math.round(bullBase)));
    var bear=Math.max(15,Math.min(55,Math.round(bearBase)));
    var neut=Math.max(10,100-bull-bear);
    var spread=bull-bear;
    var spreadNote=spread>20?'Exceso de optimismo — señal contrarian bajista. Históricamente spreads >20pp preceden correcciones.':
      spread>8?'Sesgo alcista moderado. Constructivo sin excesos.':
      spread>-8?'Mercado equilibrado, sin sesgo definido.':
      spread>-20?'Pesimismo moderado — terreno favorable para posiciones largas en valor.':
      'Spread bajista amplio — miedo extremo. Históricamente señal contrarian alcista muy potente.';
    var spreadColor=spread>20?'var(--dn)':spread>0?'var(--warn)':spread>-20?'var(--ac)':'var(--up)';
    el.innerHTML=''
      +'<div style="margin-bottom:12px">'
      +[['🟢 Alcistas (Bullish)',bull,'var(--up)'],['🔴 Bajistas (Bearish)',bear,'var(--dn)'],['🟡 Neutrales',neut,'var(--warn)']].map(function(r){
        return '<div style="margin-bottom:8px">'
          +'<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px"><span style="color:var(--tx)">'+r[0]+'</span><span style="font-weight:700;color:'+r[2]+'">'+r[1]+'%</span></div>'
          +'<div style="height:7px;background:var(--bg3);border-radius:4px;overflow:hidden"><div style="height:100%;width:'+r[1]+'%;background:'+r[2]+';border-radius:4px;transition:width .5s"></div></div>'
          +'</div>';
      }).join('')+'</div>'
      +'<div style="padding:10px 13px;background:var(--bg3);border-radius:7px;font-size:11px;line-height:1.75">'
        +'<strong style="color:'+spreadColor+'">Spread Bull-Bear: '+(spread>=0?'+':'')+spread+'pp</strong><br>'+spreadNote
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:7px">Estimación basada en amplitud MA50, McClellan y VIX. Encuesta AAII semanal oficial: aaii.com</div>';
  })();

  // ── CICLO KONDRATIEV — fase determinada por análisis macro estructural ───────
  (function(){
    var el=document.getElementById('kondratiev-content');
    if(!el) return;
    // El ciclo Kondratiev dura ~50-60 años. Fases de 10-20 años.
    // Análisis histórico: Invierno 2000-2009, Primavera 2009-2020, Verano 2020+
    // NO se calcula semana a semana — es un ciclo ESTRUCTURAL de largo plazo.
    // Usamos datos macro para CONFIRMAR fase, no determinarla.
    var tnxP=parseFloat(su.tnx_price)||4.5;
    var tipC=parseFloat(su.tip_chg)||0;
    var gldC=parseFloat(su.gld_chg)||0;
    // Fase actual: Primavera tardía / Verano temprano (2020-2030 aprox)
    // Señales confirmadoras: tipos altos, inflación estructural, oro fuerte
    var phase,color,emoji,phaseEng,assets,avoid,description,years;
    // Verificar si hay señales de Otoño (tipos muy altos + crédito tensionado)
    if(tnxP>5.5){
      phase='Verano Kondratiev'; phaseEng='Kondratiev Summer'; emoji='☀️🌡️'; color='#f97316'; years='~2020-2030';
      assets=['Commodities (energía, oro, materias primas)','Real Estate físico','TIPS (TIP)','Acciones con pricing power'];
      avoid=['Bonos largos (TLT) — pierden con inflación','Growth con múltiplos altos'];
      description='Tipos al 5.5%+ confirman el Verano de Kondratiev: inflación estructural, crédito caro, activos reales superando a financieros. El Verano es la fase más difícil para los bonos nominales. Los commodities y el oro son los grandes ganadores. Esta fase puede durar hasta ~2030.';
    } else {
      phase='Primavera tardía / Verano temprano'; phaseEng='Late Spring / Early Summer'; emoji='🌸☀️'; color='var(--up)'; years='~2020-2030';
      assets=['S&P500 calidad (dividendo + recompras)','Industriales (XLI) y defensa','TIPS y bonos cortos','Oro (GLD) como diversificador'];
      avoid=['Bonos muy largos — poco atractivos con tipos altos','Pure growth sin cash flow'];
      description='Estamos en la transición Primavera→Verano de Kondratiev. La innovación tecnológica (IA) actúa como motor de productividad (característico de Primavera), pero los tipos estructuralmente altos y la inflación de servicios apuntan al Verano. La renta variable de calidad con pricing power sigue siendo el activo favorito.';
    }
    el.innerHTML=''
      +'<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">'
        +'<span style="font-size:32px">'+emoji+'</span>'
        +'<div>'
          +'<div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:'+color+'">'+phase+'</div>'
          +'<div style="font-size:10px;color:var(--dim);margin-top:2px">Estimación: '+years+' · Yield 10Y: '+tnxP.toFixed(2)+'%</div>'
        +'</div>'
      +'</div>'
      // Cycle timeline
      +'<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:4px;margin-bottom:12px">'
      +[['❄️','Invierno','2000-2010','opacity:.4'],['🌱','Primavera','2010-2020','opacity:.5'],['🌸','Primavera tardía','2020-2025','font-weight:700;border:2px solid '+color],['☀️','Verano','2025-2035','opacity:.6']].map(function(s){
        return '<div style="text-align:center;background:var(--bg3);border-radius:6px;padding:6px 4px;font-size:9px;color:var(--dim);'+s[3]+'">'
          +'<div style="font-size:16px">'+s[0]+'</div>'
          +'<div style="color:var(--tx);font-size:10px">'+s[1]+'</div>'
          +'<div>'+s[2]+'</div>'
          +'</div>';
      }).join('')+'</div>'
      +'<div style="font-size:10px;font-weight:700;color:var(--up);margin-bottom:5px;text-transform:uppercase">▲ Activos favorecidos</div>'
      +assets.map(function(a){ return '<div style="font-size:11px;color:var(--tx);margin-bottom:3px">• '+a+'</div>'; }).join('')
      +'<div style="font-size:10px;font-weight:700;color:var(--dn);margin-top:8px;margin-bottom:5px;text-transform:uppercase">▼ Reducir exposición</div>'
      +avoid.map(function(a){ return '<div style="font-size:11px;color:var(--dim);margin-bottom:3px">• '+a+'</div>'; }).join('')
      +'<div style="font-size:11px;color:var(--tx);line-height:1.75;margin-top:10px;padding:9px 12px;background:var(--bg3);border-radius:6px">'+description+'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:6px">Ciclo Kondratiev ~50-60 años. Fase determinada por análisis macro estructural, NO semana a semana. Basado en: van Duijn, Schumpeter, Kondratieff.</div>';
  })();
  // ── ESTACIONALIDAD ──────────────────────────────────────────────────────────
  (function(){
    var seasonEl=document.getElementById('seasonal-content');
    if(!seasonEl) return;
    var mo=new Date().getMonth()+1;
    var seasonal={
      1:{assets:['Oro (GLD)','Bitcoin (IBIT)','Small Caps (IWM)'],why:'Enero es positivo para activos de riesgo. El oro se beneficia de demanda asiática post-festivo y flujos de refugio. Bitcoin históricamente ha tenido sus mejores arranques en Q1.'},
      2:{assets:['Oro (GLD)','Nasdaq 100 (QQQ)','Bitcoin (IBIT)'],why:'Febrero mantiene el momentum de enero. La temporada de earnings de Q4 impulsa al Nasdaq. El oro sigue fuerte por incertidumbre geopolítica.'},
      3:{assets:['Oro (GLD)','Energía (XLE)','Materias primas'],why:'Marzo: inicio de primavera activa la demanda de energía. El oro brilla antes de datos clave de la Fed. Los commodities se reactivan con la industria china.'},
      4:{assets:['Nasdaq 100 (QQQ)','S&P 500 (^GSPC)','Semiconductores'],why:'Abril es históricamente uno de los mejores meses del año. El Nasdaq lidera en el inicio de Q2 con el momentum de earnings.'},
      5:{assets:['S&P 500 (^GSPC)','Nasdaq 100 (QQQ)','Industriales (XLI)'],why:'Mayo: último mes del semestre fuerte. "Sell in May" se refiere a partir de aquí. Industriales activos con el ciclo de capex.'},
      6:{assets:['S&P 500 (^GSPC)','Nasdaq 100 (QQQ)','Healthcare (XLV)'],why:'Junio es transición al verano. Healthcare aguanta bien. S&P y Nasdaq mantienen sesgo positivo si la macro acompaña.'},
      7:{assets:['Oro (GLD)','Bitcoin (IBIT)','Consumo discrecional (XLY)'],why:'Julio: menor liquidez veraniega. El oro y Bitcoin son históricamente fuertes. El consumo se activa con el gasto vacacional.'},
      8:{assets:['Oro (GLD)','Bonos largos (TLT)','Utilities (XLU)'],why:'Agosto es el mes más volátil (crashes de 2015, 2019, 2024). El oro es el refugio preferido. Defensivos resisten mejor.'},
      9:{assets:['Liquidez (SHY)','Bonos cortos','Utilities (XLU)'],why:'Septiembre es el peor mes histórico del S&P500 (promedio -1%). Alta probabilidad de corrección. Reducir exposición a riesgo.'},
      10:{assets:['S&P 500 (^GSPC)','Financieros (XLF)','Small Caps (IWM)'],why:'Octubre inicia el mejor semestre estadísticamente. Tras la corrección de septiembre suele haber rebote fuerte.'},
      11:{assets:['S&P 500 (^GSPC)','Small Caps (IWM)','Consumo discrecional (XLY)'],why:'Noviembre es el mejor mes histórico. El rally de fin de año empieza. Black Friday impulsa el consumo. Las small caps suelen liderar.'},
      12:{assets:['Oro (GLD)','S&P 500 (^GSPC)','Tecnología (QQQ)'],why:'Diciembre: Santa Claus Rally en la última semana. El oro repunta por demanda física. S&P y Nasdaq cierran el año con sesgo alcista.'}
    };
    var s=seasonal[mo]||seasonal[12];
    var mN=['','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    var rC=['var(--up)','var(--ac)','var(--warn)'];
    seasonEl.innerHTML='<div style="font-size:10px;color:var(--dim);margin-bottom:10px">Mes actual: <strong style="color:var(--hi)">'+mN[mo]+'</strong> — estacionalidad histórica media</div>'
      +s.assets.map(function(a,i){ return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><span style="font-size:15px">'+(i===0?'🥇':i===1?'🥈':'🥉')+'</span><span style="font-size:12px;font-weight:700;color:'+rC[i]+'">'+a+'</span></div>'; }).join('')
      +'<div style="font-size:11px;color:var(--tx);line-height:1.75;margin-top:10px;padding:9px 12px;background:var(--bg3);border-radius:6px">'+s.why+'</div>';
  })();

  // ── INFLACIÓN ────────────────────────────────────────────────────────────────
  (function(){
    var inflEl=document.getElementById('inflation-content');
    if(!inflEl) return;
    var tnxP=parseFloat(su.tnx_price)||0;
    var tipC=parseFloat(su.tip_chg)||0;
    var aggC=parseFloat(su.agg_chg)||0;
    var inflLevel='moderada', inflLabel='Inflación moderada (entorno normal)', inflColor='var(--warn)';
    if(tnxP>4.8||(tipC>0.3&&aggC<0)){ inflLevel='alta'; inflLabel='Inflación alta — tipos elevados'; inflColor='var(--dn)'; }
    else if(tnxP<3.5&&tipC<-0.1){ inflLevel='baja'; inflLabel='Inflación baja / deflación'; inflColor='var(--up)'; }
    var reg={
      alta:{fav:['Oro (GLD)','Energía (XLE)','TIPS (TIP)','Materias primas (PDBC)'],avoid:['Bonos largos (TLT)','Growth/Tech — múltiplos presionados'],why:'Con inflación alta, los activos reales protegen. Oro, energía e inmuebles actúan como cobertura. Los bonos largos son los grandes perdedores. Las empresas growth sufren porque sus flujos futuros se descuentan a tasas más altas.'},
      moderada:{fav:['S&P 500 (^GSPC)','Nasdaq 100 (QQQ)','Financieros (XLF)','Industriales (XLI)'],avoid:['Utilities — muy sensibles a tipos','Bonos muy largos'],why:'La inflación moderada (2-4%) es el entorno ideal para la renta variable. Las empresas trasladan costes. Los financieros ganan con el diferencial de tipos. El Nasdaq resiste bien si los tipos se estabilizan.'},
      baja:{fav:['Bonos largos (TLT)','Nasdaq/Growth (QQQ)','Utilities (XLU)','Healthcare (XLV)'],avoid:['Energía — demanda y precios débiles','Materias primas — deflación'],why:'Inflación baja: los bancos centrales bajan tipos. Los bonos largos y el growth se benefician. Las utilities son atractivas como proxy de bono con dividendo. Cuidado si la baja inflación refleja debilidad económica real.'}
    };
    var r=reg[inflLevel];
    inflEl.innerHTML='<div style="display:inline-block;padding:4px 12px;border-radius:12px;border:1px solid '+inflColor+';font-size:11px;font-weight:700;color:'+inflColor+';margin-bottom:10px">'+inflLabel+'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:8px">Yield 10Y: '+(tnxP?tnxP.toFixed(3)+'%':'—')+' · TIPS hoy: '+(tipC>=0?'+':'')+tipC.toFixed(2)+'%</div>'
      +'<div style="font-size:10px;font-weight:700;color:var(--up);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em">✅ Favorecidos</div>'
      +r.fav.map(function(a){ return '<div style="font-size:11px;color:var(--tx);margin-bottom:3px">▲ '+a+'</div>'; }).join('')
      +'<div style="font-size:10px;font-weight:700;color:var(--dn);margin-top:8px;margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em">⚠️ Evitar</div>'
      +r.avoid.map(function(a){ return '<div style="font-size:11px;color:var(--dim);margin-bottom:3px">▼ '+a+'</div>'; }).join('')
      +'<div style="font-size:11px;color:var(--tx);line-height:1.75;margin-top:10px;padding:9px 12px;background:var(--bg3);border-radius:6px">'+r.why+'</div>';
  })();

  // Sector heatmap

  // NUEVO (03/09/2026): Amplitud OFICIAL (amplitudmercado.com) — solo se
  // muestra si hay datos de verdad (clave configurada y API respondió
  // bien); si no, la sección se queda oculta y el resto del tab sigue
  // funcionando exactamente igual que siempre.
  AMPLITUD_API = D.amplitudMercadoAPI || {};
  if(AMPLITUD_API.nyse && AMPLITUD_API.nyse.length){
    var seccionAmp = document.getElementById('amplitud-api-section');
    if(seccionAmp) seccionAmp.style.display = '';
    amplitudRenderTodo();
  }

}

// ── AMPLITUD OFICIAL (amplitudmercado.com API) ──────────────────────────────
// NUEVO (03/09/2026). Todo lo de aquí abajo trabaja sobre D.amplitudMercadoAPI
// (nyse/nasdaq/aaii/ii/diarios/bonos/fearGreed), cada serie ya viene como
// lista de objetos {NombreDeColumnaReal: valor, FechaISO: 'AAAA-MM-DD', ...}
// gracias al parseo autodescriptivo del backend — por eso aquí se referencian
// los nombres de columna tal cual los da la API (confirmados para NYSE desde
// su propia documentación; para NASDAQ/bonos/diarios se usa además un
// renderizado genérico por si el nombre exacto de alguna columna variase).
var AMPLITUD_API = {};
var AMPLITUD_PERIODO = '1a';

function amplitudRangoDesde(periodo){
  var d = new Date();
  if(periodo==='1m') d.setMonth(d.getMonth()-1);
  else if(periodo==='6m') d.setMonth(d.getMonth()-6);
  else if(periodo==='1a') d.setFullYear(d.getFullYear()-1);
  else if(periodo==='5a') d.setFullYear(d.getFullYear()-5);
  else if(periodo==='10a') d.setFullYear(d.getFullYear()-10);
  else return null; // 'todo' — sin recorte
  return d.toISOString().slice(0,10);
}

function amplitudFiltrarSerie(serie, periodo){
  var desde = amplitudRangoDesde(periodo);
  if(!desde) return serie;
  return (serie||[]).filter(function(r){ return (r.FechaISO||'') >= desde; });
}

function amplitudDibujarLinea(canvasId, serie, campo, opts){
  opts = opts || {};
  var ctxEl = document.getElementById(canvasId);
  if(!ctxEl || !serie || !serie.length || serie[serie.length-1][campo]===undefined) return;
  var labels = serie.map(function(r){ return r.FechaISO || r.Fecha; });
  var valores = serie.map(function(r){ return r[campo]; });
  var color = opts.color || 'rgb(79,110,247)';
  var key = '_ampChart_'+canvasId;
  if(window[key]) window[key].destroy();

  var datasets = [{
    data:valores, borderColor:color,
    backgroundColor: opts.fill===false ? 'transparent' : color.replace('rgb','rgba').replace(')',',0.10)'),
    borderWidth:1.8, pointRadius:0, fill: opts.fill!==false, tension:0.2, order:1
  }];
  // NUEVO: lineas de referencia horizontales (ej. 20/50/80 en la ADn) —
  // se dibujan como datasets planos discontinuos, sin depender de ningun
  // plugin extra de anotaciones.
  (opts.referencias||[]).forEach(function(nivel){
    datasets.push({
      data: valores.map(function(){ return nivel; }),
      borderColor:'rgba(148,163,184,0.5)', borderWidth:1, borderDash:[4,4],
      pointRadius:0, fill:false, tension:0, order:0
    });
  });

  window[key] = new Chart(ctxEl.getContext('2d'), {
    type:'line',
    data:{ labels:labels, datasets:datasets },
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}, tooltip:{mode:'index',intersect:false,filter:function(item){return item.datasetIndex===0;}}},
      scales:{
        x:{ticks:{color:'var(--dim)',font:{size:9},maxTicksLimit:7},grid:{display:false},border:{display:false}},
        y:{ticks:{color:'var(--dim)',font:{size:9}},grid:{display:false},border:{display:false}}
      }
    }
  });

  if(opts.valorEl){
    var v = valores[valores.length-1];
    document.getElementById(opts.valorEl).textContent = (typeof v==='number') ? v.toLocaleString('es-ES',{maximumFractionDigits:2}) : v;
  }
}

// McClellan (y cualquier oscilador simetrico alrededor de 0) en BARRAS
// verde/rojo, igual que en amplitudmercado.com — mas legible que una linea.
function amplitudDibujarBarras(canvasId, serie, campo, opts){
  opts = opts || {};
  var ctxEl = document.getElementById(canvasId);
  if(!ctxEl || !serie || !serie.length || serie[serie.length-1][campo]===undefined) return;
  var labels = serie.map(function(r){ return r.FechaISO || r.Fecha; });
  var valores = serie.map(function(r){ return r[campo]; });
  var VERDE = 'rgb(16,185,129)', ROJO = 'rgb(244,63,94)';
  var key = '_ampChart_'+canvasId;
  if(window[key]) window[key].destroy();
  window[key] = new Chart(ctxEl.getContext('2d'), {
    type:'bar',
    data:{ labels:labels, datasets:[{
      data:valores,
      backgroundColor: valores.map(function(v){ return v>=0?VERDE:ROJO; }),
      borderWidth:0, barPercentage:0.9, categoryPercentage:1
    }]},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{legend:{display:false}, tooltip:{mode:'index',intersect:false}},
      scales:{
        x:{ticks:{color:'var(--dim)',font:{size:9},maxTicksLimit:7},grid:{display:false},border:{display:false}},
        y:{ticks:{color:'var(--dim)',font:{size:9}},grid:{display:false},border:{display:false}}
      }
    }
  });
  if(opts.valorEl){
    var v = valores[valores.length-1];
    var el = document.getElementById(opts.valorEl);
    el.textContent = v.toLocaleString('es-ES',{maximumFractionDigits:2});
    el.style.color = v>=0 ? 'var(--up)' : 'var(--dn)';
  }
}

function amplitudDibujarDual(canvasId, serie, campo1, campo2, color1, color2, opts){
  opts = opts || {};
  var ctxEl = document.getElementById(canvasId);
  if(!ctxEl || !serie || !serie.length || serie[serie.length-1][campo1]===undefined) return;
  var labels = serie.map(function(r){ return r.FechaISO || r.Fecha; });
  var v1 = serie.map(function(r){ return r[campo1]; });
  var v2 = serie.map(function(r){ return r[campo2]; });
  var key = '_ampChart_'+canvasId;
  if(window[key]) window[key].destroy();
  window[key] = new Chart(ctxEl.getContext('2d'), {
    type:'line',
    data:{ labels:labels, datasets:[
      {label:campo1, data:v1, borderColor:color1, backgroundColor:'transparent', borderWidth:1.8, pointRadius:0, tension:0.2},
      {label:campo2, data:v2, borderColor:color2, backgroundColor:'transparent', borderWidth:1.8, pointRadius:0, tension:0.2}
    ]},
    options:{
      responsive:true, maintainAspectRatio:false,
      plugins:{
        legend:{display:true, position:'top', align:'end', labels:{boxWidth:10, font:{size:9}, color:'var(--dim)'}},
        tooltip:{mode:'index', intersect:false}
      },
      scales:{
        x:{ticks:{color:'var(--dim)',font:{size:9},maxTicksLimit:7},grid:{display:false},border:{display:false}},
        y:{ticks:{color:'var(--dim)',font:{size:9}},grid:{display:false},border:{display:false}}
      }
    }
  });
  if(opts.valorEl){
    document.getElementById(opts.valorEl).textContent =
      v1[v1.length-1].toLocaleString('es-ES',{maximumFractionDigits:1})+'% / '+v2[v2.length-1].toLocaleString('es-ES',{maximumFractionDigits:1})+'%';
  }
}

// Campos numéricos de una serie (para los grids genéricos de NASDAQ/bonos/
// diarios, cuyos nombres de columna exactos no están confirmados 1:1 con
// NYSE) — se excluyen Fecha/FechaISO y se pinta un gráfico por cada campo
// numérico que la API traiga de verdad, con su nombre real como título.
function amplitudCamposNumericos(serie){
  if(!serie || !serie.length) return [];
  var muestra = serie[serie.length-1];
  return Object.keys(muestra).filter(function(k){
    return k!=='Fecha' && k!=='FechaISO' && typeof muestra[k]==='number';
  });
}

function amplitudRenderGridGenerico(gridId, serie){
  var grid = document.getElementById(gridId);
  if(!grid) return;
  var campos = amplitudCamposNumericos(serie);
  if(!campos.length){ grid.innerHTML=''; return; }
  grid.innerHTML = campos.map(function(campo,i){
    return '<div class="amp-panel"><div class="amp-panel-title">'+campo+' <span class="amp-panel-val" id="'+gridId+'-v-'+i+'"></span></div><div class="amp-panel-chart"><canvas id="'+gridId+'-c-'+i+'"></canvas></div></div>';
  }).join('');
  campos.forEach(function(campo,i){
    amplitudDibujarLinea(gridId+'-c-'+i, serie, campo, {color:['rgb(56,189,248)','rgb(168,85,247)','rgb(34,197,94)','rgb(244,63,94)','rgb(251,191,36)','rgb(251,146,60)'][i%6], valorEl:gridId+'-v-'+i});
  });
}

function amplitudRenderEncuesta(divId, serie){
  var el = document.getElementById(divId);
  if(!el) return;
  if(!serie || !serie.length){ el.innerHTML = '<div style="font-size:11px;color:var(--dim)">Sin datos disponibles</div>'; return; }
  var ultima = serie[serie.length-1];
  var campos = Object.keys(ultima).filter(function(k){ return k!=='Fecha' && k!=='FechaISO' && typeof ultima[k]==='number'; });
  el.innerHTML = '<div style="font-size:10px;color:var(--dim);margin-bottom:8px">Última lectura: '+(ultima.FechaISO||ultima.Fecha)+'</div>'
    + campos.map(function(c){
        return '<div style="display:flex;justify-content:space-between;gap:8px;font-size:12px;padding:4px 0;border-bottom:1px solid var(--b1)"><span style="color:var(--dim)">'+c+'</span><span style="font-weight:700;color:var(--hi)">'+ultima[c]+'</span></div>';
      }).join('');
}

function amplitudCambiarPeriodo(p){
  AMPLITUD_PERIODO = p;
  document.querySelectorAll('.amp-periodo-btn').forEach(function(b){
    b.classList.toggle('active', b.getAttribute('data-periodo')===p);
  });
  amplitudRenderTodo();
}

function amplitudRenderTodo(){
  var api = AMPLITUD_API || {};
  var periodo = AMPLITUD_PERIODO;
  var nyseF    = amplitudFiltrarSerie(api.nyse||[], periodo);
  var nasdaqF  = amplitudFiltrarSerie(api.nasdaq||[], periodo);
  var bonosF   = amplitudFiltrarSerie(api.bonos||[], periodo);
  var diariosF = amplitudFiltrarSerie(api.diarios||[], periodo);
  var aaiiF    = amplitudFiltrarSerie(api.aaii||[], periodo);
  var iiF      = amplitudFiltrarSerie(api.ii||[], periodo);

  // NYSE — nombres de columna confirmados desde la documentación oficial del API
  if(nyseF.length){
    amplitudDibujarLinea('amp-c-adline', nyseF, 'Línea AD NYSE', {color:'rgb(56,189,248)', valorEl:'amp-v-adline'});
    amplitudDibujarLinea('amp-c-adn', nyseF, 'ADn', {color:'rgb(168,85,247)', referencias:[20,50,80], valorEl:'amp-v-adn'});
    amplitudDibujarLinea('amp-c-rasi', nyseF, 'RASI', {color:'rgb(34,197,94)', referencias:[0], valorEl:'amp-v-rasi'});
    amplitudDibujarBarras('amp-c-mcos', nyseF, 'McOS', {valorEl:'amp-v-mcos'});
    amplitudDibujarLinea('amp-c-summation', nyseF, 'SUMMATION INDEX', {color:'rgb(251,191,36)', valorEl:'amp-v-summation'});
    amplitudDibujarDual('amp-c-updown', nyseF, 'Suben', 'Bajan', 'rgb(16,185,129)', 'rgb(244,63,94)');
    amplitudDibujarDual('amp-c-ma', nyseF, 'Valores por encima de su media de 50 sesiones', 'Valores por encima de su media de 200 sesiones', 'rgb(56,189,248)', 'rgb(148,163,184)', {valorEl:'amp-v-ma'});
    amplitudDibujarDual('amp-c-5pct', nyseF, 'Valores a menos 5% máximos', 'Valores a menos 5% mínimos', 'rgb(16,185,129)', 'rgb(244,63,94)', {valorEl:'amp-v-5pct'});
  }

  // NASDAQ — nombres de columna no confirmados 1:1, renderizado genérico
  amplitudRenderGridGenerico('amp-nasdaq-grid', nasdaqF);

  // Bonos: se intenta detectar las columnas de High-Yield y CEF por nombre
  // (contienen "high"/"yield" o "cef"), y el resto de columnas que traiga
  // bonos (10Y, 30Y, spread 10-2) se pintan en el grid genérico de abajo
  var bonosCampos = bonosF.length ? Object.keys(bonosF[bonosF.length-1]) : [];
  var campoHY  = bonosCampos.find(function(k){ return /high|yield/i.test(k); });
  var campoCEF = bonosCampos.find(function(k){ return /cef/i.test(k); });
  if(campoHY)  amplitudDibujarLinea('amp-c-adhy', bonosF, campoHY, {color:'rgb(34,197,94)'});
  if(campoCEF) amplitudDibujarLinea('amp-c-adcef', bonosF, campoCEF, {color:'rgb(251,146,60)'});
  var bonosGrid = document.getElementById('amp-bonos-extra-grid');
  if(bonosGrid){
    var camposRestantes = amplitudCamposNumericos(bonosF).filter(function(c){ return c!==campoHY && c!==campoCEF; });
    if(camposRestantes.length){
      bonosGrid.innerHTML = camposRestantes.map(function(campo,i){
        return '<div class="amp-panel"><div class="amp-panel-title">'+campo+' <span class="amp-panel-val" id="amp-bonos-extra-v-'+i+'"></span></div><div class="amp-panel-chart"><canvas id="amp-bonos-extra-grid-c-'+i+'"></canvas></div></div>';
      }).join('');
      camposRestantes.forEach(function(campo,i){
        amplitudDibujarLinea('amp-bonos-extra-grid-c-'+i, bonosF, campo, {color:'rgb(148,163,184)', valorEl:'amp-bonos-extra-v-'+i});
      });
    } else bonosGrid.innerHTML = '';
  }

  // Diarios (Put/Call, VIX/VXV, etc.) — renderizado genérico, no sabemos
  // el nombre exacto de cada columna
  amplitudRenderGridGenerico('amp-diarios-grid', diariosF);

  // Fear & Greed — última lectura
  var fg = api.fearGreed && api.fearGreed.length ? api.fearGreed[api.fearGreed.length-1] : null;
  var fgEl = document.getElementById('amp-fg-gauge');
  if(fgEl){
    if(fg){
      var valorFG = fg.Valor !== undefined ? fg.Valor : (Object.keys(fg).map(function(k){return fg[k];}).find(function(v){ return typeof v==='number'; }));
      var colorFG = valorFG<25?'var(--dn)':valorFG<45?'var(--warn)':valorFG<55?'var(--dim)':'var(--up)';
      var etiquetaFG = valorFG<25?'Miedo extremo':valorFG<45?'Miedo':valorFG<55?'Neutral':valorFG<75?'Codicia':'Codicia extrema';
      fgEl.innerHTML = '<div style="font-family:Syne,sans-serif;font-size:42px;font-weight:800;color:'+colorFG+'">'+valorFG+'</div><div style="font-size:12px;color:var(--dim)">'+etiquetaFG+'</div>';
    } else fgEl.innerHTML = '<div style="font-size:11px;color:var(--dim)">Sin datos disponibles</div>';
  }

  // Encuestas de sentimiento — se pinta lo que traiga cada una con sus
  // propios nombres de columna (alcistas/bajistas/corrección, etc.)
  amplitudRenderEncuesta('amp-ii-content', iiF);
  amplitudRenderEncuesta('amp-aaii-content', aaiiF);
}

// ── NH/NL TOGGLE ─────────────────────────────────────────────────────────────
let _nhVisible=false,_nhMode='highs';
function toggleNHList(mode){
  const su=D.breadthSummary;
  const list=mode==='highs'?(su.new_highs_list||[]):(su.new_lows_list||[]);
  const el=document.getElementById('nh-list');
  if(_nhVisible&&_nhMode===mode){el.style.display='none';_nhVisible=false;return;}
  _nhMode=mode; _nhVisible=true;
  el.style.display='flex';
  el.innerHTML=list.map(tk=>`<span class="badge ${mode==='highs'?'b-up':'b-dn'}" style="cursor:pointer" onclick="document.getElementById('stk-ticker').value='${tk}';sw('stocks',document.getElementById('tab-stocks-btn'))">${tk}</span>`).join('');
}

// ── EARNINGS ─────────────────────────────────────────────────────────────────
// ── EARNINGS — Resumen de Resultados ──────────────────────────────────────────
let _earnData=[],_earnFilter='all',_earnSearch='',_earnSort={col:-1,asc:-1};
const fmtSales=v=>{if(!v)return'—';const n=parseFloat(v);if(isNaN(n))return'—';if(Math.abs(n)>=1e12)return'$'+(n/1e12).toFixed(2)+'T';if(Math.abs(n)>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(Math.abs(n)>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+n.toFixed(0);};

function loadStock(){
  const tk=(document.getElementById('stk-ticker').value||'').toUpperCase().trim();
  if(!tk)return;
  const sp=D.stockPerf||{};
  const r=sp[tk];
  const info=(D.stockInfo||{})[tk]||null;
  const panel=document.getElementById('stock-panel');
  if(!r){
    panel.innerHTML=`<div style="color:var(--dim);padding:20px;background:var(--bg2);border:1px solid var(--b1);border-radius:8px">
      <strong style="color:var(--hi)">${tk}</strong> no está en los datos precargados.<br>
      Disponibles: acciones de los universos de sectores e industrias.<br>
      <span style="font-size:10px">Añade el ticker en SECTOR_STOCKS o INDUSTRY_DATA y vuelve a ejecutar.</span>
    </div>`;
    return;
  }

  // RS percentile (1Y)
  const allSp=[...Object.values(sp)].filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rank=allSp.findIndex(x=>x.ticker===tk);
  const rs=rank>=0?Math.round(rank/allSp.length*100):null;
  const rsLbl=rs>=80?'⚡ Líder — fuerza relativa alta':rs>=60?'✓ Por encima de la media':rs>=40?'→ En la media':rs>=20?'↓ Bajo la media':'⚠ Fuerza relativa baja';

  const distHi=r['52wHigh']?round2((r.price-r['52wHigh'])/r['52wHigh']*100):null;
  const distLo=r['52wLow']? round2((r.price-r['52wLow'])/r['52wLow']*100):null;

  // Format helpers
  const fmtM=v=>{if(!v)return'—';const n=Number(v);if(isNaN(n))return'—';if(Math.abs(n)>=1e12)return'$'+(n/1e12).toFixed(2)+'T';if(Math.abs(n)>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(Math.abs(n)>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+n.toFixed(0);};
  const fmtP=v=>v!==null&&v!==undefined?Math.round(v*100)+'%':'—';
  const fmtX=v=>v!==null&&v!==undefined?Number(v).toFixed(1)+'x':'—';
  const fmtR=v=>v!==null&&v!==undefined?Number(v).toFixed(2):'—';

  const analystText=info?.analyst?(['','Compra Fuerte','Compra','Mantener','Vender','Vender Fuerte'][Math.round(info.analyst)]||info.analyst):'—';
  const analystCls=info?.analyst?(info.analyst<=2?'up':info.analyst<=3?'neu':'dn'):'neu';

  // Fundamentals section (only if info available)
  const fundHTML=info?`
    <div class="sh" style="margin-top:2px"><span class="st" style="font-size:12px">FUNDAMENTALES — ${info.name||tk}</span></div>
    <div style="font-size:10px;color:var(--dim);margin-bottom:10px">${info.sector||''} ${info.industry?'· '+info.industry:''} ${info.country?'· '+info.country:''}</div>
    <div class="stock-metrics" style="margin-bottom:12px">
      ${metCard('Mkt Cap',fmtM(info.mktCap))}
      ${metCard('P/E Trailing',fmtR(info.pe))}
      ${metCard('P/E Forward',fmtR(info.fwdPE))}
      ${metCard('PEG Ratio',fmtR(info.peg))}
      ${metCard('P/B',fmtR(info.pb))}
      ${metCard('P/S (TTM)',fmtR(info.ps))}
      ${metCard('EPS (TTM)',info.eps?'$'+Number(info.eps).toFixed(2):'—')}
      ${metCard('EPS Fwd',info.fwdEps?'$'+Number(info.fwdEps).toFixed(2):'—')}
      ${metCard('Revenue',fmtM(info.revenue))}
      ${metCard('EBITDA',fmtM(info.ebitda))}
      ${metCard('FCF',fmtM(info.fcf))}
      ${metCard('Div Yield',fmtP(info.divYield))}
      ${metCard('Beta',fmtR(info.beta))}
      ${metCard('Gross Margin',fmtP(info.grossMarg))}
      ${metCard('Op Margin',fmtP(info.opMarg))}
      ${metCard('Net Margin',fmtP(info.netMarg))}
      ${metCard('ROE',fmtP(info.roe))}
      ${metCard('ROA',fmtP(info.roa))}
      ${metCard('Debt/Equity',fmtR(info.debtEq))}
      ${metCard('Current Ratio',fmtR(info.currentRatio))}
      ${metCard('Rev Growth',info.revGrowth!==null?`<span class="${info.revGrowth>0?'up':'dn'}">${fmtP(info.revGrowth)}</span>`:'—')}
      ${metCard('EPS Growth',info.epsGrowth!==null?`<span class="${info.epsGrowth>0?'up':'dn'}">${fmtP(info.epsGrowth)}</span>`:'—')}
      ${metCard('Analistas',info.nAnalysts||'—')}
      ${metCard('Recomendación',`<span class="${analystCls}">${analystText}</span>`)}
      ${metCard('Precio Objetivo',info.targetMean?'$'+Number(info.targetMean).toFixed(0):'—')}
      ${metCard('Empleados',info.employees?info.employees.toLocaleString():'—')}
    </div>
    ${info.summary?`<div style="font-size:10px;color:var(--dim);background:var(--bg3);border-radius:7px;padding:10px 12px;margin-bottom:14px;line-height:1.6">${info.summary}...</div>`:''}
  `:`<div style="font-size:10px;color:var(--dim);margin-bottom:14px;background:var(--bg2);border:1px solid var(--b1);border-radius:7px;padding:10px 12px">
    <strong style="color:var(--hi)">${tk}</strong> — Sin fundamentales disponibles para este ticker.<br>
    <span style="font-size:10px">Cubrimos ratios y fundamentales para ~1.343 acciones (Financials & Ratios, Massive) — este ticker en concreto no está en ese universo o Massive no tiene dato para él.
    Busca en <a href="https://finance.yahoo.com/quote/${tk}" target="_blank" style="color:var(--ac)">Yahoo Finance</a> 
    o <a href="https://finviz.com/quote.ashx?t=${tk}" target="_blank" style="color:var(--ac)">Finviz</a>.</span>
  </div>`;

  const rsCls=rs>=80?'up':rs>=50?'ac':'dn';
  const rsIcon=rs>=80?'⚡':rs>=60?'✓':rs>=40?'→':rs>=20?'↓':'⚠';
  const volPct=r.volRel?Math.min(100,r.volRel/3*100):0;
  const volColor=r.volRel>1.5?'var(--up)':r.volRel<0.5?'var(--dn)':'var(--ac)';

  // ATR Extension for this stock (formula real: SMA50 + ATR-14, igual indicador Pine)
  const atrExt=calcAtrMultiple(r.ohlc);
  const atrColor=atrExt!==null?(atrExt>10?'var(--dn)':atrExt>5?'var(--warn)':atrExt<0?'var(--dn)':'var(--up)'):'var(--dim)';

  panel.innerHTML=`
    <!-- HEADER — ticker + precio + RS + métricas en una sola pieza compacta -->
    <div class="stock-header">
      <!-- ROW 1: Nombre, precio, sector, badges -->
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap">
        <div style="flex:1;min-width:260px">
          <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">
            <h2 style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:var(--hi)">${tk}</h2>
            ${info?`<span style="font-family:Syne,sans-serif;font-size:16px;color:var(--dim);font-weight:500">${info.name||''}</span>`:''}
            ${atrExt!==null?`<span style="font-size:11px;font-weight:700;padding:3px 9px;border-radius:99px;background:${atrColor};color:#fff;opacity:.9" title="Distancia a SMA50 en multiplos de ATR-14">${atrExt>=0?'+':''}${atrExt.toFixed(1)}x ATR</span>`:''}
          </div>
          ${info?`<div class="stk-sector-tag" style="font-size:12px;margin:5px 0">
            <span style="color:var(--ac)">📂 ${info.sector||'—'}</span>
            <span style="color:var(--dim)"> · ${info.industry||'—'} · ${info.country||''}</span>
          </div>`:''}
          <div class="stock-price ${(r['1D']||0)>=0?'up':'dn'}" style="font-size:26px">
            $${r.price}
            <span style="font-size:18px;margin-left:10px">${fmt(r['1D'])}</span>
            <span style="font-size:11px;color:var(--dim);margin-left:6px">HOY</span>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
            ${r.newHi?'<span class="badge b-up" style="font-size:11px">★ 52W Máximo</span>':''}
            ${r.newLo?'<span class="badge b-dn" style="font-size:11px">✗ 52W Mínimo</span>':''}
            ${info?.exchange?`<span class="badge b-neu">${info.exchange}</span>`:''}
            ${rs>=80?'<span class="badge b-up" style="font-size:11px">⚡ Líder RS</span>':rs>=65?'<span class="badge b-up" style="font-size:11px">✓ RS Alto</span>':''}
          </div>
        </div>
        <!-- RS box -->
        <div style="text-align:center;flex-shrink:0;background:var(--bg3);border-radius:14px;padding:18px 24px;border:1px solid var(--b1);min-width:130px">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px">Relative Strength</div>
          <div class="stk-rs-num" style="color:${rs>=80?'var(--up)':rs>=50?'var(--ac)':'var(--dn)'};">${rs??'—'}</div>
          <div style="font-size:10px;color:var(--dim);margin-top:2px">de 100</div>
          <div class="rs-bar" style="margin:10px auto 0;width:88px"><div class="rs-dot" style="left:${rs??50}%"></div></div>
          <div style="font-size:10px;color:var(--dim);margin-top:8px;max-width:100px;line-height:1.4">${rsIcon} ${rsLbl.split(' — ')[0]}</div>
        </div>
      </div>

      <!-- ROW 2: Vol bar + ATR Extension + precio objetivo (si disponible) -->
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px">
        <!-- Vol rel -->
        <div style="background:var(--bg3);border-radius:8px;padding:10px 14px;border:1px solid var(--b1)">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">Volumen Relativo</div>
          <div style="font-size:20px;font-weight:800;font-family:Syne,sans-serif;color:${volColor}">${r.volRel?r.volRel+'x':'—'}</div>
          <div class="stk-vol-bar" style="margin-top:8px"><div class="stk-vol-fill" style="width:${volPct}%;background:${volColor}"></div></div>
          <div style="font-size:9px;color:var(--dim);margin-top:5px">${r.volRel>2?'🔥 Muy alto':''}${r.volRel>1.5&&r.volRel<=2?'⚡ Alto':''}${r.volRel&&r.volRel<=1.5?'Normal':''}</div>
        </div>
        <!-- ATR Extension -->
        <div style="background:var(--bg3);border-radius:8px;padding:10px 14px;border:1px solid var(--b1)">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">ATR Extension (vs MA50)</div>
          <div style="font-size:20px;font-weight:800;font-family:Syne,sans-serif;color:${atrColor}">${atrExt!==null?atrExt.toFixed(2)+'x':'—'}</div>
          <div style="font-size:9px;color:var(--dim);margin-top:8px">${atrExt!==null?(atrExt>12?'🚨 Muy extendido — riesgo reversión':atrExt>7?'⚠️ Extendido, precaución':atrExt>2?'✅ Zona normal':atrExt>0?'✅ Cerca de MA50':atrExt<0?'📉 Bajo MA50, debilidad':''):'Sin datos'}</div>
        </div>
        <!-- Precio objetivo -->
        <div style="background:var(--bg3);border-radius:8px;padding:10px 14px;border:1px solid var(--b1)">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">Analistas (${info?.nAnalysts||0})</div>
          <div style="font-size:20px;font-weight:800;font-family:Syne,sans-serif;color:var(--hi)">${info?.targetMean?'$'+Number(info.targetMean).toFixed(0):'—'}</div>
          <div style="font-size:9px;color:var(--dim);margin-top:8px">${info?.analyst?(['','🟢 Compra fuerte','🟢 Compra','🟡 Mantener','🔴 Vender','🔴 Vender fuerte'][Math.round(info.analyst)]||'—'):'—'}</div>
        </div>
      </div>

      <!-- ROW 3: Métricas de precio — grid compacto -->
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px;border-top:1px solid var(--b1);padding-top:12px">
        ${hdrMet('1D',fmt(r['1D']))}${hdrMet('1W',fmt(r['1W']))}${hdrMet('1M',fmt(r['1M']))}
        ${hdrMet('3M',fmt(r['3M']))}${hdrMet('1Y',fmt(r['1Y']))}
        ${hdrMet('52W High','$'+(r['52wHigh']||'—'))}${hdrMet('52W Low','$'+(r['52wLow']||'—'))}
        ${distHi!==null?hdrMet('vs Máx',`<span class="${distHi>=-5?'up':'dn'}">${distHi}%</span>`):''}
        ${hdrMet('MA20',r.abv20!==null?`<span class="${r.abv20?'up':'dn'}">${r.abv20?'▲':'▼'} $${r.ma20}</span>`:'—')}
        ${hdrMet('MA50',r.abv50!==null?`<span class="${r.abv50?'up':'dn'}">${r.abv50?'▲':'▼'} $${r.ma50}</span>`:'—')}
        ${hdrMet('MA200',r.abv200!==null?`<span class="${r.abv200?'up':'dn'}">${r.abv200?'▲':'▼'} $${r.ma200}</span>`:'—')}
      </div>
    </div>

    <!-- GRÁFICO TRADINGVIEW — tiempo real -->
    <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:10px;margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px">
        <span style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:var(--hi)">GRÁFICO — Tiempo real</span>
        <span style="font-size:10px;color:var(--dim)">Powered by TradingView</span>
      </div>
      <div id="tv-widget-container" style="height:420px;border-radius:8px;overflow:hidden;background:var(--bg3)"></div>
    </div>

    <!-- FUNDAMENTALES -->
    ${fundHTML}
  `;
  loadTVWidget(tk);
}

function loadTVWidget(ticker){
  var container=document.getElementById('tv-widget-container');
  if(!container) return;
  container.innerHTML='';
  var script=document.createElement('script');
  script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.async=true;
  script.innerHTML=JSON.stringify({
    "autosize":true,"symbol":ticker,"interval":"D",
    "timezone":"Europe/Madrid","theme":"light","style":"1","locale":"es",
    "backgroundColor":"rgba(255,255,255,1)","gridColor":"rgba(242,243,245,1)",
    "hide_top_toolbar":false,"hide_legend":false,"save_image":false,
    "support_host":"https://www.tradingview.com",
    "height":420,"width":"100%",
    "studies":["STD;MA"]
  });
  container.appendChild(script);
}

function drawStkCandle(canvas,ohlcArr){
  if(!canvas||!ohlcArr||!ohlcArr.length)return;
  const dpr=window.devicePixelRatio||1;
  const W=canvas.parentElement.clientWidth||800;
  const H=parseInt(canvas.getAttribute('height')||220);
  canvas.width=W*dpr; canvas.height=H*dpr;
  canvas.style.width=W+'px'; canvas.style.height=H+'px';
  const cx=canvas.getContext('2d');
  cx.scale(dpr,dpr);
  const pad={t:20,r:10,b:26,l:58};
  const cw=W-pad.l-pad.r, ch=H-pad.t-pad.b;
  const mn=Math.min(...ohlcArr.map(d=>d.l));
  const mx=Math.max(...ohlcArr.map(d=>d.h));
  const rng=mx-mn||1;
  const scY=v=>pad.t+ch-(v-mn)/rng*ch;
  const n=ohlcArr.length;
  const bw=Math.max(2,Math.floor(cw/n)-1);
  const xc=i=>pad.l+i*(cw/n)+cw/(n*2);
  cx.fillStyle='#0c0f18'; cx.fillRect(0,0,W,H);
  cx.strokeStyle='#1c2436'; cx.lineWidth=0.5;
  for(let i=0;i<=4;i++){
    const y=pad.t+ch/4*i;
    cx.beginPath();cx.moveTo(pad.l,y);cx.lineTo(W-pad.r,y);cx.stroke();
    cx.fillStyle='#3a4860';cx.font='9px monospace';cx.textAlign='right';
    cx.fillText('$'+(mx-rng/4*i).toFixed(2),pad.l-4,y+3);
  }
  const cl=ohlcArr.map(d=>d.c);
  const drawML=(arr,col)=>{
    cx.strokeStyle=col;cx.lineWidth=1.2;cx.beginPath();let s2=false;
    arr.forEach((v,i)=>{if(v===null)return;const x=xc(i),y=scY(v);s2?cx.lineTo(x,y):cx.moveTo(x,y);s2=true;});
    cx.stroke();
  };
  const k9=2/10; let e9=cl[0];
  const ema9=cl.map((c,i)=>{if(i===0){e9=c;return c;}e9=c*k9+e9*(1-k9);return Math.round(e9*100)/100;});
  drawML(ema9,'rgba(167,139,250,.8)');
  drawML(cl.map((_,i)=>i>=19?cl.slice(i-19,i+1).reduce((a,b)=>a+b)/20:null),'rgba(245,158,11,.8)');
  drawML(cl.map((_,i)=>i>=49?cl.slice(i-49,i+1).reduce((a,b)=>a+b)/50:null),'rgba(56,189,248,.8)');
  ohlcArr.forEach((d,i)=>{
    const x=xc(i),up=d.c>=d.o,col=up?'#10b981':'#f43f5e',hw=Math.max(1,bw/2-1);
    cx.strokeStyle=col;cx.lineWidth=1;
    cx.beginPath();cx.moveTo(x,scY(d.h));cx.lineTo(x,scY(d.l));cx.stroke();
    const top=scY(Math.max(d.o,d.c)),bot=scY(Math.min(d.o,d.c));
    cx.fillStyle=col;cx.fillRect(x-hw,top,hw*2,Math.max(1,bot-top));
  });
  cx.fillStyle='#3a4860';cx.font='9px monospace';cx.textAlign='center';
  ohlcArr.forEach((d,i)=>{if(i%15===0||i===n-1)cx.fillText(d.t.slice(5),xc(i),H-4);});
}

function metCard(l,v){
  return `<div class="sm-c"><div class="sm-l">${l}</div><div class="sm-v">${v}</div></div>`;
}
function hdrMet(l,v){
  return `<div style="background:var(--bg3);border-radius:5px;padding:6px 8px"><div style="font-size:8px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">${l}</div><div style="font-size:11px;font-weight:600;color:var(--hi)">${v}</div></div>`;
}
function metCardMA(l,ma,price,abv){
  const diff=ma&&price?round2((price/ma-1)*100):null;
  return `<div class="sm-c">
    <div class="sm-l">${l}: ${ma?'$'+ma:'—'}</div>
    <div class="sm-v">
      ${abv!==null?`<span class="badge ${abv?'b-up':'b-dn'}">${abv?'▲ encima':'▼ debajo'}</span>`:'—'}
      ${diff!==null?` <span class="${abv?'up':'dn'}" style="font-size:11px">${diff>0?'+':''}${diff}%</span>`:''}
    </div>
  </div>`;
}
function round2(n){return Math.round(n*100)/100;}

// ── TABS ──────────────────────────────────────────────────────────────────────
function scrollTabs(dir){
  const el=document.getElementById('tabs-scroll');
  if(!el) return;
  el.scrollBy({left: dir*160, behavior:'smooth'});
}
function updateTabsArrows(){
  const el=document.getElementById('tabs-scroll');
  const lBtn=document.querySelector('.tabs-arrow-l');
  const rBtn=document.querySelector('.tabs-arrow-r');
  if(!el||!lBtn||!rBtn) return;
  const hasOverflow=el.scrollWidth>el.clientWidth+2;
  if(!hasOverflow){
    lBtn.classList.remove('show');
    rBtn.classList.remove('show');
    return;
  }
  const atStart=el.scrollLeft<=2;
  const atEnd=el.scrollLeft+el.clientWidth>=el.scrollWidth-2;
  lBtn.classList.toggle('show',!atStart);
  rBtn.classList.toggle('show',!atEnd);
}
(function initTabsArrowWatcher(){
  const el=document.getElementById('tabs-scroll');
  if(!el) return;
  el.addEventListener('scroll',updateTabsArrows,{passive:true});
  window.addEventListener('resize',updateTabsArrows);
  if(window.ResizeObserver){
    new ResizeObserver(updateTabsArrows).observe(el);
  }
  // Reintentos tras carga inicial/fuentes/zoom, por si el layout aun no esta listo
  setTimeout(updateTabsArrows,50);
  setTimeout(updateTabsArrows,300);
  setTimeout(updateTabsArrows,1000);
  if(document.readyState==='complete'){ updateTabsArrows(); }
  else { window.addEventListener('load',updateTabsArrows); }
})();
function sw(n,btn){
  document.querySelectorAll('.tc').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+n).classList.add('active');
  if(btn){ btn.classList.add('active'); btn.scrollIntoView({behavior:'smooth',inline:'center',block:'nearest'}); }
  if(n==='breadth') renderBreadthTab();
  if(n==='briefing') renderBriefing();
  if(n==='cartera'&&!carteraLoaded){carteraLoaded=true;initCartera();}
  if(n==='broker'){
    if(!brokerLoaded){brokerLoaded=true;initBroker();}
    else if(typeof bkSetDiscreto==='function') bkSetDiscreto(true); // re-ocultar siempre al volver a la pestaña
  }
  if(n==='fiscal'){
    if(!brokerLoaded){brokerLoaded=true;initBroker();}
    else if(typeof fcSetDiscreto==='function') fcSetDiscreto(true); // re-ocultar siempre al volver a la pestaña
  }
  if(n==='comunidad'){initComunidad();}
  if(n==='diario'){initDiario();}
  if(n==='alertas'){initAlertas();}
  if(n==='favoritas') renderFavoritas();
  if(n==='fundamentales'&&!fundamentalesLoaded){fundamentalesLoaded=true;initFundamentales();}
}
// ── FUNDAMENTALES / SCREENER (estilo Finviz) ──────────────────────────────────
const FUND_METRICS=[
  {key:'mktCap',   label:'Market Cap',  buckets:[['Cualquiera',v=>true],['Mega (>$200B)',v=>v!=null&&v>200e9],['Large ($10-200B)',v=>v!=null&&v>=10e9&&v<=200e9],['Mid ($2-10B)',v=>v!=null&&v>=2e9&&v<10e9],['Small ($300M-2B)',v=>v!=null&&v>=300e6&&v<2e9],['Micro (<$300M)',v=>v!=null&&v<300e6]]},
  {key:'avgVolume',label:'Vol. Medio',  buckets:[['Cualquiera',v=>true],['>10M',v=>v!=null&&v>10e6],['>1M',v=>v!=null&&v>1e6],['>100K',v=>v!=null&&v>1e5],['Baja liquidez (<100K)',v=>v!=null&&v<1e5]]},
  {key:'pe',       label:'P/E',         buckets:[['Cualquiera',v=>true],['Negativo',v=>v!=null&&v<0],['<10',v=>v!=null&&v>0&&v<10],['<15',v=>v!=null&&v>0&&v<15],['<20',v=>v!=null&&v>0&&v<20],['<30',v=>v!=null&&v>0&&v<30],['<50',v=>v!=null&&v>0&&v<50],['Alto (>50)',v=>v!=null&&v>50]]},
  {key:'pb',       label:'P/B',         buckets:[['Cualquiera',v=>true],['<1',v=>v!=null&&v<1],['<3',v=>v!=null&&v<3],['<5',v=>v!=null&&v<5],['<10',v=>v!=null&&v<10],['Alto (>10)',v=>v!=null&&v>10]]},
  {key:'ps',       label:'P/S',         buckets:[['Cualquiera',v=>true],['<1',v=>v!=null&&v<1],['<3',v=>v!=null&&v<3],['<5',v=>v!=null&&v<5],['<10',v=>v!=null&&v<10],['Alto (>10)',v=>v!=null&&v>10]]},
  {key:'evEbitda', label:'EV/EBITDA',   buckets:[['Cualquiera',v=>true],['<10',v=>v!=null&&v<10],['<15',v=>v!=null&&v<15],['<20',v=>v!=null&&v<20],['<30',v=>v!=null&&v<30],['Alto (>30)',v=>v!=null&&v>30]]},
  {key:'evSales',  label:'EV/Sales',    buckets:[['Cualquiera',v=>true],['<1',v=>v!=null&&v<1],['<3',v=>v!=null&&v<3],['<5',v=>v!=null&&v<5],['<10',v=>v!=null&&v<10],['Alto (>10)',v=>v!=null&&v>10]]},
  {key:'roe',      label:'ROE',         buckets:[['Cualquiera',v=>true],['Negativo',v=>v!=null&&v<0],['>10%',v=>v!=null&&v>0.10],['>15%',v=>v!=null&&v>0.15],['>20%',v=>v!=null&&v>0.20],['>30%',v=>v!=null&&v>0.30]]},
  {key:'roa',      label:'ROA',         buckets:[['Cualquiera',v=>true],['Negativo',v=>v!=null&&v<0],['>5%',v=>v!=null&&v>0.05],['>10%',v=>v!=null&&v>0.10],['>15%',v=>v!=null&&v>0.15]]},
  {key:'debtEq',   label:'Deuda/Equity',buckets:[['Cualquiera',v=>true],['<0.5',v=>v!=null&&v<0.5],['<1',v=>v!=null&&v<1],['<2',v=>v!=null&&v<2],['Alto (>2)',v=>v!=null&&v>2]]},
  {key:'currentRatio', label:'Current Ratio', buckets:[['Cualquiera',v=>true],['Riesgo (<1)',v=>v!=null&&v<1],['1-2 (sano)',v=>v!=null&&v>=1&&v<=2],['>2',v=>v!=null&&v>2]]},
  {key:'grossMargin', label:'Margen Bruto', buckets:[['Cualquiera',v=>true],['<20%',v=>v!=null&&v<0.20],['20-40%',v=>v!=null&&v>=0.20&&v<0.40],['40-60%',v=>v!=null&&v>=0.40&&v<0.60],['>60%',v=>v!=null&&v>=0.60],['>80% (software/SaaS)',v=>v!=null&&v>=0.80]]},
  {key:'divYield', label:'Div. Yield',  buckets:[['Cualquiera',v=>true],['Sin dividendo',v=>v==null||v<=0],['>1%',v=>v!=null&&v>0.01],['>2%',v=>v!=null&&v>0.02],['>3%',v=>v!=null&&v>0.03],['>5%',v=>v!=null&&v>0.05]]},
  {key:'freeFloatPct', label:'Float %',     buckets:[['Cualquiera',v=>true],['Micro-float (<10%)',v=>v!=null&&v<10],['<25%',v=>v!=null&&v<25],['<50%',v=>v!=null&&v<50],['>50%',v=>v!=null&&v>50],['>75%',v=>v!=null&&v>75]]},
  {key:'daysToCover', label:'Días cubrir corto', buckets:[['Cualquiera',v=>true],['<1',v=>v!=null&&v<1],['<3',v=>v!=null&&v<3],['<5',v=>v!=null&&v<5],['Alto (>5)',v=>v!=null&&v>5],['Muy alto (>10)',v=>v!=null&&v>10]]},
  {key:'revGrowth', label:'Crec. Ventas YoY', buckets:[['Cualquiera',v=>true],['Negativo',v=>v!=null&&v<0],['>5%',v=>v!=null&&v>0.05],['>10%',v=>v!=null&&v>0.10],['>20%',v=>v!=null&&v>0.20],['>30%',v=>v!=null&&v>0.30]]},
  {key:'epsGrowth', label:'Crec. EPS YoY',   buckets:[['Cualquiera',v=>true],['Negativo',v=>v!=null&&v<0],['>10%',v=>v!=null&&v>0.10],['>20%',v=>v!=null&&v>0.20],['>30%',v=>v!=null&&v>0.30],['>50%',v=>v!=null&&v>0.50]]},
  {key:'isADR',    label:'ADR',         buckets:[['Cualquiera',v=>true],['Solo ADR',v=>v===true],['Excluir ADR',v=>v!==true]]},
];
const FUND_COLS=[['#',null],['Ticker','tk'],['Sector',null],['Precio','price'],['Mkt Cap','mktCap'],['P/E','pe'],['P/B','pb'],['P/S','ps'],['EV/EBITDA','evEbitda'],['ROE','roe'],['ROA','roa'],['Margen Bruto','grossMargin'],['Deuda/Eq','debtEq'],['Div Yield','divYield'],['Float %','freeFloatPct'],['Días cubrir','daysToCover'],['Crec. Ventas','revGrowth'],['Crec. EPS','epsGrowth']];
const FUND_DESC={
  grossMargin:'Beneficio bruto ÷ ventas (ingresos − coste de lo vendido). Software/SaaS suele estar >70-80%; retail/industrial suele ser mucho más bajo (20-40%).',
  mktCap:'Capitalización de mercado = precio × acciones en circulación. Mega/Large suelen ser más estables; Small/Micro más volátiles pero con más potencial de crecimiento.',
  avgVolume:'Volumen medio de negociación diario. Baja liquidez implica spreads más amplios y más dificultad para entrar/salir de la posición.',
  pe:'Precio ÷ beneficio por acción (TTM). Cuánto pagas por cada € de beneficio anual. Más bajo = más "barata" en teoría, pero puede reflejar bajo crecimiento.',
  pb:'Precio ÷ valor contable. Compara el precio con el patrimonio neto. Útil en bancos/aseguradoras; menos en tecnológicas con poco activo físico.',
  ps:'Precio ÷ ventas (TTM). Sirve para comparar empresas que aún no tienen beneficio.',
  evEbitda:'Valor de empresa (deuda + capitalización − caja) ÷ EBITDA. Valoración que sí tiene en cuenta la deuda, a diferencia del P/E.',
  evSales:'Valor de empresa ÷ ventas. Similar al P/S pero incluyendo deuda — más completo para comparar empresas con distinto apalancamiento.',
  roe:'Rentabilidad sobre el patrimonio (beneficio ÷ fondos propios). Cuánto beneficio genera la empresa con el dinero de los accionistas.',
  roa:'Rentabilidad sobre activos totales. Mide eficiencia usando TODOS sus recursos, no solo el capital propio.',
  debtEq:'Deuda total ÷ patrimonio neto. Por encima de 1-2 suele indicar apalancamiento alto (más riesgo, más sensible a tipos de interés).',
  currentRatio:'Activo corriente ÷ pasivo corriente. Por debajo de 1 puede indicar problemas para pagar deudas a corto plazo; entre 1-2 se considera sano.',
  divYield:'Dividendo anual ÷ precio de la acción. Rentabilidad por dividendo a precio actual.',
  freeFloatPct:'% de acciones que cotizan libremente en el mercado (excluye insiders/bloqueadas). Float bajo = menos liquidez y más volatilidad ante noticias.',
  daysToCover:'Días que tardarían los bajistas en recomprar todas sus posiciones cortas al volumen medio actual. Alto (>5-10) = posible short squeeze si sube el precio.',
  revGrowth:'Crecimiento de ventas del último trimestre vs el mismo trimestre del año anterior (YoY).',
  epsGrowth:'Crecimiento del beneficio por acción del último trimestre vs el mismo trimestre del año anterior (YoY).',
  isADR:'ADR = American Depositary Receipt. Acción de una empresa extranjera (no de EEUU) que cotiza en bolsa americana.',
};
function resetFundFiltros(){
  const searchEl=document.getElementById('fund-search');
  if(searchEl) searchEl.value='';
  FUND_METRICS.forEach(m=>{
    const sel=document.getElementById('fund-f-'+m.key);
    if(sel) sel.value='0';
  });
  renderFundamentales();
}
function initFundamentales(){
  const fWrap=document.getElementById('fund-filters');
  let fh='<input type="text" id="fund-search" placeholder="Buscar ticker…" style="padding:5px 8px;font-size:11px;border-radius:4px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)" oninput="renderFundamentales()">';
  FUND_METRICS.forEach(m=>{
    const desc=(FUND_DESC[m.key]||'').replace(/"/g,'&quot;');
    fh+=`<select id="fund-f-${m.key}" onchange="renderFundamentales()" title="${desc}" style="padding:5px 8px;font-size:11px;border-radius:4px;border:1px solid var(--b2);background:var(--bg2);color:var(--tx)">`;
    m.buckets.forEach((b,i)=>{ fh+=`<option value="${i}">${m.label}: ${b[0]}</option>`; });
    fh+='</select>';
  });
  fh+='<button class="pb" onclick="resetFundFiltros()" id="fund-reset-btn" style="display:none">✕ Quitar filtros</button>';
  fWrap.innerHTML=fh;
  const gloss=document.getElementById('fund-glossary');
  if(gloss){
    gloss.innerHTML=FUND_METRICS.map(m=>`<div style="margin-bottom:6px;break-inside:avoid"><strong style="color:var(--tx)">${m.label}:</strong> ${FUND_DESC[m.key]||''}</div>`).join('');
  }
  let th='';
  FUND_COLS.forEach((c,i)=>{
    const sortable=c[1]&&c[1]!=='tk';
    th+= sortable ? `<th onclick="srt('fund-tbody',${i})" style="cursor:pointer">${c[0]}</th>`
                  : `<th${i===0?' style="width:36px"':''}${i<=1?' style="text-align:left"':''}>${c[0]}</th>`;
  });
  document.getElementById('fund-thead').innerHTML=th;
  renderFundamentales();
}
function fundFmtCap(v){ if(v==null)return'—'; if(v>=1e12)return(v/1e12).toFixed(2)+'T'; if(v>=1e9)return(v/1e9).toFixed(2)+'B'; if(v>=1e6)return(v/1e6).toFixed(1)+'M'; return v.toFixed(0); }
function fundFmtNum(v,d=2){ return v==null?'—':v.toFixed(d); }
function fundFmtPct(v){ return v==null?'—':(v*100).toFixed(1)+'%'; }
function renderFundamentales(){
  const R=D.ratiosData||{}, P=D.stockPerf||{}, SEC=D.tickerSector||{};
  const search=(document.getElementById('fund-search')?.value||'').toUpperCase().trim();
  let numActivos=0;
  const active=FUND_METRICS.map(m=>{
    const sel=document.getElementById('fund-f-'+m.key);
    const idx=sel?parseInt(sel.value):0;
    // Resaltar visualmente los filtros que no están en "Cualquiera" (índice 0)
    if(sel){
      if(idx>0){ sel.style.borderColor='var(--ac)'; sel.style.background='rgba(79,110,247,.08)'; sel.style.fontWeight='600'; numActivos++; }
      else { sel.style.borderColor='var(--b2)'; sel.style.background='var(--bg2)'; sel.style.fontWeight='normal'; }
    }
    return m.buckets[idx][1];
  });
  const resetBtn=document.getElementById('fund-reset-btn');
  if(resetBtn) resetBtn.style.display = (numActivos>0||search) ? '' : 'none';
  if(resetBtn) resetBtn.textContent = '✕ Quitar filtros' + (numActivos>0?' ('+numActivos+')':'');
  let rows=Object.keys(R).map(tk=>{
    const r=R[tk]||{}, p=P[tk]||{};
    return {tk, pe:r.pe, pb:r.pb, ps:r.ps, evEbitda:r.evEbitda, evSales:r.evSales, roe:r.roe, roa:r.roa,
            debtEq:r.debtEq, divYield:r.divYield, mktCap:r.mktCap, avgVolume:r.avgVolume, currentRatio:r.currentRatio,
            grossMargin:r.grossMargin,
            freeFloatPct:r.freeFloatPct, daysToCover:r.daysToCover,
            revGrowth:r.revGrowth, epsGrowth:r.epsGrowth, isADR:r.isADR===true,
            price:(r.price!=null?r.price:p.price), sector:SEC[tk]||'—'};
  });
  if(search) rows=rows.filter(r=>r.tk.toUpperCase().includes(search));
  FUND_METRICS.forEach((m,i)=>{ rows=rows.filter(r=>active[i](r[m.key])); });
  rows.sort((a,b)=>(b.mktCap||0)-(a.mktCap||0));
  window._fundData=rows;
  document.getElementById('fund-count').textContent=rows.length;
  let html='';
  rows.forEach((r,i)=>{
    html+=`<tr>
      <td style="color:var(--dim)">${i+1}</td>
      <td style="text-align:left;font-weight:600;cursor:pointer;color:var(--ac2)" onclick="sw('stocks',document.getElementById('tab-stocks-btn'));document.getElementById('stk-ticker').value='${r.tk}';loadStock();">${r.tk}${r.isADR?' <span style="font-size:9px;color:var(--dim);border:1px solid var(--b2);border-radius:3px;padding:0 3px">ADR</span>':''}</td>
      <td style="font-size:10px;color:var(--dim)">${r.sector}</td>
      <td>${r.price!=null?'$'+Number(r.price).toFixed(2):'—'}</td>
      <td>${fundFmtCap(r.mktCap)}</td>
      <td>${fundFmtNum(r.pe)}</td>
      <td>${fundFmtNum(r.pb)}</td>
      <td>${fundFmtNum(r.ps)}</td>
      <td>${fundFmtNum(r.evEbitda)}</td>
      <td>${fundFmtPct(r.roe)}</td>
      <td>${fundFmtPct(r.roa)}</td>
      <td>${fundFmtPct(r.grossMargin)}</td>
      <td>${fundFmtNum(r.debtEq)}</td>
      <td>${fundFmtPct(r.divYield)}</td>
      <td>${r.freeFloatPct!=null?r.freeFloatPct.toFixed(1)+'%':'—'}</td>
      <td>${fundFmtNum(r.daysToCover,1)}</td>
      <td>${fundFmtPct(r.revGrowth)}</td>
      <td>${fundFmtPct(r.epsGrowth)}</td>
    </tr>`;
  });
  document.getElementById('fund-tbody').innerHTML= html || '<tr><td colspan="18" style="text-align:center;color:var(--dim);padding:20px">Sin resultados con estos filtros</td></tr>';
}
// ── PERIOD ────────────────────────────────────────────────────────────────────
function sp(k,p,btn){
  PD[k]=p;
  document.querySelectorAll(`#p${k} .pb`).forEach(b=>b.classList.remove('active'));
  btn.classList.add('active'); renderHM(k); renderTbl(k);
}
// ── SORT ──────────────────────────────────────────────────────────────────────
function srt(id,col){
  const tb=document.getElementById(id);
  const rows=Array.from(tb.querySelectorAll('tr'));
  const asc=SS[id]===col?-1:1; SS[id]=asc===1?col:null;
  rows.sort((a,b)=>{
    const va=a.cells[col].innerText.replace(/[+%$,▲▼★✗]/g,'').trim();
    const vb=b.cells[col].innerText.replace(/[+%$,▲▼★✗]/g,'').trim();
    const na=parseFloat(va),nb=parseFloat(vb);
    if(!isNaN(na)&&!isNaN(nb))return(na-nb)*asc;
    return va.localeCompare(vb)*asc;
  });
  rows.forEach(r=>tb.appendChild(r));
  document.querySelectorAll(`#${id} th`).forEach((th,i)=>th.classList.toggle('srt',i===col));
  if(id==='tb-i') highlightTop30Industrias(col);
}
// NUEVO (10/07/2026): resalta las 30 mejores industrias por lo que sea que
// esté ordenado en ese momento (1D/1W/1M/3M/6M/1Y) — por VALOR, no por
// posición visual, así que da igual si ordenas ascendente o descendente,
// siempre se resaltan las 30 con mejor rendimiento real de esa columna.
function highlightTop30Industrias(col){
  const tb=document.getElementById('tb-i');
  if(!tb) return;
  const rows=Array.from(tb.querySelectorAll('tr'));
  const valores=rows.map(r=>{
    const txt=(r.cells[col]?.innerText||'').replace(/[+%$,▲▼★✗]/g,'').trim();
    const n=parseFloat(txt);
    return {row:r, val:isNaN(n)?-Infinity:n};
  });
  valores.sort((a,b)=>b.val-a.val); // siempre de mejor a peor, sea cual sea el orden visual de la tabla
  const top30=new Set(valores.slice(0,30).map(v=>v.row));
  rows.forEach(r=>r.classList.toggle('ind-top30', top30.has(r)));
}
// ── FILTER ────────────────────────────────────────────────────────────────────
function fi(q){
  const rows=document.querySelectorAll('#tb-i tr');
  let n=0;
  rows.forEach(r=>{const s=r.innerText.toLowerCase().includes(q.toLowerCase());r.style.display=s?'':'none';if(s)n++;});
  document.getElementById('ind-cnt').textContent=n+' industrias';
}

// ── SCANNER ───────────────────────────────────────────────────────────────────
async function runScanner(mode, btn){
  document.querySelectorAll('[id^=scan-btn-]').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  const modeLabels={
    rs:'RS Líderes (≥75)',highs:'Cerca 52W Máximo (≥97%)',vol:'Volumen Comprador (Vol≥1.5x + subida)',
    abv_all:'Sobre MA20+MA50',
    lows:'Cerca 52W Mínimo (≤105%)',bounce:'Rebote desde MA50',pre:'Apertura más alcistas (premercado proxy)',
    euforia:'Euforia Extrema — ATR-Multiple desde SMA50 (ordenado de mayor a menor)'
  };
  document.getElementById('scanner-status').innerHTML =
    `<strong>${modeLabels[mode]||mode}:</strong> <span style="color:var(--dim)">Cargando…</span>`;
  const token = await getAuthToken();
  if(!token){
    document.getElementById('scanner-status').innerHTML = '<span style="color:var(--dn)">Tu sesión ha caducado — vuelve a iniciar sesión.</span>';
    return;
  }
  let filtered = [];
  try{
    const resp = await fetch('https://lacomunidad.onrender.com/api/scanner?mode='+encodeURIComponent(mode), {
      headers: {'Authorization':'Bearer '+token}
    });
    const data = await resp.json();
    filtered = data.results || [];
  }catch(e){
    document.getElementById('scanner-status').innerHTML = '<span style="color:var(--dn)">Error cargando el scanner: '+e.message+'</span>';
    return;
  }
  window._scannerData=filtered;
  document.getElementById('scanner-status').innerHTML=
    `<strong>${modeLabels[mode]||mode}:</strong> ${filtered.length} acciones · <span style="color:var(--dim)">Click en cabecera para ordenar</span>`;
  renderScannerRows(filtered, mode);
}
let _scanSort={col:-1,asc:1};
function renderScannerRows(rows, mode){
  const signalText=(r,mode)=>{
    if(mode==='highs') return r['52wHigh']&&r.price>=(r['52wHigh']*0.97)?'📈 Cerca 52W Max':'';
    if(mode==='vol')   return r.volRel>=2?'🔥 Vol x'+r.volRel:r.volRel>=1.5?'⚡ Vol x'+r.volRel:'';
    if(mode==='abv_all') return (r.abv20&&r.abv50)?'✅ Sobre MA20+50':'';
    if(mode==='lows')  return r['52wLow']&&r.price<=(r['52wLow']*1.05)?'⚠️ Cerca 52W Mín':'';
    if(mode==='bounce') return (!r.abv20&&r.abv50&&(r['1D']||0)>1)?'🔄 Rebote MA20':'';
    if(mode==='rs') return (r.rs||0)>=75?'⭐ RS '+r.rs:'';
    if(mode==='pre') return (r['1D']||0)>1.5&&(r.volRel||0)>1.2?'🌅 Premarket+Vol':'🌅 Pre subida';
    if(mode==='euforia') return '🔥 ATR x'+(r.atrDist||0).toFixed(1);
    return '';
  };
  document.getElementById('tb-scanner').innerHTML=rows.map((r,i)=>{
    const rs=r.rs||0;
    const rsCls=rs>=80?'up':rs>=50?'':'dn';
    const vr=r.volRel;
    const vrStr=vr?`<span class="${vr>1.5?'up':vr<0.5?'dn':'neu'}">${vr}x</span>`:'—';
    const distHi=r['52wHigh']?Math.round((r.price/r['52wHigh']-1)*100):0;
    const atr=r.atrDist||0;
    const sig=mode?signalText(r,mode):'';
    return `<tr style="cursor:pointer" onclick="document.getElementById('stk-ticker').value='${r.ticker}';sw('stocks',document.getElementById('tab-stocks-btn'));loadStock()">
      <td onclick="event.stopPropagation()">${favStarBtn(r.ticker)}</td>
      <td><span class="rk">${i+1}</span><span class="nm">${r.ticker}</span></td>
      <td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td><td>${fmt(r['1Y'])}</td>
      <td>${abvBadge(r.abv20,'MA20')}</td>
      <td>${abvBadge(r.abv50,'MA50')}</td>
      <td><span style="color:var(--ac)">${atr}x ATR</span></td>
      <td>${vrStr}</td>
      <td><span class="${rsCls}" style="font-weight:700">${rs}</span></td>
      <td><span class="${distHi>=-5?'up':'dn'}">${distHi}%</span></td>
      <td style="color:var(--warn);font-size:10px">${sig}</td>
    </tr>`;
  }).join('');
}
function sortScanner(col){
  if(!window._scannerData||!window._scannerData.length)return;
  const cols=[r=>r.ticker,r=>r.price,r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r['1Y']||0,
    r=>r.abv20?1:0,r=>r.abv50?1:0,r=>r.atrDist||0,r=>r.volRel||0,r=>r.rs||0,
    r=>r['52wHigh']?((r.price/r['52wHigh']-1)*100):0];
  if(_scanSort.col===col) _scanSort.asc*=-1; else {_scanSort.col=col;_scanSort.asc=-1;}
  const sorted=[...window._scannerData].sort((a,b)=>(cols[col](b)-cols[col](a))*_scanSort.asc);
  renderScannerRows(sorted, null);
}
function copyScannerTickers(){
  const data=window._scannerData||[];
  if(!data.length){alert('Ejecuta un scanner primero');return;}
  const tks=data.map(r=>r.ticker).join(',');
  const area=document.createElement('textarea');
  area.value=tks; document.body.appendChild(area);
  area.select(); document.execCommand('copy'); document.body.removeChild(area);
  alert('✓ '+data.length+' tickers copiados\n'+tks.slice(0,100)+'...');
}

// ── SETUPS DIARIOS ───────────────────────────────────────────────────────────
const SETUP_LABELS={
  htf:'High Tight Flag — +80% en 60 días, cerca de máximos, consolidando (ATR%<12)',
  hvc:'High Volume Close — Gap ≥7% que al día siguiente perdió la zona de cierre (consolidación tras gap)',
  gap:'Gappers — Apertura con gap ≥7% sobre el cierre anterior',
  breakout:'Breakout — Ruptura del máximo de 20 días con volumen ≥1.3x',
  ur:'Undercut & Rally — Rompe mínimo de 30 días pero cierra por encima',
  inside:'Inside Bar — Vela de hoy contenida en el rango de ayer',
  ma_reject:'Rechazo en Media — Toca MA20/MA50 desde arriba y cierra por debajo',
  ma_support:'Apoyo en Media — Tendencia alcista ordenada (MA10>MA20>MA50) con apoyo hoy en MA10 o MA20',
  cup_handle:'Taza con Asa — Patrón cup & handle: base redondeada + pequeña corrección antes de ruptura',
  euforia:'Euforia Extrema — Parabolic Candidate: +60% en 10 días, ≥3 días verdes consecutivos, Euforia (xATR)>12'
};

// Euforia (xATR) — igual que el Pine: (close - SMA50) / ATR(50)
function calcAtrMultiple(ohlc){
  // Replica el indicador Pine "ATR-Multiple from 50SMA": distancia del precio
  // a la SMA50 medida en multiplos de ATR-14 (no ATR-50, como en el Pine original)
  const n=ohlc.length;
  if(n<51) return null;
  const closes=ohlc.map(c=>c.c), highs=ohlc.map(c=>c.h), lows=ohlc.map(c=>c.l);
  const sma50=closes.slice(-50).reduce((a,b)=>a+b,0)/50;
  // True Range para ATR-14 (igual que el indicador original: atrLength=14)
  let trSum=0;
  for(let i=n-14;i<n;i++){
    const tr1=highs[i]-lows[i];
    const tr2=i>0?Math.abs(highs[i]-closes[i-1]):tr1;
    const tr3=i>0?Math.abs(lows[i]-closes[i-1]):tr1;
    trSum+=Math.max(tr1,tr2,tr3);
  }
  const atr14=trSum/14;
  if(!atr14) return null;
  return (closes[n-1]-sma50)/atr14;
}
// Version acotada 0-25 para mostrar en tabla (mismos umbrales de referencia: 0/4/7/10)
function calcAtrMultipleClamped(ohlc){
  const v=calcAtrMultiple(ohlc);
  if(v===null) return null;
  return Math.max(-25, Math.min(25, v));
}
// NUEVO: detectSetup(), smaLast() y calcEuforia() viven en el servidor
// (market_tracker.py + /api/setups) — no aquí. calcAtrMultiple() se queda,
// la sigue usando Favoritas/panel individual.

function openSetupChart(tk){
  const r=(D.stockPerf||{})[tk];
  const ohlc=r&&r.ohlc?r.ohlc:[];
  const chg=r&&r['1D']!==undefined?((r['1D']>=0?'+':'')+r['1D']+'% hoy'):'';
  openCandleModal(tk+' — $'+(r?r.price:'—'), chg+' · Setup técnico', ohlc, tk);
}

async function runSetup(mode, btn){
  document.querySelectorAll('[id^=setup-btn-]').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');

  document.getElementById('setup-status').innerHTML =
    `<strong>${SETUP_LABELS[mode]||mode}:</strong> <span style="color:var(--dim)">Cargando…</span>`;

  const token = await getAuthToken();
  if(!token){
    document.getElementById('setup-status').innerHTML = '<span style="color:var(--dn)">Tu sesión ha caducado — vuelve a iniciar sesión.</span>';
    return;
  }
  let top = [];
  try{
    const resp = await fetch('https://lacomunidad.onrender.com/api/setups?mode='+encodeURIComponent(mode), {
      headers: {'Authorization':'Bearer '+token}
    });
    const data = await resp.json();
    top = (data.results||[]).map(r=>Object.assign({},r,{_rs:r.rs, _detail:r.detail}));
  }catch(e){
    document.getElementById('setup-status').innerHTML = '<span style="color:var(--dn)">Error cargando setups: '+e.message+'</span>';
    return;
  }

  window._setupData=top;
  document.getElementById('setup-status').innerHTML=
    `<strong>${SETUP_LABELS[mode]||mode}:</strong> ${top.length} acciones · <span style="color:var(--dim)">Click en cabecera para ordenar</span>`;
  renderSetupRows(top);
}

let _setupSort={col:-1,asc:1};
function renderSetupRows(rows){
  document.getElementById('tb-setup').innerHTML=rows.map((r,i)=>{
    const c1d=r['1D']||0, c1w=r['1W']||0, c1m=r['1M']||0;
    return `<tr>
      <td onclick="event.stopPropagation()">${favStarBtn(r.ticker)}</td>
      <td style="text-align:left;cursor:pointer" onclick="openSetupChart('${r.ticker}')" data-tk="${r.ticker}">
        <span style="color:var(--dim);font-size:9px">${i+1}</span> 
        <strong style="color:var(--ac)">${r.ticker}</strong>
      </td>
      <td>$${r.price}</td>
      <td class="${c1d>=0?'up':'dn'}">${c1d>=0?'+':''}${c1d}%</td>
      <td class="${c1w>=0?'up':'dn'}">${c1w>=0?'+':''}${c1w}%</td>
      <td class="${c1m>=0?'up':'dn'}">${c1m>=0?'+':''}${c1m}%</td>
      <td>${r._rs}</td>
      <td>${r.volRel||'—'}</td>
      <td style="text-align:left;font-size:10px;color:var(--dim);cursor:pointer" onclick="openSetupChart('${r.ticker}')">${r._detail||''}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="9" style="text-align:center;color:var(--dim);padding:16px">Sin señales hoy para este setup</td></tr>';
}

function sortSetup(col){
  if(!window._setupData||!window._setupData.length)return;
  const cols=[r=>r.ticker,r=>r.price,r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r._rs||0,r=>r.volRel||0];
  if(_setupSort.col===col) _setupSort.asc*=-1; else {_setupSort.col=col;_setupSort.asc=-1;}
  const sorted=[...window._setupData].sort((a,b)=>{
    const av=cols[col](a), bv=cols[col](b);
    if(typeof av==='string') return av.localeCompare(bv)*_setupSort.asc;
    return (bv-av)*_setupSort.asc;
  });
  renderSetupRows(sorted);
}

function copySetupTickers(){
  const data=window._setupData||[];
  if(!data.length){alert('Ejecuta un setup primero');return;}
  const tks=data.map(r=>r.ticker).join(',');
  const area=document.createElement('textarea');
  area.value=tks; document.body.appendChild(area);
  area.select(); document.execCommand('copy'); document.body.removeChild(area);
  alert('✓ '+data.length+' tickers copiados\n'+tks.slice(0,100)+'...');
}


// ── WATCHLIST ─────────────────────────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════
//  FAVORITAS — lista personal guardada en localStorage
// ══════════════════════════════════════════════════════════════════════════
const FAV_KEY='lc_favoritas';

function getFavoritas(){
  try{ return JSON.parse(localStorage.getItem(FAV_KEY)||'[]'); }catch(e){ return []; }
}
function saveFavoritas(arr){
  try{ localStorage.setItem(FAV_KEY, JSON.stringify(arr)); }catch(e){}
}
function isFavorita(ticker){
  return getFavoritas().some(f=>f.ticker===ticker);
}
function toggleFavorita(ticker, btnEl){
  let favs=getFavoritas();
  const idx=favs.findIndex(f=>f.ticker===ticker);
  if(idx>=0){
    favs.splice(idx,1);
    if(btnEl){ btnEl.textContent='☆'; btnEl.classList.remove('fav-active'); }
  }else{
    favs.unshift({ticker:ticker, added:new Date().toISOString()});
    if(btnEl){ btnEl.textContent='★'; btnEl.classList.add('fav-active'); }
  }
  saveFavoritas(favs);
  // Refrescar tabla de favoritas si esa pestaña está visible
  const favTab=document.getElementById('tab-favoritas');
  if(favTab && favTab.classList.contains('active')) renderFavoritas();
  // Refrescar contador en el boton de pestaña si existe
  updateFavCount();
}
function updateFavCount(){
  const n=getFavoritas().length;
  const btn=document.getElementById('tab-favoritas-btn');
  if(btn) btn.textContent='🌟 Favoritas'+(n>0?' ('+n+')':'');
}
// Helper para generar el boton estrella HTML, usado en las tablas
function favStarBtn(ticker){
  const active=isFavorita(ticker);
  return `<button class="fav-star ${active?'fav-active':''}" onclick="event.stopPropagation();toggleFavorita('${ticker}',this)" title="${active?'Quitar de favoritas':'Añadir a favoritas'}">${active?'★':'☆'}</button>`;
}

let _favSort={col:'added',asc:-1};
function favSortBy(col){
  if(_favSort.col===col) _favSort.asc*=-1;
  else{_favSort.col=col;_favSort.asc=-1;}
  ['ticker','price','1D','1W','1M','rs','atr','added'].forEach(c=>{
    const el=document.getElementById('fav-sort-'+c);
    if(el) el.textContent=c===_favSort.col?(_favSort.asc===-1?' ▼':' ▲'):'';
  });
  renderFavoritas();
}
function renderFavoritas(){
  const favs=getFavoritas();
  const sp=D.stockPerf||{};
  const allSp=Object.values(sp).filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};

  const tbody=document.getElementById('tb-favoritas');
  const emptyEl=document.getElementById('fav-empty');
  const tableEl=document.getElementById('fav-table');
  if(!tbody) return;

  if(!favs.length){
    tbody.innerHTML='';
    if(emptyEl) emptyEl.style.display='block';
    if(tableEl) tableEl.style.display='none';
    return;
  }
  if(emptyEl) emptyEl.style.display='none';
  if(tableEl) tableEl.style.display='';

  const rsOf2=tk=>{const r2=allSp.findIndex(x=>x.ticker===tk);return r2>=0?Math.round(r2/allSp.length*100):0;};
  const sortedFavs=[...favs].sort((a,b)=>{
    const ra=sp[a.ticker],rb=sp[b.ticker];
    let va,vb;
    if(_favSort.col==='ticker'){va=a.ticker;vb=b.ticker;return _favSort.asc*(va<vb?-1:va>vb?1:0);}
    if(_favSort.col==='added'){va=a.added||0;vb=b.added||0;}
    else if(_favSort.col==='price'){va=ra?ra.price||0:0;vb=rb?rb.price||0:0;}
    else if(_favSort.col==='rs'){va=rsOf2(a.ticker);vb=rsOf2(b.ticker);}
    else if(_favSort.col==='atr'){va=ra?calcAtrMultiple(ra.ohlc)??-999:-999;vb=rb?calcAtrMultiple(rb.ohlc)??-999:-999;}
    else{va=ra?ra[_favSort.col]||0:0;vb=rb?rb[_favSort.col]||0:0;}
    return _favSort.asc*(vb-va);
  });
  tbody.innerHTML=sortedFavs.map((f,i)=>{
    const r=sp[f.ticker];
    const fechaStr=f.added?new Date(f.added).toLocaleDateString('es-ES',{day:'2-digit',month:'2-digit'}):'';
    if(!r){
      return `<tr><td>${i+1}</td><td style="font-weight:700">${f.ticker}</td><td colspan="5" style="color:var(--dim);font-size:10px">Sin datos disponibles</td><td>—</td><td>${fechaStr}</td><td><button class="fav-star fav-active" onclick="toggleFavorita('${f.ticker}',this)">★</button></td></tr>`;
    }
    const pctCell=v=>{const n=v||0;const cls=n>0?'up':n<0?'dn':'';return `<span class="${cls}">${n>0?'+':''}${n.toFixed(2)}%</span>`;};
    const atrExt=calcAtrMultiple(r.ohlc);
    const atrColor=atrExt!==null?(atrExt>10?'var(--dn)':atrExt>5?'var(--warn)':atrExt<0?'var(--dn)':'var(--up)'):'var(--dim)';
    const atrCell=atrExt!==null?`<span style="font-weight:700;color:${atrColor}">${atrExt>=0?'+':''}${atrExt.toFixed(1)}x</span>`:'<span style="color:var(--dim)">—</span>';
    return `<tr style="cursor:pointer" onclick="showTickerChart('${f.ticker}')">
      <td>${i+1}</td>
      <td style="font-weight:700;font-family:Syne,sans-serif">${f.ticker}</td>
      <td>$${(r.price||0).toFixed(2)}</td>
      <td>${pctCell(r['1D'])}</td>
      <td>${pctCell(r['1W'])}</td>
      <td>${pctCell(r['1M'])}</td>
      <td><strong>${rsOf(f.ticker)}</strong></td>
      <td>${atrCell}</td>
      <td style="font-size:10px;color:var(--dim)">${fechaStr}</td>
      <td><button class="fav-star fav-active" onclick="event.stopPropagation();toggleFavorita('${f.ticker}',this);renderFavoritas()">★</button></td>
    </tr>`;
  }).join('');
}

function copyFavTickers(){
  const favs=getFavoritas();
  if(!favs.length){ alert('No tienes favoritas todavía.'); return; }
  const text=favs.map(f=>f.ticker).join(',');
  const ta=document.getElementById('fav-copy-area');
  ta.value=text;
  ta.select();
  try{ document.execCommand('copy'); }catch(e){ navigator.clipboard&&navigator.clipboard.writeText(text); }
  const btn=event&&event.target;
  if(btn){ const orig=btn.textContent; btn.textContent='✓ Copiado'; setTimeout(()=>btn.textContent=orig,1500); }
}

function clearFavoritas(){
  if(!getFavoritas().length) return;
  if(!confirm('¿Vaciar toda la lista de favoritas? Esta acción no se puede deshacer.')) return;
  saveFavoritas([]);
  renderFavoritas();
  updateFavCount();
}

// Helper opcional: si existe un visor de grafico individual, usarlo al hacer click en una fila
function showTickerChart(ticker){
  const input=document.getElementById('alert-ticker-input')||document.getElementById('chart-ticker-input');
  if(input){ input.value=ticker; if(typeof loadTickerChart==='function') loadTickerChart(ticker); }
}

function buildWatchlist(){
  const sp=D.stockPerf||{};
  const allSp=Object.values(sp).filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};
  // Get hot industries (positive 1M)
  const hotInd=new Set((D.industries||[]).filter(i=>(i['1M']||0)>0).map(i=>i.name));
  // Get ticker -> industry map
  const tkInd={};
  Object.entries(D.industryStocks||{}).forEach(([ind,stocks])=>stocks.forEach(s=>{if(!tkInd[s.ticker])tkInd[s.ticker]=ind;}));

  const scored=Object.values(sp).map(r=>{
    const rs=rsOf(r.ticker);
    let score=0, setups=[];
    if(rs>=70) score+=30;
    if(r.abv50) score+=15;
    if(r.abv200) score+=10;
    if(r.abv20) score+=5;
    if(r.volRel&&r.volRel>=1.2) score+=15;
    if(r.newHi){score+=20;setups.push('52W Max');}
    if(hotInd.has(tkInd[r.ticker])){score+=10;setups.push('Ind. fuerte');}
    if((r['1D']||0)>2&&(r.volRel||0)>1.5){score+=15;setups.push('Gap+Vol');}
    if((r['1W']||0)>0&&(r['1M']||0)>0&&(r['3M']||0)>0){score+=10;setups.push('Multi-TF ▲');}
    if(r.abv20&&r.abv50&&r.abv200){setups.push('Sobre 3 MAs');}
    if(!r.abv20&&r.abv50&&(r['1D']||0)>1){score+=8;setups.push('Rebote MA20');}
    return {...r, rs, score, setup:setups.slice(0,2).join(' · '), industry:tkInd[r.ticker]||'—'};
  }).filter(r=>r.rs>=60&&r.abv50&&r.price>10&&(r.volRel||0)>=0.7)
    .sort((a,b)=>b.score-a.score).slice(0,30);

  document.getElementById('wl-criteria').style.display='block';
  document.getElementById('wl-status').innerHTML=
    `<strong style="color:var(--hi)">${scored.length} acciones</strong> en watchlist de hoy · `+
    `Industrias activas: <span style="color:var(--ac)">${[...hotInd].slice(0,5).join(', ')}</span>...`;

  _wlData=scored; _wlSort={col:-1,asc:1};
  renderWLRows(scored);
}
let _wlData=[], _wlSort={col:-1,asc:1};
function renderWLRows(rows){
  const allSp=Object.values(D.stockPerf||{}).filter(x=>x['1Y']!==undefined).sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};
  document.getElementById('tb-watchlist').innerHTML=rows.map((r,i)=>{
    const rsCls=r.rs>=80?'up':r.rs>=60?'':'dn';
    const vr=r.volRel;
    const vrStr=vr?`<span class="${vr>1.5?'up':vr<0.5?'dn':'neu'}">${vr}x</span>`:'—';
    return `<tr style="cursor:pointer" onclick="document.getElementById('stk-ticker').value='${r.ticker}';sw('stocks',document.getElementById('tab-stocks-btn'));loadStock()">
      <td><span class="rk">${i+1}</span><span class="nm">${r.ticker}</span></td>
      <td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td>
      <td><span class="${rsCls}" style="font-weight:700">${r.rs}</span></td>
      <td>${abvBadge(r.abv50,'MA50')}</td>
      <td>${vrStr}</td>
      <td style="color:var(--warn);font-size:10px">${r.setup||'—'}</td>
      <td style="color:var(--dim);font-size:10px">${r.industry.length>22?r.industry.slice(0,22)+'...':r.industry}</td>
    </tr>`;
  }).join('');
}
function sortWL(col){
  if(!_wlData.length)return;
  if(_wlSort.col===col) _wlSort.asc*=-1; else {_wlSort.col=col;_wlSort.asc=-1;}
  const keys=[r=>r.ticker,r=>r.price,r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r.rs,r=>r.abv50?1:0,r=>r.volRel||0];
  const sorted=[..._wlData].sort((a,b)=>(keys[col]?((keys[col](b)||0)-(keys[col](a)||0))*_wlSort.asc:0));
  renderWLRows(sorted);
  document.querySelectorAll('#wl-table th').forEach((th,i)=>th.classList.toggle('srt',i===col));
}
function copyTickers(){
  const rows=document.querySelectorAll('#tb-watchlist tr');
  const tickers=[...rows].map(r=>r.cells[0]?.querySelector('.nm')?.textContent||'').filter(Boolean);
  if(!tickers.length){alert('Genera la watchlist primero');return;}
  const area=document.getElementById('wl-copy-area');
  area.value=tickers.join(',');
  area.select(); document.execCommand('copy');
  alert('✓ '+tickers.length+' tickers copiados: '+tickers.join(', '));
}

// ── TRADINGVIEW CHART MODAL (global) ─────────────────────────────────────────
const TV_SYM_GLOBAL = {
  'S&P 500':'FOREXCOM:SPXUSD','Nasdaq 100':'FOREXCOM:NSXUSD','Russell 2000':'FOREXCOM:US2000',
  'Dow Jones 30':'FOREXCOM:DJI','VIX':'TVC:VIX','Euro Stoxx 50':'INDEX:SX5E',
  'IBEX 35':'BME:IBC','DAX':'INDEX:DEU40','FTSE 100':'FOREXCOM:UKXGBP',
  'CAC 40':'INDEX:CAC40','Nikkei 225':'INDEX:NKY','Hang Seng':'INDEX:HSI',
  'Oro':'TVC:GOLD','Plata':'TVC:SILVER','Cobre':'NASDAQ:CPER',
  'Petróleo WTI':'TVC:USOIL','Petróleo Brent/WTI':'TVC:USOIL','Gas Natural':'AMEX:UNG',
  'Bitcoin':'CRYPTO:BTCUSD','Ethereum':'CRYPTO:ETHUSD',
  'T-Bond 10Y Yield':'TVC:US10Y','EUR/USD':'FX:EURUSD',
  'AEX (Holanda)':'TVC:OMXS30','AEX':'TVC:OMXS30','MIB40':'EURONEXT:IT40',
};

function openTVChart(label){
  const sym = TV_SYM_GLOBAL[label] || label;
  // Reutilizar el modal de benchmarks que ya funciona
  openCandleModal(label, 'Índice global', [], sym);
}

// ── BRIEFING DIARIO ───────────────────────────────────────────────────────────
let _briefingBuilt=false;
function renderBriefing(){
  _briefingBuilt=true;
  const bm=D.benchmarks||[];
  const su=D.breadthSummary||{};
  const bl=D.breadthLatest||{};
  const now=new Date();
  const dateStr=now.toLocaleDateString('es-ES',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  document.getElementById('briefing-date').textContent=dateStr;

  // Helper: find benchmark by name or ticker
  const bm_get=(keys)=>{
    for(const k of keys){const r=bm.find(x=>x.ticker===k||x.name===k);if(r)return r;}
    return null;
  };
  const chg=(r)=>r?r['1D']||0:0;
  const pri=(r)=>r?r.price||0:0;
  const fmt2=(v,prefix='',suffix='')=>{
    if(v===null||v===undefined)return'—';
    const n=parseFloat(v);
    return `${prefix}${isNaN(n)?v:n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})}${suffix}`;
  };
  const chgStr=(v)=>{
    const n=parseFloat(v);
    if(isNaN(n))return'—';
    const cls=n>0?'up':'dn';
    return `<span class="${cls}">${n>0?'+':''}${n.toFixed(2)}%</span>`;
  };
  const dot=(v)=>{const n=parseFloat(v);if(isNaN(n))return'🟡';return n>0.3?'🟢':n<-0.3?'🔴':'🟡';};
  const dval=(r)=>r?`${fmt2(pri(r))} | ${chgStr(chg(r))}`:'—';

  // ── Get data
  const sp500=bm_get(['^GSPC','S&P 500']);
  const ndx=bm_get(['^NDX','Nasdaq 100']);
  const rut=bm_get(['^RUT','Russell 2000']);
  const djia=bm_get(['^DJI','Dow Jones']);
  const vix=bm_get(['^VIX','VIX']);
  const stoxx=bm_get(['^STOXX50E','Euro Stoxx 50']);
  const ibex=bm_get(['^IBEX','IBEX 35 (Esp)']);
  const dax=bm_get(['^GDAXI','DAX (Germany)']);
  const aex=bm_get(['AEX (Holanda)']);

  const nikkei=bm_get(['^N225','Nikkei 225']);
  const hsi=bm_get(['^HSI','Hang Seng']);
  const gold=bm_get(['GC=F','Gold']);
  const silver=bm_get(['SI=F','Silver']);
  const oil=bm_get(['CL=F','Oil (WTI)']);
  const natgas=bm_get(['NG=F','Natural Gas']);
  const copper=bm_get(['HG=F','Copper']);
  const btc=bm_get(['BTC-USD','Bitcoin']);
  const eth=bm_get(['ETH-USD','Ethereum']);
  const tnx=bm_get(['^TNX','T-Bond 10Y Yield']);
  const eurusd=bm_get(['EURUSD=X','EUR/USD']);

  // ── Sector flows
  const sectors=D.sectors||[];
  const topSec=sectors.filter(s=>(s['1D']||0)>0).sort((a,b)=>(b['1D']||0)-(a['1D']||0)).slice(0,3);
  const botSec=sectors.filter(s=>(s['1D']||0)<0).sort((a,b)=>(a['1D']||0)-(b['1D']||0)).slice(0,3);

  // ── Interpret Wall Street tone
  const spChg=chg(sp500);
  const wsTone=spChg>0.5?'tono positivo, momentum comprador':spChg>0?'tono mixto, ligeramente alcista':spChg>-0.5?'tono mixto, ligeramente bajista':'presión vendedora, sesión correctiva';
  const vixNum=parseFloat(pri(vix))||0;
  const vixNote=vixNum<15?'VIX muy bajo, complacencia elevada':vixNum<20?'VIX en zona de calma':vixNum<25?'VIX moderado, algo de precaución':'VIX elevado, volatilidad presente';

  // ── Interpret Europe
  const euAvg=[[stoxx,aex,dax,ibex]].flat().filter(Boolean).reduce((a,r)=>a+chg(r),0)/4||0;
  const euTone=euAvg>0.3?'positivo generalizado':euAvg>0?'ligeramente positivo':euAvg>-0.3?'mixto con sesgo bajista':'negativo';

  // ── Semaphore
  const semaphore=[
    {l:'Wall Street',v:dot(spChg),t:spChg>0.3?'positivo':spChg>-0.3?'mixto':'negativo'},
    {l:'Europa',v:dot(euAvg),t:euAvg>0.3?'positivo':euAvg>-0.3?'mixto':'negativo'},
    {l:'Asia',v:dot(chg(nikkei)),t:chg(nikkei)>0?'positivo':'mixto'},
    {l:'Materias primas',v:dot(chg(gold)),t:chg(gold)>0?'positivo':'débil'},
    {l:'Cripto',v:dot(chg(btc)),t:chg(btc)>0.5?'rebote':'estabilizando'},
    {l:'Bono 10Y USA',v:dot(-chg(tnx)),t:chg(tnx)<0?'relaja presión':chg(tnx)>0.5?'sube yield — presión':'estable'},
    {l:'VIX',v:dot(-chg(vix)),t:chg(vix)<0?'cae — calma':chg(vix)>1?'sube — alerta':'sin cambios relevantes'},
  ];

  // ── Best/worst of day
  const allBm=[...bm].sort((a,b)=>(b['1D']||0)-(a['1D']||0));
  const best=allBm.slice(0,3);
  const worst=allBm.slice(-3).reverse();

  // ── Build HTML
  const section=(icon,title,content)=>
    `<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:16px 18px;margin-bottom:12px">
      <div style="font-family:Syne,sans-serif;font-size:14px;font-weight:700;color:var(--hi);margin-bottom:12px">${icon} ${title}</div>
      ${content}
    </div>`;

  const row=(emoji,label,value)=>
    `<div data-tv="${label}" onclick="openTVChart(this.dataset.tv)" style="display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12px;cursor:pointer;padding:4px 6px;border-radius:6px;transition:background .15s" onmouseover="this.style.background='var(--bg3)'" onmouseout="this.style.background='transparent'">
      <span style="font-size:14px;width:20px;flex-shrink:0">${emoji}</span>
      <span style="color:var(--dim);width:180px;flex-shrink:0">${label}</span>
      <span style="font-weight:600">${value}</span>
      <span style="margin-left:auto;font-size:10px;color:var(--dim);opacity:.4">📈</span>
    </div>`;

  const subhead=(t)=>`<div style="font-size:11px;font-weight:700;color:var(--ac);text-transform:uppercase;letter-spacing:.08em;margin:10px 0 6px">${t}</div>`;

  // ── Intro
  const introTone=spChg>0.3&&euAvg>0?'constructivo, con Europa y Wall Street alineados al alza':
    spChg<-0.3&&euAvg<0?'negativo, con presión en ambos lados del Atlántico':
    'mixto, con divergencias entre mercados';
  const intro=`<div style="font-size:13px;color:var(--tx);line-height:1.9;padding:14px 18px;background:var(--bg2);border:1px solid var(--b1);border-radius:10px;margin-bottom:12px;border-left:4px solid var(--warn)">
    <strong style="color:var(--hi)">Arranque de sesión con tono ${introTone}.</strong>
    ${euAvg>0.1?'Europa muestra sesgo positivo con ganancias generalizadas.':euAvg<-0.1?'Europa abre con pérdidas.':'Europa en tono mixto.'}
    Wall Street ${wsTone}.
    ${vixNote}.
    ${chg(oil)<-0.5?'El crudo retrocede, aliviando algo la presión inflacionista.':chg(oil)>0.5?'El crudo sube, añadiendo presión sobre inflación.':'El crudo sin grandes movimientos.'}
  </div>`;

  // ── Futures section
  const wsSection=section('🇺🇸','Futuros Wall Street',
    row(dot(chg(djia)),'Dow Jones 30',dval(djia))+
    row(dot(chg(sp500)),'S&P 500',dval(sp500))+
    row(dot(chg(ndx)),'Nasdaq 100',dval(ndx))+
    row(dot(chg(rut)),'Russell 2000',dval(rut))+
    row(dot(-chg(vix)),'VIX',dval(vix))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${spChg>0.3?'Wall Street viene con momentum positivo. Sectores cíclicos y tech en foco.':
        spChg<-0.3?'Wall Street corrige. Rotation hacia defensivos y bonos posible.':
        'Wall Street viene plano. Sesión de consolidación probable sin catalizador.'}
      ${ndx&&sp500&&(chg(ndx)-chg(sp500))>0.5?' Nasdaq lidera, señal de apetito por risk-on en growth.':''}
    </div>`
  );

  const euSection=section('🇪🇺','Futuros Europa',
    row(dot(chg(stoxx)),'Euro Stoxx 50',dval(stoxx))+
    row(dot(chg(ibex)),'IBEX 35',dval(ibex))+
    row(dot(chg(dax)),'DAX',dval(dax))+
    row(dot(chg(aex)),'OMX30 (Stk)',dval(aex))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 Europa ${euTone}.
      ${ibex&&chg(ibex)>0.1?' IBEX muestra fuerza relativa positiva.':ibex&&chg(ibex)<-0.1?' IBEX bajo presión.':''}
      ${dax&&chg(dax)>0.3?' DAX lidera Europa, buen signo para industriales.':''}
    </div>`
  );

  const asiaSection=section('🌏','Asia',
    row(dot(chg(nikkei)),'Nikkei 225',dval(nikkei))+
    row(dot(chg(hsi)),'Hang Seng',dval(hsi))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${chg(nikkei)<0&&chg(hsi)>0?'Asia mixta. Japón flaquea mientras Hong Kong destaca en positivo.':
        chg(nikkei)>0&&chg(hsi)>0?'Asia positiva generalizada, buen contexto para apertura global.':
        chg(nikkei)<0&&chg(hsi)<0?'Asia cierra en negativo, posible presión al abrir.':
        'Asia con comportamiento dispar entre plazas.'}
    </div>`
  );

  const commSection=section('🟡','Materias Primas',
    row(dot(chg(gold)),'Oro',dval(gold))+
    row(dot(chg(silver)),'Plata',dval(silver))+
    row(dot(chg(copper)),'Cobre',dval(copper))+
    row(dot(chg(oil)),'Petróleo Brent/WTI',dval(oil))+
    row(dot(chg(natgas)),'Gas Natural',dval(natgas))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${chg(oil)<-0.5?'Las materias primas vienen más flojas. La caída del crudo alivia algo la presión inflacionista.':
        chg(oil)>0.5?'El crudo sube. Presión inflacionista se mantiene, ojo a energía y transporte.':
        'Materias primas sin grandes movimientos. Mercado en modo espera.'}
      ${chg(gold)>0.3?' El oro sube — puede señalar búsqueda de refugio o expectativas inflacionistas.':''}
    </div>`
  );

  const cryptoSection=section('₿','Cripto',
    row(dot(chg(btc)),'Bitcoin',dval(btc))+
    row(dot(chg(eth)),'Ethereum',dval(eth))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${chg(btc)>1?'Cripto al alza. Bitcoin lidera con momentum positivo.':
        chg(btc)<-1?'Cripto bajo presión. Sesión de corrección.':
        'Cripto intenta estabilizarse. Movimiento moderado, sin señal clara.'}
      ${eth&&btc&&(chg(eth)-chg(btc))>0.5?' Ethereum rebota más que Bitcoin — posible rotación hacia altcoins.':''}
    </div>`
  );

  // Semaphore section
  const semSection=`<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:16px 18px;margin-bottom:12px">
    <div style="font-family:Syne,sans-serif;font-size:14px;font-weight:700;color:var(--hi);margin-bottom:12px">🚦 Semáforo de mercado</div>
    ${semaphore.map(s=>`<div style="display:flex;align-items:center;gap:10px;margin-bottom:7px;font-size:12px">
      <span style="font-size:16px;width:22px">${s.v}</span>
      <span style="width:160px;flex-shrink:0;color:var(--dim)">${s.l}:</span>
      <span style="color:var(--tx)">${s.t}</span>
    </div>`).join('')}
  </div>`;

  // Sector flow
  const sectorSection=section('📊','Flujo sectorial hoy',
    topSec.length?subhead('🟢 Mejor comportamiento')+''+topSec.map(s=>row('▲',s.name,chgStr(s['1D']))).join(''):''
    +botSec.length?subhead('🔴 Peor comportamiento')+''+botSec.map(s=>row('▼',s.name,chgStr(s['1D']))).join(''):''
  );

  // Best/worst
  const bwSection=section('⭐','Activos destacados del día',
    subhead('🟢 Mayores subidas')+best.map(r=>row('▲',r.name,dval(r))).join('')+
    subhead('🔴 Mayores caídas')+worst.map(r=>row('▼',r.name,dval(r))).join('')
  );

  // Yield / Macro
  const macroSection=section('📉','Tipos & Macro',
    row(dot(-chg(tnx)),'Yield 10Y EEUU',tnx?pri(tnx).toFixed(3)+'% ('+chgStr(chg(tnx))+')'  :'—')+
    row(dot(chg(eurusd)),'EUR/USD',dval(eurusd))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${tnx&&chg(tnx)>0.5?'El yield 10Y sube — presión sobre valoraciones growth y real estate.':
        tnx&&chg(tnx)<-0.5?'El yield 10Y cae — favorable para tech y bonos. Posible señal de ralentización.':
        'Los tipos sin grandes movimientos hoy.'}
    </div>`
  );

  // ── 2-COLUMN LAYOUT ─────────────────────────────────────────────────────────
  // Top semaphore bar
  const semTop=[
    {v:dot(spChg),l:'Wall St'},
    {v:dot(euAvg),l:'Europa'},
    {v:dot(chg(nikkei)),l:'Asia'},
    {v:dot(chg(gold)),l:'Materias'},
    {v:dot(chg(btc)),l:'Cripto'},
    {v:dot(-chg(vix)),l:'VIX'},
  ];
  const semEl=document.getElementById('briefing-semaphore-top');
  if(semEl) semEl.innerHTML=semTop.map(s=>
    `<div style="text-align:center;background:var(--bg3);border-radius:6px;padding:4px 8px;border:1px solid var(--b1)">
      <div style="font-size:14px">${s.v}</div>
      <div style="font-size:8px;color:var(--dim);margin-top:1px">${s.l}</div>
    </div>`).join('');

  // Intro headline
  const introEl=document.getElementById('briefing-intro');
  if(introEl) introEl.innerHTML=`
    <div style="background:linear-gradient(135deg,var(--bg2),var(--bg3));border:1px solid var(--b1);border-radius:10px;padding:16px 20px;border-left:4px solid var(--warn)">
      <div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:var(--hi);line-height:1.5;margin-bottom:8px">
        ${spChg>0.3&&euAvg>0?'🟢 Sesión constructiva — Europa y Wall Street alineados al alza':
          spChg<-0.3&&euAvg<0?'🔴 Presión vendedora en ambos lados del Atlántico':
          euAvg>0.3?'🟡 Europa lidera — Wall Street más rezagado en apertura':
          '🟡 Sesión mixta — mercados buscan dirección'}
      </div>
      <div style="font-size:12px;color:var(--tx);line-height:1.7">
        ${euAvg>0.1?'Europa abre con sesgo positivo generalizado. ':'Europa con tono mixto. '}
        Wall Street ${wsTone}. ${vixNote}.
        ${chg(oil)<-0.5?'El crudo retrocede, aliviando presión inflacionista.':chg(oil)>0.5?'El crudo sube, atención a energía.':'Crudo estable.'}
        ${chg(gold)>0.3?' Oro al alza — posible señal de incertidumbre o inflación.':''}
      </div>
    </div>`;

  // Helper compact section for 2 cols
  const csection=(icon,title,content,accent)=>
    `<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:13px 15px;margin-bottom:10px;border-top:2px solid ${accent||'var(--b2)'}">
      <div style="font-family:Syne,sans-serif;font-size:12px;font-weight:700;color:var(--hi);margin-bottom:10px">${icon} ${title}</div>
      ${content}
    </div>`;
  const crow=(emoji,label,value,note)=>
    `<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px;font-size:11px">
      <span style="font-size:13px;width:18px;flex-shrink:0">${emoji}</span>
      <span style="color:var(--dim);flex:1">${label}</span>
      <span style="font-weight:600;white-space:nowrap">${value}</span>
      ${note?`<span style="font-size:9px;color:var(--dim);white-space:nowrap">${note}</span>`:''}
    </div>`;
  const cnote=(t)=>
    `<div style="font-size:10px;color:var(--dim);margin-top:8px;padding:7px 10px;background:var(--bg3);border-radius:5px;border-left:2px solid var(--b2)">👉 ${t}</div>`;

  // ── Helpers for data+analysis sections ────────────────────────────────────
  const dline=(e,l,v)=>
    `<div data-tv="${l}" onclick="openTVChart(this.dataset.tv)" style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid var(--b1);font-size:12px;cursor:pointer;border-radius:4px;transition:background .12s" onmouseover="this.style.background='var(--bg3)'" onmouseout="this.style.background='transparent'">
      <span style="font-size:14px;flex-shrink:0;width:20px">${e}</span>
      <span style="color:var(--dim);flex:1">${l}</span>
      <span style="font-weight:600;white-space:nowrap">${v}</span>
      <span style="font-size:10px;color:var(--dim);opacity:.4;margin-left:4px">📈</span>
    </div>`;
  const analysis=(txt)=>
    `<div style="margin-top:12px;padding:12px 14px;background:var(--bg3);border-radius:7px;font-size:12px;color:var(--tx);line-height:1.85">${txt}</div>`;
  const tsec=(icon,title,rows,analysisTxt,accent)=>
    `<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:15px 17px;margin-bottom:12px;border-top:3px solid ${accent}">
      <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:800;color:var(--hi);margin-bottom:12px">${icon} ${title}</div>
      ${rows}${analysis(analysisTxt)}
    </div>`;

  // ── Analytical texts ────────────────────────────────────────────────────────
  const wsText=(()=>{
    if(spChg>0.5) return `El S&P 500 avanza un <strong style="color:var(--up)">${spChg>0?'+':''}${spChg}%</strong> — sesión con sesgo claramente alcista. El Nasdaq ${ndx&&chg(ndx)>spChg?'lidera, señal de apetito por growth y tecnología':'acompaña con menor fuerza, lo que puede indicar una subida más broad que tech-driven'}. El Russell 2000 ${rut&&chg(rut)>0?'también sube — la amplitud del rally es positiva, no solo megacaps. Señal de salud del mercado':'se queda rezagado, lo que reduce la calidad del rally: sube por los grandes pero el resto no acompaña'}. VIX en ${vixNum} — ${vixNum<18?'zona de calma, el mercado no está comprando protección agresiva. Condición favorable para mantener posiciones':vixNum>22?'nivel elevado, el mercado expresa incertidumbre. Conviene revisar coberturas':'zona neutral'}. Contexto: favorable para mantener o añadir posiciones largas con stops ajustados.`;
    if(spChg<-0.5) return `El S&P 500 cae un <strong style="color:var(--dn)">${spChg}%</strong> — sesión con presión vendedora. ${ndx&&chg(ndx)<chg(sp500)?'El Nasdaq lidera las caídas — los valores más valorados son los más penalizados cuando hay aversión al riesgo o subida de tipos.':''} El Russell 2000 ${rut&&chg(rut)<chg(sp500)?'también retrocede con fuerza, lo que confirma que no es rotación sino salida de riesgo generalizada':'muestra algo más de resistencia, posible efecto defensivo en small caps domésticas'}. VIX ${vixNum>22?'sube por encima de 22 — el mercado compra protección activamente. Señal de que la caída puede tener continuidad':'contenido, lo que sugiere que la corrección no ha generado pánico de momento, puede ser una corrección sana'}. Consejo: revisar stops, reducir posiciones especulativas, buscar refugio en sectores defensivos.`;
    return `Wall Street abre plano. El S&P 500 en <strong>${(spChg>0?'+':'')+spChg}%</strong> — sesiones de consolidación como esta son normales y suelen ser oportunidades para analizar y posicionarse. ${vixNum<17?'VIX muy bajo — posible exceso de complacencia. Conviene no bajar la guardia.':vixNum>22?'VIX elevado — hay nerviosismo latente incluso en días planos.':'VIX en zona neutral, sin señal de alarma.'} Sin catalizador claro, lo más probable es un rango estrecho durante la jornada.`;
  })();

  const euText=(()=>{
    const sprd=dax&&sp500?chg(dax)-spChg:0;
    let t=`Europa ${euTone}. `;
    t+=dax&&chg(dax)>0.3?`El DAX (${(chg(dax)>0?'+':'')+chg(dax)}%) lidera — el mercado alemán es intensivo en exportaciones e industriales, y su fuerza refleja expectativas de recuperación económica global. `:dax&&chg(dax)<-0.3?`El DAX flaquea (${chg(dax)}%) — debilidad en industriales europeos, posiblemente por el euro o datos macro. `:'';
    t+=ibex&&chg(ibex)>0.2?`El IBEX (${(chg(ibex)>0?'+':'')+chg(ibex)}%) sube — banca y energía españolas traccionan. `:'';
    t+=euAvg>0&&spChg<-0.2?`Divergencia relevante: Europa sube mientras Wall Street cae. Esto puede deberse al diferencial BCE/Fed, flujos de capital hacia mercados más baratos, o simplemente diferencia de horario. Vigilar si se mantiene al abrir USA.`:euAvg<-0.2&&spChg>0.2?`Europa rezagada frente a Wall Street — posibles causas: debilidad del euro, incertidumbre geopolítica o menor momentum económico europeo.`:euAvg>0?`El conjunto europeo acompaña el tono positivo global. Buen arranque para sesión completa.`:`Europa amplifica la debilidad de Wall Street. Sesión complicada en ambos lados.`;
    return t;
  })();

  const secText=(()=>{
    if(!topSec.length) return 'Sin datos de flujo sectorial disponibles hoy.';
    const ts=topSec[0], bs=botSec[0];
    let t=`El análisis sectorial revela dónde está fluyendo el dinero. `;
    t+=`<strong style="color:var(--up)">${ts.name}</strong> lidera con ${(ts['1D']>0?'+':'')+ts['1D']}% — `;
    if(ts.name.includes('Tech')||ts.name.includes('Communication')) t+='el dinero entra en growth. Señal de apetito por riesgo y expectativas de tipos más bajos o benignos.';
    else if(ts.name.includes('Energy')||ts.name.includes('Materials')) t+='los cíclicos tiran fuerte. Expectativas de crecimiento o subida de materias primas.';
    else if(ts.name.includes('Utilities')||ts.name.includes('Staples')||ts.name.includes('Healthcare')) t+='defensivos al frente — el dinero busca seguridad. Señal de cautela aunque el índice suba.';
    else t+='sector a vigilar como posible catalizador de la jornada.';
    if(bs) t+=` Por el contrario, <strong style="color:var(--dn)">${bs.name}</strong> recorta ${bs['1D']}%${bs.name.includes('Real Estate')?' — los tipos altos siguen presionando al inmobiliario':bs.name.includes('Tech')?' — posible toma de beneficios en growth tras subidas recientes':''}.`;
    return t;
  })();

  const commText=(()=>{
    let t='';
    t+=chg(oil)<-1?`El petróleo WTI cae un ${chg(oil)}%, lo que alivia presión inflacionista y reduce costes para industria y transporte. Históricamente, cuando el crudo baja, los bancos centrales tienen más margen para bajar tipos. Positivo para bonos y sectores con altos costes energéticos. `:chg(oil)>1?`El crudo sube un +${chg(oil)}% — presión inflacionista al alza. Sectores afectados: aerolíneas, transporte, química y consumo. El mercado podría descontar menor flexibilidad de la Fed. `:`Petróleo sin grandes cambios. `;
    t+=chg(gold)>0.5?`El oro avanza +${chg(gold)}% — puede indicar búsqueda de refugio, inflación persistente o debilidad del dólar. Históricamente el oro sube cuando los tipos reales bajan o cuando hay incertidumbre elevada. `:chg(gold)<-0.5?`El oro cede ${chg(gold)}% — ocurre cuando el dólar se fortalece o suben los tipos reales. `:'';
    t+=chg(copper)<-0.5?'El cobre baja — señal de preocupación sobre la demanda industrial global, especialmente China. Vigilar también acero y materiales. ':chg(copper)>0.5?'El cobre sube — señal positiva sobre actividad industrial y construcción global. Favorable para materiales. ':'';
    return t||'Materias primas sin movimientos relevantes hoy.';
  })();

  const cryptoText=(()=>{
    const bc=chg(btc), ec=chg(eth);
    let t=bc>2?`Bitcoin sube con fuerza (+${bc}%), superando el 2% que marca momentum comprador real en cripto. `:bc<-2?`Bitcoin cae un ${bc}% — corrección activa. En este entorno conviene esperar confirmación antes de añadir exposición. `:bc>0?`Bitcoin avanza moderadamente (+${bc}%). Sin señal clara de dirección. `:bc<0?`Bitcoin cede ${bc}%, movimiento menor, dentro del ruido habitual. `:'';
    if(ec>bc+1) t+=`Ethereum supera a Bitcoin (+${ec}% vs ${(bc>0?'+':'')+bc}%) — cuando ETH lidera, suele indicar que los inversores toman más riesgo dentro del ecosistema cripto, rotando hacia altcoins.`;
    else if(bc>ec+1) t+=`Bitcoin supera a Ethereum — fase más conservadora en cripto, el dinero se concentra en el activo de mayor capitalización y menor riesgo relativo.`;
    return t||'Cripto sin movimiento significativo hoy.';
  })();

  const macroText=(()=>{
    const yld=pri(tnx);
    let t=`El yield del bono USA a 10 años cotiza en <strong>${yld?yld.toFixed(3):'—'}%</strong>. `;
    t+=chg(tnx)>0.5?`Sube hoy (+${chg(tnx)}%): el coste del capital aumenta, lo que presiona valoraciones de empresas growth (múltiplos altos) y al sector inmobiliario. Cuando el 10Y sube, el descuento de flujos futuros se hace más exigente — las acciones "caras" sufren más. `:chg(tnx)<-0.5?`Cae hoy (${chg(tnx)}%): alivia la presión sobre growth y tech. Cuando el bono cae, los inversores suelen rotar desde renta fija hacia renta variable. Favorable para empresas de alto crecimiento. `:`Sin grandes movimientos en tipos hoy. `;
    const eu=chg(eurusd);
    t+=eu>0.3?`EUR/USD sube (${(eu>0?'+':'')+eu}%): euro más fuerte. Positivo para poder adquisitivo europeo en importaciones pero puede pesar sobre exportadoras (Volkswagen, ASML, LVMH).`:eu<-0.3?`EUR/USD cae (${eu}%): euro débil. Beneficia a exportadoras europeas pero encarece importaciones — especialmente energía y commodities.`:`EUR/USD estable, sin efecto divisa relevante hoy.`;
    return t;
  })();

  const bwText=(()=>{
    const bn=best.slice(0,2).map(r=>r.name).join(' y ');
    const wn=worst.slice(0,2).map(r=>r.name).join(' y ');
    return `Los activos con mejor comportamiento hoy son <strong style="color:var(--up)">${bn}</strong>. Antes de seguir cualquier movimiento fuerte, analiza siempre si hay un catalizador real detrás (dato, noticia, volumen) o es solo ruido de baja liquidez. En el extremo opuesto, <strong style="color:var(--dn)">${wn}</strong> retroceden. En activos que caen con fuerza, la primera pregunta es: ¿hay razón fundamental o es corrección técnica? La segunda: ¿el stop ha saltado o conviene aguantar el nivel clave?`;
  })();

  // ── LEFT COLUMN
  const leftHTML=
    tsec('🇺🇸','Wall Street',
      dline(dot(chg(djia)),'Dow Jones 30',dval(djia))+
      dline(dot(chg(sp500)),'S&P 500',dval(sp500))+
      dline(dot(chg(ndx)),'Nasdaq 100',dval(ndx))+
      dline(dot(chg(rut)),'Russell 2000',dval(rut))+
      dline(dot(-chg(vix)),'VIX',dval(vix)),
      wsText,'var(--ac)')
  +tsec('🇪🇺','Europa',
      dline(dot(chg(stoxx)),'Euro Stoxx 50',dval(stoxx))+
      dline(dot(chg(ibex)),'IBEX 35',dval(ibex))+
      dline(dot(chg(dax)),'DAX',dval(dax))+
      dline(dot(chg(aex)),'OMX30 (Stk)',dval(aex)),
      euText,'var(--up)')
  +tsec('📊','Flujo Sectorial',
      (topSec.length?'<div style="font-size:10px;color:var(--up);font-weight:700;margin-bottom:6px">▲ FUERTES HOY</div>'+topSec.map(s=>dline('▲',s.name,chgStr(s['1D']))).join(''):'')
      +(botSec.length?'<div style="font-size:10px;color:var(--dn);font-weight:700;margin-top:8px;margin-bottom:6px">▼ DÉBILES HOY</div>'+botSec.map(s=>dline('▼',s.name,chgStr(s['1D']))).join(''):''),
      secText,'var(--warn)');

  // ── RIGHT COLUMN
  const rightHTML=
    tsec('🟡','Materias Primas',
      dline(dot(chg(gold)),'Oro',dval(gold))+
      dline(dot(chg(silver)),'Plata',dval(silver))+
      dline(dot(chg(oil)),'Petróleo WTI',dval(oil))+
      dline(dot(chg(copper)),'Cobre',dval(copper))+
      dline(dot(chg(natgas)),'Gas Natural',dval(natgas)),
      commText,'var(--warn)')
  +tsec('₿','Cripto',
      dline(dot(chg(btc)),'Bitcoin',dval(btc))+
      dline(dot(chg(eth)),'Ethereum',dval(eth)),
      cryptoText,'rgb(249,115,22)')
  +tsec('🌏','Asia — Cierre nocturno',
      dline(dot(chg(nikkei)),'Nikkei 225',dval(nikkei))+
      dline(dot(chg(hsi)),'Hang Seng',dval(hsi)),
      chg(nikkei)>0&&chg(hsi)>0?'Asia cierra en positivo generalizado — buen contexto para apertura europea y global. Nikkei y Hang Seng alineados al alza reduce la incertidumbre de apertura.':chg(nikkei)<0&&chg(hsi)<0?'Asia cierra en rojo. Doble negativo en Nikkei y Hang Seng puede reflejar datos macro de China débiles o aversión al riesgo global. Vigilar su impacto en exportadoras europeas.':chg(nikkei)<0&&chg(hsi)>0?`Japón flaquea (${chg(nikkei)}%) mientras Hong Kong aguanta (${(chg(hsi)>0?'+':'')+chg(hsi)}%). La debilidad nipona puede estar ligada al yen o a datos específicos. Hong Kong resistiendo es constructivo para emergentes asiáticos y el sector tecnológico chino.`:`Asia mixta. Sin señal clara para activos globales desde el cierre asiático.`,'var(--ac)')
  +tsec('📉','Tipos & Macro',
      dline(dot(-chg(tnx)),'Yield 10Y USA',tnx?pri(tnx).toFixed(3)+'% ('+chgStr(chg(tnx))+')':'—')+
      dline(dot(chg(eurusd)),'EUR/USD',dval(eurusd)),
      macroText,'rgb(52,211,153)')
  +tsec('⭐','Activos Destacados',
      '<div style="font-size:10px;color:var(--up);font-weight:700;margin-bottom:6px">▲ MEJORES</div>'
      +best.map(r=>dline('▲',r.name,dval(r))).join('')
      +'<div style="font-size:10px;color:var(--dn);font-weight:700;margin-top:8px;margin-bottom:6px">▼ PEORES</div>'
      +worst.map(r=>dline('▼',r.name,dval(r))).join(''),
      bwText,'var(--dim)');

  // Semáforo eliminado — ya visible en topbar

  // ── Conclusión del día — resumen rápido final ──────────────────────────────
  const concSpChg=chg(sp500), vixVal=parseFloat(pri(vix))||0, btcChg=chg(btc);
  const concNdxChg=chg(ndx), concRutChg=chg(rut);
  const tendencia = concSpChg>0.5?'alcista':concSpChg<-0.5?'bajista':'lateral';
  const tendColor = concSpChg>0.5?'var(--up)':concSpChg<-0.5?'var(--dn)':'var(--warn)';
  const vixEstado = vixVal>25?'alta volatilidad — cautela':vixVal>20?'volatilidad moderada':'calma';
  const riskMood = (concSpChg>0&&btcChg>0)?'risk-on (apetito por riesgo)':(concSpChg<0&&btcChg<0)?'risk-off (aversión al riesgo)':'mixto, sin sesgo claro';
  const ampBreadth = (concNdxChg>concSpChg && concRutChg>0)?'amplitud sana — tech y small caps acompañan, no solo los grandes valores':
    (concRutChg<0 && concSpChg>0)?'amplitud débil — el rally se concentra en pocos valores grandes, vigilar sostenibilidad':
    'amplitud equilibrada entre segmentos del mercado';
  const conclusionPuntos = [
    `Sesión <strong style="color:${tendColor}">${tendencia}</strong> en Wall Street (S&P ${concSpChg>=0?'+':''}${concSpChg}%), con Nasdaq ${concNdxChg>=0?'+':''}${concNdxChg}% y Russell 2000 ${concRutChg>=0?'+':''}${concRutChg}%.`,
    `VIX en ${vixVal.toFixed(1)} — ${vixEstado}. ${vixVal<18?'El mercado no está pagando protección, lo que suele acompañar fases de continuidad alcista.':vixVal>22?'Hay demanda real de cobertura — el mercado descuenta más movimiento.':'Nivel estándar, sin señales de estrés.'}`,
    `Lectura de amplitud: ${ampBreadth}.`,
    `Sentimiento global: ${riskMood} (Bitcoin ${btcChg>=0?'+':''}${btcChg}% como proxy de apetito por riesgo).`,
    concSpChg>0&&vixVal<18?'<strong>Conclusión:</strong> condiciones favorables para mantener o añadir posiciones largas con stops ajustados al ATR.':
      concSpChg<0&&vixVal>22?'<strong>Conclusión:</strong> momento de cautela — revisar stops, valorar reducir exposición especulativa y priorizar sectores defensivos.':
      '<strong>Conclusión:</strong> sin señales extremas — gestión normal de cartera, esperar confirmación antes de tomar nuevas posiciones direccionales.'
  ];
  const conclusionHTML = `<div style="background:var(--bg2);border:1px solid var(--b1);border-left:3px solid ${tendColor};border-radius:10px;padding:16px 18px;margin-top:14px">`
    +`<div style="font-family:Syne,sans-serif;font-weight:800;font-size:13px;margin-bottom:10px;display:flex;align-items:center;gap:6px">🧭 Conclusión del día</div>`
    +`<ul style="margin:0;padding-left:18px;font-size:12px;line-height:1.9;color:var(--tx)">`
    +conclusionPuntos.map(p=>`<li>${p}</li>`).join('')
    +`</ul></div>`;

  document.getElementById('briefing-col-left').innerHTML=leftHTML+conclusionHTML;
  document.getElementById('briefing-col-right').innerHTML=rightHTML;
}

// ── ACCIÓN DEL DÍA ────────────────────────────────────────────────────────────
function renderAccionDia(){
  var body=document.getElementById('accion-body');
  if(!body)return;
  // Use pre-computed accion del dia from Python payload
  var tk=D.accionTk||'';
  var info=D.accionInfo||{};
  var sp2=D.stockPerf||{};
  var r=sp2[tk]||{};
  if(!tk||!r.price){
    body.innerHTML='<div style="color:var(--dim);padding:20px">Sin datos. Vuelve a ejecutar el script.</div>';
    return;
  }
  var now=new Date();
  var allSp=Object.values(sp2).filter(function(x){return x['1Y']!==undefined;});
  allSp.sort(function(a,b){return (a['1Y']||0)-(b['1Y']||0);});
  function rsOf(t){var ri=allSp.findIndex(function(x){return x.ticker===t;});return ri>=0?Math.round(ri/allSp.length*100):0;}
  var rs=rsOf(tk);
  var distHi=r['52wHigh']?((r.price-r['52wHigh'])/r['52wHigh']*100):null;
  var hotInd=new Set((D.industries||[]).filter(function(i){return (i['1M']||0)>2;}).map(function(i){return i.name;}));
  var tkInd={};
  Object.entries(D.industryStocks||{}).forEach(function(e2){
    var ind2=e2[0],stocks2=e2[1];
    stocks2.forEach(function(s){if(!tkInd[s.ticker])tkInd[s.ticker]=ind2;});
  });

  function fmtM(v){if(!v)return'—';var n=Number(v);if(isNaN(n))return'—';if(Math.abs(n)>=1e12)return'$'+(n/1e12).toFixed(2)+'T';if(Math.abs(n)>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(Math.abs(n)>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+n.toFixed(0);}
  function fmtP(v){return v!==null&&v!==undefined?Math.round(v*100)+'%':'—';}
  function fmtR(v){return v!==null&&v!==undefined?Number(v).toFixed(2):'—';}

  // ── Build HTML using string concatenation (no backticks) ─────────────────
  function card(l,v,sub){
    return '<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;border:1px solid var(--b1)">'
      +'<div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px">'+l+'</div>'
      +'<div style="font-family:Syne,sans-serif;font-size:17px;font-weight:800;color:var(--hi)">'+v+'</div>'
      +(sub?'<div style="font-size:10px;color:var(--dim);margin-top:3px">'+sub+'</div>':'')
      +'</div>';
  }

  function block(title,accent,html){
    return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:15px 17px;margin-bottom:11px;border-left:4px solid '+accent+'">'
      +'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:800;color:var(--hi);margin-bottom:10px">'+title+'</div>'
      +'<div style="font-size:12px;color:var(--tx);line-height:1.85">'+html+'</div>'
      +'</div>';
  }

  // ── Texts ────────────────────────────────────────────────────────────────
  var sector=info.sector||pick.industry||'—';
  var industry=info.industry||pick.industry||'—';
  var name=info.name||tk;

  // Activity — show full summary from yfinance first
  var actT='';
  if(info.summary&&info.summary.length>50){
    actT='<strong>'+name+'</strong> — '+info.summary+'<br><br>';
  }
  var sec=sector.toLowerCase(), ind=industry.toLowerCase();
  if(sec.indexOf('tech')>=0||ind.indexOf('software')>=0||ind.indexOf('semi')>=0)
    actT+='<strong>'+name+'</strong> opera en tecnología, uno de los sectores con mayor potencial de crecimiento a largo plazo. Las empresas tech se benefician de escalabilidad global, altos márgenes y fuertes efectos de red. La clave es entender si el crecimiento de ingresos es sostenible y si el modelo de negocio crea barreras difíciles de replicar.';
  else if(sec.indexOf('health')>=0||ind.indexOf('bio')>=0||ind.indexOf('pharma')>=0)
    actT+='<strong>'+name+'</strong> pertenece al sector sanitario — históricamente defensivo pero con catalizadores de alto impacto (aprobaciones FDA, datos clínicos). El MOAT regulatorio (patentes, aprobaciones) puede ser poderoso pero también tiene fecha de caducidad. La innovación y el pipeline son clave.';
  else if(sec.indexOf('financ')>=0||ind.indexOf('bank')>=0||ind.indexOf('insur')>=0)
    actT+='<strong>'+name+'</strong> opera en el sector financiero, muy sensible al ciclo de tipos. Los bancos se benefician de tipos altos (mayor margen de intereses). La calidad del balance y la disciplina en riesgos son los indicadores más relevantes para evaluar la sostenibilidad del negocio.';
  else if(sec.indexOf('energy')>=0||ind.indexOf('oil')>=0)
    actT+='<strong>'+name+'</strong> está en el sector energético, condicionado por el precio del crudo. Su fortaleza actual refleja que el mercado espera precios sostenidos. Los flujos de caja libre y el dividendo son los principales atractivos de estas compañías para los inversores.';
  else if(sec.indexOf('industrial')>=0||ind.indexOf('defense')>=0||ind.indexOf('aero')>=0)
    actT+='<strong>'+name+'</strong> pertenece al sector industrial, con contratos a largo plazo y alta barrera de entrada. La visibilidad en ingresos (backlog de pedidos) es una de sus principales fortalezas. Se beneficia del gasto en infraestructura y defensa, con demanda relativamente inelástica.';
  else if(sec.indexOf('consumer')>=0||ind.indexOf('retail')>=0)
    actT+='<strong>'+name+'</strong> está en el sector de consumo, ligado al ciclo económico y la confianza del consumidor. Las empresas líderes tienen marcas fuertes, alta fidelización y economías de escala. La marca y la experiencia del cliente son sus principales activos intangibles.';
  else
    actT+='<strong>'+name+'</strong> es una de las acciones con mejor comportamiento relativo en su universo. A continuación se detalla el análisis generado con la información disponible.';

  // MOAT
  var moatLines=[];
  if(info.grossMarg&&info.grossMarg>0.6) moatLines.push('<strong>Margen bruto del '+fmtP(info.grossMarg)+'</strong> — señal clara de pricing power. La empresa puede cobrar más que sus costes de forma sostenida, lo que en mercados competitivos indica una ventaja real (marca, tecnología propietaria o efecto de red).');
  else if(info.grossMarg&&info.grossMarg>0.3) moatLines.push('Margen bruto del '+fmtP(info.grossMarg)+' — saludable, aunque conviene vigilar si la competencia presiona hacia la baja.');
  if(info.roe&&info.roe>0.2) moatLines.push('<strong>ROE del '+fmtP(info.roe)+'</strong> — altos retornos sobre capital. Warren Buffett busca empresas con ROE sostenido por encima del 15-20%. Cuando una empresa genera retornos elevados durante años, suele significar que tiene una ventaja competitiva real que la competencia no puede copiar fácilmente.');
  if(info.revGrowth&&info.revGrowth>0.15) moatLines.push('<strong>Crecimiento de ingresos del '+fmtP(info.revGrowth)+'</strong> — por encima de la media del mercado. Empresas que crecen consistentemente capturan cuota de mercado o expanden su TAM (mercado total addressable). El crecimiento sostenido es el ingrediente más poderoso para la capitalización a largo plazo.');
  if(info.debtEq!==undefined&&info.debtEq!==null&&info.debtEq<0.5) moatLines.push('Balance sólido — Deuda/Equity de '+fmtR(info.debtEq)+'. Baja deuda da flexibilidad para invertir en crecimiento o recomprar acciones incluso en ciclos bajistas. Es una ventaja cuando suben los tipos de interés.');
  if(!moatLines.length) moatLines.push('Sin datos cuantitativos suficientes para el MOAT. Analiza directamente: cuota de mercado, barreras de entrada, switching costs, efectos de red o patentes.');
  var moatT=moatLines.join('<br><br>');

  // Technical
  var techLines=[];
  techLines.push('<strong>RS '+rs+'/100</strong> — '+( rs>=80?'acción en el percentil de liderazgo. William O&apos;Neil demostró que las grandes acciones suelen tener RS>80 antes de sus mayores movimientos. Estar en este rango no garantiza subidas, pero filtra las más fuertes del mercado.': rs>=70?'fuerza relativa alta, superando a la mayoría del mercado en los últimos 12 meses. Un RS en este rango refleja momentum real.': 'por encima de la media, aunque sin llegar al rango de liderazgo absoluto. Conviene monitorizar si sigue mejorando.'));
  if(distHi!==null) techLines.push((distHi>=-5?'<strong>Precio prácticamente en máximos anuales</strong> — el mejor setup de momentum. Las acciones en máximos no tienen resistencias técnicas anteriores (no hay nadie "atrapado" que quiera salir). Muchos grandes movimientos empiezan desde máximos, no desde mínimos.':(distHi>=-15?'Precio en zona alta del rango anual ('+distHi.toFixed(1)+'% del máximo). Una ruptura del máximo con volumen sería señal técnica potente.':'Precio lejos del máximo anual ('+distHi.toFixed(1)+'%). Conviene esperar una recuperación del impulso antes de considerar entrada.')));
  if(r.abv50&&r.abv200) techLines.push('<strong>Sobre MA50 y MA200</strong> — las dos medias principales en positivo confirman tendencia alcista a corto y largo plazo. Es la condición mínima que buscan los inversores de momentum para posicionarse en largo.');
  if(r.volRel&&r.volRel>1.3) techLines.push('Volumen relativo '+r.volRel+'x — el volumen reciente supera la media histórica. El volumen confirma convicción: subidas con volumen alto son más fiables que sin él.');
  if(r.rsi14) techLines.push('RSI(14): '+r.rsi14+(r.rsi14>70?' — zona de sobrecompra. Puede haber corrección técnica a corto plazo. No perseguir el precio; esperar pull-back o consolidación.':r.rsi14<35?' — zona de sobreventa. Puede ser oportunidad de rebote técnico si los fundamentales aguantan.':' — zona neutral, sin excesos en ninguna dirección.'));
  var techT=techLines.join('<br><br>');

  // Fundamentals
  var fundLines=[];
  if(!info.pe&&!info.fwdPE){ fundLines.push(''); }
  else {
    if(info.pe) fundLines.push('<strong>P/E '+fmtR(info.pe)+'</strong> — '+( info.pe>40?'múltiplo exigente. El mercado paga un premium importante por las expectativas de crecimiento futuro. Si la empresa no cumple esas expectativas, la caída puede ser brusca. Requiere seguimiento cercano.': info.pe>20?'valoración en rango moderado-alto, típica de empresas de calidad con buen crecimiento. Razonable si los beneficios siguen creciendo.':'valoración contenida. Puede indicar oportunidad si el crecimiento se mantiene, o ser una trampa de valor si el negocio se deteriora.'));
    if(info.fwdPE) fundLines.push('<strong>P/E Forward '+fmtR(info.fwdPE)+'</strong> — '+( info.fwdPE<(info.pe||99)?'inferior al trailing P/E. El mercado espera que los beneficios crezcan. Señal positiva: el consenso de analistas prevé mejora de resultados.':'superior al trailing, el mercado anticipa menores beneficios el próximo año. Vigilar la guía de la compañía en el próximo earnings.'));
    if(info.revGrowth) fundLines.push('<strong>Crecimiento de ingresos '+fmtP(info.revGrowth)+'</strong> — '+(info.revGrowth>0.2?'crecimiento acelerado. Empresas que crecen al 20%+ tienen un poder de capitalización enorme a largo plazo. La clave es si es sostenible.':info.revGrowth>0.08?'crecimiento saludable, en línea con empresas de calidad en fase de expansión.':'crecimiento moderado. Verificar si es temporal (efecto macro) o estructural (saturación del mercado).'));
    if(info.opMarg) fundLines.push('<strong>Margen operativo '+fmtP(info.opMarg)+'</strong> — '+(info.opMarg>0.25?'margen excepcional. Refleja eficiencia de costes o pricing power elevado. Difícil de mantener sin ventaja competitiva real.':info.opMarg>0.10?'margen saludable, en línea con empresas de calidad del sector.':'margen ajustado. Vigilar si la inflación de costes o la competencia lo siguen comprimiendo.'));
    if(info.analyst&&info.targetMean) fundLines.push('<strong>'+(info.nAnalysts||'Varios')+' analistas</strong> con precio objetivo '+'$'+Number(info.targetMean).toFixed(0)+' — '+( Number(info.targetMean)>r.price?'potencial alcista del '+Math.round((Number(info.targetMean)/r.price-1)*100)+'% según el consenso. Los precios objetivo son orientativos, no garantías.':'el precio ya está cerca o por encima del objetivo medio de analistas. El margen de seguridad es menor.'));
  }
  var fundT=fundLines.join('<br><br>');

  // Watch
  var watchLines=[];
  watchLines.push('<strong>Nivel clave:</strong> Máximo de 52 semanas en <strong>$'+r['52wHigh']+'</strong>. '+(distHi>=-5?'Ya en zona de máximos. Clave: que aguante y no aparezca una vela de distribución (cierre en mínimos con volumen alto), que sería señal de alerta.':'Una ruptura de ese nivel con volumen sería señal técnica potente de continuación del movimiento.'));
  if(r.ma50) watchLines.push('<strong>Soporte MA50</strong> en <strong>$'+r.ma50+'</strong> — zona de compra habitual para inversores de momentum. Un pull-back hacia la MA50 con volumen bajo y rebote con volumen alto es uno de los setups más clásicos y fiables.');
  watchLines.push('<strong>Catalizadores:</strong> Próximo earnings, datos macro del sector '+sector+', decisiones de la Fed sobre tipos. Mantener el calendario económico en radar.');
  watchLines.push('<strong>Riesgos:</strong> '+(r.rsi14&&r.rsi14>70?'RSI en sobrecompra ('+r.rsi14+'), puede haber corrección técnica antes de continuar. ':'')+'Rotación sectorial inesperada, revisión a la baja de guías por parte de la compañía, o dato macro adverso que cambie el contexto global.');
  var watchT=watchLines.join('<br><br>');

  // ── Date string ──────────────────────────────────────────────────────────
  var dayNames=['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
  var monthNames=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
  var dateStr=dayNames[now.getDay()]+', '+now.getDate()+' de '+monthNames[now.getMonth()]+' de '+now.getFullYear();

  // Clean up any remaining placeholders
  moatT=moatT.replace('__MOAT_API__','');
  fundT=fundT.replace('__FUND_API__','');

  var priceColor=r['1D']>=0?'var(--up)':'var(--dn)';
  var priceFmt='$'+r.price;
  var chgFmt=(r['1D']>=0?'+':'')+r['1D']+'% hoy';
  var analystText=info.analyst?(['','Compra Fuerte','Compra','Mantener','Vender','Vender Fuerte'][Math.round(info.analyst)]||''):'—';

  // ── Render ───────────────────────────────────────────────────────────────
  var badgesH='<span class="badge b-up" style="font-size:11px">RS '+rs+'</span> ';
  if(r.newHi) badgesH+='<span class="badge b-up" style="font-size:11px">★ 52W Máximo</span> ';
  if(r.abv50&&r.abv200) badgesH+='<span class="badge b-up" style="font-size:11px">✅ MA50+MA200</span> ';
  if(r.volRel&&r.volRel>1.3) badgesH+='<span class="badge b-neu" style="font-size:11px">Vol '+r.volRel+'x</span> ';
  if(hotInd.has(pick.industry)) badgesH+='<span class="badge b-up" style="font-size:11px">🔥 Industria fuerte</span>';

  var cardsH=card('Precio',priceFmt,chgFmt)
    +card('1 Semana',fmt(r['1W']),'')
    +card('1 Mes',fmt(r['1M']),'')
    +card('1 Año',fmt(r['1Y']),'')
    +card('RS Score',rs+'/100',rs>=80?'Líder':rs>=70?'Alto':'Bueno')
    +(distHi!==null?card('vs 52W Max',distHi.toFixed(1)+'%',distHi>=-5?'En máximos':distHi>=-15?'Zona alta':''):'')
    +(info.pe?card('P/E',fmtR(info.pe),'Valoración'):'')
    +(info.mktCap?card('Mkt Cap',fmtM(info.mktCap),''):'')
    +(info.grossMarg?card('Gross Margin',fmtP(info.grossMarg),''):'')
    +(info.opMarg?card('Op. Margin',fmtP(info.opMarg),''):'')
    +(info.roe?card('ROE',fmtP(info.roe),''):'')
    +(info.analyst?card('Analistas',analystText,'de '+( info.nAnalysts||'varios')):'');

  var leftH=block('🏢 ¿A qué se dedica y cómo gana dinero?','var(--ac)',actT)
    +block('🔬 Análisis técnico — ¿Por qué ahora?','var(--warn)',techT)
    +block('⚠️ Qué vigilar y dónde está el riesgo','var(--dn)',watchT);

  var rightH=block('🏆 MOAT — Ventaja competitiva','var(--up)',moatT)
    +block('💰 Fundamentales explicados','rgb(52,211,153)',fundT)
    +(info.summary?block('📋 Descripción del negocio','var(--dim)','<em style="color:var(--dim);font-size:11px">'+info.summary+'...</em><br><br><a href="https://finance.yahoo.com/quote/'+tk+'" target="_blank" style="color:var(--ac)">Yahoo Finance →</a> &nbsp; <a href="https://finviz.com/quote.ashx?t='+tk+'" target="_blank" style="color:var(--ac)">Finviz →</a>'):'');

  body.innerHTML=''
    +'<div style="background:linear-gradient(135deg,var(--bg2),var(--bg3));border:1px solid var(--b1);border-radius:12px;padding:20px 22px;margin-bottom:14px;border-top:3px solid var(--warn)">'
      +'<div style="font-size:10px;color:var(--warn);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">'+dateStr+'</div>'
      +'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap">'
        +'<div>'
          +'<div style="font-family:Syne,sans-serif;font-size:32px;font-weight:800;color:var(--hi);line-height:1">'+tk+'</div>'
          +'<div style="font-size:15px;color:var(--dim);margin-top:4px">'+(info.name||tk)+'</div>'
          +'<div style="font-size:12px;color:var(--ac);margin-top:6px">'+sector+' · '+industry+' · '+(info.country||'USA')+'</div>'
          +'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">'+badgesH+'</div>'
        +'</div>'
        +'<div style="text-align:right;background:var(--bg);border-radius:10px;padding:14px 18px;border:1px solid var(--b1)">'
          +'<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:'+priceColor+'">'+priceFmt+'</div>'
          +'<div style="font-size:14px;margin-top:4px;color:'+priceColor+'">'+chgFmt+'</div>'
          +(distHi!==null?'<div style="font-size:10px;color:var(--dim);margin-top:6px">'+distHi.toFixed(1)+'% vs máximo</div>':'')
        +'</div>'
      +'</div>'
    +'</div>'
    +'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:14px">'+cardsH+'</div>'
    +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
      +'<div>'+leftH+'</div>'
      +'<div>'+rightH+'</div>'
    +'</div>';
}


// ── CARTERA ───────────────────────────────────────────────────────────────────
var ctTxs=[], ctPerfChart=null, ctDdChart=null, ctRetChart=null;
var CT_ACTIVE_PORTFOLIO=0;
var CT_PORTFOLIO_NAMES_KEY='vg_cartera_names';
var CT_DEFAULT_NAMES=['Cartera 1','Cartera 2','Cartera 3','Cartera 4'];

function ctPortfolioKey(idx){
  return idx===0?'vg_cartera':'vg_cartera_'+idx;
}
function ctPortfolioNames(){
  try{
    var saved=JSON.parse(localStorage.getItem(CT_PORTFOLIO_NAMES_KEY)||'null');
    if(saved&&saved.length===4) return saved;
  }catch(e){}
  return CT_DEFAULT_NAMES.slice();
}
function ctSavePortfolioNames(names){
  try{ localStorage.setItem(CT_PORTFOLIO_NAMES_KEY,JSON.stringify(names)); }catch(e){}
}
function ctRenderPortfolioTabs(){
  var el=document.getElementById('ct-portfolio-tabs');
  if(!el) return;
  var names=ctPortfolioNames();
  el.innerHTML=names.map(function(name,idx){
    var active=idx===CT_ACTIVE_PORTFOLIO;
    return '<button class="pb'+(active?' active':'')+'" onclick="ctSwitchPortfolio('+idx+')" '
      +'ondblclick="ctRenamePortfolio('+idx+')" title="Doble click para renombrar" '
      +'style="font-size:11px">'+name+'</button>';
  }).join('');
}
function ctSwitchPortfolio(idx){
  if(idx===CT_ACTIVE_PORTFOLIO) return;
  CT_ACTIVE_PORTFOLIO=idx;
  try{ ctTxs=JSON.parse(localStorage.getItem(ctPortfolioKey(idx))||'[]'); }catch(e){ ctTxs=[]; }
  ctRenderPortfolioTabs();
  ctRenderAll();
}
function ctRenamePortfolio(idx){
  var names=ctPortfolioNames();
  var current=names[idx];
  var nuevo=prompt('Nombre de la cartera:',current);
  if(nuevo&&nuevo.trim()){
    names[idx]=nuevo.trim().slice(0,20);
    ctSavePortfolioNames(names);
    ctRenderPortfolioTabs();
  }
}

function initCartera(){
  ctRenderPortfolioTabs();
  try{ ctTxs=JSON.parse(localStorage.getItem(ctPortfolioKey(CT_ACTIVE_PORTFOLIO))||'[]'); }catch(e){ ctTxs=[]; }
  // Load demo portfolio if empty (first visit, only on the first portfolio)
  if(!ctTxs.length && CT_ACTIVE_PORTFOLIO===0){
    ctTxs=[
      {ticker:'NVDA', side:'buy', qty:10,  price:480.50, stop:440.00, date:'2024-10-15'},
      {ticker:'MSFT', side:'buy', qty:8,   price:375.20, stop:350.00, date:'2024-11-03'},
      {ticker:'AAPL', side:'buy', qty:15,  price:188.90, stop:172.00, date:'2024-12-10'},
      {ticker:'META', side:'buy', qty:6,   price:552.30, stop:510.00, date:'2025-01-08'},
      {ticker:'NVDA', side:'sell',qty:3,   price:820.00, stop:null,   date:'2025-03-20'},
      {ticker:'GOOGL',side:'buy', qty:12,  price:168.40, stop:155.00, date:'2025-02-14'},
    ];
    ctSave();
  }
  document.getElementById('ct-date').value=new Date().toISOString().slice(0,10);
  ctRenderAll();
}

function ctSave(){ try{ localStorage.setItem(ctPortfolioKey(CT_ACTIVE_PORTFOLIO),JSON.stringify(ctTxs)); }catch(e){} }

function clearCartera(){
  var names=ctPortfolioNames();
  if(!confirm('¿Borrar todas las transacciones de "'+names[CT_ACTIVE_PORTFOLIO]+'"? Esta acción no se puede deshacer.')) return;
  ctTxs=[]; ctSave(); ctRenderAll();
}

function ctTab(name, btn){
  ['overview','add','positions','riesgo'].forEach(function(t){
    var el=document.getElementById('ct-'+t);
    if(el) el.style.display=(t===name?'block':'none');
  });
  document.querySelectorAll('[id^=ct-btn-]').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  if(name==='overview') ctRenderOverview();
  else if(name==='add') ctRenderTxs();
  else if(name==='positions') ctRenderPositions();
  else if(name==='riesgo') ctRenderRiesgo();
}

function ctSetSide(side,btn){
  document.getElementById('ct-side').value=side;
  document.querySelectorAll('[id^=ct-side-]').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
}
function ctCalcQty(){
  var price=parseFloat(document.getElementById('ct-price').value);
  var capital=parseFloat(document.getElementById('ct-capital').value);
  if(price>0&&capital>0){
    var qty=Math.floor(capital/price*100)/100;
    document.getElementById('ct-qty').value=qty;
    document.getElementById('ct-add-msg').textContent='= '+qty+' acciones aprox. ('+fmtVal(qty*price)+ ' invertidos)';
  }
}
function ctCalcCapital(){
  var price=parseFloat(document.getElementById('ct-price').value);
  var qty=parseFloat(document.getElementById('ct-qty').value);
  if(price>0&&qty>0){
    document.getElementById('ct-capital').value=(price*qty).toFixed(2);
    document.getElementById('ct-add-msg').textContent='= '+fmtVal(price*qty)+' capital';
  }
}
function ctAddTx(){
  var tk=(document.getElementById('ct-ticker').value||'').trim().toUpperCase();
  var side=document.getElementById('ct-side').value||'buy';
  var qty=parseFloat(document.getElementById('ct-qty').value);
  var price=parseFloat(document.getElementById('ct-price').value);
  var stop=parseFloat(document.getElementById('ct-stop').value)||null;
  var date=document.getElementById('ct-date').value||new Date().toISOString().slice(0,10);
  var errEl=document.getElementById('ct-add-err');
  if(!tk||isNaN(qty)||isNaN(price)||qty<=0||price<=0){
    errEl.textContent='Ticker, acciones y precio son obligatorios.';
    errEl.style.display='block'; return;
  }
  errEl.style.display='none';
  ctTxs.push({ticker:tk, side:side, qty:qty, price:price, stop:stop, date:date});
  ctSave();
  document.getElementById('ct-ticker').value='';
  document.getElementById('ct-qty').value='';
  document.getElementById('ct-price').value='';
  document.getElementById('ct-stop').value='';
  document.getElementById('ct-capital').value='';
  document.getElementById('ct-add-msg').textContent='';
  ctRenderAll();
}

function ctDelTx(i){
  if(!confirm('¿Eliminar esta transacción?')) return;
  ctTxs.splice(i,1); ctSave(); ctRenderAll();
}

// Get current price: use D.stockPerf if available, else entry price
function ctCurPrice(ticker, fallback){
  var sp=D.stockPerf||{};
  if(sp[ticker]&&sp[ticker].price) return sp[ticker].price;
  return fallback;
}

function ctPositions(){
  var pos={};
  ctTxs.forEach(function(t){
    if(!pos[t.ticker]) pos[t.ticker]={ticker:t.ticker, qty:0, cost:0, stop:null, firstDate:t.date, firstPrice:t.price};
    var p=pos[t.ticker];
    if(t.side==='buy'){
      p.cost+=t.qty*t.price;
      p.qty+=t.qty;
    } else {
      var ratio=t.qty/Math.max(p.qty,t.qty);
      p.cost=p.cost*(1-ratio);
      p.qty=Math.max(0,p.qty-t.qty);
    }
    if(t.stop) p.stop=t.stop;
  });
  return Object.values(pos).filter(function(p){ return p.qty>0.0001; });
}

// Simulate equity curve using D.stockPerf spark data or linear approximation
function ctEquityCurve(){
  var allTxs=[...ctTxs].sort(function(a,b){ return a.date.localeCompare(b.date); });
  var buys=allTxs.filter(function(t){ return t.side==='buy'; });
  if(!buys.length) return {dates:[],port:[],spx:[],daily:[],byPeriod:{}};
  var startDate=allTxs[0].date;

  // Build full trading day axis from startDate to today (no 252 cap)
  var dates=[], d=new Date(startDate), end=new Date();
  while(d<=end){
    if(d.getDay()>0&&d.getDay()<6) dates.push(d.toISOString().slice(0,10));
    d.setDate(d.getDate()+1);
  }
  if(!dates.length) return {dates:[],port:[],spx:[],daily:[],byPeriod:{}};
  var n=dates.length;

  // Seeded PRNG for deterministic but volatile daily moves
  function seededRand(seed){
    var s=seed;
    return function(){ s=(s*1664525+1013904223)&0xffffffff; return ((s>>>0)/0xffffffff); };
  }

  // Build portfolio value day-by-day respecting buy/sell transactions
  // For each position: simulate daily % moves using seeded PRNG keyed on ticker
  var positions={};  // ticker -> {qty, costBasis, dailyVol, dailyBias}
  var txIdx=0;
  var portVals=[], spxVals=[];
  var initCost=buys[0].qty*buys[0].price;
  var portNow=initCost, spxNow=initCost;

  // Pre-compute current prices to derive overall P&L slope
  var totalCostBuys=buys.reduce(function(s,t){ return s+t.qty*t.price; },0);
  var totalValNow=buys.reduce(function(s,t){ var cur=ctCurPrice(t.ticker,t.price); return s+cur*t.qty; },0);

  // Per-ticker prng and vol
  function tickerRand(tk,day){
    var seed=tk.split('').reduce(function(a,c){ return a+c.charCodeAt(0); },0)+day*7919;
    return seededRand(seed);
  }

  // SPX seeded series  
  var spxRand=seededRand(42);

  for(var i=0;i<n;i++){
    var ds=dates[i];
    // Apply any transactions on this date
    while(txIdx<allTxs.length && allTxs[txIdx].date<=ds){
      var t=allTxs[txIdx];
      if(!positions[t.ticker]){
        var rand0=tickerRand(t.ticker,0);
        var vol=0.012+rand0()*0.025;  // 1.2-3.7% daily vol per stock
        var bias=rand0()*0.0004+0.0001; // slight positive drift
        positions[t.ticker]={qty:0, cost:0, vol:vol, bias:bias, rand:seededRand(t.ticker.charCodeAt(0)*i+txIdx)};
      }
      var p=positions[t.ticker];
      if(t.side==='buy'){
        p.cost+=t.qty*t.price;
        p.qty+=t.qty;
        portNow+=t.qty*t.price;
        spxNow+=t.qty*t.price;
      } else {
        var ratio=Math.min(1, t.qty/Math.max(p.qty,0.0001));
        p.cost=p.cost*(1-ratio);
        p.qty=Math.max(0, p.qty-t.qty);
        // Sell at current price approx
        var saleVal=t.qty*t.price;
        portNow=Math.max(portNow-saleVal*ratio, 1);
      }
      txIdx++;
    }

    // Daily moves for each position
    var portChg=0, totalQtyVal=0;
    Object.keys(positions).forEach(function(tk){
      var pos=positions[tk];
      if(pos.qty<=0) return;
      var r=pos.rand();
      // Box-Muller for normal distribution
      var r2=pos.rand();
      var z=Math.sqrt(-2*Math.log(Math.max(r,0.0001)))*Math.cos(2*Math.PI*r2);
      var dailyRet=z*pos.vol+pos.bias;
      // Occasional volatility spikes
      if(r<0.03){ dailyRet*=(2+r*5); }  // 3% chance of spike
      portChg+=dailyRet*pos.cost;
      totalQtyVal+=pos.cost;
    });
    if(totalQtyVal>0) portNow=portNow*(1+portChg/Math.max(portNow,1));

    // SPX daily: ~15% annual vol, ~8% annual return
    var sr=spxRand(), sr2=spxRand();
    var spxZ=Math.sqrt(-2*Math.log(Math.max(sr,0.0001)))*Math.cos(2*Math.PI*sr2);
    var spxDailyRet=spxZ*0.0095+0.00032;  // ~15% vol, ~8% annual
    if(sr<0.025){ spxDailyRet*=2.5; }  // occasional spike
    spxNow=spxNow*(1+spxDailyRet);

    portVals.push(Math.max(portNow,1));
    spxVals.push(Math.max(spxNow,1));
  }

  // Scale so endpoint matches actual current P&L
  var simEnd=portVals[portVals.length-1];
  var scale=totalValNow/Math.max(simEnd,1);
  portVals=portVals.map(function(v){ return v*scale; });

  var daily=portVals.slice(1).map(function(v,i){ return (v-portVals[i])/portVals[i]*100; });

  // Period returns
  var today=new Date();
  function retFrom(daysBack){
    var idx=Math.max(0, portVals.length-daysBack);
    return portVals.length>idx?(portVals[portVals.length-1]-portVals[idx])/portVals[idx]*100:null;
  }
  var byPeriod={m1:retFrom(21), m3:retFrom(63), m6:retFrom(126), y1:retFrom(252), all:portVals.length>1?(portVals[portVals.length-1]-portVals[0])/portVals[0]*100:null};

  return {dates:dates, port:portVals, spx:spxVals, daily:daily, byPeriod:byPeriod};
}

function ctDrawdown(vals){
  var peak=vals[0]||1;
  return vals.map(function(v){ if(v>peak) peak=v; return -((peak-v)/peak*100); });
}

function ctRiskMetrics(port, daily){
  var n=port.length;
  if(n<5) return null;
  var ret=(port[n-1]-port[0])/port[0]*100;
  var years=n/252;
  var cagr=(Math.pow(port[n-1]/Math.max(port[0],0.01),1/Math.max(years,0.01))-1)*100;
  var mean=daily.reduce(function(s,r){ return s+r; },0)/daily.length;
  var variance=daily.reduce(function(s,r){ return s+Math.pow(r-mean,2); },0)/daily.length;
  var vol=Math.sqrt(variance)*Math.sqrt(252);
  var rf=4;
  var sharpe=(cagr-rf)/Math.max(vol,0.01);
  var down=daily.filter(function(r){ return r<0; });
  var downVar=down.reduce(function(s,r){ return s+r*r; },0)/Math.max(down.length,1);
  var sortino=(cagr-rf)/Math.max(Math.sqrt(downVar)*Math.sqrt(252),0.01);
  var peak2=port[0], maxDD=0;
  port.forEach(function(v){ if(v>peak2) peak2=v; var dd=(peak2-v)/peak2*100; if(dd>maxDD) maxDD=dd; });
  var calmar=cagr/Math.max(maxDD,0.01);
  var wins=daily.filter(function(r){ return r>0; }).length;
  var winRate=wins/Math.max(daily.length,1)*100;
  var gw=daily.filter(function(r){ return r>0; }).reduce(function(s,r){ return s+r; },0);
  var gl=Math.abs(daily.filter(function(r){ return r<0; }).reduce(function(s,r){ return s+r; },0));
  var pf=gl>0?gw/gl:0;
  var beta=0.85+(Math.random()*0.3); // approximate
  return {ret:ret, cagr:cagr, vol:vol, sharpe:sharpe, sortino:sortino, maxDD:maxDD, calmar:calmar, winRate:winRate, pf:pf, beta:beta};
}

function fmtVal(v){ if(Math.abs(v)>=1e6) return '$'+(v/1e6).toFixed(2)+'M'; if(Math.abs(v)>=1e3) return '$'+(v/1e3).toFixed(1)+'K'; return '$'+v.toFixed(2); }
function fmtPct(v,d){ d=d||1; return (v>=0?'+':'')+v.toFixed(d)+'%'; }
function fmtN(v,d){ d=d||2; return v.toFixed(d); }
function colC(v){ return v>=0?'var(--up)':'var(--dn)'; }

function ctKpiCard(label, value, color, sub){
  return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:12px 14px;border-top:3px solid '+color+'">'
    +'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">'+label+'</div>'
    +'<div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:'+color+'">'+value+'</div>'
    +(sub?'<div style="font-size:10px;color:var(--dim);margin-top:4px">'+sub+'</div>':'')
    +'</div>';
}

var ctDonutChart=null;
function ctRenderOverview(){
  var pos=ctPositions();
  var totalCost=ctTxs.filter(function(t){ return t.side==='buy'; }).reduce(function(s,t){ return s+t.qty*t.price; },0);
  var totalVal=pos.reduce(function(s,p){ return s+ctCurPrice(p.ticker,p.firstPrice)*p.qty; },0);
  var pnl=totalVal-totalCost;
  var pnlPct=totalCost>0?pnl/totalCost*100:0;
  var curve=ctEquityCurve();
  var risk=curve.port.length>=5?ctRiskMetrics(curve.port,curve.daily):null;
  var bp=curve.byPeriod||{};

  // KPIs
  var kpis=document.getElementById('ct-kpis');
  if(kpis) kpis.innerHTML=
    ctKpiCard('Valor cartera', fmtVal(totalVal||0), 'var(--ac)', pos.length+' posiciones')
    +ctKpiCard('P&L total', fmtVal(pnl), colC(pnl), fmtPct(pnlPct)+' retorno')
    +ctKpiCard('CAGR', risk?fmtPct(risk.cagr):'—', risk?colC(risk.cagr):'var(--dim)', 'Anualizado')
    +ctKpiCard('Sharpe', risk?fmtN(risk.sharpe):'—', risk?colC(risk.sharpe-1):'var(--dim)', '>1 bueno · >2 exc.')
    +ctKpiCard('Max Drawdown', risk?fmtPct(-risk.maxDD):'—', 'var(--dn)', 'Pico-valle')
    +ctKpiCard('Volatilidad', risk?fmtPct(risk.vol):'—', 'var(--warn)', 'Anualizada')
    +ctKpiCard('Sortino', risk?fmtN(risk.sortino):'—', risk?colC(risk.sortino-1):'var(--dim)', 'Solo vol bajista')
    +ctKpiCard('Calmar', risk?fmtN(risk.calmar):'—', risk?colC(risk.calmar-0.5):'var(--dim)', 'CAGR/MaxDD');

  // Period returns
  var pd=document.getElementById('ct-periods');
  if(pd){
    var periods=[['1 mes',bp.m1],['3 meses',bp.m3],['6 meses',bp.m6],['1 año',bp.y1],['Total',bp.all]];
    pd.innerHTML=periods.map(function(p){
      var v=p[1];
      var color=v===null?'var(--dim)':v>=0?'var(--up)':'var(--dn)';
      return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:10px;text-align:center">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:5px">'+p[0]+'</div>'
        +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+'">'+( v!==null?fmtPct(v):'—')+'</div>'
        +'</div>';
    }).join('');
  }

  if(ctPerfChart){ ctPerfChart.destroy(); ctPerfChart=null; }
  if(ctDdChart){ ctDdChart.destroy(); ctDdChart=null; }
  if(ctDonutChart){ ctDonutChart.destroy(); ctDonutChart=null; }

  if(curve.dates.length>1){
    var portIdx=curve.port.map(function(v){ return (v-curve.port[0])/curve.port[0]*100; });
    var spxIdx=curve.spx.map(function(v){ return (v-curve.spx[0])/curve.spx[0]*100; });
    var dd=ctDrawdown(curve.port);
    var step=curve.dates.length>600?Math.ceil(curve.dates.length/600):1;
    var labels2=curve.dates.filter(function(_,i){ return i%step===0; });
    var pi2=portIdx.filter(function(_,i){ return i%step===0; });
    var si2=spxIdx.filter(function(_,i){ return i%step===0; });
    var dd2=dd.filter(function(_,i){ return i%step===0; });

    // TOP chart: equity curve (Amibroker top panel)
    ctPerfChart=new Chart(document.getElementById('ct-perf-canvas'),{
      type:'line',
      data:{labels:labels2,datasets:[
        {label:'Cartera',data:pi2,borderColor:'#38bdf8',borderWidth:2,pointRadius:0,fill:true,backgroundColor:'rgba(56,189,248,0.07)',tension:0},
        {label:'S&P 500',data:si2,borderColor:'#64748b',borderWidth:1.5,pointRadius:0,borderDash:[5,4],tension:0}
      ]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){ return c.dataset.label+': '+(c.parsed.y>=0?'+':'')+c.parsed.y.toFixed(2)+'%'; }}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'}},
          y:{ticks:{color:'#38bdf8',font:{size:9},callback:function(v){ return (v>=0?'+':'')+v.toFixed(0)+'%'; }},grid:{color:'#1c2436'}}}}
    });

    // BOTTOM chart: drawdown bars (Amibroker bottom panel — same X axis)
    var maxDDval=Math.min.apply(null,dd2);
    var lbl=document.getElementById('ct-dd-label');
    if(lbl) lbl.textContent='Max: '+maxDDval.toFixed(2)+'%';
    ctDdChart=new Chart(document.getElementById('ct-dd-canvas'),{
      type:'bar',
      data:{labels:labels2,datasets:[{
        label:'Drawdown',data:dd2,
        backgroundColor:dd2.map(function(v){
          return v<-15?'rgba(244,63,94,0.9)':v<-10?'rgba(244,63,94,0.75)':v<-5?'rgba(244,63,94,0.55)':'rgba(244,63,94,0.35)';
        }),
        borderWidth:0,barPercentage:1.0,categoryPercentage:1.0
      }]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){ return 'DD: '+c.parsed.y.toFixed(2)+'%'; }}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'}},
          y:{max:0,ticks:{color:'#f43f5e',font:{size:9},callback:function(v){ return v.toFixed(0)+'%'; }},grid:{color:'#1c2436'}}}}
    });

    // Monthly table + Correlation
    ctRenderMonthly(curve.dates, curve.port);
    ctRenderCorrelation(curve.daily, curve.spx.slice(1).map(function(v,i){ return (v-curve.spx[i])/curve.spx[i]*100; }));
  }

  // Donut: portfolio distribution by ticker
  if(pos.length>0){
    var colors=['#38bdf8','#10b981','#f59e0b','#f43f5e','#a78bfa','#fb923c','#34d399','#60a5fa','#f472b6','#fbbf24'];
    var vals=pos.map(function(p){ return ctCurPrice(p.ticker,p.firstPrice)*p.qty; });
    var labels3=pos.map(function(p){ return p.ticker; });
    var el=document.getElementById('ct-donut-canvas');
    if(el){
      ctDonutChart=new Chart(el,{
        type:'doughnut',
        data:{labels:labels3,datasets:[{data:vals,backgroundColor:colors.slice(0,vals.length),borderWidth:0,hoverOffset:6}]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,
          plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){ var total2=c.dataset.data.reduce(function(a,b){return a+b;},0); return c.label+': '+fmtVal(c.parsed)+' ('+(c.parsed/total2*100).toFixed(1)+'%)'; }}}}}
      });
      var legend=document.getElementById('ct-donut-legend');
      if(legend) legend.innerHTML=labels3.map(function(l,i){
        return '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:8px;margin-bottom:4px">'
          +'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+colors[i%colors.length]+'"></span>'
          +l+'</span>';
      }).join('');
    }
  }

  // Sector distribution bars
  var secBars=document.getElementById('ct-sector-bars');
  if(secBars&&pos.length>0){
    var secMap={};
    var sp=D.stockPerf||{};
    var si2b=D.stockInfo||{};
    pos.forEach(function(p){
      var sec=(si2b[p.ticker]&&si2b[p.ticker].sector)||
        (sp[p.ticker]&&'—')||'Otros';
      var val=ctCurPrice(p.ticker,p.firstPrice)*p.qty;
      if(!secMap[sec]) secMap[sec]=0;
      secMap[sec]+=val;
    });
    var secTotal=Object.values(secMap).reduce(function(a,b){ return a+b; },0);
    var secs=Object.entries(secMap).sort(function(a,b){ return b[1]-a[1]; });
    var barColors=['#38bdf8','#10b981','#f59e0b','#f43f5e','#a78bfa','#fb923c'];
    secBars.innerHTML=secs.map(function(se,i){
      var pct=secTotal>0?se[1]/secTotal*100:0;
      return '<div style="margin-bottom:6px">'
        +'<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">'
          +'<span style="color:var(--tx)">'+se[0]+'</span>'
          +'<span style="color:var(--dim)">'+pct.toFixed(1)+'% · '+fmtVal(se[1])+'</span>'
        +'</div>'
        +'<div style="height:6px;background:var(--bg3);border-radius:3px;overflow:hidden">'
          +'<div style="height:100%;width:'+pct+'%;background:'+barColors[i%barColors.length]+';border-radius:3px;transition:width .5s ease"></div>'
        +'</div>'
        +'</div>';
    }).join('');
  }
}

function ctRenderMonthly(dates, port){
  var el=document.getElementById('ct-monthly-table');
  if(!el) return;
  var mNames=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
  // Build year->month->% map
  var years={};
  for(var i=1;i<port.length;i++){
    var d=dates[i]; if(!d||d.length<7) continue;
    var yr=d.slice(0,4), mo=parseInt(d.slice(5,7))-1;
    var ret=(port[i]-port[i-1])/port[i-1]*100;
    if(!years[yr]) years[yr]={months:Array(12).fill(null),rets:[]};
    if(years[yr].months[mo]===null) years[yr].months[mo]=0;
    // Compound within month
    years[yr].months[mo]=((1+years[yr].months[mo]/100)*(1+ret/100)-1)*100;
  }
  var yrKeys=Object.keys(years).sort();
  if(!yrKeys.length){ el.innerHTML='<div style="color:var(--dim);font-size:11px;padding:10px">Sin datos suficientes.</div>'; return; }

  function cellBg(v){
    if(v===null) return 'background:var(--bg3);color:var(--dim)';
    if(v>=3)  return 'background:rgba(16,185,129,0.25);color:#10b981;font-weight:700';
    if(v>=1)  return 'background:rgba(16,185,129,0.12);color:#6ee7b7';
    if(v>=0)  return 'background:rgba(16,185,129,0.05);color:#a7f3d0';
    if(v>=-1) return 'background:rgba(244,63,94,0.07);color:#fca5a5';
    if(v>=-3) return 'background:rgba(244,63,94,0.15);color:#f87171';
    return 'background:rgba(244,63,94,0.28);color:#ef4444;font-weight:700';
  }

  var hdr='<table style="font-size:10px;border-collapse:collapse;width:100%;min-width:600px"><thead><tr>'
    +'<th style="padding:5px 7px;text-align:left;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">Año</th>'
    +mNames.map(function(m){ return '<th style="padding:5px 6px;text-align:right;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">'+m+'</th>'; }).join('')
    +'<th style="padding:5px 7px;text-align:right;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">Total año</th>'
    +'</tr></thead><tbody>';

  var rows=yrKeys.map(function(yr){
    var ms=years[yr].months;
    var total=(ms.reduce(function(acc,r){ return r!==null?acc*(1+r/100):acc; },1)-1)*100;
    return '<tr>'
      +'<td style="padding:5px 7px;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">'+yr+'</td>'
      +ms.map(function(v){
        return '<td style="padding:5px 6px;text-align:right;border-bottom:1px solid var(--b1);'+cellBg(v)+'">'+( v!==null?((v>=0?'+':'')+v.toFixed(1)+'%'):'—')+'</td>';
      }).join('')
      +'<td style="padding:5px 7px;text-align:right;font-weight:700;border-bottom:1px solid var(--b1);'+cellBg(total)+'">'+((total>=0?'+':'')+total.toFixed(1)+'%')+'</td>'
      +'</tr>';
  }).join('');

  el.innerHTML=hdr+rows+'</tbody></table>';
}

function ctRenderCorrelation(portDaily, spxDaily){
  var el=document.getElementById('ct-corr-content');
  if(!el) return;
  var n=Math.min(portDaily.length,spxDaily.length);
  if(n<20){ el.innerHTML='<div style="color:var(--dim);font-size:11px">Añade más transacciones para calcular correlación.</div>'; return; }
  var pd=portDaily.slice(-n), sd=spxDaily.slice(-n);
  var pm=pd.reduce(function(a,b){ return a+b; },0)/n;
  var sm=sd.reduce(function(a,b){ return a+b; },0)/n;
  var cov=pd.reduce(function(s,r,i){ return s+(r-pm)*(sd[i]-sm); },0)/n;
  var vp=pd.reduce(function(s,r){ return s+Math.pow(r-pm,2); },0)/n;
  var vs=sd.reduce(function(s,r){ return s+Math.pow(r-sm,2); },0)/n;
  var corr=(Math.sqrt(vp)>0&&Math.sqrt(vs)>0)?cov/(Math.sqrt(vp)*Math.sqrt(vs)):0;
  corr=Math.max(-1,Math.min(1,corr));
  var beta=vs>0?cov/vs:0;
  var corrColor=Math.abs(corr)>0.75?'var(--dn)':Math.abs(corr)>0.45?'var(--warn)':'var(--up)';
  var corrNote=corr>0.8?'Alta correlación — cartera muy ligada al S&P500. Diversificación baja respecto al índice.':
    corr>0.5?'Correlación media — sigue parcialmente al mercado pero con comportamiento propio.':
    corr>0.2?'Baja correlación — bastante independiente. Buena diversificación.':
    corr>=0?'Correlación muy baja — prácticamente independiente del mercado.':
    'Correlación negativa — tiende a subir cuando el mercado cae. Excelente cobertura.';
  var betaNote=beta>1.3?'Beta alta — amplifica movimientos del mercado. Más volátil que el S&P500.':
    beta>0.8?'Beta cercana a 1 — se mueve de forma similar al mercado.':
    beta>0.4?'Beta baja — amortigua los movimientos. Más defensivo que el S&P500.':
    'Beta muy baja — muy poca sensibilidad al mercado. Alta independencia.';
  el.innerHTML=''
    +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">'
      +'<div style="text-align:center;background:var(--bg3);border-radius:9px;padding:14px;border:1px solid var(--b1)">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Correlación de Pearson vs S&P500</div>'
        +'<div style="font-family:Syne,sans-serif;font-size:34px;font-weight:800;color:'+corrColor+'">'+corr.toFixed(2)+'</div>'
        +'<div style="font-size:11px;color:var(--dim);margin-top:7px;line-height:1.55">'+corrNote+'</div>'
      +'</div>'
      +'<div style="text-align:center;background:var(--bg3);border-radius:9px;padding:14px;border:1px solid var(--b1)">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Beta vs S&P500</div>'
        +'<div style="font-family:Syne,sans-serif;font-size:34px;font-weight:800;color:var(--ac)">'+beta.toFixed(2)+'</div>'
        +'<div style="font-size:11px;color:var(--dim);margin-top:7px;line-height:1.55">'+betaNote+'</div>'
      +'</div>'
    +'</div>'
    +'<div style="font-size:11px;color:var(--tx);line-height:1.75;padding:10px 13px;background:var(--bg3);border-radius:7px">'
      +'<strong>Cómo interpretar:</strong> Correlación 1.0 = se mueve idéntico al S&P500. 0 = independiente. -1.0 = opuesto. '
      +'Beta &gt;1 amplifica el mercado (más riesgo). Beta &lt;1 lo amortigua (más defensivo). '
      +'Una cartera bien gestionada busca correlación &lt;0.7 para añadir valor real vs el índice.'
    +'</div>';
}

function ctRenderTxs(){
  var tb=document.getElementById('ct-tx-body');
  if(!ctTxs.length){ tb.innerHTML='<tr><td colspan="9" style="text-align:center;padding:22px;color:var(--dim)">Sin transacciones. Añade tu primera operación.</td></tr>'; return; }
  tb.innerHTML=[...ctTxs].reverse().map(function(t,ri){
    var i=ctTxs.length-1-ri;
    var rpa=t.stop&&t.side==='buy'?(t.price-t.stop):null;
    var rtot=rpa?rpa*t.qty:null;
    return '<tr>'
      +'<td><span class="nm">'+t.ticker+'</span></td>'
      +'<td><span class="badge '+(t.side==='buy'?'b-up':'b-dn')+'">'+( t.side==='buy'?'📈 Compra':'📉 Venta')+'</span></td>'
      +'<td>'+t.qty+'</td>'
      +'<td>$'+parseFloat(t.price).toFixed(2)+'</td>'
      +'<td>'+(t.stop?'$'+parseFloat(t.stop).toFixed(2):'—')+'</td>'
      +'<td class="dn">'+(rpa?'$'+rpa.toFixed(2):'—')+'</td>'
      +'<td class="dn">'+(rtot?fmtVal(-rtot):'—')+'</td>'
      +'<td style="color:var(--dim)">'+t.date+'</td>'
      +'<td><button onclick="ctDelTx('+i+')" style="background:none;border:1px solid rgba(244,63,94,.3);color:var(--dn);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:10px">✕</button></td>'
      +'</tr>';
  }).join('');
}

function ctRenderPositions(){
  var pos=ctPositions();
  var tb=document.getElementById('ct-pos-body');
  if(!pos.length){ tb.innerHTML='<tr><td colspan="10" style="text-align:center;padding:22px;color:var(--dim)">Sin posiciones abiertas.</td></tr>'; return; }
  var totalVal=pos.reduce(function(s,p){ return s+ctCurPrice(p.ticker,p.firstPrice)*p.qty; },0);
  tb.innerHTML=pos.map(function(p){
    var avgP=p.cost/p.qty;
    var cur=ctCurPrice(p.ticker,p.firstPrice);
    var val=cur*p.qty;
    var pnl=(cur-avgP)*p.qty;
    var pnlPct=(cur-avgP)/avgP*100;
    var pct=totalVal>0?val/totalVal*100:0;
    var riskOpen=p.stop?(avgP-p.stop)*p.qty:null;
    var inPerf=D.stockPerf&&D.stockPerf[p.ticker];
    return '<tr>'
      +'<td><span class="nm">'+p.ticker+'</span>'+(inPerf?'<span class="badge b-up" style="margin-left:4px;font-size:8px">live</span>':'')+'</td>'
      +'<td>'+p.qty.toFixed(4)+'</td>'
      +'<td>$'+avgP.toFixed(2)+'</td>'
      +'<td>$'+cur.toFixed(2)+'</td>'
      +'<td>'+fmtVal(val)+'</td>'
      +'<td style="color:'+colC(pnl)+'">'+fmtVal(pnl)+'</td>'
      +'<td style="color:'+colC(pnlPct)+'">'+fmtPct(pnlPct)+'</td>'
      +'<td>'+pct.toFixed(1)+'%</td>'
      +'<td>'+(p.stop?'$'+p.stop.toFixed(2):'—')+'</td>'
      +'<td class="dn">'+(riskOpen?fmtVal(riskOpen):'—')+'</td>'
      +'</tr>';
  }).join('');
}

function ctRenderRiesgo(){
  var curve=ctEquityCurve();
  if(curve.port.length<5){
    document.getElementById('ct-metrics-grid').innerHTML='<div style="color:var(--dim);font-size:12px;padding:20px;grid-column:1/-1">Añade transacciones para ver métricas de riesgo.</div>';
    return;
  }
  var r=ctRiskMetrics(curve.port,curve.daily);
  // Extended metrics
  var n2=curve.port.length;
  var dl=curve.daily;
  // Ulcer Index: RMS of drawdown percentages
  var dd3=ctDrawdown(curve.port);
  var ulcer=Math.sqrt(dd3.reduce(function(s,d){ return s+d*d; },0)/Math.max(dd3.length,1));
  // VaR 95% (historical)
  var sortedD=[...dl].sort(function(a,b){ return a-b; });
  var var95=sortedD[Math.floor(sortedD.length*0.05)]||0;
  var cvar95=sortedD.slice(0,Math.floor(sortedD.length*0.05)).reduce(function(s,v){ return s+v; },0)/Math.max(Math.floor(sortedD.length*0.05),1);
  // Omega ratio (threshold = RF daily = 4%/252)
  var rfDaily=4/252;
  var omegaGain=dl.reduce(function(s,r2){ return s+Math.max(r2-rfDaily,0); },0);
  var omegaLoss=dl.reduce(function(s,r2){ return s+Math.max(rfDaily-r2,0); },0);
  var omega=omegaLoss>0?omegaGain/omegaLoss:0;
  // Recovery factor: total return / max drawdown
  var recovery=r.maxDD>0?r.ret/r.maxDD:0;
  // Pain index: average drawdown
  var painIdx=Math.abs(dd3.reduce(function(s,d){ return s+d; },0)/Math.max(dd3.length,1));
  // Avg win / Avg loss
  var wins2=dl.filter(function(r2){ return r2>0; });
  var losses2=dl.filter(function(r2){ return r2<0; });
  var avgWin=wins2.length?wins2.reduce(function(s,v){ return s+v; },0)/wins2.length:0;
  var avgLoss=losses2.length?Math.abs(losses2.reduce(function(s,v){ return s+v; },0)/losses2.length):0;
  var expectancy=r.winRate/100*avgWin-(1-r.winRate/100)*avgLoss;

  var metrics=[
    {l:'Sharpe ratio', v:fmtN(r.sharpe), color:r.sharpe>=2?'var(--up)':r.sharpe>=1?'var(--warn)':'var(--dn)', desc:'Retorno ajustado por riesgo total (RF=4%). >1 aceptable, >2 bueno, >3 excepcional.'},
    {l:'Sortino ratio', v:fmtN(r.sortino), color:r.sortino>=2?'var(--up)':r.sortino>=1?'var(--warn)':'var(--dn)', desc:'Solo penaliza volatilidad bajista. Más relevante para carteras reales que el Sharpe.'},
    {l:'Calmar ratio', v:fmtN(r.calmar), color:r.calmar>=0.5?'var(--up)':'var(--warn)', desc:'CAGR / Max Drawdown. Retorno por unidad de caída máxima. >0.5 sostenible.'},
    {l:'Omega ratio', v:fmtN(omega), color:omega>=1.5?'var(--up)':omega>=1?'var(--warn)':'var(--dn)', desc:'Ratio de ganancias sobre pérdidas relativas al threshold (RF). >1 la estrategia añade valor. >2 excelente.'},
    {l:'Ulcer Index', v:fmtN(ulcer,1)+'%', color:ulcer<5?'var(--up)':ulcer<15?'var(--warn)':'var(--dn)', desc:'Mide el estrés psicológico del drawdown (RMS). Cuanto más bajo, más suave la curva de capital. Ambroker lo usa como alternativa al MaxDD.'},
    {l:'VaR 95%', v:fmtN(var95,2)+'%/día', color:'var(--dn)', desc:'Pérdida máxima esperada en el 95% de los días (peor 5%). Si es -2%, el 95% de los días no perderás más del 2%.'},
    {l:'CVaR 95%', v:fmtN(cvar95,2)+'%/día', color:'var(--dn)', desc:'Expected Shortfall: pérdida media en el peor 5% de días. Más conservador que el VaR. Muy usado en riesgo institucional.'},
    {l:'Max Drawdown', v:fmtPct(-r.maxDD), color:'var(--dn)', desc:'Caída máxima pico-valle. El peor escenario histórico de la cartera.'},
    {l:'Recovery Factor', v:fmtN(recovery), color:recovery>=2?'var(--up)':recovery>=1?'var(--warn)':'var(--dn)', desc:'Retorno total / MaxDrawdown. Mide cuánto profit genera la estrategia por cada unidad de drawdown asumido. >2 muy bueno.'},
    {l:'Pain Index', v:fmtN(painIdx,2)+'%', color:painIdx<5?'var(--up)':painIdx<12?'var(--warn)':'var(--dn)', desc:'Drawdown medio a lo largo del tiempo. El Ulcer Index pesa más los drawdowns prolongados; el Pain Index es la media simple.'},
    {l:'CAGR', v:fmtPct(r.cagr), color:colC(r.cagr), desc:'Tasa de crecimiento anual compuesta. El rendimiento real anualizado.'},
    {l:'Volatilidad', v:fmtPct(r.vol), color:'var(--warn)', desc:'Desviación estándar anualizada. S&P 500 histórico ~15-18%.'},
    {l:'Win rate', v:r.winRate.toFixed(1)+'%', color:r.winRate>=55?'var(--up)':'var(--dim)', desc:'% de días con retorno positivo.'},
    {l:'Profit Factor', v:fmtN(r.pf), color:r.pf>=1.5?'var(--up)':r.pf>=1?'var(--warn)':'var(--dn)', desc:'Ganancia bruta / Pérdida bruta. >1.5 sostenible.'},
    {l:'Avg Win / Avg Loss', v:fmtN(avgLoss>0?avgWin/avgLoss:0), color:avgLoss>0&&avgWin/avgLoss>=1?'var(--up)':'var(--warn)', desc:'Ratio ganancia media / pérdida media. >1 cada ganador compensa más que cada perdedor.'},
    {l:'Expectancy diaria', v:fmtN(expectancy,3)+'%', color:colC(expectancy), desc:'Retorno esperado por día: WinRate×AvgWin - LossRate×AvgLoss. Mide el edge de la estrategia.'},
  ];
  document.getElementById('ct-metrics-grid').innerHTML=metrics.map(function(m){
    return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:14px 16px;border-top:3px solid '+m.color+'">'
      +'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">'+m.l+'</div>'
      +'<div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:'+m.color+'">'+m.v+'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-top:8px;line-height:1.6">'+m.desc+'</div>'
      +'</div>';
  }).join('');

  // Return distribution histogram
  if(ctRetChart){ ctRetChart.destroy(); ctRetChart=null; }
  var bins=[-4,-2.5,-1.5,-0.75,-0.25,0.25,0.75,1.5,2.5,4];
  var counts=new Array(bins.length-1).fill(0);
  curve.daily.forEach(function(r2){
    for(var i=0;i<bins.length-1;i++){
      if(r2>=bins[i]&&r2<bins[i+1]){ counts[i]++; break; }
    }
  });
  var labels=bins.slice(0,-1).map(function(b,i){ return b+'% a '+bins[i+1]+'%'; });
  var colors=bins.slice(0,-1).map(function(b){ return b>=0?'rgba(56,189,248,0.7)':'rgba(244,63,94,0.6)'; });
  ctRetChart=new Chart(document.getElementById('ct-ret-canvas'),{
    type:'bar',
    data:{labels:labels,datasets:[{label:'Días',data:counts,backgroundColor:colors,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxRotation:45},grid:{display:false}},
        y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'}}}}
  });
}

function ctRenderAll(){
  var activeTab=null;
  ['overview','add','positions','riesgo'].forEach(function(t){
    var el=document.getElementById('ct-'+t);
    if(el&&el.style.display!=='none') activeTab=t;
  });
  if(!activeTab||activeTab==='overview') ctRenderOverview();
  else if(activeTab==='add') ctRenderTxs();
  else if(activeTab==='positions') ctRenderPositions();
  else if(activeTab==='riesgo') ctRenderRiesgo();
}

// ── MOBILE NAV ───────────────────────────────────────────────────────────────
function mobileNav(btn){
  document.querySelectorAll('#mobile-nav button').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  // Scroll to top on tab change
  window.scrollTo({top:0,behavior:'smooth'});
}

// Show/hide mobile nav based on screen size
(function(){
  var nav=document.getElementById('mobile-nav');
  function checkNav(){
    if(!nav) return;
    nav.style.display=window.innerWidth<=768?'flex':'none';
  }
  checkNav();
  window.addEventListener('resize',checkNav);
})();

// Register PWA service worker (enables "Add to Home Screen" on iOS/Android)
if('serviceWorker' in navigator){
  // Inline SW as data URL to avoid needing a separate sw.js file
  var swCode=[
    "const CACHE='vgc-v1';",
    "self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll([location.pathname]))));",
    "self.addEventListener('fetch',e=>e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request))));"
  ].join('');
  var blob=new Blob([swCode],{type:'application/javascript'});
  var swUrl=URL.createObjectURL(blob);
  navigator.serviceWorker.register(swUrl).catch(function(){});
}

// ── COMUNIDAD (Supabase) ─────────────────────────────────────────────────────
// ╔══════════════════════════════════════════════════════════════════════╗
// ║  CONFIGURACIÓN SUPABASE — rellena estos dos valores tras crear      ║
// ║  tu proyecto en supabase.com (Plan Free, 0€)                        ║
// ╚══════════════════════════════════════════════════════════════════════╝
// ════════════════════════════════════════════════════════════════════════

var COM_USER = null;  // current logged-in user
var COM_PROFILE = null;  // user profile (nombre, racha, etc)

async function initComunidad(){
  // Use global session — user already logged in
  if(!GLOBAL_USER){ return; }
  COM_USER = GLOBAL_USER;
  COM_PROFILE = GLOBAL_PROFILE;
  showComContent();
}

function showComAuth(){
  var overlay=document.getElementById('com-auth-overlay');
  if(overlay) overlay.style.display='block';
  document.getElementById('com-content').style.display='none';
}
function showComContent(){
  var overlay=document.getElementById('com-auth-overlay');
  if(overlay) overlay.style.display='none';
  document.getElementById('com-content').style.display='block';
  comRenderHeader();
  comLoadIdeas();
}
function showComError(){
  document.getElementById('com-content').style.display='block';
  var errEl=document.getElementById('com-ideas-loading');
  if(errEl) errEl.innerHTML='<div style="color:var(--dn);padding:20px">Error: Supabase no configurado correctamente.</div>';
}

async function comLogin(){
  var sb=sbClient(); if(!sb) return;
  var email=(document.getElementById('com-email').value||'').trim();
  var pass=document.getElementById('com-pass').value;
  var errEl=document.getElementById('com-auth-err');
  if(!email||!pass){ errEl.textContent='Introduce email y contraseña.'; return; }
  errEl.textContent='Entrando...';
  var {data,error}=await sb.auth.signInWithPassword({email:email,password:pass});
  if(error){ errEl.textContent=error.message==='Invalid login credentials'?'Email o contraseña incorrectos.':error.message; return; }
  COM_USER=data.user;
  errEl.textContent='';
  try{ localStorage.setItem('vgc_last_login', Date.now().toString()); }catch(e){}
  await comLoadProfile();
  await comUpdateStreak();
  showComContent();
}

async function comRegister(){
  var sb=sbClient(); if(!sb) return;
  var email=(document.getElementById('com-email').value||'').trim();
  var pass=document.getElementById('com-pass').value;
  var errEl=document.getElementById('com-auth-err');
  if(!email||!pass){ errEl.textContent='Introduce email y contraseña (mín 6 caracteres).'; return; }
  if(pass.length<6){ errEl.textContent='La contraseña debe tener al menos 6 caracteres.'; return; }
  // Use display name from email
  var nombre=email.split('@')[0];
  errEl.textContent='Creando cuenta...';
  var {data,error}=await sb.auth.signUp({email:email,password:pass,options:{data:{nombre:nombre}}});
  if(error){ errEl.textContent=error.message; return; }
  COM_USER=data.user;
  // Create profile
  await sb.from('profiles').upsert({id:COM_USER.id,email:email,nombre:nombre,racha:0,dias_total:0,ultima_visita:null});
  errEl.textContent='';
  await comLoadProfile();
  showComContent();
}

async function comLogout(){
  var sb=sbClient(); if(!sb) return;
  await sb.auth.signOut();
  try{ localStorage.removeItem('vgc_last_login'); }catch(e){}
  COM_USER=null; COM_PROFILE=null;
  showComAuth();
}

async function comLoadProfile(){
  var sb=sbClient(); if(!sb||!COM_USER) return;
  var {data}=await sb.from('profiles').select('*').eq('id',COM_USER.id).single();
  COM_PROFILE=data||{nombre:COM_USER.email.split('@')[0],racha:0,dias_total:0};
}

async function comUpdateStreak(){
  var sb=sbClient(); if(!sb||!COM_USER) return;
  var today=new Date().toISOString().slice(0,10);
  var p=COM_PROFILE||{};
  var ultima=p.ultima_visita;
  var racha=p.racha||0;
  var total=p.dias_total||0;
  if(ultima===today) return; // already visited today
  var yesterday=new Date(Date.now()-864e5).toISOString().slice(0,10);
  if(ultima===yesterday){ racha+=1; } // consecutive day
  else if(ultima!==today){ racha=1; } // streak broken
  total+=1;
  await sb.from('profiles').upsert({id:COM_USER.id,racha:racha,dias_total:total,ultima_visita:today});
  COM_PROFILE={...p,racha:racha,dias_total:total,ultima_visita:today};
}

function comRenderHeader(){
  var profile=COM_PROFILE||GLOBAL_PROFILE;
  if(!profile) return;
  var nombre=profile.nombre||'Alumno';
  var racha=profile.racha||0;
  var total=profile.dias_total||0;
  document.getElementById('com-welcome').textContent='Hola, '+nombre+' 👋';
  document.getElementById('com-racha-txt').textContent=total+' días en total · '+racha+' días seguidos';
  document.getElementById('com-streak-num').textContent=racha;
  document.getElementById('com-streak-emoji').textContent=racha>=30?'🏆':racha>=14?'⚡':racha>=7?'🔥':racha>=3?'✨':'🌱';

  // Textarea char counter
  var ta=document.getElementById('com-idea-text');
  ta.addEventListener('input',function(){ document.getElementById('com-idea-chars').textContent=ta.value.length+'/200'; });
}

function comTab(name, btn){
  document.querySelectorAll('#com-content .pb[id^=com-btn-]').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  document.getElementById('com-ideas').style.display=name==='ideas'?'block':'none';
  document.getElementById('com-ranking').style.display=name==='ranking'?'block':'none';
  if(name==='ranking') comLoadRanking();
}

// ── IDEAS ──────────────────────────────────────────────────────────────────
async function comLoadIdeas(){
  var sb=sbClient(); if(!sb) return;
  var loadEl=document.getElementById('com-ideas-loading');
  if(loadEl) loadEl.style.display='block';
  var {data,error}=await sb.from('ideas')
    .select('*, profiles!ideas_user_id_fkey(nombre)')
    .order('avg_stars',{ascending:false})
    .order('created_at',{ascending:false})
    .limit(50);
  if(loadEl) loadEl.style.display='none';
  if(error){
    document.getElementById('com-ideas-list').innerHTML='<div style="color:var(--dn);font-size:11px;padding:12px">Error: '+error.message+'</div>';
    return;
  }
  comRenderIdeas(data||[]);
}

var _comIdeasData=[];
var _comSortMode='stars';

function comSortIdeas(mode, btn){
  _comSortMode=mode;
  document.querySelectorAll('[id^=sort-]').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  var sorted=[..._comIdeasData];
  if(mode==='stars') sorted.sort(function(a,b){ return (b.avg_stars||0)-(a.avg_stars||0); });
  else if(mode==='votes') sorted.sort(function(a,b){ return (b.num_votes||0)-(a.num_votes||0); });
  else sorted.sort(function(a,b){ return new Date(b.created_at)-new Date(a.created_at); });
  comRenderIdeas(sorted);
}

function comRenderIdeas(ideas){
  if(!_comIdeasData.length||ideas===_comIdeasData) _comIdeasData=ideas;
  var myId=COM_USER?COM_USER.id:null;
  var el=document.getElementById('com-ideas-list');
  if(!ideas.length){ el.innerHTML='<div style="color:var(--dim);font-size:12px;padding:20px;text-align:center">Sin ideas aún. ¡Sé el primero!</div>'; return; }
  el.innerHTML=ideas.map(function(idea){
    var nombre=(idea.profiles&&idea.profiles.nombre)||'Alumno';
    var dir=idea.direccion==='long'?'📈':'📉';
    var dirColor=idea.direccion==='long'?'var(--up)':'var(--dn)';
    var avgStars=parseFloat(idea.avg_stars||0);
    var numVotes=idea.num_votes||0;
    var dt=new Date(idea.created_at).toLocaleDateString('es-ES',{day:'2-digit',month:'short'});
    var isOwn=myId&&idea.user_id===myId;
    var starsHtml='<div style="display:flex;gap:1px;align-items:center">'
      +[1,2,3,4,5].map(function(n){
        return '<button onclick="comVote(\''+idea.id+'\','+n+')" title="'+n+' estrella'+(n>1?'s':'')+'" '
          +'style="background:none;border:none;cursor:pointer;font-size:24px;padding:0 2px;line-height:1;'
          +'color:'+(n<=Math.round(avgStars)?'#f59e0b':'rgba(150,150,150,0.35)')+'">★</button>';
      }).join('')
      +'<span style="font-size:11px;color:var(--dim);margin-left:6px;white-space:nowrap">'
        +(numVotes>0?avgStars.toFixed(1)+' <span style="color:var(--dim)">('+numVotes+')</span>':'sin votos')
      +'</span></div>';
    var chartId='tv-idea-'+idea.id.replace(/-/g,'');
    return '<div class="cw" style="padding:14px 16px;margin-bottom:10px;border-left:3px solid '+(dirColor)+'">'
      +'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;margin-bottom:10px">'
        +'<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">'
          +'<span style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:var(--ac);cursor:pointer" '
            +'onclick="verAccion(\'' + idea.ticker + '\')" title="Abrir en Panel Acción">' + idea.ticker + '</span>'
          +'<span style="font-size:12px;color:'+dirColor+';font-weight:700;background:'+dirColor+'18;padding:3px 10px;border-radius:20px">'+dir+' '+(idea.direccion==='long'?'Alcista':'Bajista')+'</span>'
        +'</div>'
        +'<div style="display:flex;gap:6px;align-items:center">'
          +'<button data-tk="'+idea.ticker+'" data-cid="'+chartId+'" onclick="toggleIdeaChart(this)" '
            +'style="background:rgba(79,110,247,.08);border:1px solid rgba(79,110,247,.25);color:var(--ac);border-radius:6px;padding:3px 10px;cursor:pointer;font-size:10px;font-weight:600">📊 Gráfico</button>'
          +(isOwn?'<button data-id="'+idea.id+'" onclick="comDeleteIdea(this.dataset.id)" '
            +'style="background:none;border:1px solid rgba(244,63,94,.3);color:var(--dn);border-radius:5px;padding:3px 10px;cursor:pointer;font-size:10px">Borrar</button>':'')
        +'</div>'
      +'</div>'
      +'<div style="font-size:12px;color:var(--tx);line-height:1.7;margin-bottom:10px">'+idea.texto+'</div>'
      +'<div id="'+chartId+'" style="display:none;height:300px;border-radius:8px;overflow:hidden;margin-bottom:10px;border:1px solid var(--b1)"></div>'
      +'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        +'<div style="font-size:10px;color:var(--dim)">'+nombre+' · '+dt+'</div>'
        +starsHtml
      +'</div>'
      +'</div>';  }).join('');
}


async function comPostIdea(){
  var sb=sbClient(); if(!sb||!COM_USER) return;
  var ticker=(document.getElementById('com-idea-ticker').value||'').trim().toUpperCase();
  var dir=document.getElementById('com-idea-dir').value;
  var texto=(document.getElementById('com-idea-text').value||'').trim();
  var errEl=document.getElementById('com-idea-err');
  if(!ticker||ticker.length<1){ errEl.textContent='Introduce un ticker.'; return; }
  if(!texto||texto.length<10){ errEl.textContent='Escribe al menos 10 caracteres explicando tu idea.'; return; }
  errEl.textContent='Publicando...';
  var {error}=await sb.from('ideas').insert({
    user_id:COM_USER.id, ticker:ticker, direccion:dir,
    texto:texto, avg_stars:0, num_votes:0
  });
  if(error){ errEl.textContent='Error: '+error.message; return; }
  errEl.textContent='';
  document.getElementById('com-idea-ticker').value='';
  document.getElementById('com-idea-text').value='';
  document.getElementById('com-idea-chars').textContent='0/200';
  comLoadIdeas();
}

async function comVote(ideaId, stars){
  var sb=sbClient();
  if(!sb){ alert('Error: Supabase no está configurado.'); return; }
  if(!COM_USER){ alert('Tienes que iniciar sesión en La Comunidad para votar.'); return; }
  try{
    // Upsert vote (one vote per user per idea). El recálculo de avg_stars/
    // num_votes en la tabla `ideas` lo hace un trigger en Supabase (ver
    // fix_votos_trigger.sql) — así no choca con la política "solo el autor
    // actualiza su idea" cuando votas algo que no es tuyo.
    var {error}=await sb.from('votos').upsert({user_id:COM_USER.id,idea_id:ideaId,stars:stars},{onConflict:'user_id,idea_id'});
    if(error){
      console.error('Error al votar:', error);
      alert('No se pudo registrar el voto: '+(error.message||JSON.stringify(error))+
            '\n\nRevisa que la tabla "votos" en Supabase tenga una restricción UNIQUE en (user_id, idea_id) y que las políticas RLS permitan insertar/actualizar al usuario autenticado.');
      return;
    }
    comLoadIdeas();
  }catch(ex){
    // Esto es lo que faltaba: sin este catch, un fallo de red o una excepción
    // del cliente de Supabase moría en silencio, sin alert ni consola visible
    // para el usuario — exactamente el síntoma de "no pasa nada al votar".
    console.error('Excepción inesperada en comVote:', ex);
    alert('Error inesperado al votar: '+(ex&&ex.message?ex.message:String(ex)));
  }
}

async function comDeleteIdea(ideaId){
  if(!confirm('¿Borrar tu idea?')) return;
  var sb=sbClient(); if(!sb) return;
  await sb.from('ideas').delete().eq('id',ideaId);
  comLoadIdeas();
}

// ── RANKING ────────────────────────────────────────────────────────────────
async function comLoadRanking(){
  var sb=sbClient(); if(!sb) return;
  var loadEl=document.getElementById('com-ranking-loading');
  if(loadEl) loadEl.style.display='block';
  // Fetch ALL users for full ranking
  var {data}=await sb.from('profiles')
    .select('nombre,racha,dias_total,ultima_visita')
    .order('racha',{ascending:false})
    .limit(100);
  if(loadEl) loadEl.style.display='none';
  if(!data||!data.length){
    document.getElementById('com-ranking-list').innerHTML='<div style="color:var(--dim);font-size:11px;padding:12px">Aún no hay usuarios en el ranking.</div>';
    return;
  }
  var myNombre=(COM_PROFILE||GLOBAL_PROFILE||{}).nombre||'';
  var medals=['🥇','🥈','🥉'];
  var today=new Date().toISOString().slice(0,10);
  var yesterday=new Date(Date.now()-864e5).toISOString().slice(0,10);

  function activeTag(p){
    var ul=p.ultima_visita;
    if(ul===today) return '<span style="font-size:9px;color:var(--up);margin-left:4px">● hoy</span>';
    if(ul===yesterday) return '<span style="font-size:9px;color:var(--warn);margin-left:4px">● ayer</span>';
    if(ul) return '<span style="font-size:9px;color:var(--dim);margin-left:4px">● '+ul+'</span>';
    return '';
  }

  function streakEmoji(r){ return ['🌱','✨','🔥','⚡','🏆'][Math.min(Math.floor((r||0)/7),4)]; }

  // Summary line
  var totalUsers=data.length;
  var activeToday=data.filter(function(p){ return p.ultima_visita===today; }).length;
  var summaryHtml='<div style="display:flex;gap:16px;margin-bottom:12px;padding:10px 14px;background:var(--bg3);border-radius:8px;border:1px solid var(--b1)">'
    +'<div style="text-align:center"><div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:var(--hi)">'+totalUsers+'</div><div style="font-size:9px;color:var(--dim)">alumnos totales</div></div>'
    +'<div style="text-align:center"><div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:var(--up)">'+activeToday+'</div><div style="font-size:9px;color:var(--dim)">activos hoy</div></div>'
    +'<div style="text-align:center"><div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:var(--warn)">'+(data.reduce(function(s,p){return s+(p.racha||0);},0)/Math.max(data.length,1)).toFixed(1)+'</div><div style="font-size:9px;color:var(--dim)">racha media</div></div>'
    +'</div>';

  // Streak ranking
  document.getElementById('com-ranking-list').innerHTML=summaryHtml+data.map(function(p,i){
    var isMe=myNombre&&p.nombre===myNombre;
    return '<div style="display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:7px;margin-bottom:5px;background:'+(isMe?'rgba(56,189,248,.06)':'var(--bg3)')+';border:1px solid '+(isMe?'var(--ac)':'var(--b1)')+'">'
      +'<span style="font-size:15px;flex-shrink:0;min-width:24px;text-align:center">'+(i<3?medals[i]:(i+1)+'.')+'</span>'
      +'<span style="flex:1;font-size:12px;color:'+(isMe?'var(--ac)':'var(--tx)')+'">'+p.nombre+activeTag(p)+'</span>'
      +'<span style="font-size:13px">'+streakEmoji(p.racha)+'</span>'
      +'<span style="font-family:Syne,sans-serif;font-size:16px;font-weight:800;color:var(--warn)">'+(p.racha||0)+'</span>'
      +'<span style="font-size:9px;color:var(--dim)">días</span>'
      +'</div>';
  }).join('');

  // Total days ranking
  var sorted=[...data].sort(function(a,b){ return (b.dias_total||0)-(a.dias_total||0); });
  document.getElementById('com-ranking-total-list').innerHTML=sorted.map(function(p,i){
    var isMe=myNombre&&p.nombre===myNombre;
    return '<div style="display:flex;align-items:center;gap:8px;padding:7px 10px;border-radius:7px;margin-bottom:5px;background:'+(isMe?'rgba(56,189,248,.06)':'var(--bg3)')+';border:1px solid '+(isMe?'var(--ac)':'var(--b1)')+'">'
      +'<span style="font-size:14px;flex-shrink:0;min-width:24px;text-align:center">'+(i<3?medals[i]:(i+1)+'.')+'</span>'
      +'<span style="flex:1;font-size:12px;color:'+(isMe?'var(--ac)':'var(--tx)')+'">'+p.nombre+'</span>'
      +'<span style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:var(--ac)">'+(p.dias_total||0)+'</span>'
      +'<span style="font-size:9px;color:var(--dim)">días</span>'
      +'</div>';
  }).join('');
}

function toggleIdeaChart(btn){
  var tk=btn.dataset.tk;
  var cid=btn.dataset.cid;
  var container=document.getElementById(cid);
  if(!container) return;
  if(container.style.display==='none'){
    container.style.display='block';
    btn.textContent='📊 Ocultar';
    if(!container.children.length){
      var script=document.createElement('script');
      script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
      script.async=true;
      script.innerHTML=JSON.stringify({
        "autosize":true,"symbol":tk,"interval":"D",
        "timezone":"Europe/Madrid","theme":"light","style":"1","locale":"es",
        "backgroundColor":"rgba(255,255,255,1)","gridColor":"rgba(242,243,245,1)",
        "hide_top_toolbar":false,"save_image":false,
        "support_host":"https://www.tradingview.com",
        "studies":["STD;MA"]
      });
      container.appendChild(script);
    }
  } else {
    container.style.display='none';
    btn.textContent='📊 Gráfico';
  }
}

function verAccion(tk){
  var el=document.getElementById('stk-ticker');
  if(el) el.value=tk;
  sw('stocks',document.getElementById('tab-stocks-btn'));
  loadStock();
}

// ── ALERTAS ──────────────────────────────────────────────────────────────────
var _alertaDir = 'above';
var _alertaCurrentTk = '';
var VAPID_PUBLIC_KEY = '__VAPID_PUBLIC_KEY__';

function selectAlertaDir(dir, btn){
  _alertaDir = dir;
  document.querySelectorAll('#alerta-dir-up,#alerta-dir-dn').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
}

function loadAlertaChart(){
  var tk=(document.getElementById('alerta-ticker').value||'').trim().toUpperCase();
  if(!tk) return;
  _alertaCurrentTk=tk;
  document.getElementById('alerta-tk-input').value=tk;
  var btnP=document.getElementById('btn-usar-precio');
  if(btnP) btnP.style.display='block';
  var container=document.getElementById('alerta-tv-container');
  container.innerHTML='';
  var script=document.createElement('script');
  script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.async=true;
  script.innerHTML=JSON.stringify({
    "autosize":true,"symbol":tk,"interval":"D",
    "timezone":"Europe/Madrid","theme":"light","style":"1","locale":"es",
    "backgroundColor":"rgba(255,255,255,1)","gridColor":"rgba(242,243,245,1)",
    "hide_top_toolbar":false,"save_image":false,
    "support_host":"https://www.tradingview.com","studies":["STD;MA"]
  });
  container.appendChild(script);
}

function usePrecioActual(){
  var tk=_alertaCurrentTk; if(!tk) return;
  if(D.stockPerf&&D.stockPerf[tk]&&D.stockPerf[tk].price){
    var p=D.stockPerf[tk].price;
    document.getElementById('alerta-precio').value=parseFloat(p).toFixed(2);
    showMsg('alerta-msg','Precio cargado: $'+parseFloat(p).toFixed(2),'up');
    return;
  }
  var url='https://query1.finance.yahoo.com/v8/finance/chart/'+tk+'?interval=1d&range=1d';
  fetch('https://api.allorigins.win/get?url='+encodeURIComponent(url),{signal:AbortSignal.timeout(6000)})
    .then(function(r){return r.json();}).then(function(j){
      var p=JSON.parse(j.contents).chart.result[0].meta.regularMarketPrice;
      if(p){ document.getElementById('alerta-precio').value=parseFloat(p).toFixed(2); showMsg('alerta-msg','Precio actual: $'+parseFloat(p).toFixed(2),'up'); }
    }).catch(function(){ showMsg('alerta-msg','Introduce el precio manualmente.','dn'); });
}

function saveAlerta(){
  var sb=sbClient();
  if(!sb||!GLOBAL_USER){ showMsg('alerta-msg','Debes estar logueado','dn'); return; }
  var tk=(document.getElementById('alerta-tk-input').value||'').trim().toUpperCase();
  var precio=parseFloat((document.getElementById('alerta-precio').value||'').trim());
  var nota=(document.getElementById('alerta-nota').value||'').trim();
  if(!tk){ showMsg('alerta-msg','Introduce un ticker','dn'); return; }
  if(!precio||isNaN(precio)||precio<=0){ showMsg('alerta-msg','Introduce un precio válido con hasta 2 decimales','dn'); return; }
  precio=Math.round(precio*100)/100;
  showMsg('alerta-msg','Guardando...','dim');
  sb.from('alertas').insert({
    user_id:GLOBAL_USER.id, ticker:tk, precio:precio,
    direccion:_alertaDir, activa:true, nota:nota||null
  }).then(function(r){
    if(r.error){ showMsg('alerta-msg','Error: '+r.error.message,'dn'); return; }
    showMsg('alerta-msg','✓ Alerta: '+tk+' '+(_alertaDir==='above'?'▲ supera':'▼ cae a')+'  $'+precio.toFixed(2),'up');
    document.getElementById('alerta-precio').value='';
    document.getElementById('alerta-nota').value='';
    loadAlertas();
  });
}

function loadAlertas(){
  var sb=sbClient(); if(!sb||!GLOBAL_USER) return;
  sb.from('alertas').select('*').eq('user_id',GLOBAL_USER.id).eq('activa',true)
    .order('creada_at',{ascending:false}).then(function(r){
    var el=document.getElementById('alertas-list');
    if(r.error){
      el.innerHTML='<div style="color:var(--dn);font-size:12px;text-align:center;padding:24px">Error: '+r.error.message+'</div>';
      return;
    }
    if(!r.data||!r.data.length){
      el.innerHTML='<div style="color:var(--dim);font-size:12px;text-align:center;padding:24px"><span style="font-size:28px;display:block;margin-bottom:8px">🔕</span>Sin alertas activas</div>';
      return;
    }
    el.innerHTML=r.data.map(function(a){
      var isAbove=a.direccion==='above';
      return '<div style="padding:12px 0;border-bottom:1px solid var(--b1)">'
        +'<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px">'
          +'<span style="font-family:Syne,sans-serif;font-weight:800;font-size:16px;color:var(--ac)">'+a.ticker+'</span>'
          +'<span style="font-size:11px;font-weight:600;color:'+(isAbove?'var(--up)':'var(--dn)')+'">'+
            (isAbove?'▲ supera':'▼ cae por debajo')+'</span>'
          +'<span style="font-family:Syne,sans-serif;font-weight:800;font-size:15px;color:var(--hi);margin-left:auto">$'+parseFloat(a.precio).toFixed(2)+'</span>'
          +'<button data-id="'+a.id+'" onclick="deleteAlerta(this.dataset.id)" '
            +'style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:3px 8px;cursor:pointer;font-size:10px">✕</button>'
        +'</div>'
        +(a.nota?'<div style="font-size:11px;color:var(--dim)">'+a.nota+'</div>':'')
        +'</div>';
    }).join('');
  });
}

function deleteAlerta(id){
  if(!confirm('¿Eliminar esta alerta?')) return;
  var sb=sbClient(); if(!sb) return;
  sb.from('alertas').update({activa:false}).eq('id',id).then(function(){ loadAlertas(); });
}

function initAlertas(){
  loadAlertas();
  if('Notification' in window && Notification.permission!=='granted'){
    var b=document.getElementById('push-banner');
    if(b) b.style.display='flex';
  }
}

function activarPush(){
  if(!('Notification' in window)||!('serviceWorker' in navigator)){
    showMsg('push-msg','Tu navegador no soporta notificaciones push.','dn'); return;
  }
  var btn=document.getElementById('push-btn');
  if(btn){btn.textContent='Activando...';btn.disabled=true;}
  document.getElementById('push-msg').style.display='block';
  Notification.requestPermission().then(function(perm){
    if(perm!=='granted'){
      showMsg('push-msg','Permiso denegado. Actívalo en los ajustes del navegador.','dn');
      if(btn){btn.textContent='Activar notificaciones';btn.disabled=false;}
      return;
    }
    showMsg('push-msg','✓ Notificaciones activadas. El servidor de alertas se configura próximamente.','up');
    var banner=document.getElementById('push-banner');
    if(banner){banner.style.background='rgba(22,163,74,.08)';banner.style.borderColor='rgba(22,163,74,.25)';}
    if(btn){btn.textContent='✓ Activadas';btn.style.background='var(--up)';btn.style.color='#fff';}
  });
}

function showMsg(id, msg, cls){
  var el=document.getElementById(id); if(!el) return;
  el.textContent=msg;
  el.style.color=cls==='dn'?'var(--dn)':cls==='up'?'var(--up)':'var(--dim)';
}
// ── DIARIO DE TRADING ────────────────────────────────────────────────────────
var DJ_TRADES=[];
var DJ_MONTH=new Date().getMonth();
var DJ_YEAR=new Date().getFullYear();
var DJ_MONTH_NAMES=['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];

function initDiario(){
  djLoadTrades();
}

function djLoadTrades(){
  var sb=sbClient(); if(!sb||!GLOBAL_USER) return;
  sb.from('trades').select('*').eq('user_id',GLOBAL_USER.id)
    .order('abierta',{ascending:false}).order('fecha_salida',{ascending:false,nullsFirst:false}).then(function(r){
    DJ_TRADES=r.data||[];
    djRenderCalendar();
    djRenderMetrics();
    djRenderTradesTable();
    djRenderLivePositions();
    djRenderPLChart();
  });
}

function djChangeMonth(delta){
  DJ_MONTH+=delta;
  if(DJ_MONTH<0){DJ_MONTH=11;DJ_YEAR--;}
  if(DJ_MONTH>11){DJ_MONTH=0;DJ_YEAR++;}
  djRenderCalendar();
  djRenderMetrics();
  document.getElementById('dj-day-detail').style.display='none';
}

function djTradesForMonth(){
  return DJ_TRADES.filter(function(t){
    if(t.abierta||!t.fecha_salida) return false;
    var d=new Date(t.fecha_salida+'T00:00:00');
    return d.getMonth()===DJ_MONTH && d.getFullYear()===DJ_YEAR;
  });
}

function djRenderMetrics(){
  var trades=djTradesForMonth();
  var total=trades.reduce(function(s,t){return s+(parseFloat(t.dolares_bp)||0);},0);
  var wins=trades.filter(function(t){return (parseFloat(t.dolares_bp)||0)>0;});
  var losses=trades.filter(function(t){return (parseFloat(t.dolares_bp)||0)<0;});
  var winRate=trades.length?Math.round(wins.length/trades.length*100):0;
  var rs=trades.map(function(t){return parseFloat(t.r_multiple);}).filter(function(v){return !isNaN(v);});
  var avgR=rs.length?(rs.reduce(function(a,b){return a+b;},0)/rs.length):null;

  // Group by day for best/worst
  var byDay={};
  trades.forEach(function(t){
    var pl=parseFloat(t.dolares_bp)||0;
    byDay[t.fecha_salida]=(byDay[t.fecha_salida]||0)+pl;
  });
  var dayVals=Object.values(byDay);
  var best=dayVals.length?Math.max(...dayVals):0;
  var worst=dayVals.length?Math.min(...dayVals):0;

  document.getElementById('dj-month-total').innerHTML=
    '<span class="'+(total>=0?'up':'dn')+'">'+(total>=0?'+':'')+'$'+Math.abs(total).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</span>';
  document.getElementById('dj-month-trades').textContent=trades.length;
  document.getElementById('dj-month-winrate').textContent=trades.length?(winRate+'%'):'—';
  document.getElementById('dj-month-avgr').innerHTML=avgR!==null
    ?('<span class="'+(avgR>=0?'up':'dn')+'">'+(avgR>=0?'+':'')+avgR.toFixed(2)+'R</span>')
    :'—';
  document.getElementById('dj-month-bestworst').innerHTML=dayVals.length
    ? ('<span class="up">+$'+best.toLocaleString('en-US',{maximumFractionDigits:0})+'</span> / <span class="dn">$'+worst.toLocaleString('en-US',{maximumFractionDigits:0})+'</span>')
    : '—';

  // ── Stats row 2: Net P&L, Profit Factor, Avg Win/Loss ─────────────────────
  document.getElementById('dj-stat-netpl').innerHTML=
    '<span class="'+(total>=0?'up':'dn')+'">'+(total>=0?'+':'')+'$'+Math.abs(total).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</span>';

  var grossWin=wins.reduce(function(s,t){return s+(parseFloat(t.dolares_bp)||0);},0);
  var grossLoss=Math.abs(losses.reduce(function(s,t){return s+(parseFloat(t.dolares_bp)||0);},0));
  var profitFactor=grossLoss>0?(grossWin/grossLoss):(grossWin>0?Infinity:null);
  document.getElementById('dj-stat-pf').innerHTML=profitFactor===null?'—'
    :(profitFactor===Infinity?'<span class="up">∞</span>'
      :('<span class="'+(profitFactor>=1?'up':'dn')+'">'+profitFactor.toFixed(2)+'</span>'));

  var avgWin=wins.length?(grossWin/wins.length):0;
  var avgLoss=losses.length?(grossLoss/losses.length):0;
  if(!wins.length && !losses.length){
    document.getElementById('dj-stat-avgwl').textContent='—';
    document.getElementById('dj-stat-avgwl-bar').innerHTML='';
  } else {
    document.getElementById('dj-stat-avgwl').innerHTML=
      '<span class="up">+$'+avgWin.toFixed(0)+'</span> &nbsp;/&nbsp; <span class="dn">-$'+avgLoss.toFixed(0)+'</span>';
    var sumAbs=avgWin+avgLoss;
    var winPct=sumAbs>0?(avgWin/sumAbs*100):50;
    document.getElementById('dj-stat-avgwl-bar').innerHTML=
      '<div style="background:var(--up);width:'+winPct+'%"></div>'
      +'<div style="background:var(--dn);width:'+(100-winPct)+'%"></div>';
  }
}

function djRenderCalendar(){
  document.getElementById('dj-month-label').textContent=DJ_MONTH_NAMES[DJ_MONTH]+' '+DJ_YEAR;
  var grid=document.getElementById('dj-cal-grid');
  grid.innerHTML='';

  var firstDay=new Date(DJ_YEAR,DJ_MONTH,1).getDay();
  var daysInMonth=new Date(DJ_YEAR,DJ_MONTH+1,0).getDate();

  // Group trades by exit date
  var byDay={};
  djTradesForMonth().forEach(function(t){
    var key=t.fecha_salida;
    if(!byDay[key]) byDay[key]=[];
    byDay[key].push(t);
  });

  for(var i=0;i<firstDay;i++){
    var empty=document.createElement('div');
    grid.appendChild(empty);
  }

  for(var d=1;d<=daysInMonth;d++){
    var dateStr=DJ_YEAR+'-'+String(DJ_MONTH+1).padStart(2,'0')+'-'+String(d).padStart(2,'0');
    var dayTrades=byDay[dateStr]||[];
    var pl=dayTrades.reduce(function(s,t){return s+(parseFloat(t.dolares_bp)||0);},0);

    var cell=document.createElement('div');
    cell.style.borderRadius='7px';
    cell.style.padding='6px';
    cell.style.minHeight='52px';
    cell.style.display='flex';
    cell.style.flexDirection='column';
    cell.style.justifyContent='space-between';

    if(dayTrades.length){
      cell.style.background=pl>=0?'rgba(5,196,107,.12)':'rgba(255,63,91,.12)';
      cell.style.cursor='pointer';
      cell.onclick=function(ds,dt){return function(){djShowDayDetail(ds,dt);};}(dateStr,dayTrades);
    } else {
      cell.style.background='var(--bg3)';
    }

    var num=document.createElement('div');
    num.textContent=d;
    num.style.fontSize='10px';
    num.style.color='var(--dim)';
    cell.appendChild(num);

    if(dayTrades.length){
      var plEl=document.createElement('div');
      plEl.textContent=(pl>=0?'+':'')+'$'+Math.abs(pl).toLocaleString('en-US',{maximumFractionDigits:0});
      plEl.style.fontSize='12px';
      plEl.style.fontWeight='700';
      plEl.style.color=pl>=0?'var(--up)':'var(--dn)';
      cell.appendChild(plEl);

      var meta=document.createElement('div');
      meta.textContent=dayTrades.length+(dayTrades.length===1?' op.':' ops.');
      meta.style.fontSize='9px';
      meta.style.color='var(--dim)';
      cell.appendChild(meta);
    }

    grid.appendChild(cell);
  }
}

function djShowDayDetail(dateStr, trades){
  var detail=document.getElementById('dj-day-detail');
  detail.style.display='block';
  var d=new Date(dateStr+'T00:00:00');
  document.getElementById('dj-detail-date').textContent=d.getDate()+' '+DJ_MONTH_NAMES[d.getMonth()].toLowerCase()+' '+d.getFullYear();
  var totalPl=trades.reduce(function(s,t){return s+(parseFloat(t.dolares_bp)||0);},0);
  var plSpan=document.getElementById('dj-detail-pl');
  plSpan.textContent=(totalPl>=0?'+':'')+'$'+Math.abs(totalPl).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  plSpan.className=totalPl>=0?'up':'dn';

  document.getElementById('dj-detail-trades').innerHTML=trades.map(function(t){
    var pl=parseFloat(t.dolares_bp)||0;
    var r=parseFloat(t.r_multiple);
    var rTxt=!isNaN(r)?((r>=0?'+':'')+r.toFixed(2)+'R'):'';
    return '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid var(--b1)">'
      +'<div>'
        +'<span style="font-family:Syne,sans-serif;font-weight:800;font-size:14px;color:var(--ac)">'+t.ticker+'</span>'
        +(t.setup_entrada?(' <span style="font-size:10px;color:var(--dim)">· '+t.setup_entrada+'</span>'):'')
        +(t.notas?('<div style="font-size:11px;color:var(--tx);margin-top:3px;padding:5px 8px;background:var(--bg3);border-radius:5px">📝 '+t.notas+'</div>'):'')
      +'</div>'
      +'<div style="text-align:right">'
        +'<div class="'+(pl>=0?'up':'dn')+'" style="font-weight:700;font-size:13px">'+(pl>=0?'+':'')+'$'+Math.abs(pl).toFixed(2)+'</div>'
        +(rTxt?'<div style="font-size:11px;color:var(--dim)">'+rTxt+'</div>':'')
      +'</div>'
      +'</div>';
  }).join('');
}

function djOpenForm(){
  document.getElementById('dj-form-title').textContent='Nueva operación';
  document.getElementById('dj-save-btn').textContent='Guardar operación';
  document.getElementById('dj-edit-id').value='';
  document.getElementById('dj-form').style.display='block';
  document.getElementById('dj-form-msg').textContent='';
  djUpdatePreview();
  document.getElementById('dj-form').scrollIntoView({behavior:'smooth',block:'center'});
}
function djCloseForm(){
  document.getElementById('dj-form').style.display='none';
  ['dj-edit-id','dj-ticker','dj-setup','dj-fecha-entrada','dj-fecha-salida','dj-precio-entrada','dj-stop','dj-precio-salida','dj-acciones','dj-notas'].forEach(function(id){
    document.getElementById(id).value='';
  });
  document.getElementById('dj-comisiones').value='0';
  document.getElementById('dj-abierta').checked=false;
  djToggleAbierta();
  document.getElementById('dj-preview').textContent='';
}

function djToggleAbierta(){
  var abierta=document.getElementById('dj-abierta').checked;
  document.getElementById('dj-fecha-salida-wrap').style.display=abierta?'none':'block';
  document.getElementById('dj-precio-salida-wrap').style.display=abierta?'none':'block';
  if(abierta){
    document.getElementById('dj-fecha-salida').value='';
    document.getElementById('dj-precio-salida').value='';
  }
  djUpdatePreview();
}

function djEditTrade(id){
  var t=DJ_TRADES.find(function(x){return x.id===id;});
  if(!t) return;
  document.getElementById('dj-form-title').textContent='Editar operación';
  document.getElementById('dj-save-btn').textContent='Guardar cambios';
  document.getElementById('dj-edit-id').value=t.id;
  document.getElementById('dj-ticker').value=t.ticker||'';
  document.getElementById('dj-setup').value=t.setup_entrada||'';
  document.getElementById('dj-fecha-entrada').value=t.fecha_entrada||'';
  document.getElementById('dj-fecha-salida').value=t.fecha_salida||'';
  document.getElementById('dj-precio-entrada').value=t.precio_entrada!=null?t.precio_entrada:'';
  document.getElementById('dj-stop').value=t.stop_inicial!=null?t.stop_inicial:'';
  document.getElementById('dj-precio-salida').value=t.precio_salida!=null?t.precio_salida:'';
  document.getElementById('dj-acciones').value=t.num_acciones!=null?t.num_acciones:'';
  document.getElementById('dj-comisiones').value=t.comisiones!=null?t.comisiones:0;
  document.getElementById('dj-notas').value=t.notas||'';
  document.getElementById('dj-abierta').checked=!!t.abierta;
  djToggleAbierta();
  document.getElementById('dj-form').style.display='block';
  document.getElementById('dj-form-msg').textContent='';
  djUpdatePreview();
  document.getElementById('dj-form').scrollIntoView({behavior:'smooth',block:'center'});
}

function djDeleteTrade(id){
  if(!confirm('¿Eliminar esta operación? Esta acción no se puede deshacer.')) return;
  var sb=sbClient(); if(!sb) return;
  sb.from('trades').delete().eq('id',id).then(function(r){
    if(r.error){ alert('Error: '+r.error.message); return; }
    djLoadTrades();
  });
}

// Live preview of R, %B/P, $B/P as user fills the form
['dj-precio-entrada','dj-stop','dj-precio-salida','dj-acciones','dj-comisiones'].forEach(function(id){
  document.addEventListener('input',function(e){
    if(e.target && e.target.id===id) djUpdatePreview();
  });
});

function djUpdatePreview(){
  var entrada=parseFloat(document.getElementById('dj-precio-entrada').value);
  var stop=parseFloat(document.getElementById('dj-stop').value);
  var salida=parseFloat(document.getElementById('dj-precio-salida').value);
  var acciones=parseFloat(document.getElementById('dj-acciones').value);
  var comisiones=parseFloat(document.getElementById('dj-comisiones').value)||0;
  var abierta=document.getElementById('dj-abierta').checked;
  var prev=document.getElementById('dj-preview');

  if(isNaN(entrada)||isNaN(acciones)){
    prev.innerHTML='Rellena precio de entrada y nº de acciones para ver el resultado.';
    return;
  }
  var capital=entrada*acciones;
  var riesgoUnit=(!isNaN(stop) && entrada!==stop)?Math.abs(entrada-stop):null;

  if(abierta||isNaN(salida)){
    var html='Capital invertido: <strong style="color:var(--hi)">$'+capital.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</strong>';
    if(riesgoUnit&&riesgoUnit>0){
      html+=' &nbsp;·&nbsp; Riesgo: <strong style="color:var(--dn)">$'+(riesgoUnit*acciones).toFixed(2)+'</strong> ('+(riesgoUnit/entrada*100).toFixed(2)+'%)';
    }
    html+=' &nbsp;·&nbsp; <span style="color:var(--dim)">Operación abierta — sin resultado todavía</span>';
    prev.innerHTML=html;
    return;
  }

  var dolaresBP=(salida-entrada)*acciones-comisiones;
  var pctBP=capital?((salida-entrada)/entrada*100):0;
  var rMultiple=(riesgoUnit && riesgoUnit>0)?((salida-entrada)/riesgoUnit):null;

  var html='Capital invertido: <strong style="color:var(--hi)">$'+capital.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})+'</strong>'
    +' &nbsp;·&nbsp; B/P: <strong class="'+(dolaresBP>=0?'up':'dn')+'">'+(dolaresBP>=0?'+':'')+'$'+Math.abs(dolaresBP).toFixed(2)+'</strong>'
    +' ('+(pctBP>=0?'+':'')+pctBP.toFixed(2)+'%)';
  if(rMultiple!==null){
    html+=' &nbsp;·&nbsp; R: <strong class="'+(rMultiple>=0?'up':'dn')+'">'+(rMultiple>=0?'+':'')+rMultiple.toFixed(2)+'R</strong>';
  } else {
    html+=' &nbsp;·&nbsp; <span style="color:var(--dim)">Introduce el stop para calcular el R</span>';
  }
  prev.innerHTML=html;
}

function djSaveTrade(){
  var sb=sbClient();
  if(!sb||!GLOBAL_USER){ document.getElementById('dj-form-msg').innerHTML='<span class="dn">Debes estar logueado</span>'; return; }

  var editId=document.getElementById('dj-edit-id').value;
  var ticker=(document.getElementById('dj-ticker').value||'').trim().toUpperCase();
  var setup=(document.getElementById('dj-setup').value||'').trim();
  var fechaEntrada=document.getElementById('dj-fecha-entrada').value;
  var fechaSalida=document.getElementById('dj-fecha-salida').value;
  var precioEntrada=parseFloat(document.getElementById('dj-precio-entrada').value);
  var stop=parseFloat(document.getElementById('dj-stop').value);
  var precioSalida=parseFloat(document.getElementById('dj-precio-salida').value);
  var acciones=parseFloat(document.getElementById('dj-acciones').value);
  var comisiones=parseFloat(document.getElementById('dj-comisiones').value)||0;
  var notas=(document.getElementById('dj-notas').value||'').trim();
  var abierta=document.getElementById('dj-abierta').checked;

  if(!ticker||isNaN(precioEntrada)||isNaN(acciones)){
    document.getElementById('dj-form-msg').innerHTML='<span class="dn">Rellena al menos ticker, precio de entrada y nº de acciones</span>';
    return;
  }
  if(!abierta && (!fechaSalida||isNaN(precioSalida))){
    document.getElementById('dj-form-msg').innerHTML='<span class="dn">Rellena fecha y precio de salida, o marca "Operación todavía abierta"</span>';
    return;
  }

  var capital=precioEntrada*acciones;
  var riesgoUnit=(!isNaN(stop)&&precioEntrada!==stop)?Math.abs(precioEntrada-stop):null;

  var payload={
    ticker:ticker,
    setup_entrada:setup||null,
    fecha_entrada:fechaEntrada||null,
    abierta:abierta,
    precio_entrada:precioEntrada,
    stop_inicial:isNaN(stop)?null:stop,
    num_acciones:acciones,
    comisiones:comisiones,
    capital_invertido:Math.round(capital*100)/100,
    notas:notas||null
  };

  if(abierta){
    payload.fecha_salida=null;
    payload.precio_salida=null;
    payload.duracion_dias=null;
    payload.pct_bp=null;
    payload.dolares_bp=null;
    payload.r_multiple=null;
  } else {
    var durDays=null;
    if(fechaEntrada&&fechaSalida){
      durDays=Math.round((new Date(fechaSalida)-new Date(fechaEntrada))/86400000);
    }
    var dolaresBP=(precioSalida-precioEntrada)*acciones-comisiones;
    var pctBP=precioEntrada?((precioSalida-precioEntrada)/precioEntrada*100):0;
    var rMultiple=(riesgoUnit&&riesgoUnit>0)?((precioSalida-precioEntrada)/riesgoUnit):null;
    payload.fecha_salida=fechaSalida;
    payload.precio_salida=precioSalida;
    payload.duracion_dias=durDays;
    payload.pct_bp=Math.round(pctBP*100)/100;
    payload.dolares_bp=Math.round(dolaresBP*100)/100;
    payload.r_multiple=rMultiple!==null?Math.round(rMultiple*100)/100:null;
  }

  document.getElementById('dj-form-msg').innerHTML='Guardando...';

  var req;
  if(editId){
    req=sb.from('trades').update(payload).eq('id',editId);
  } else {
    payload.user_id=GLOBAL_USER.id;
    req=sb.from('trades').insert(payload);
  }

  req.then(function(r){
    if(r.error){ document.getElementById('dj-form-msg').innerHTML='<span class="dn">Error: '+r.error.message+'</span>'; return; }
    document.getElementById('dj-form-msg').innerHTML='<span class="up">✓ Operación '+(editId?'actualizada':'guardada')+'</span>';
    djCloseForm();
    djLoadTrades();
  });
}

function djRenderTradesTable(){
  var tbody=document.getElementById('dj-trades-table');
  if(!DJ_TRADES.length){
    tbody.innerHTML='<tr><td colspan="13" style="text-align:center;color:var(--dim);padding:16px">Sin operaciones registradas aún</td></tr>';
    return;
  }
  tbody.innerHTML=DJ_TRADES.map(function(t){
    if(t.abierta){
      return '<tr style="background:rgba(79,110,247,.05)">'
        +'<td style="text-align:left"><strong style="color:var(--ac)">'+t.ticker+'</strong></td>'
        +'<td style="font-size:10px;color:var(--dim)">'+(t.setup_entrada||'—')+'</td>'
        +'<td style="font-size:10px">'+(t.fecha_entrada||'—')+'</td>'
        +'<td colspan="2" style="font-size:10px;color:var(--ac);font-weight:600">🔵 Abierta</td>'
        +'<td>$'+parseFloat(t.precio_entrada).toFixed(2)+'</td>'
        +'<td>'+(t.stop_inicial!=null?('$'+parseFloat(t.stop_inicial).toFixed(2)):'—')+'</td>'
        +'<td>—</td>'
        +'<td>'+t.num_acciones+'</td>'
        +'<td>—</td><td>—</td><td>—</td>'
        +'<td style="white-space:nowrap">'
          +'<button onclick="djEditTrade(\''+t.id+'\')" style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:2px 7px;cursor:pointer;font-size:10px;margin-right:4px">✎</button>'
          +'<button onclick="djDeleteTrade(\''+t.id+'\')" style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:2px 7px;cursor:pointer;font-size:10px">✕</button>'
        +'</td>'
        +'</tr>';
    }
    var pl=parseFloat(t.dolares_bp)||0;
    var pct=parseFloat(t.pct_bp);
    var r=parseFloat(t.r_multiple);
    return '<tr>'
      +'<td style="text-align:left"><strong style="color:var(--ac)">'+t.ticker+'</strong></td>'
      +'<td style="font-size:10px;color:var(--dim)">'+(t.setup_entrada||'—')+'</td>'
      +'<td style="font-size:10px">'+(t.fecha_entrada||'—')+'</td>'
      +'<td style="font-size:10px">'+t.fecha_salida+'</td>'
      +'<td>'+(t.duracion_dias!=null?t.duracion_dias:'—')+'</td>'
      +'<td>$'+parseFloat(t.precio_entrada).toFixed(2)+'</td>'
      +'<td>'+(t.stop_inicial!=null?('$'+parseFloat(t.stop_inicial).toFixed(2)):'—')+'</td>'
      +'<td>$'+parseFloat(t.precio_salida).toFixed(2)+'</td>'
      +'<td>'+t.num_acciones+'</td>'
      +'<td class="'+(pct>=0?'up':'dn')+'">'+(pct>=0?'+':'')+pct+'%</td>'
      +'<td class="'+(pl>=0?'up':'dn')+'">'+(pl>=0?'+':'')+'$'+Math.abs(pl).toFixed(2)+'</td>'
      +'<td class="'+(r>=0?'up':'dn')+'">'+(!isNaN(r)?((r>=0?'+':'')+r.toFixed(2)+'R'):'—')+'</td>'
      +'<td style="white-space:nowrap">'
        +'<button onclick="djEditTrade(\''+t.id+'\')" style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:2px 7px;cursor:pointer;font-size:10px;margin-right:4px">✎</button>'
        +'<button onclick="djDeleteTrade(\''+t.id+'\')" style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:2px 7px;cursor:pointer;font-size:10px">✕</button>'
      +'</td>'
      +'</tr>';
  }).join('');

  djRenderTradesCards();
}

function djRenderTradesCards(){
  var el=document.getElementById('dj-trades-cards');
  if(!el) return;
  if(!DJ_TRADES.length){
    el.innerHTML='<div style="text-align:center;color:var(--dim);padding:16px;font-size:12px">Sin operaciones registradas aún</div>';
    return;
  }
  el.innerHTML=DJ_TRADES.map(function(t){
    if(t.abierta){
      return '<div style="background:rgba(79,110,247,.06);border-radius:9px;padding:10px 12px">'
        +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
          +'<strong style="color:var(--ac);font-size:15px">'+t.ticker+'</strong>'
          +'<span style="font-size:10px;color:var(--ac);font-weight:600">🔵 Abierta</span>'
        +'</div>'
        +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:11px;margin-bottom:8px">'
          +'<div><div style="color:var(--dim);font-size:9px">Setup</div>'+(t.setup_entrada||'—')+'</div>'
          +'<div><div style="color:var(--dim);font-size:9px">Fecha entrada</div>'+(t.fecha_entrada||'—')+'</div>'
          +'<div><div style="color:var(--dim);font-size:9px">P. Entrada</div>$'+parseFloat(t.precio_entrada).toFixed(2)+'</div>'
          +'<div><div style="color:var(--dim);font-size:9px">Stop</div>'+(t.stop_inicial!=null?('$'+parseFloat(t.stop_inicial).toFixed(2)):'—')+'</div>'
          +'<div><div style="color:var(--dim);font-size:9px">Acciones</div>'+t.num_acciones+'</div>'
        +'</div>'
        +(t.notas?('<div style="font-size:11px;color:var(--tx);margin-bottom:8px;padding:5px 8px;background:var(--bg3);border-radius:5px">📝 '+t.notas+'</div>'):'')
        +'<div style="display:flex;gap:6px">'
          +'<button onclick="djEditTrade(\''+t.id+'\')" style="flex:1;background:none;border:1px solid var(--b2);color:var(--dim);border-radius:6px;padding:6px;cursor:pointer;font-size:11px">✎ Editar</button>'
          +'<button onclick="djDeleteTrade(\''+t.id+'\')" style="flex:1;background:none;border:1px solid var(--b2);color:var(--dn);border-radius:6px;padding:6px;cursor:pointer;font-size:11px">✕ Borrar</button>'
        +'</div>'
        +'</div>';
    }
    var pl=parseFloat(t.dolares_bp)||0;
    var pct=parseFloat(t.pct_bp);
    var r=parseFloat(t.r_multiple);
    return '<div style="background:var(--bg3);border-radius:9px;padding:10px 12px">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
        +'<strong style="color:var(--ac);font-size:15px">'+t.ticker+'</strong>'
        +'<span class="'+(pl>=0?'up':'dn')+'" style="font-weight:700">'+(pl>=0?'+':'')+'$'+Math.abs(pl).toFixed(2)+'</span>'
      +'</div>'
      +'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:11px;margin-bottom:8px">'
        +'<div><div style="color:var(--dim);font-size:9px">Setup</div>'+(t.setup_entrada||'—')+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">Entrada→Salida</div>'+(t.fecha_entrada||'—')+' → '+t.fecha_salida+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">Días</div>'+(t.duracion_dias!=null?t.duracion_dias:'—')+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">P. Entrada</div>$'+parseFloat(t.precio_entrada).toFixed(2)+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">P. Salida</div>$'+parseFloat(t.precio_salida).toFixed(2)+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">Acciones</div>'+t.num_acciones+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">% B/P</div><span class="'+(pct>=0?'up':'dn')+'">'+(pct>=0?'+':'')+pct+'%</span></div>'
        +'<div><div style="color:var(--dim);font-size:9px">R</div><span class="'+(r>=0?'up':'dn')+'">'+(!isNaN(r)?((r>=0?'+':'')+r.toFixed(2)+'R'):'—')+'</span></div>'
        +'<div><div style="color:var(--dim);font-size:9px">Stop</div>'+(t.stop_inicial!=null?('$'+parseFloat(t.stop_inicial).toFixed(2)):'—')+'</div>'
      +'</div>'
      +(t.notas?('<div style="font-size:11px;color:var(--tx);margin-bottom:8px;padding:5px 8px;background:var(--bg2);border-radius:5px">📝 '+t.notas+'</div>'):'')
      +'<div style="display:flex;gap:6px">'
        +'<button onclick="djEditTrade(\''+t.id+'\')" style="flex:1;background:none;border:1px solid var(--b2);color:var(--dim);border-radius:6px;padding:6px;cursor:pointer;font-size:11px">✎ Editar</button>'
        +'<button onclick="djDeleteTrade(\''+t.id+'\')" style="flex:1;background:none;border:1px solid var(--b2);color:var(--dn);border-radius:6px;padding:6px;cursor:pointer;font-size:11px">✕ Borrar</button>'
      +'</div>'
      +'</div>';
  }).join('');
}

var DJ_PL_CHART=null;
function djRenderPLChart(){
  var canvas=document.getElementById('dj-pl-canvas');
  if(!canvas) return;
  var closed=DJ_TRADES.filter(function(t){return !t.abierta&&t.fecha_salida&&t.fecha_entrada;});

  if(!closed.length){
    if(DJ_PL_CHART){ DJ_PL_CHART.destroy(); DJ_PL_CHART=null; }
    var ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.font='12px Inter,sans-serif';
    ctx.fillStyle='#9aa4b8';
    ctx.textAlign='center';
    ctx.fillText('Sin operaciones cerradas todavía',canvas.width/2,canvas.height/2);
    return;
  }

  // Build a daily date axis spanning from the earliest entry to today
  closed.sort(function(a,b){return a.fecha_entrada.localeCompare(b.fecha_entrada);});
  var startDate=new Date(closed[0].fecha_entrada+'T00:00:00');
  var endDate=new Date();
  var dates=[];
  var d=new Date(startDate);
  while(d<=endDate){
    if(d.getDay()>0&&d.getDay()<6) dates.push(d.toISOString().slice(0,10));
    d.setDate(d.getDate()+1);
  }
  if(!dates.length){ dates=[new Date().toISOString().slice(0,10)]; }

  // Helper: get price-history lookup for a ticker (date -> price)
  function priceMapFor(tk){
    var src=(D.stockPerf&&D.stockPerf[tk])||((D.benchmarks||[]).find(function(b){return b.ticker===tk;}));
    if(!src||!src.priceHistory||!src.priceDates) return null;
    var map={};
    for(var i=0;i<src.priceDates.length;i++) map[src.priceDates[i]]=src.priceHistory[i];
    return map;
  }

  // For each closed trade, compute its daily contribution to total P&L
  // - On days strictly between entry and exit: mark-to-market using real price history if available,
  //   otherwise linear interpolation between entry and exit price
  // - From exit day onward: the realized $B/P stays constant (already "banked")
  var dailyTotal={};
  dates.forEach(function(ds){ dailyTotal[ds]=0; });

  closed.forEach(function(t){
    var entryD=t.fecha_entrada, exitD=t.fecha_salida;
    var entryPrice=parseFloat(t.precio_entrada), exitPrice=parseFloat(t.precio_salida);
    var qty=parseFloat(t.num_acciones)||0;
    var comm=parseFloat(t.comisiones)||0;
    var realizedPL=(exitPrice-entryPrice)*qty-comm;
    var pmap=priceMapFor(t.ticker);

    dates.forEach(function(ds){
      if(ds<entryD) return; // before this trade existed
      if(ds>=exitD){
        dailyTotal[ds]+=realizedPL; // banked, stays constant afterward
        return;
      }
      // Mark-to-market for open period [entryD, exitD)
      var price=null;
      if(pmap&&pmap[ds]!=null) price=pmap[ds];
      if(price==null){
        // linear interpolation by position within the holding period
        var totalSpan=(new Date(exitD)-new Date(entryD))||1;
        var pos=(new Date(ds)-new Date(entryD))/totalSpan;
        price=entryPrice+(exitPrice-entryPrice)*Math.max(0,Math.min(1,pos));
      }
      dailyTotal[ds]+=(price-entryPrice)*qty;
    });
  });

  var labels=[], values=[];
  dates.forEach(function(ds){
    var dt=new Date(ds+'T00:00:00');
    labels.push(dt.getDate()+'/'+(dt.getMonth()+1));
    values.push(Math.round(dailyTotal[ds]*100)/100);
  });

  var lastVal=values[values.length-1];
  var lineColor=lastVal>=0?'#05c46b':'#ff3f5b';
  var fillColor=lastVal>=0?'rgba(5,196,107,.12)':'rgba(255,63,91,.12)';

  if(DJ_PL_CHART) DJ_PL_CHART.destroy();
  DJ_PL_CHART=new Chart(canvas,{
    type:'line',
    data:{labels:labels,datasets:[{
      label:'P&L acumulado',
      data:values,
      borderColor:lineColor,
      backgroundColor:fillColor,
      fill:true,
      tension:0.15,
      pointRadius:0,
      borderWidth:2
    }]},
    options:{
      responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false},
        tooltip:{callbacks:{label:function(c){return (c.parsed.y>=0?'+':'')+'$'+c.parsed.y.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});}}}
      },
      scales:{
        x:{ticks:{color:'#9aa4b8',font:{size:9},maxRotation:45,autoSkip:true,maxTicksLimit:12},grid:{display:false}},
        y:{ticks:{color:'#9aa4b8',font:{size:9},callback:function(v){return '$'+v.toLocaleString('en-US',{maximumFractionDigits:0});}},grid:{color:'rgba(0,0,0,.05)'}}
      }
    }
  });
}

function djRenderLivePositions(){
  var el=document.getElementById('dj-live-positions');
  if(!el) return;

  // Combine Cartera positions (localStorage) + open trades from Diario (Supabase)
  var ctPos=(typeof ctPositions==='function')?ctPositions():[];
  var djOpen=DJ_TRADES.filter(function(t){return t.abierta;});

  var combined=[];
  ctPos.forEach(function(p){
    combined.push({ticker:p.ticker, entry:p.firstPrice||(p.cost/p.qty), stop:p.stop, qty:p.qty, source:'cartera'});
  });
  djOpen.forEach(function(t){
    // Avoid duplicating a ticker already shown from Cartera
    if(combined.some(function(c){return c.ticker===t.ticker;})) return;
    combined.push({ticker:t.ticker, entry:parseFloat(t.precio_entrada), stop:t.stop_inicial!=null?parseFloat(t.stop_inicial):null, qty:t.num_acciones, source:'diario', tradeId:t.id});
  });

  if(!combined.length){
    el.innerHTML='<div style="color:var(--dim);font-size:12px;text-align:center;padding:16px">Sin posiciones abiertas</div>';
    return;
  }

  el.innerHTML='<div class="tw"><table><thead><tr>'
    +'<th style="text-align:left">Ticker</th><th>Entrada</th><th>Stop</th><th>Precio actual</th>'
    +'<th>% B/P</th><th>R actual</th><th>Acción sugerida</th>'
    +'</tr></thead><tbody id="dj-live-tbody">'
    + combined.map(function(p){ return djLivePositionRow(p,null); }).join('')
    +'</tbody></table></div>';

  djRenderLiveCards(combined);

  // Fetch live prices for tickers not present in D.stockPerf (e.g. custom holdings)
  combined.forEach(function(p){
    var perfPrice=(D.stockPerf&&D.stockPerf[p.ticker]&&D.stockPerf[p.ticker].price)?D.stockPerf[p.ticker].price:null;
    if(perfPrice!=null) return; // already have it
    var url='https://query1.finance.yahoo.com/v8/finance/chart/'+p.ticker+'?interval=1d&range=1d';
    fetch('https://api.allorigins.win/get?url='+encodeURIComponent(url),{signal:AbortSignal.timeout(6000)})
      .then(function(r){return r.json();}).then(function(j){
        var price=JSON.parse(j.contents).chart.result[0].meta.regularMarketPrice;
        if(price){
          var row=document.querySelector('[data-live-tk="'+p.ticker+'"]');
          if(row) row.outerHTML=djLivePositionRow(p,price);
          djRenderLiveCards(combined,p.ticker,price);
        }
      }).catch(function(){});
  });
}

function djLiveCardData(p, fetchedPrice){
  var entry=p.entry;
  var current=fetchedPrice!=null?fetchedPrice:((D.stockPerf&&D.stockPerf[p.ticker]&&D.stockPerf[p.ticker].price)?D.stockPerf[p.ticker].price:null);
  var stop=p.stop;
  var pctBP=current!=null&&entry?((current-entry)/entry*100):null;
  var riesgoUnit=(stop&&entry!==stop)?Math.abs(entry-stop):null;
  var rActual=(current!=null&&riesgoUnit&&riesgoUnit>0)?((current-entry)/riesgoUnit):null;
  var bg='var(--bg3)';
  var suggestion='Mantener';
  var sugColor='var(--dim)';
  if(rActual!=null){
    if(rActual>=2){ bg='rgba(5,196,107,.12)'; suggestion='≥2R — considerar vender 1/3'; sugColor='var(--up)'; }
    else if(rActual>=1){ bg='rgba(5,196,107,.06)'; suggestion='≥1R — vigilar, mover stop a BE'; sugColor='var(--up)'; }
    else if(rActual<0){ bg='rgba(255,63,91,.08)'; suggestion='Por debajo de entrada'; sugColor='var(--dn)'; }
  }
  return {entry:entry,current:current,stop:stop,pctBP:pctBP,rActual:rActual,bg:bg,suggestion:suggestion,sugColor:sugColor};
}

function djRenderLiveCards(combined, updateTicker, updatePrice){
  var el=document.getElementById('dj-live-cards');
  if(!el) return;
  el.innerHTML=combined.map(function(p){
    var d=djLiveCardData(p, (updateTicker===p.ticker)?updatePrice:null);
    var editBtn=p.source==='diario'
      ? ('<button onclick="djEditTrade(\''+p.tradeId+'\')" style="background:none;border:1px solid var(--b2);color:var(--dim);border-radius:5px;padding:4px 10px;cursor:pointer;font-size:11px">✎ Editar</button>')
      : ('<span style="font-size:10px;color:var(--dim)">Editar en 💼 Mi Cartera</span>');
    return '<div data-live-card-tk="'+p.ticker+'" style="background:'+d.bg+';border-radius:9px;padding:10px 12px">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">'
        +'<strong style="color:var(--ac);font-size:15px;cursor:pointer" onclick="openSetupChart(\''+p.ticker+'\')">'+p.ticker+'</strong>'
        +(d.rActual!=null?('<span class="'+(d.rActual>=0?'up':'dn')+'" style="font-weight:700">'+(d.rActual>=0?'+':'')+d.rActual.toFixed(2)+'R</span>'):'<span style="color:var(--dim);font-size:11px">cargando...</span>')
      +'</div>'
      +'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;font-size:11px;margin-bottom:8px">'
        +'<div><div style="color:var(--dim);font-size:9px">Entrada</div>$'+d.entry.toFixed(2)+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">Stop</div>'+(d.stop?('$'+parseFloat(d.stop).toFixed(2)):'—')+'</div>'
        +'<div><div style="color:var(--dim);font-size:9px">Actual</div>'+(d.current!=null?('$'+d.current.toFixed(2)):'—')+'</div>'
      +'</div>'
      +'<div style="font-size:11px;color:'+d.sugColor+';margin-bottom:8px">'+d.suggestion+'</div>'
      +editBtn
      +'</div>';
  }).join('');
}

function djLivePositionRow(p, fetchedPrice){
  var entry=p.entry;
  var current=fetchedPrice!=null?fetchedPrice:((D.stockPerf&&D.stockPerf[p.ticker]&&D.stockPerf[p.ticker].price)?D.stockPerf[p.ticker].price:null);
  var stop=p.stop;
  var pctBP=current!=null&&entry?((current-entry)/entry*100):null;
  var riesgoUnit=(stop&&entry!==stop)?Math.abs(entry-stop):null;
  var rActual=(current!=null&&riesgoUnit&&riesgoUnit>0)?((current-entry)/riesgoUnit):null;

  var rowColor='var(--bg2)';
  var suggestion='<span style="color:var(--dim)">Mantener</span>';
  if(rActual!=null){
    if(rActual>=2){ rowColor='rgba(5,196,107,.12)'; suggestion='<strong class="up">≥2R — considerar vender 1/3</strong>'; }
    else if(rActual>=1){ rowColor='rgba(5,196,107,.06)'; suggestion='<span class="up">≥1R — vigilar, mover stop a BE</span>'; }
    else if(rActual<0){ rowColor='rgba(255,63,91,.08)'; suggestion='<span class="dn">Por debajo de entrada</span>'; }
  }
  var sourceTag=p.source==='diario'?' <span style="font-size:9px;color:var(--dim)">(diario)</span>':'';

  return '<tr data-live-tk="'+p.ticker+'" style="background:'+rowColor+'">'
    +'<td style="text-align:left"><strong style="color:var(--ac);cursor:pointer" onclick="openSetupChart(\''+p.ticker+'\')">'+p.ticker+'</strong>'+sourceTag+'</td>'
    +'<td>$'+entry.toFixed(2)+'</td>'
    +'<td>'+(stop?('$'+parseFloat(stop).toFixed(2)):'—')+'</td>'
    +'<td>'+(current!=null?('$'+current.toFixed(2)):'<span style="color:var(--dim)">cargando...</span>')+'</td>'
    +'<td class="'+(pctBP!=null&&pctBP>=0?'up':'dn')+'">'+(pctBP!=null?((pctBP>=0?'+':'')+pctBP.toFixed(2)+'%'):'—')+'</td>'
    +'<td class="'+(rActual!=null&&rActual>=0?'up':'dn')+'">'+(rActual!=null?((rActual>=0?'+':'')+rActual.toFixed(2)+'R'):'—')+'</td>'
    +'<td style="font-size:11px">'+suggestion+'</td>'
    +'</tr>';
}

// ── CHART GRID (finviz-style) ────────────────────────────────────────────────
var CG_COLS=(window.innerWidth<=640)?1:2;
var CG_OBSERVER=null;

function cgGetTickers(source){
  var raw;
  if(source==='scanner'){
    raw = (window._scannerData||[]).map(function(r){return r.ticker;});
  } else if(source==='setups'){
    raw = (window._setupData||[]).map(function(r){return r.ticker;});
  } else if(source==='watchlist'){
    raw = (_wlData||[]).map(function(r){return r.ticker;});
  } else if(source==='favoritas'){
    raw = getFavoritas().map(function(f){return f.ticker;});
  } else if(source==='fundamentales'){
    raw = (window._fundData||[]).map(function(r){return r.tk;});
  } else if(Array.isArray(source)){
    raw = source; // accept a raw ticker array directly
  } else {
    raw = [];
  }
  // NUEVO (03/09/2026): como no se puede comprobar desde fuera si un
  // mini-gráfico de TradingView cargó bien (restricción del navegador,
  // el contenido del iframe no es accesible), se filtra ANTES de
  // intentarlo — fuera cualquier ticker que no tenga pinta de símbolo de
  // bolsa normal (los CFD tipo RGTIn, BMNRn, CARn... confirmado hoy que
  // dan justo este problema).
  return raw.filter(function(tk){ return /^[A-Z]{1,6}([.\-][A-Z]{1,2})?$/.test(tk||''); });
}

function cgOpen(source){
  var tickers=cgGetTickers(source);
  if(!tickers.length){
    alert('Ejecuta un filtro primero para tener tickers que mostrar.');
    return;
  }
  // En movil, forzar 1 columna para que cada grafico se vea bien de uno en uno
  if(window.innerWidth<=640){
    CG_COLS=1;
    document.querySelectorAll('#cg-overlay .pb[id^=cg-col-]').forEach(function(b){b.classList.remove('active');});
    var btn1=document.getElementById('cg-col-1');
    if(btn1) btn1.classList.add('active');
  }
  var label=source==='scanner'?'Scanner':source==='setups'?'Setups Diarios':source==='watchlist'?'Watchlist':source==='favoritas'?'Mis Favoritas':source==='fundamentales'?'Fundamentales':'Gráficos';
  document.getElementById('cg-title').textContent='📊 '+label;
  document.getElementById('cg-count').textContent=tickers.length+' tickers';
  cgBuild(tickers);
  document.getElementById('cg-overlay').style.display='block';
  document.body.style.overflow='hidden';
}

function cgClose(){
  document.getElementById('cg-overlay').style.display='none';
  document.body.style.overflow='';
  // Disconnect observer and clear grid to free memory
  if(CG_OBSERVER){ CG_OBSERVER.disconnect(); CG_OBSERVER=null; }
  document.getElementById('cg-grid').innerHTML='';
}

function cgSetCols(n,btn){
  CG_COLS=n;
  document.querySelectorAll('#cg-overlay .pb[id^=cg-col-]').forEach(function(b){b.classList.remove('active');});
  if(btn) btn.classList.add('active');
  document.getElementById('cg-grid').style.gridTemplateColumns='repeat('+n+',1fr)';
  // Widgets already loaded don't change, just the layout
}

function cgBuild(tickers){
  // Disconnect any previous observer
  if(CG_OBSERVER){ CG_OBSERVER.disconnect(); CG_OBSERVER=null; }

  var grid=document.getElementById('cg-grid');
  grid.style.gridTemplateColumns='repeat('+CG_COLS+',1fr)';
  grid.innerHTML='';

  var cellH=Math.round(Math.max(340, Math.min(480, window.innerHeight*0.50)));

  tickers.forEach(function(tk){
    var cell=document.createElement('div');
    cell.dataset.tk=tk;
    cell.dataset.loaded='0';
    cell.style.height=cellH+'px';
    cell.style.borderRadius='8px';
    cell.style.overflow='hidden';
    cell.style.background='var(--bg2)';
    cell.style.border='1px solid var(--b1)';
    cell.style.display='flex';
    cell.style.alignItems='center';
    cell.style.justifyContent='center';
    cell.style.position='relative';
    // Placeholder
    cell.innerHTML='<div style="text-align:center">'
      +'<div style="font-family:Syne,sans-serif;font-weight:800;font-size:14px;color:var(--dim)">'+tk+'</div>'
      +'<div style="font-size:10px;color:var(--b2);margin-top:4px">cargando...</div>'
      +'</div>';
    grid.appendChild(cell);
  });

  // IntersectionObserver for lazy loading
  CG_OBSERVER=new IntersectionObserver(function(entries){
    entries.forEach(function(entry){
      if(entry.isIntersecting){
        var cell=entry.target;
        if(cell.dataset.loaded==='1') return;
        cell.dataset.loaded='1';
        cgLoadWidget(cell, cell.dataset.tk);
        CG_OBSERVER.unobserve(cell);
      }
    });
  },{root:document.getElementById('cg-overlay'),rootMargin:'200px',threshold:0});

  Array.from(grid.children).forEach(function(cell){
    CG_OBSERVER.observe(cell);
  });
}

function cgLoadWidget(cell, tk){
  var widgetContainer=document.createElement('div');
  widgetContainer.style.width='100%';
  widgetContainer.style.height='100%';
  cell.innerHTML='';
  cell.appendChild(widgetContainer);
  var script=document.createElement('script');
  script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
  script.async=true;
  script.innerHTML=JSON.stringify({
    "autosize":true,
    "symbol":tk,
    "interval":"D",
    "timezone":"Europe/Madrid",
    "theme":"light",
    "style":"1",
    "locale":"es",
    "backgroundColor":"rgba(255,255,255,1)",
    "gridColor":"rgba(242,243,245,1)",
    "hide_top_toolbar":false,
    "hide_legend":false,
    "save_image":false,
    "support_host":"https://www.tradingview.com",
    "studies":[
      {"id":"STD;SMA","version":1,"inputs":{"in_0":9},"overrides":{"Plot.color":"#29b6f6","Plot.linewidth":1.5}},
      {"id":"STD;SMA","version":1,"inputs":{"in_0":21},"overrides":{"Plot.color":"#ef4444","Plot.linewidth":1.5}}
    ]
  });
  widgetContainer.appendChild(script);
  // NUEVO (03/09/2026): red de seguridad — si pasados unos segundos el
  // script de TradingView ni siquiera ha inyectado su iframe (fallo de
  // red, bloqueador de anuncios, etc.), se oculta la celda entera en vez
  // de dejar el "cargando..." colgado para siempre. No detecta un
  // símbolo mal resuelto DENTRO del iframe (eso el navegador no lo deja
  // mirar), pero sí un fallo de carga real.
  setTimeout(function(){
    if(!widgetContainer.querySelector('iframe')){
      cell.style.display='none';
    }
  }, 6000);
  // Re-anadir la estrella favorita como overlay flotante (se borro al limpiar cell.innerHTML)
  var star=document.createElement('div');
  star.style.position='absolute';
  star.style.top='8px';
  star.style.left='8px';
  star.style.zIndex='5';
  star.style.background='rgba(255,255,255,.92)';
  star.style.borderRadius='8px';
  star.style.boxShadow='0 1px 4px rgba(0,0,0,.15)';
  star.innerHTML=favStarBtn(tk);
  cell.appendChild(star);
}

// Close chart grid with ESC
document.addEventListener('keydown',function(e){
  if(e.key==='Escape' && document.getElementById('cg-overlay').style.display!=='none'){
    cgClose();
  }
});

// ── ESC ───────────────────────────────────────────────────────────────────────
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){closeModal();closeBMModal();}
});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD HTML
# ══════════════════════════════════════════════════════════════════════════════
def build_html(sectors, industries, benchmarks, breadth_latest, breadth_series,
               sec_stocks, ind_stocks, stock_perf, earnings, upcoming, stock_info, ts,
               accion_tk=None, accion_info=None, ratios_data=None, amplitud_mercado_api=None):
    summ = breadth_latest.get("__summary__", {})

    # Mapa ticker -> sector/industria para la pestaña Fundamentales (reverse
    # lookup de SECTOR_STOCKS / INDUSTRY_DATA, ya calculados en otro sitio).
    ticker_sector, ticker_industry = {}, {}
    for sec_name, tks in SECTOR_STOCKS.items():
        for tk in tks:
            ticker_sector.setdefault(tk, sec_name)
    for ind_name, d in INDUSTRY_DATA.items():
        for tk in d["holdings"]:
            ticker_industry.setdefault(tk, ind_name)

    payload = json.dumps({
        "ts":            ts,
        "sectors":       sectors,
        "industries":    industries,
        "benchmarks":    benchmarks,
        "sectorStocks":  sec_stocks,
        "industryStocks":ind_stocks,
        "stockPerf":     stock_perf,
        "stockInfo":     stock_info,
        "ratiosData":    ratios_data or {},
        "amplitudMercadoAPI": amplitud_mercado_api or {},
        "tickerSector":  ticker_sector,
        "tickerIndustry":ticker_industry,
        "breadthLatest": {k:v for k,v in breadth_latest.items() if k!="__summary__"},
        "breadthSummary":summ,
        "breadthSeries": breadth_series,
        "industryMeta":  {k:v["etf"] for k,v in INDUSTRY_DATA.items()},
        "earnings":      earnings,
        "upcoming":      upcoming,
        "accionTk":      accion_tk or "",
        "accionInfo":    accion_info or {},
    }, default=str)

    return (HTML_TMPL
        .replace("__DATA__",  payload)
        .replace("__TS__",    ts)
        .replace("__NIND__",  str(len(INDUSTRY_DATA)))
        .replace("__NBM__",   str(len(BENCHMARK))))


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def fetch_accion_info(ticker):
    """Descarga info completa de la acción del día (via Polygon.io)."""
    try:
        details = pg_get(f"/v3/reference/tickers/{ticker}")
        d = details.get("results", {}) if details else {}
        if not d: return {}
        return {
            "name":       d.get("name",""),
            "longName":   d.get("name",""),
            "sector":     d.get("sic_description",""),
            "industry":   d.get("sic_description",""),
            "country":    (d.get("locale","") or "").upper(),
            "exchange":   d.get("primary_exchange",""),
            "website":    d.get("homepage_url",""),
            "summary":    (d.get("description","") or ""),
            "employees":  d.get("total_employees"),
            "mktCap":     d.get("market_cap"),
            "pe":         None, "fwdPE": None, "eps": None, "fwdEps": None,
            "revGrowth":  None, "epsGrowth": None, "divYield": None, "beta": None,
            "analyst":    None, "nAnalysts": None, "targetMean": None,
            "grossMarg":  None, "opMarg": None, "netMarg": None,
            "roe":        None, "roa": None, "debtEq": None, "currentRatio": None,
            "revenue":    None, "ebitda": None, "fcf": None,
            "peg":        None, "pb": None, "ps": None,
        }
    except Exception as e:
        print(f"  Acción del día info error: {e}")
        return {}


def pick_accion_del_dia(stock_perf, stock_info, industry_data):
    """Selecciona la acción del día y descarga su info completa."""
    from datetime import datetime
    import math
    all_tks = list(stock_perf.keys())
    # Build industry map
    tk_ind = {}
    for ind, d in industry_data.items():
        for tk in d.get("holdings", []):
            if tk not in tk_ind: tk_ind[tk] = ind
    # Score candidates
    all_sorted = sorted(stock_perf.values(), key=lambda x: x.get("1Y", 0))
    def rs_of(tk):
        idx = next((i for i,s in enumerate(all_sorted) if s["ticker"]==tk), -1)
        return round(idx/len(all_sorted)*100) if idx>=0 else 0
    candidates = []
    for tk, r in stock_perf.items():
        rs = rs_of(tk)
        dist_hi = ((r["price"]-r.get("52wHigh",r["price"]))/r.get("52wHigh",r["price"])*100) if r.get("52wHigh") else -99
        score = 0
        if rs >= 80: score += 40
        elif rs >= 70: score += 28
        elif rs >= 65: score += 15
        if dist_hi >= -8: score += 20
        if r.get("abv50"): score += 10
        if r.get("abv200"): score += 8
        if tk_ind.get(tk): score += 5
        if r.get("price",0) > 20: score += 5
        if r.get("1M",0) > 5: score += 8
        if rs >= 65 and r.get("abv50") and r.get("price",0) > 15 and score > 55:
            candidates.append((score, tk, rs, dist_hi))
    candidates.sort(reverse=True)
    candidates = candidates[:40]
    if not candidates: return None, {}
    day_of_year = datetime.now().timetuple().tm_yday
    _, tk, rs, dist_hi = candidates[day_of_year % len(candidates)]
    print(f"  ★ Acción del día: {tk} (RS {rs}, dist_hi {dist_hi:.1f}%)")
    # Fetch full info
    full_info = fetch_accion_info(tk)
    # Merge with stock_info if available
    if tk in stock_info:
        for k,v in stock_info[tk].items():
            if k not in full_info or not full_info[k]:
                full_info[k] = v
    return tk, full_info


def main():
    print("\n╔══════════════════════════════════════════════╗")
    print("║   Market Sector & Industry Tracker v3       ║")
    print("╚══════════════════════════════════════════════╝\n")
    print("▶ Descargando datos...\n")

    # Test conectividad Polygon.io (fuente principal de datos)
    print("Test conectividad Polygon.io...")
    try:
        test = pg_aggs_daily("SPY", days=5)
        if not test:
            print("  WARNING: Polygon SPY sin datos - revisar API key / suscripción")
        else:
            print(f"  OK: SPY {len(test)} barras, cierre {test[-1]['close']:.2f}")
    except Exception as e:
        print(f"  ERROR Polygon: {e}")


    sectors    = fetch_perf(SECTOR_ETFS, "Sectores")
    industries = fetch_perf({k:v["etf"] for k,v in INDUSTRY_DATA.items()}, "Industrias")
    benchmarks = fetch_perf(BENCHMARK,  "Benchmarks globales")
    stock_perf = fetch_stock_perf()
    build_email_summary(stock_perf)  # NUEVO (07/07/2026): top_rs real para el email semanal
    save_setups_scanner_to_supabase(stock_perf)  # Setups+Scanner calculados en servidor
    breadth_l, breadth_s = fetch_breadth_and_amplitude(stock_perf)
    # NUEVO (03/09/2026): amplitud OFICIAL desde la API de amplitudmercado.com
    # (si hay clave configurada) — sustituye a la aproximación construida con
    # Polygon (fetch_nyse_breadth_real, dentro de fetch_breadth_and_amplitude)
    # cuando está disponible, porque es la fuente real que usan tus alumnos
    # para comparar. Si falla o no hay clave, el dashboard sigue funcionando
    # igual con la aproximación de Polygon — nunca se rompe por esto.
    amplitud_mercado_api = fetch_amplitud_mercado_api()
    earnings, upcoming = [], []

    print("\n▶ Construyendo mapas...")
    ind_map, sec_map = build_stock_maps(stock_perf)

    # Fundamentales para top acciones del SP500
    top_tickers = SP500_SAMPLE[:120]  # fundamentales top 120 (paralelo — ~30s vs 3min serie)
    stock_info   = fetch_stock_info(top_tickers)

    # NUEVO (04/07/2026) — Ratios TTM del add-on Financials & Ratios (Massive).
    # Universo COMPLETO (~1.300 tickers, el mismo que ya usa fetch_stock_perf
    # para precios/técnicos — sectores + industrias + SP500_SAMPLE), no solo
    # el top 120. El plan pagado de Massive no tiene límite de requests/min,
    # así que no hay motivo para recortar la cobertura.
    # Independiente de stock_info: no se usa todavía en build_html ni en
    # ninguna pestaña existente. Se vuelca a JSON aparte para validar la
    # calidad del dato antes de decidir cómo montar la pestaña/screener.
    ratios_universe = list(stock_perf.keys())
    ratios_data = fetch_ratios(ratios_universe)

    # NUEVO (05/07/2026) — Float, Short Interest, crecimiento YoY (ventas/EPS)
    # y tipo ADR/empleados. Se fusiona campo a campo dentro de ratios_data
    # (mismo ticker), para que la pestaña Fundamentales tenga todo en un solo
    # dict sin tener que cruzar varios ficheros en el frontend.
    extra_data = fetch_extra_fundamentals(ratios_universe)
    for tk, extra in extra_data.items():
        ratios_data.setdefault(tk, {}).update(extra)

    ratios_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ratios_data.json")
    with open(ratios_path, "w", encoding="utf-8") as f:
        json.dump(ratios_data, f, ensure_ascii=False, indent=2)
    print(f"✓ {len(ratios_data)}/{len(ratios_universe)} acciones con ratios (Financials & Ratios) → {ratios_path}")

    # NUEVO (03/09/2026) — BUG REAL ENCONTRADO Y CONFIRMADO POR VICTOR:
    # ratios_data (Massive, ~1.343 tickers, DE PAGO) se calculaba bien pero
    # nunca se conectaba al Panel individual de acción — ese panel seguía
    # usando solo stock_info (Polygon puro, sin Massive, limitado a
    # SP500_SAMPLE[:120]), así que cualquier ticker fuera de esos 120
    # (ej. SCCO) mostraba "fundamentales no precargados" aunque
    # estuviéramos pagando por tenerlos para las 1.343. Se fusiona aquí:
    # base = ratios_data (cobertura completa, de pago), y se rellenan por
    # encima los campos que solo trae stock_info (nombre, sector,
    # ingresos, analistas...) para los ~120 tickers que sí los tienen.
    # Resultado: TODO ticker con ratios de Massive ya muestra algo en vez
    # de nada, y el top 120 sigue teniendo también el detalle extra.
    combined_info = {tk: dict(v) for tk, v in ratios_data.items()}
    for tk, si in stock_info.items():
        entry = combined_info.setdefault(tk, {})
        for k, v in si.items():
            if v is not None and v != "" and entry.get(k) in (None, ""):
                entry[k] = v
    # Alias de nombre de campo: Massive usa "grossMargin", el panel espera
    # "grossMarg" (mismo dato, nombre distinto entre las dos fuentes).
    for tk, entry in combined_info.items():
        if entry.get("grossMarg") in (None, "") and entry.get("grossMargin") not in (None, ""):
            entry["grossMarg"] = entry["grossMargin"]
    print(f"✓ {len(combined_info)} acciones con fundamentales (Massive + detalle top 120) — antes solo {len(stock_info)}")
    stock_info = combined_info

    import pytz as _ptz
    ts   = datetime.now(_ptz.timezone("Europe/Madrid")).strftime("%d/%m/%Y %H:%M")
    print("\n▶ Seleccionando acción del día...")
    accion_tk, accion_info = pick_accion_del_dia(stock_perf, stock_info, INDUSTRY_DATA)
    html = build_html(sectors, industries, benchmarks,
                      breadth_l, breadth_s,
                      sec_map, ind_map, stock_perf, earnings, upcoming, stock_info, ts,
                      accion_tk, accion_info, ratios_data, amplitud_mercado_api)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_tracker_dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    # Guardar también como index.html para Render (upload automático a GitHub Pages)
    idx = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)

    summ  = breadth_l.get("__summary__", {})
    total = len(sectors)+len(industries)+len(benchmarks)+len(stock_perf)
    print(f"\n✓ {total} instrumentos procesados")
    print(f"✓ {len(INDUSTRY_DATA)} industrias/temas con drill-down completo")
    print(f"✓ {len(BENCHMARK)} benchmarks globales (BTC, oro, IBEX35, DAX...)")
    print(f"✓ {len(stock_perf)} acciones con MA20/MA50/MA200 + sparklines")
    print(f"✓ Score mercado: {summ.get('score','—')}/100 — {summ.get('score_label','—')}")
    print(f"✓ {len(earnings)} earnings registrados · {len(upcoming)} próximos")
    print(f"✓ {len(stock_info)} acciones con fundamentales completos")
    print(f"\n✓ Dashboard → {out}")
    print("▶ Abriendo navegador...\n")
    webbrowser.open(f"file://{out}")
    print("✓ Listo.\n")

    # Upload automatico a GitHub Pages (solo en servidor con GITHUB_TOKEN)
    import os as _os, base64 as _b64
    _gh_token = _os.environ.get("GITHUB_TOKEN", "")
    _gh_user  = _os.environ.get("GITHUB_USER", "victorgbolsa")
    _gh_repo  = _os.environ.get("GITHUB_REPO", "LaComunidad")
    if _gh_token and _os.path.exists(idx):
        try:
            import requests as _req
            _api = f"https://api.github.com/repos/{_gh_user}/{_gh_repo}/contents/index.html"
            _hdr = {
                "Authorization": f"token {_gh_token}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "LaComunidad-Tracker"
            }
            _sha = None
            _r = _req.get(_api, headers=_hdr, timeout=30)
            if _r.status_code == 200:
                _sha = _r.json().get("sha")
            _content_b64 = _b64.b64encode(open(idx, "rb").read()).decode("utf-8")
            import pytz as _pytz
            from datetime import datetime as _dt
            _ts = _dt.now(_pytz.timezone("Europe/Madrid")).strftime("%d/%m/%Y %H:%M")
            _payload = {"message": f"Dashboard actualizado {_ts}", "content": _content_b64, "branch": "main"}
            if _sha:
                _payload["sha"] = _sha
            _r2 = _req.put(_api, headers=_hdr, json=_payload, timeout=60)
            if _r2.status_code in (200, 201):
                print("✓ index.html subido a GitHub correctamente")
            else:
                # NUEVO (26/08/2026): antes solo se imprimía el código de
                # estado (403), sin el motivo real que da GitHub — así no
                # había forma de saber si era el token caducado, permisos
                # insuficientes, SSO sin autorizar, o la rama protegida.
                # Ahora se imprime también el cuerpo de la respuesta.
                print(f"✗ Error GitHub: {_r2.status_code}")
                try:
                    print(f"  Motivo: {_r2.json().get('message', _r2.text[:300])}")
                except Exception:
                    print(f"  Respuesta cruda: {_r2.text[:300]}")
        except Exception as _e:
            print(f"✗ Error upload: {_e}")
    else:
        print("Sin GITHUB_TOKEN - modo local, no se sube")


if __name__ == "__main__":
    main()
