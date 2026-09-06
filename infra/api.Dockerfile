FROM ghcr.io/astral-sh/uv:0.12.10 AS uv
FROM python:3.11.16-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY services/api ./services/api
USER 10001:10001
EXPOSE 8000
CMD ["/app/.venv/bin/python", "-m", "uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
