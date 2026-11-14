# syntax=docker/dockerfile:1.6
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app

FROM base AS builder
COPY requirements.txt ./
RUN pip install --prefix=/usr/local --no-cache-dir -r requirements.txt

FROM base AS production
COPY --from=builder /usr/local /usr/local
# Criar usuário não-root
RUN useradd -m -u 10001 appuser
COPY src ./src
COPY requirements.txt ./
# Garante que src seja importável e cache limpo
RUN chown -R appuser:appuser /app
USER appuser
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]
CMD ["streamlit", "run", "src/app.py", "--server.port=8501", "--server.address=0.0.0.0"]

FROM production AS development
USER root
# Ferramentas leves para debug (opcional)
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
USER appuser
# Em dev, o código será montado via bind-mount; mantém HEALTHCHECK e CMD iguais
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=20s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"]
CMD ["streamlit", "run", "src/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.runOnSave=true"]
