FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir flask gunicorn yt-dlp
COPY app.py vtt2txt.py .
EXPOSE 8000
# Update yt-dlp on every start: YouTube breaks old versions often
CMD ["sh", "-c", "pip install -q -U yt-dlp && exec gunicorn -w 1 --threads 4 --timeout 240 -b 0.0.0.0:8000 app:app"]
