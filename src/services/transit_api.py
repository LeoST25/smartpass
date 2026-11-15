"""Roteamento de transporte público via OpenTripPlanner (OTP).

Extração rica por leg: mode, distance, duration, from{ name lat lon }, to{ name lat lon },
route{ gtfsId shortName longName agency{ gtfsId name } } e legGeometry{ points }.
A geometria decodificada (Google Encoded Polyline) é exposta em ``leg["pontos"]``
como lista de tuplas ``(lat, lon)`` para renderização cartográfica por modal.
A tarifa NÃO é consultada no OTP: o campo ``fare`` do schema GraphQL 2.x é opcional
e, quando ausente no grafo, aborta a query com ``Field 'fare' in type 'Itinerary'
is undefined``. O cálculo tarifário é responsabilidade exclusiva do ``fare_engine``.

Timeout 10s conforme gis-routing-otp/SKILL.md e fallback LGPD stateless.
Erros técnicos são registrados apenas no logging do servidor; o usuário recebe
uma mensagem genérica e acionável.
"""

import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OTP_GRAPHQL_URL = os.getenv("OTP_GRAPHQL_URL", "http://localhost:8080/otp/gtfs/v1")
VT_TARIFA_PADRAO = float(os.getenv("VT_TARIFA_PADRAO", "5.00"))
TIMEZONE_RMSP = ZoneInfo("America/Sao_Paulo")

# Bounding box da RMSP (gis-routing-otp/SKILL.md) usado para descartar
# geometria fora da área coberta pelos feeds GTFS locais.
RMSN_LAT_MIN, RMSP_LAT_MAX = -24.1, -23.1
RMSP_LON_MIN, RMSP_LON_MAX = -47.2, -45.7


def _coordenada_na_rmsp(lat: float, lon: float) -> bool:
    """Indica se uma coordenada (WGS84) está dentro do bbox da RMSP.

    Args:
        lat: Latitude decimal.
        lon: Longitude decimal.

    Returns:
        bool: ``True`` quando latitude e longitude estão dentro dos limites.
    """
    try:
        return (
            RMSN_LAT_MIN <= float(lat) <= RMSP_LAT_MAX
            and RMSP_LON_MIN <= float(lon) <= RMSP_LON_MAX
        )
    except (TypeError, ValueError):
        return False


def decodificar_polyline(polyline: str | None) -> list[tuple[float, float]]:
    """Decodifica uma Google Encoded Polyline em coordenadas (lat, lon).

    Implementação pura (sem dependências externas) do algoritmo oficial: a string
    é lida em blocos de 5 caracteres, cada bloco representa um valor inteiro
    com deslocamento de 5 bits e sinal em zigzag; latitude e longitude são
    acumuladas incrementalmente.

    Args:
        polyline: String codificada no formato Google Encoded Polyline.
            ``None`` ou string vazia retornam lista vazia.

    Returns:
        list[tuple[float, float]]: Lista de pontos ``(lat, lon)`` na ordem do
        traçado. Lista vazia quando não há pontos decodificáveis.

    Raises:
        ValueError: Se a string contiver caracteres fora do alfabeto válido
            (``ASCII 63..126``), indicando payload corrompido.
    """
    if not polyline:
        return []

    pontos: list[tuple[float, float]] = []
    lat = 0.0
    lon = 0.0
    indice = 0
    tamanho = len(polyline)

    while indice < tamanho:
        valores: list[int] = []
        for _ in range(2):  # latitude e longitude, nesta ordem
            resultado = 0
            deslocamento = 0
            while True:
                if indice >= tamanho:
                    raise ValueError("Polyline truncada: bloco incompleto.")
                byte = ord(polyline[indice]) - 63
                indice += 1
                if byte < 0 or byte > 63:
                    raise ValueError(f"Polyline inválida: byte {byte} fora do intervalo.")
                resultado |= (byte & 0x1F) << deslocamento
                deslocamento += 5
                if byte < 0x20:
                    break
            valores.append(~(resultado >> 1) if resultado & 1 else (resultado >> 1))

        lat += valores[0] / 100000.0
        lon += valores[1] / 100000.0
        pontos.append((lat, lon))

    return pontos


def _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Monta a consulta GraphQL compatível com OTP 2.x — apenas pernas e rotas.

    O campo ``fare`` é intencionalmente omitido: o schema do OTP 2.x não garante
    esse campo no tipo ``Itinerary`` quando o grafo não é buildado com
    ``fare_attributes.txt``, e a query inteira falha. A tarifa é resolvida
    exclusivamente em ``fare_engine.py`` (GTFS > catálogo RMSP > base).
    """
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
              legGeometry {{ points }}
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
    """Enriquece leg com campos canônicos para fare_engine e mapa (não muta original).

    Adiciona ``agency``, ``codigo_linha``, normaliza ``from``/``to`` para float e
    decodifica ``legGeometry.points`` em ``pontos`` (lista de ``(lat, lon)``).

    Args:
        leg: Leg crua devolvida pelo OTP GraphQL.

    Returns:
        dict: Cópia enriquecida da leg. ``pontos`` fica vazio e
        ``geometria_fallback`` ``True`` quando não há polyline utilizável.
    """
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
    # fare por leg não existe no OTP 2.x sem grafo tarifário — cálculo fica no fare_engine

    # Geometria real da perna: decodifica a polyline do OTP e descarta pontos
    # fora do bbox da RMSP (garantindo traçado auditável na área atendida).
    geometry = leg.get("legGeometry") or {}
    encoded = geometry.get("points") if isinstance(geometry, dict) else None
    pontos: list[tuple[float, float]] = []
    descartados = 0
    if encoded:
        try:
            decodificados = decodificar_polyline(encoded)
        except ValueError:
            logger.warning("OTP retornou legGeometry inválida; usando fallback de geometria.")
            decodificados = []
        for lat, lon in decodificados:
            if _coordenada_na_rmsp(lat, lon):
                pontos.append((lat, lon))
            else:
                descartados += 1
        if descartados:
            logger.warning(
                "Descartados %d ponto(s) de legGeometry fora do bbox da RMSP.", descartados
            )
    enriched["pontos"] = pontos
    enriched["geometria_fallback"] = not pontos
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
        "geometria_fallback": primeiro.get("geometria_fallback", True),
    }


def _extrair_todos_itinerarios_otp(payload):
    """Converte payload OTP para lista de itinerários enriquecidos (até 3)."""
    erros = payload.get("errors") or []
    if erros:
        detalhes = "; ".join(
            str(erro.get("message", erro)) if isinstance(erro, dict) else str(erro)
            for erro in erros
        )
        logger.error("OTP GraphQL retornou erros: %s", detalhes)
        raise RuntimeError("O serviço de rotas rejeitou a consulta.")

    edges = payload.get("data", {}).get("planConnection", {}).get("edges", [])
    if not edges:
        logger.warning("OTP GraphQL não retornou itinerários para o trajeto informado.")
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
                "geometria_fallback": all(leg.get("geometria_fallback", True) for leg in legs),
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
        "resumo_trajeto": "Estimativa provisória de transporte público para validação manual pelo time de Admissão.",
    }


def consultar_linhas_transporte_oficial(origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem="", endereco_destino=""):
    """Compatibilidade com o serviço anterior, agora usando OTP como fonte primária.

    Em falha, o detalhe técnico vai apenas para o logging do servidor; o contrato
    devolve uma mensagem genérica e acionável para a interface.
    """
    try:
        resultado = resolver_itinerario_com_otp(origem_lat, origem_lon, destino_lat, destino_lon)
        return {"sucesso": True, "fonte": "OpenTripPlanner (GTFS local)", **resultado}
    except (requests.RequestException, requests.Timeout, requests.ConnectionError, ValueError, TypeError, RuntimeError) as exc:
        logger.warning(
            "Falha na consulta OTP (%.5f,%.5f -> %.5f,%.5f): %s",
            origem_lat,
            origem_lon,
            destino_lat,
            destino_lon,
            exc,
            exc_info=True,
        )
        return {
            "sucesso": False,
            "fonte": "Estimativa de contingência",
            "erro": "Não foi possível obter a rota oficial agora. Exibindo estimativa provisória para validação manual.",
            "detalhes": [],
        }


def consultar_todos_itinerarios_oficial(origem_lat, origem_lon, destino_lat, destino_lon):
    """Retorna até 3 itinerários OTP para motor de economicidade; fallback em lista vazia."""
    try:
        itinerarios = resolver_todos_itinerarios_com_otp(origem_lat, origem_lon, destino_lat, destino_lon)
        return {"sucesso": True, "fonte": "OpenTripPlanner (GTFS local)", "itinerarios": itinerarios}
    except (requests.RequestException, requests.Timeout, requests.ConnectionError, ValueError, TypeError, RuntimeError) as exc:
        logger.warning(
            "Falha ao consultar itinerários OTP (%.5f,%.5f -> %.5f,%.5f): %s",
            origem_lat,
            origem_lon,
            destino_lat,
            destino_lon,
            exc,
            exc_info=True,
        )
        return {
            "sucesso": False,
            "fonte": "Estimativa de contingência",
            "erro": "Não foi possível obter as rotas oficiais agora.",
            "itinerarios": [],
        }
