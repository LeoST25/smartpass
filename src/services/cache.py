"""Cache agnóstico de framework (cachetools.TTLCache) para desacoplar services/database do Streamlit.

Substitui @st.cache_data e @st.cache_resource, mantendo TTLs idênticos e compatibilidade
com testes legados que usam func.clear() e func._info.ttl/show_spinner.

TTLs canônicos (mantidos dos decorators originais):
- Geocoding: 3600s (1h)
- Routing/OTP/Mapa: 600s (10min)
- DB connection: None (singleton, ttl infinito — equivalente a @st.cache_resource)

Thread-safety: todos os caches usam threading.RLock() para compatibilidade com uvicorn
(workers múltiplos) e execução concorrente.
"""

from __future__ import annotations

import functools
import threading
from types import SimpleNamespace

from cachetools import TTLCache, cached


def st_cache_data(ttl: int = 3600, show_spinner: bool = False, max_entries: int = 512):
    """Decorator compatível com @st.cache_data usando cachetools.TTLCache.

    Args:
        ttl: Time-to-live em segundos (default 3600).
        show_spinner: Mantido apenas para compatibilidade com _info.show_spinner (não renderiza).
        max_entries: Tamanho máximo do cache (default 512).

    Returns:
        function: Decorator que aplica @cached(cache=TTLCache, lock=RLock) e anexa
                  atributos de compatibilidade _info e clear.
    """
    cache = TTLCache(maxsize=max_entries, ttl=ttl)
    lock = threading.RLock()

    def decorator(fn):
        @functools.wraps(fn)
        @cached(cache=cache, lock=lock)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        # Compatibilidade com testes legados (test_geocoding.py:255, fixture clear_cache)
        wrapper._info = SimpleNamespace(ttl=ttl, show_spinner=show_spinner)
        wrapper.clear = cache.clear
        wrapper.cache_info = lambda: SimpleNamespace(currsize=len(cache), maxsize=max_entries)

        return wrapper

    return decorator


def st_cache_resource(show_spinner: bool = False, maxsize: int = 1):
    """Decorator compatível com @st.cache_resource usando cachetools.TTLCache (ttl=None = singleton).

    Args:
        show_spinner: Mantido para compatibilidade (não renderiza).
        maxsize: Tamanho do cache (default 1 para singleton).

    Returns:
        function: Decorator que aplica @cached(cache=TTLCache, lock=RLock) com ttl=None.
    """
    cache = TTLCache(maxsize=maxsize, ttl=None)  # ttl=None = sem expiração (singleton)
    lock = threading.RLock()

    def decorator(fn):
        @functools.wraps(fn)
        @cached(cache=cache, lock=lock)
        def wrapper(*args, **kwargs):
            return fn(*args, **kwargs)

        wrapper._info = SimpleNamespace(ttl=None, show_spinner=show_spinner)
        wrapper.clear = cache.clear

        return wrapper

    return decorator
