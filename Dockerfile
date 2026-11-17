# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS builder
COPY requirements.txt ./
RUN pip install --prefix=/usr/local --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage: API (FastAPI + Uvicorn) — único entry point do backend
# -----------------------------------------------------------------------------
FROM base AS api
COPY --from=builder /usr/local /usr/local
RUN useradd -m -u 10001 appuser
COPY src ./src
COPY requirements.txt ./
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"]
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
