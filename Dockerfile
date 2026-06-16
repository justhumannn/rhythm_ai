FROM denoland/deno:bin-2.3.0 AS deno

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY --from=deno /deno /usr/local/bin/deno

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.api.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.api.txt

COPY . .

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data /app/audio/web/downloads \
    && chown -R appuser:appuser /app /home/appuser

USER appuser

CMD ["sh", "-c", "uvicorn web_app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
