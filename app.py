import glob
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading

from flask import Flask, request, send_file, render_template_string

from vtt2txt import vtt_to_text

app = Flask(__name__)
job_lock = threading.Lock()  # one download at a time, to avoid YouTube 429s

ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")
LANG_PREFERENCE = ["es", "en"]  # first match wins

PAGE = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>YouTube → TXT</title>
<style>
 body{font-family:system-ui,sans-serif;max-width:560px;margin:12vh auto;padding:0 16px;color:#222}
 form{display:flex;gap:8px} input{flex:1;padding:10px;font-size:16px}
 button{padding:10px 16px;font-size:16px;cursor:pointer}
 .err{color:#b00020;margin-top:12px}
</style></head><body>
<h2>Transcripción de YouTube</h2>
<form method="post" onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').innerText='Procesando…'">
 <input name="url" placeholder="https://www.youtube.com/watch?v=..." required autofocus value="{{ url or '' }}">
 <button>Descargar .txt</button>
</form>
{% if error %}<p class="err">{{ error }}</p>{% endif %}
</body></html>"""


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
        return render_template_string(PAGE)

    url = request.form.get("url", "").strip()
    m = ID_RE.search(url)
    if not m:
        return render_template_string(PAGE, url=url, error="URL de YouTube no válida."), 400
    video_id = m.group(1)

    if not job_lock.acquire(timeout=60):
        return render_template_string(PAGE, url=url, error="Servidor ocupado, intente de nuevo en un minuto."), 503
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
            return render_template_string(PAGE, url=url, error=msg), 502

        name = re.sub(r"\.[\w-]+\.vtt$", ".txt", os.path.basename(vtt))
        data = io.BytesIO(vtt_to_text(vtt).encode("utf-8"))
        return send_file(data, as_attachment=True, download_name=name,
                         mimetype="text/plain; charset=utf-8")
    except subprocess.TimeoutExpired:
        return render_template_string(PAGE, url=url, error="Tiempo de espera agotado."), 504
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        job_lock.release()


@app.route("/health")
def health():
    return "ok"
