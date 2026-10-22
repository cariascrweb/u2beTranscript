import glob
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone
import urllib.parse
import urllib.request

from flask import Flask, request, send_file, render_template_string

from vtt2txt import vtt_to_text

app = Flask(__name__)
job_lock = threading.Lock()  # one download at a time, to avoid YouTube 429s

ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
LANG_PREFERENCE = ["es", "en"]  # first match wins

# Cloudflare Turnstile (bot check). Disabled when the keys are not set.
TS_SITE = os.environ.get("TURNSTILE_SITE_KEY", "")
TS_SECRET = os.environ.get("TURNSTILE_SECRET_KEY", "")

# Daily caps on requests that reach YouTube (0 = no limit). Counters live in
# memory and reset at local midnight (or when the container restarts).
DAILY_LIMIT = int(os.environ.get("DAILY_LIMIT", "50"))
PER_IP_DAILY_LIMIT = int(os.environ.get("PER_IP_DAILY_LIMIT", "10"))
LOCAL_TZ = timezone(timedelta(hours=int(os.environ.get("UTC_OFFSET_HOURS", "-6"))))  # Costa Rica
_quota = {"day": None, "total": 0, "per_ip": {}}
_quota_lock = threading.Lock()

PAGE = r"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube → TXT</title>
{% if site_key %}<script src="https://challenges.cloudflare.com/turnstile/v0/api.js" async defer></script>{% endif %}
<style>
 body{font-family:system-ui,sans-serif;max-width:560px;margin:12vh auto;padding:0 16px;color:#222}
 form{display:flex;flex-wrap:wrap;gap:8px} .cf-turnstile{flex-basis:100%} input{flex:1;padding:10px;font-size:16px}
 button{padding:10px 16px;font-size:16px;cursor:pointer}
 .err{color:#b00020;margin-top:12px}
</style></head><body>
<h2>Transcripción de YouTube</h2>
<form method="post" id="f">
 <input name="url" placeholder="https://www.youtube.com/watch?v=..." required autofocus value="{{ url or '' }}">
 <button>Descargar .txt</button>
 {% if site_key %}<div class="cf-turnstile" data-sitekey="{{ site_key }}"></div>{% endif %}
</form>
<p class="err" id="err">{{ error or '' }}</p>
<script>
const f = document.getElementById('f'), btn = f.querySelector('button'), err = document.getElementById('err');
f.addEventListener('submit', async (e) => {
  e.preventDefault();
  btn.disabled = true; btn.innerText = 'Procesando…'; err.textContent = '';
  try {
    const r = await fetch('/', {method: 'POST', body: new FormData(f)});
    if (!r.ok) {
      // error pages are this same page with the message in #err
      const doc = new DOMParser().parseFromString(await r.text(), 'text/html');
      err.textContent = doc.getElementById('err')?.textContent || ('Error ' + r.status);
      return;
    }
    const cd = r.headers.get('Content-Disposition') || '';
    const m = cd.match(/filename\*=UTF-8''([^;]+)/i) || cd.match(/filename="?([^";]+)"?/i);
    const name = m ? decodeURIComponent(m[1]) : 'transcript.txt';
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob()); a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  } catch (x) {
    err.textContent = 'No se pudo conectar con el servidor.';
  } finally {
    btn.disabled = false; btn.innerText = 'Descargar .txt';
    if (window.turnstile) turnstile.reset();  // each token is single-use
  }
});
</script>
</body></html>"""


def page(**kw):
    return render_template_string(PAGE, site_key=TS_SITE, **kw)


def turnstile_ok():
    if not TS_SECRET:
        return True
    token = request.form.get("cf-turnstile-response", "")
    if not token:
        return False
    data = urllib.parse.urlencode({
        "secret": TS_SECRET,
        "response": token,
        "remoteip": client_ip(),
    }).encode()
    try:
        with urllib.request.urlopen(
                "https://challenges.cloudflare.com/turnstile/v0/siteverify", data, timeout=10) as r:
            return bool(json.load(r).get("success"))
    except Exception as e:
        app.logger.warning("Turnstile verify failed: %s", e)
        return False


def client_ip():
    # Behind the Cloudflare Tunnel every request comes from the tunnel
    # container, so the real visitor IP is in CF-Connecting-IP.
    return request.headers.get("CF-Connecting-IP") or request.remote_addr or "unknown"


def take_quota(ip):
    """Count one YouTube request. Returns an error message if a cap is hit."""
    today = datetime.now(LOCAL_TZ).date()
    with _quota_lock:
        if _quota["day"] != today:
            _quota.update(day=today, total=0, per_ip={})
        if DAILY_LIMIT and _quota["total"] >= DAILY_LIMIT:
            return "Se alcanzó el límite diario del servicio. Intente mañana."
        if PER_IP_DAILY_LIMIT and _quota["per_ip"].get(ip, 0) >= PER_IP_DAILY_LIMIT:
            return f"Alcanzó su límite de {PER_IP_DAILY_LIMIT} transcripciones por día. Intente mañana."
        _quota["total"] += 1
        _quota["per_ip"][ip] = _quota["per_ip"].get(ip, 0) + 1
    return None


def pick_vtt(files):
    for lang in LANG_PREFERENCE:
        for f in files:
            # filenames look like "Title [id].es.vtt" or "Title [id].es-orig.vtt"
            if re.search(rf"\.{lang}(-[\w-]+)?\.vtt$", f):
                return f
    return files[0] if files else None


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        return page()

    url = request.form.get("url", "").strip()
    m = ID_RE.search(url)
    if not m:
        return page(url=url, error="URL de YouTube no válida."), 400
    video_id = m.group(1)

    if not turnstile_ok():
        return page(url=url, error="Verificación anti-bot fallida. Intente de nuevo."), 403

    over = take_quota(client_ip())
    if over:
        app.logger.warning("Quota hit for %s: %s", client_ip(), over)
        return page(url=url, error=over), 429

    if not job_lock.acquire(timeout=60):
        return page(url=url, error="Servidor ocupado, intente de nuevo en un minuto."), 503
    tmp = tempfile.mkdtemp(prefix="yt_")
    try:
        cmd = [
            "yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs",
            "--sub-langs", "es.*,en.*", "--sub-format", "vtt",
            "-o", "%(title).80B [%(id)s].%(ext)s", "--paths", tmp,
            f"https://www.youtube.com/watch?v={video_id}",
        ]
        if os.path.exists("/cookies/cookies.txt"):
            cmd[1:1] = ["--cookies", "/cookies/cookies.txt"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

        vtt = pick_vtt(sorted(glob.glob(os.path.join(tmp, "*.vtt"))))
        if not vtt:
            if "429" in proc.stderr:
                msg = "YouTube limitó las solicitudes (429). Espere unos minutos e intente de nuevo."
            else:
                msg = "No se encontraron subtítulos para este video."
            app.logger.warning(proc.stderr[-2000:])
            return page(url=url, error=msg), 502

        name = re.sub(r"\.[\w-]+\.vtt$", ".txt", os.path.basename(vtt))
        data = io.BytesIO(vtt_to_text(vtt).encode("utf-8"))
        return send_file(data, as_attachment=True, download_name=name,
                         mimetype="text/plain; charset=utf-8")
    except subprocess.TimeoutExpired:
        return page(url=url, error="Tiempo de espera agotado."), 504
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        job_lock.release()


@app.route("/health")
def health():
    return "ok"
