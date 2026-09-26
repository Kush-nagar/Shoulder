FROM ghcr.io/astral-sh/uv:0.12.10 AS uv
FROM python:3.11.16-slim-bookworm
# ffmpeg/ffprobe for transcode, probe and sprite sheets (services/worker/media.py).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY services/api ./services/api
COPY services/worker ./services/worker
COPY services/timeline.py ./services/timeline.py
ENV FFMPEG_BINARY=/usr/bin/ffmpeg FFPROBE_BINARY=/usr/bin/ffprobe
USER 10001:10001
CMD ["/app/.venv/bin/python", "-m", "services.worker.main"]
