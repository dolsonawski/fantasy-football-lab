FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Persistent data (accounts, drafts, leagues, rankings, caches) lives here.
# Mount a volume/disk at /data on your host so it survives restarts.
ENV FFL_DATA_DIR=/data \
    FFL_SECURE_COOKIES=1 \
    PORT=8000

EXPOSE 8000

# Shell form so $PORT (set by most hosts) is honored.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips="*"
