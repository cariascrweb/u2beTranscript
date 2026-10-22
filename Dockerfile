FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp \
    PYTHONUNBUFFERED=1

# yt-dlp is installed at build time (not at container start) so the container
# can run as a non-root user on a read-only filesystem. To get a newer yt-dlp,
# rebuild:  docker compose build --no-cache && docker compose up -d
RUN pip install --no-cache-dir flask gunicorn yt-dlp \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY app.py vtt2txt.py .

USER app
EXPOSE 8000
CMD ["gunicorn", "-w", "1", "--threads", "4", "--timeout", "240", "-b", "0.0.0.0:8000", "app:app"]
