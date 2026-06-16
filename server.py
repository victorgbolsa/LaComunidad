"""
VICTOR GALAN: LA COMUNIDAD — Servidor de automatización
Render.com (Pro plan) — cron jobs + alertas push + email semanal

Cron jobs configurados en Render:
  - Dashboard diario:  0 7 * * 1-5   (lunes-viernes 8:00 Madrid = 7:00 UTC)
  - Alertas precio:    * 13-20 * * 1-5 (cada minuto, horario mercado USA)
  - Email semanal:     0 8 * * 1       (lunes 9:00 Madrid = 8:00 UTC)
"""

import os, json, base64, logging, time, datetime
import requests
from flask import Flask, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

# ── CONFIGURACIÓN (variables de entorno en Render) ─────────────────────────────
GITHUB_TOKEN   = os.environ.get('GITHUB_TOKEN', '')
GITHUB_USER    = os.environ.get('GITHUB_USER',  'victorgbolsa')
GITHUB_REPO    = os.environ.get('GITHUB_REPO',  'LaComunidad')
GITHUB_BRANCH  = os.environ.get('GITHUB_BRANCH','main')

SUPABASE_URL   = os.environ.get('SUPABASE_URL', 'https://othghdtplmlkrqwfcjzk.supabase.co')
SUPABASE_KEY   = os.environ.get('SUPABASE_KEY', '')   # service_role key (no la anon)

RESEND_KEY     = os.environ.get('RESEND_KEY',   '')
FROM_EMAIL     = os.environ.get('FROM_EMAIL',   'noreply@tudominio.com')
RESEND_FROM    = os.environ.get('RESEND_FROM',  'Victor Galán <noreply@tudominio.com>')

VAPID_PRIVATE  = os.environ.get('VAPID_PRIVATE_KEY', '')
VAPID_EMAIL    = os.environ.get('VAPID_EMAIL',  'mailto:tu@email.com')

# ── HELPERS ────────────────────────────────────────────────────────────────────

def supabase_get(table, params=''):
    """GET a Supabase table via REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{params}"
    r = requests.get(url, headers={
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }, timeout=15)
    r.raise_for_status()
    return r.json()

def supabase_patch(table, match_col, match_val, data):
    """PATCH (update) rows in a Supabase table."""
    url = f"{SUPABASE_URL}/rest/v1/{table}?{match_col}=eq.{match_val}"
    r = requests.patch(url, headers={
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }, json=data, timeout=15)
    r.raise_for_status()
    return r

def get_yahoo_price(ticker):
    """Fetch current price from Yahoo Finance."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1d"
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        data = r.json()
        return data['chart']['result'][0]['meta']['regularMarketPrice']
    except Exception as e:
        log.warning(f"Yahoo price error for {ticker}: {e}")
        return None

def upload_to_github(content_bytes, filename='index.html'):
    """Upload a file to GitHub, overwriting if it exists."""
    api = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/contents/{filename}"
    headers = {
        'Authorization': f'token {GITHUB_TOKEN}',
        'Accept': 'application/vnd.github.v3+json'
    }
    # Get current SHA (needed for update)
    r = requests.get(api, headers=headers, timeout=15)
    sha = r.json().get('sha') if r.status_code == 200 else None

    payload = {
        'message': f'🤖 Dashboard actualizado {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")} UTC',
        'content': base64.b64encode(content_bytes).decode(),
        'branch': GITHUB_BRANCH,
    }
    if sha:
        payload['sha'] = sha

    r = requests.put(api, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    log.info(f"✅ {filename} subido a GitHub ({len(content_bytes)//1024}KB)")
    return True

def send_push(subscription_json, title, body, url=None):
    """Send a Web Push notification using pywebpush."""
    try:
        from pywebpush import webpush, WebPushException
        data = json.dumps({'title': title, 'body': body, 'url': url or '/'})
        webpush(
            subscription_info=subscription_json,
            data=data,
            vapid_private_key=VAPID_PRIVATE,
            vapid_claims={"sub": VAPID_EMAIL}
        )
        return True
    except Exception as e:
        log.warning(f"Push error: {e}")
        return False

def send_email_resend(to_email, subject, html_body):
    """Send email via Resend API."""
    try:
        r = requests.post('https://api.resend.com/emails', headers={
            'Authorization': f'Bearer {RESEND_KEY}',
            'Content-Type': 'application/json'
        }, json={
            'from': RESEND_FROM,
            'to': [to_email],
            'subject': subject,
            'html': html_body
        }, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error(f"Resend error to {to_email}: {e}")
        return False


# ── CRON 1: DASHBOARD DIARIO ───────────────────────────────────────────────────

@app.route('/cron/dashboard', methods=['GET','POST'])
def cron_dashboard():
    """
    Ejecuta market_tracker.py, genera index.html y lo sube a GitHub.
    Llamar con: GET /cron/dashboard
    Configurar en Render como cron job: 0 7 * * 1-5
    """
    log.info("🚀 Iniciando generación de dashboard...")
    start = time.time()
    try:
        import subprocess, sys
        # Ejecuta el script generador
        result = subprocess.run(
            [sys.executable, 'market_tracker.py'],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            log.error(f"market_tracker.py falló:\n{result.stderr[-2000:]}")
            return jsonify({'ok': False, 'error': result.stderr[-500:]}), 500

        log.info(result.stdout[-500:])

        # Leer el HTML generado (market_tracker.py lo guarda como index.html)
        with open('index.html', 'rb') as f:
            html_bytes = f.read()

        upload_to_github(html_bytes, 'index.html')
        elapsed = round(time.time() - start, 1)
        log.info(f"✅ Dashboard completado en {elapsed}s")
        return jsonify({'ok': True, 'seconds': elapsed, 'size_kb': len(html_bytes)//1024})

    except Exception as e:
        log.exception("Error en cron_dashboard")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── CRON 2: ALERTAS DE PRECIO (cada minuto en horario de mercado) ──────────────

@app.route('/cron/alertas', methods=['GET','POST'])
def cron_alertas():
    """
    Comprueba alertas activas y envía push si el precio se cumple.
    Configurar en Render como cron job: * 13-20 * * 1-5
    """
    ahora = datetime.datetime.utcnow()
    log.info(f"🔔 Comprobando alertas ({ahora.strftime('%H:%M')} UTC)...")

    try:
        # Obtener alertas activas
        alertas = supabase_get('alertas', 'activa=eq.true&select=*')
        if not alertas:
            return jsonify({'ok': True, 'checked': 0, 'triggered': 0})

        # Agrupar por ticker para reducir llamadas a Yahoo
        by_ticker = {}
        for a in alertas:
            by_ticker.setdefault(a['ticker'], []).append(a)

        triggered = 0
        for ticker, ticker_alertas in by_ticker.items():
            price = get_yahoo_price(ticker)
            if price is None:
                continue

            for alerta in ticker_alertas:
                objetivo = float(alerta['precio'])
                direccion = alerta['direccion']  # 'above' o 'below'

                cumplida = (direccion == 'above' and price >= objetivo) or \
                           (direccion == 'below' and price <= objetivo)

                if not cumplida:
                    continue

                log.info(f"✅ Alerta cumplida: {ticker} {direccion} {objetivo} (actual: {price})")

                # Marcar como inactiva para no repetir
                supabase_patch('alertas', 'id', alerta['id'], {
                    'activa': False,
                    'disparada_at': ahora.isoformat()
                })

                # Obtener subscripciones push del usuario
                if VAPID_PRIVATE:
                    subs = supabase_get('push_subscriptions',
                                        f"user_id=eq.{alerta['user_id']}&select=subscription")
                    dir_txt = '▲ superó' if direccion == 'above' else '▼ cayó por debajo de'
                    for sub_row in subs:
                        send_push(
                            sub_row['subscription'],
                            title=f"🔔 Alerta {ticker}",
                            body=f"{ticker} {dir_txt} ${objetivo:.2f} — Precio actual: ${price:.2f}",
                            url='https://victorgbolsa.github.io/LaComunidad/'
                        )
                triggered += 1

        log.info(f"Alertas comprobadas: {len(alertas)}, disparadas: {triggered}")
        return jsonify({'ok': True, 'checked': len(alertas), 'triggered': triggered})

    except Exception as e:
        log.exception("Error en cron_alertas")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── CRON 3: EMAIL SEMANAL (lunes 9:00) ────────────────────────────────────────

@app.route('/cron/email-semanal', methods=['GET','POST'])
def cron_email_semanal():
    """
    Envía email semanal con resumen de mercado a todos los alumnos.
    Configurar en Render como cron job: 0 8 * * 1  (lunes 9:00 Madrid)
    """
    log.info("📧 Enviando email semanal...")
    if not RESEND_KEY:
        return jsonify({'ok': False, 'error': 'RESEND_KEY no configurada'}), 400

    try:
        # Obtener todos los perfiles con email
        profiles = supabase_get('profiles', 'email=not.is.null&select=email,nombre')

        # Obtener top ideas de la semana (más votadas)
        ideas = supabase_get('ideas',
            'select=ticker,direccion,texto,avg_stars,num_votes,profiles(nombre)'
            '&order=avg_stars.desc&limit=5')

        fecha = datetime.datetime.now().strftime('%d de %B de %Y')
        sent = 0
        failed = 0

        for profile in profiles:
            if not profile.get('email'):
                continue
            nombre = profile.get('nombre') or profile['email'].split('@')[0]

            # Construir HTML del email
            ideas_html = ''
            for idea in ideas:
                dir_color = '#05c46b' if idea['direccion'] == 'long' else '#ff3f5b'
                dir_txt   = '▲ ALCISTA' if idea['direccion'] == 'long' else '▼ BAJISTA'
                autor     = (idea.get('profiles') or {}).get('nombre', 'Anónimo')
                ideas_html += f"""
                <tr>
                  <td style="padding:10px;border-bottom:1px solid #eee">
                    <strong style="font-size:16px;color:#4f6ef7">{idea['ticker']}</strong>
                    <span style="color:{dir_color};font-size:11px;margin-left:8px">{dir_txt}</span><br>
                    <span style="font-size:12px;color:#666">{idea['texto'][:120]}...</span><br>
                    <span style="font-size:10px;color:#999">Por {autor} · ⭐ {idea['avg_stars']:.1f} ({idea['num_votes']} votos)</span>
                  </td>
                </tr>"""

            html = f"""
<!DOCTYPE html>
<html>
<body style="font-family:Inter,Arial,sans-serif;background:#f0f2f5;margin:0;padding:20px">
<div style="max-width:600px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)">

  <!-- Header -->
  <div style="background:linear-gradient(135deg,#1e293b,#334155);padding:28px 32px">
    <div style="font-family:Georgia,serif;font-size:22px;font-weight:bold;color:#fff">
      VICTOR GALÁN: <span style="color:#4f6ef7">LA COMUNIDAD</span>
    </div>
    <div style="color:#94a3b8;font-size:12px;margin-top:4px">Resumen semanal · {fecha}</div>
  </div>

  <!-- Saludo -->
  <div style="padding:24px 32px 0">
    <p style="font-size:15px;color:#1e293b">Hola <strong>{nombre}</strong>,</p>
    <p style="font-size:13px;color:#64748b;line-height:1.7">
      Aquí tienes el resumen de la semana en La Comunidad.
      Esta semana hemos tenido <strong>{len(profiles)} alumnos activos</strong> compartiendo análisis.
    </p>
  </div>

  <!-- Top ideas -->
  <div style="padding:16px 32px">
    <div style="font-size:13px;font-weight:700;color:#1e293b;margin-bottom:12px;
                padding-bottom:8px;border-bottom:2px solid #4f6ef7">
      🌟 Top ideas de la comunidad esta semana
    </div>
    <table style="width:100%;border-collapse:collapse">
      {ideas_html or '<tr><td style="padding:16px;color:#999;text-align:center">Sin ideas esta semana</td></tr>'}
    </table>
  </div>

  <!-- CTA -->
  <div style="padding:20px 32px 28px;text-align:center">
    <a href="https://victorgbolsa.github.io/LaComunidad/"
       style="background:#4f6ef7;color:#fff;text-decoration:none;padding:12px 28px;
              border-radius:8px;font-size:13px;font-weight:600;display:inline-block">
      Abrir el dashboard →
    </a>
  </div>

  <!-- Footer -->
  <div style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;
              text-align:center;font-size:10px;color:#94a3b8">
    © Victor Galán · La Comunidad · No es asesoramiento financiero
  </div>
</div>
</body>
</html>"""

            ok = send_email_resend(
                profile['email'],
                f"📊 Resumen semanal — La Comunidad ({fecha})",
                html
            )
            if ok:
                sent += 1
            else:
                failed += 1
            time.sleep(0.1)  # rate limit

        log.info(f"📧 Emails enviados: {sent}, fallidos: {failed}")
        return jsonify({'ok': True, 'sent': sent, 'failed': failed})

    except Exception as e:
        log.exception("Error en cron_email_semanal")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── HEALTH CHECK ───────────────────────────────────────────────────────────────

@app.route('/', methods=['GET'])
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'ok',
        'service': 'VictorGalan La Comunidad — Automation Server',
        'time': datetime.datetime.utcnow().isoformat(),
        'crons': {
            'dashboard': 'POST /cron/dashboard  (0 7 * * 1-5)',
            'alertas':   'POST /cron/alertas    (* 13-20 * * 1-5)',
            'email':     'POST /cron/email-semanal (0 8 * * 1)'
        }
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
