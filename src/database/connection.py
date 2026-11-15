import os
import threading

import psycopg2
from cachetools import TTLCache, cached
from dotenv import load_dotenv

load_dotenv()

# Singleton compatível com @st.cache_resource (ttl=None = sem expiração)
_DB_CACHE = TTLCache(maxsize=1, ttl=None)
_DB_LOCK = threading.RLock()


@cached(cache=_DB_CACHE, lock=_DB_LOCK)
def get_db_connection():
    """Cria e retorna uma conexão com o banco PostGIS (singleton em memória).

    LGPD stateless: a conexão é mantida em memória (cache singleton) sem persistir
    dados de candidatos. Cada chamada reutiliza o mesmo objeto psycopg2.

    Returns:
        psycopg2.extensions.connection: Conexão ativa com o banco.
    """
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "smartpass"),
        user=os.getenv("DB_USER", ""),
        password=os.getenv("DB_PASS", ""),
        port=os.getenv("DB_PORT", "5432"),
    )
    return conn


def check_db_health(timeout: float = 3.0) -> dict:
    """Verifica saúde do PostgreSQL + PostGIS com SELECT 1 e SELECT PostGIS_Version().

    Args:
        timeout: Timeout de conexão em segundos (default 3.0).

    Returns:
        dict: {"ok": bool, "postgis_version": str | None, "latency_ms": float | None,
               "erro": str | None}
    """
    import time

    t0 = time.monotonic()
    try:
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "smartpass"),
            user=os.getenv("DB_USER", ""),
            password=os.getenv("DB_PASS", ""),
            port=os.getenv("DB_PORT", "5432"),
            connect_timeout=int(timeout),
        )
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
            cur.execute("SELECT PostGIS_Version()")
            row = cur.fetchone()
            postgis_version = row[0] if row else None
            latency_ms = round((time.monotonic() - t0) * 1000, 2)
            return {"ok": True, "postgis_version": str(postgis_version or "unknown"), "latency_ms": latency_ms, "erro": None}
        finally:
            conn.close()
    except Exception as exc:
        latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return {"ok": False, "postgis_version": None, "latency_ms": latency_ms, "erro": str(exc)}


# Compatibilidade com @st.cache_resource (para testes legados)
get_db_connection._info = type("Info", (), {"ttl": None, "show_spinner": False})()
get_db_connection.clear = _DB_CACHE.clear
