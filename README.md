# u2beTranscript

Small self-hosted web page: paste a YouTube URL, get the video's transcript as a readable `.txt` download.

It runs `yt-dlp` to fetch the subtitles (Spanish first, then English; manual or auto-generated), converts the `.vtt` to plain text with one caption line per line and a blank line at each speaker pause, and returns it as a file.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app: one textbox, runs yt-dlp, returns the `.txt` |
| `vtt2txt.py` | VTT → readable text converter (also usable on its own) |
| `Dockerfile` | Image with Flask, Gunicorn and yt-dlp; runs as non-root |
| `docker-compose.yml` | Service (localhost:8090), hardening options, optional cookies mount |

## Run

```bash
docker compose up -d --build
curl http://localhost:8090/health   # -> ok (only from the server itself)
```

Port 8090 is bound to `127.0.0.1`, so the page is only reachable through the tunnel.

## Expose with Cloudflare Tunnel

Add a public hostname in Zero Trust → Networks → Tunnels pointing to `http://yt-transcript:8000`
(after `docker network connect u2betranscript_default <tunnel-container>`).

For an open link, protect the form with **Cloudflare Turnstile** (free bot check):

1. Cloudflare dashboard → Turnstile → Add widget, hostname = your public hostname.
2. On the server: `cp .env.example .env` and fill in `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`.
3. `docker compose up -d --build`

Without the keys the check is disabled. With them, the widget only validates on the public hostname,
so use the public URL.

Add a Cloudflare rate-limiting rule (Domain → Security → Security rules → Rate limiting rules). Free plan:
`(http.host eq "<your-hostname>" and http.request.method eq "POST")`, characteristic IP,
more than **3 requests per 10 seconds** → **Block for 10 seconds**.
For a private page instead, use **Cloudflare Access** with an allow-list of emails.

## Limits

The app counts every request that reaches YouTube (after the Turnstile check). Defaults: **50 per day in total**, **10 per day per visitor IP**
(from Cloudflare's `CF-Connecting-IP`). Change them in `.env` (`DAILY_LIMIT`, `PER_IP_DAILY_LIMIT`, `0` = no limit).
Counters are in memory: they reset at local midnight and whenever the container restarts.

## Hardening

The container runs as non-root user `app` (uid 10001) on a read-only filesystem (only `/tmp` is writable, in memory),
with all Linux capabilities dropped, `no-new-privileges`, and limits of 512 MB RAM, 1 CPU and 100 processes.

## Troubleshooting

- **HTTP 429 from YouTube**: the app handles one request at a time; wait a few minutes. If it persists, export a `cookies.txt` from a browser signed into YouTube and put it in `./cookies/` and make it readable by the container (`chmod 644 cookies/cookies.txt`). Use a throwaway Google account, not your main one.
- **Outdated yt-dlp** ("No se encontraron subtítulos" for videos that have them): rebuild to get the latest version:
  `docker compose build --no-cache && docker compose up -d`. A weekly cron job is a good idea:
  `0 4 * * 1 cd ~/u2beTranscript && docker compose build -q --no-cache && docker compose up -d`
- Logs: `docker logs yt-transcript`.

## Converter only

```bash
python vtt2txt.py "*.vtt"
```
