"""Roteamento de transporte público via OpenTripPlanner (OTP)."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

OTP_GRAPHQL_URL = os.getenv("OTP_GRAPHQL_URL", "http://localhost:8080/otp/gtfs/v1")
VT_TARIFA_PADRAO = float(os.getenv("VT_TARIFA_PADRAO", "5.00"))
TIMEZONE_RMSP = ZoneInfo("America/Sao_Paulo")


def _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Monta a consulta GraphQL compatível com OTP 2.7+."""
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
              from {{ name }}
              to {{ name }}
              route {{ shortName longName }}
            }}
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


def _extrair_itinerario_otp(payload):
    """Converte a resposta GraphQL do OTP para o contrato do SmartPass."""
    erros = payload.get("errors") or []
    if erros:
        raise RuntimeError(erros[0].get("message", "OTP rejeitou a consulta."))

    edges = payload.get("data", {}).get("planConnection", {}).get("edges", [])
    if not edges:
        raise RuntimeError("OTP não encontrou itinerários de transporte para este trajeto.")

    legs = edges[0].get("node", {}).get("legs", [])
    legs_transito = [leg for leg in legs if leg.get("route")]
    if not legs_transito:
        raise RuntimeError("OTP retornou somente percurso a pé.")

    linhas = [
        {
            "linha": _nome_linha(leg),
            "valor_unitario": round(VT_TARIFA_PADRAO, 2),
            "quantidade_dia": 2,
        }
        for leg in legs_transito
    ]
    distancia_km = sum(float(leg.get("distance") or 0) for leg in legs) / 1000
    descricao = [
        f"{_nome_linha(leg)} ({(leg.get('from') or {}).get('name', 'origem')} → {(leg.get('to') or {}).get('name', 'destino')})"
        for leg in legs_transito
    ]
    baldeacoes = max(len(legs_transito) - 1, 0)
    resumo = "; ".join(descricao)
    if baldeacoes:
        resumo += f". {baldeacoes} baldeação(ões) sugerida(s)."

    return {"linhas": linhas, "distancia_km": round(distancia_km, 2), "resumo_trajeto": resumo}


def resolver_itinerario_com_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Obtém itinerários reais dos feeds GTFS carregados no OTP local."""
    response = requests.post(
        OTP_GRAPHQL_URL,
        json={"query": _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon)},
        timeout=20,
    )
    response.raise_for_status()
    return _extrair_itinerario_otp(response.json())


def estimar_itinerario_fallback(distancia_km: float):
    """Mantém o cálculo disponível quando o roteador local está indisponível."""
    return {
        "linhas": [{"linha": "Estimativa: transporte público urbano (validar com colaborador)", "valor_unitario": 5.00, "quantidade_dia": 2}],
        "distancia_km": round(max(distancia_km, 0.1), 2),
        "resumo_trajeto": "OpenTripPlanner indisponível ou sem GTFS aplicável. Estimativa provisória para validação manual pelo time de Admissão.",
    }


def consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem="", endereco_destino=""):
    """Compatibilidade com o serviço anterior, agora usando OTP como fonte primária."""
    try:
        resultado = resolver_itinerario_com_otp(origem_lat, origem_lon, destino_lat, destino_lon)
        return {"sucesso": True, "fonte": "OpenTripPlanner (GTFS local)", **resultado}
    except (requests.RequestException, ValueError, TypeError, RuntimeError) as exc:
        return {"sucesso": False, "fonte": "Estimativa de contingência", "erro": str(exc), "detalhes": []}
