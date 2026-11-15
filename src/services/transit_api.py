"""Roteamento de transporte público via OpenTripPlanner (OTP).

Extração rica por leg: mode, distance, duration, from{ name lat lon }, to{ name lat lon },
route{ gtfsId shortName longName agency{ gtfsId name } } e fare do itinerário quando disponível.
Timeout 10s conforme gis-routing-otp/SKILL.md e fallback LGPD stateless.
"""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

OTP_GRAPHQL_URL = os.getenv("OTP_GRAPHQL_URL", "http://localhost:8080/otp/gtfs/v1")
VT_TARIFA_PADRAO = float(os.getenv("VT_TARIFA_PADRAO", "5.00"))
TIMEZONE_RMSP = ZoneInfo("America/Sao_Paulo")


def _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Monta a consulta GraphQL compatível com OTP 2.7+ — extração rica."""
    data_hora = datetime.now(TIMEZONE_RMSP).isoformat(timespec="minutes")
    return f"""
    {{
      planConnection(
        origin: {{ location: {{ coordinate: {{ latitude: {origem_lat}, longitude: {origem_lon} }} }} }}
        destination: {{ location: {{ coordinate: {{ latitude: {destino_lat}, longitude: {destino_lon} }} }} }}
        dateTime: {{ earliestDeparture: \"{data_hora}\" }}
        modes: {{
          direct: [WALK]
          transit: {{ transit: [{{ mode: BUS }}, {{ mode: RAIL }}, {{ mode: SUBWAY }}, {{ mode: TRAM }}] }}
        }}
        first: 3
      ) {{
        edges {{
          node {{
            legs {{
              mode
              distance
              duration
              from {{ name lat lon }}
              to {{ name lat lon }}
              route {{ gtfsId shortName longName agency {{ gtfsId name }} }}
            }}
            fare {{ regular {{ cents }} }}
          }}
        }}
      }}
    }}
    """


def _nome_linha(leg):
    rota = leg.get("route") or {}
    curto = (rota.get("shortName") or "").strip()
    longo = (rota.get("longName") or "").strip()
    modo = (leg.get("mode") or "TRANSPORTE").replace("_", " ").title()
    if curto and longo:
        return f"{modo} {curto} — {longo}"
    return f"{modo} {curto or longo}".strip()


def _codigo_linha(leg: dict) -> str:
    """Extrai código curto da linha (shortName ou gtfsId)."""
    rota = leg.get("route") or {}
    for k in ("shortName", "gtfsId", "longName"):
        v = (rota.get(k) or "").strip()
        if v:
            # gtfsId vem como "agency:123" — pega sufixo
            if ":" in v and k == "gtfsId":
                v = v.split(":")[-1].strip()
            return v
    return (leg.get("linha") or "").strip()


def _agencia_leg(leg: dict) -> dict:
    """Retorna dict agency normalizado { gtfsId, name } ou vazio."""
    rota = leg.get("route") or {}
    agency = rota.get("agency") or {}
    return {
        "gtfsId": (agency.get("gtfsId") or "").strip(),
        "name": (agency.get("name") or "").strip(),
    }


def _enriquecer_leg(leg: dict) -> dict:
    """Enriquece leg com campos canônicos para fare_engine (não muta original)."""
    enriched = dict(leg)
    agencia = _agencia_leg(leg)
    enriched["agency"] = agencia
    enriched["codigo_linha"] = _codigo_linha(leg)
    # garante from/to com lat/lon quando OTP retornar
    for k in ("from", "to"):
        v = enriched.get(k)
        if isinstance(v, dict):
            # normaliza lat/lon como float quando presente
            for coord in ("lat", "lon"):
                if coord in v and v[coord] is not None:
                    try:
                        v[coord] = float(v[coord])
                    except Exception:
                        pass
    # fare por leg não existe no OTP 2.7 — fica no itinerário; preserva se vier do mock
    return enriched


def _extrair_itinerario_otp(payload):
    """Converte a resposta GraphQL do OTP para o contrato do SmartPass (primeiro itinerário)."""
    todos = _extrair_todos_itinerarios_otp(payload)
    if not todos:
        raise RuntimeError("OTP não encontrou itinerários de transporte para este trajeto.")
    primeiro = todos[0]
    # compat: retorna contrato legado — linhas mantidas para retrocompatibilidade
    linhas = [
        {
            "linha": _nome_linha(leg),
            "valor_unitario": round(VT_TARIFA_PADRAO, 2),
            "quantidade_dia": 2,
            "codigo_linha": _codigo_linha(leg),
            "operadora": _agencia_leg(leg).get("name") or "—",
        }
        for leg in primeiro["legs"]
        if leg.get("route")
    ]
    return {
        "linhas": linhas,
        "legs": primeiro["legs"],
        "legs_transito": [leg for leg in primeiro["legs"] if leg.get("route")],
        "distancia_km": primeiro["distancia_km"],
        "resumo_trajeto": primeiro["resumo_trajeto"],
        "caminhada_km": primeiro["caminhada_km"],
        "baldeacoes": primeiro["baldeacoes"],
        "duracao_min": primeiro["duracao_min"],
        "fare_cents": primeiro.get("fare_cents"),
    }


def _extrair_todos_itinerarios_otp(payload):
    """Converte payload OTP para lista de itinerários enriquecidos (até 3)."""
    erros = payload.get("errors") or []
    if erros:
        raise RuntimeError(erros[0].get("message", "OTP rejeitou a consulta."))

    edges = payload.get("data", {}).get("planConnection", {}).get("edges", [])
    if not edges:
        raise RuntimeError("OTP não encontrou itinerários de transporte para este trajeto.")

    itinerarios = []
    for edge in edges:
        node = edge.get("node", {})
        legs_raw = node.get("legs", [])
        # enriquece legs
        legs = [_enriquecer_leg(leg) for leg in legs_raw]
        legs_transito = [leg for leg in legs if leg.get("route")]
        if not legs_transito:
            continue

        # fare do itinerário quando grafo foi buildado com fare_attributes.txt
        fare_cents = None
        fare = node.get("fare") or {}
        regular = fare.get("regular") if isinstance(fare, dict) else None
        if isinstance(regular, dict) and "cents" in regular:
            try:
                fare_cents = int(regular["cents"])
            except Exception:
                fare_cents = None

        linhas = [
            {
                "linha": _nome_linha(leg),
                "valor_unitario": round(VT_TARIFA_PADRAO, 2),
                "quantidade_dia": 2,
                "codigo_linha": _codigo_linha(leg),
                "operadora": _agencia_leg(leg).get("name") or "—",
            }
            for leg in legs_transito
        ]
        distancia_km = sum(float(leg.get("distance") or 0) for leg in legs) / 1000
        caminhada_km = sum(float(leg.get("distance") or 0) for leg in legs if str(leg.get("mode", "")).upper() == "WALK") / 1000
        # duração: tenta somar duration/duracao se existir, senão estima 18 km/h + 6min por baldeação
        duracao_min = 0
        for leg in legs:
            d = leg.get("duration") or leg.get("duracao") or leg.get("duration_min")
            if d is not None:
                try:
                    duracao_min += int(round(float(d) / 60)) if float(d) > 100 else int(round(float(d)))
                    continue
                except Exception:
                    pass
        if duracao_min == 0:
            try:
                duracao_min = int(round((distancia_km / 18.0) * 60 + max(len(legs_transito) - 1, 0) * 6))
            except Exception:
                duracao_min = 30
        duracao_min = max(duracao_min, 5)

        descricao = [
            f"{_nome_linha(leg)} ({(leg.get('from') or {}).get('name', 'origem')} → {(leg.get('to') or {}).get('name', 'destino')})"
            for leg in legs_transito
        ]
        baldeacoes = max(len(legs_transito) - 1, 0)
        resumo = "; ".join(descricao)
        if baldeacoes:
            resumo += f". {baldeacoes} baldeação(ões) sugerida(s)."

        itinerarios.append(
            {
                "legs": legs,
                "legs_transito": legs_transito,
                "linhas": linhas,
                "distancia_km": round(distancia_km, 2),
                "caminhada_km": round(caminhada_km, 2),
                "baldeacoes": baldeacoes,
                "duracao_min": duracao_min,
                "duracao_total_min": duracao_min,
                "resumo_trajeto": resumo,
                "fare_cents": fare_cents,
            }
        )

    if not itinerarios:
        raise RuntimeError("OTP retornou somente percurso a pé.")
    return itinerarios


@st.cache_data(ttl=600, show_spinner=False)
def resolver_itinerario_com_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Obtém itinerários reais dos feeds GTFS carregados no OTP local. Cache 10min."""
    response = requests.post(
        OTP_GRAPHQL_URL,
        json={"query": _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon)},
        timeout=10,
    )
    response.raise_for_status()
    return _extrair_itinerario_otp(response.json())


@st.cache_data(ttl=600, show_spinner=False)
def resolver_todos_itinerarios_com_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Obtém até 3 itinerários OTP para comparativo econômica vs rápida. Cache 10min."""
    response = requests.post(
        OTP_GRAPHQL_URL,
        json={"query": _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon)},
        timeout=10,
    )
    response.raise_for_status()
    return _extrair_todos_itinerarios_otp(response.json())


def estimar_itinerario_fallback(distancia_km: float):
    """Mantém o cálculo disponível quando o roteador local está indisponível."""
    return {
        "linhas": [
            {"linha": "Estimativa: transporte público urbano (validar com colaborador)", "valor_unitario": 5.00, "quantidade_dia": 2}
        ],
        "distancia_km": round(max(distancia_km, 0.1), 2),
        "resumo_trajeto": "OpenTripPlanner indisponível ou sem GTFS aplicável. Estimativa provisória para validação manual pelo time de Admissão.",
    }


def consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem="", endereco_destino=""):
    """Compatibilidade com o serviço anterior, agora usando OTP como fonte primária."""
    try:
        resultado = resolver_itinerario_com_otp(origem_lat, origem_lon, destino_lat, destino_lon)
        return {"sucesso": True, "fonte": "OpenTripPlanner (GTFS local)", **resultado}
    except (requests.RequestException, requests.Timeout, requests.ConnectionError, ValueError, TypeError, RuntimeError) as exc:
        return {"sucesso": False, "fonte": "Estimativa de contingência", "erro": str(exc), "detalhes": []}


def consultar_todos_itinerarios_oficial(origem_lat, origem_lon, destino_lat, destino_lon):
    """Retorna até 3 itinerários OTP para motor de economicidade; fallback em lista vazia."""
    try:
        itinerarios = resolver_todos_itinerarios_com_otp(origem_lat, origem_lon, destino_lat, destino_lon)
        return {"sucesso": True, "fonte": "OpenTripPlanner (GTFS local)", "itinerarios": itinerarios}
    except (requests.RequestException, requests.Timeout, requests.ConnectionError, ValueError, TypeError, RuntimeError) as exc:
        return {"sucesso": False, "fonte": "Estimativa de contingência", "erro": str(exc), "itinerarios": []}
