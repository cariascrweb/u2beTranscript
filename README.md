# u2beTranscript

Small self-hosted web page: paste a YouTube URL, get the video's transcript as a readable `.txt` download.

It runs `yt-dlp` to fetch the subtitles (Spanish first, then English; manual or auto-generated), converts the `.vtt` to plain text with one caption line per line and a blank line at each speaker pause, and returns it as a file.

## Files

| File | Purpose |
|---|---|
| `app.py` | Flask app: one textbox, runs yt-dlp, returns the `.txt` |
| `vtt2txt.py` | VTT → readable text converter (also usable on its own) |
| `Dockerfile` | Image with Flask, Gunicorn and yt-dlp (yt-dlp self-updates on start) |
| `docker-compose.yml` | Service on port 8090, optional cookies mount |

## Run

```bash
docker compose up -d --build
curl http://localhost:8090/health   # -> ok
```

Open `http://<server>:8090`.

## Expose with Cloudflare Tunnel

Add a public hostname in Zero Trust → Networks → Tunnels pointing to `http://yt-transcript:8000`
(after `docker network connect u2betranscript_default <tunnel-container>`) or to `http://<server-ip>:8090`.

Protect it with **Cloudflare Access** (self-hosted app, allow-list of emails); otherwise anyone can use the server's IP against YouTube.

## Troubleshooting

- **HTTP 429 from YouTube**: the app handles one request at a time; wait a few minutes. If it persists, export a `cookies.txt` from a browser signed into YouTube and put it in `./cookies/`.
- **Outdated yt-dlp**: `docker restart yt-transcript` reinstalls the latest version.
- Logs: `docker logs yt-transcript`.

## Converter only

```bash
python vtt2txt.py "*.vtt"
```
