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
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

from src.services.cache import st_cache_data
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


def _normalizar_instante(valor) -> str | None:
    """Normaliza um instante (epoch millis ou ISO) para ``HH:MM`` em America/Sao_Paulo.

    O scalar ``DateTime`` do OTP GraphQL pode serializar como epoch em milissegundos
    (int/float) ou como string ISO-8601; ambos são tratados de forma defensiva.

    Args:
        valor: ``startTime``/``endTime`` de uma leg (epoch millis ou ISO string).

    Returns:
        str | None: Horário local ``HH:MM`` ou ``None`` quando indisponível.
    """
    if valor is None:
        return None
    try:
        if isinstance(valor, (int, float)):
            return datetime.fromtimestamp(float(valor) / 1000, TIMEZONE_RMSP).strftime("%H:%M")
        if isinstance(valor, str) and valor.strip():
            s = valor.strip()
            # tenta ISO com offset; senão devolve como veio
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=TIMEZONE_RMSP)
                return dt.astimezone(TIMEZONE_RMSP).strftime("%H:%M")
            except ValueError:
                return s
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def _data_util_referencia(uf: str = "SP", municipio: str = "São Paulo", data_base: date | None = None) -> str:
    """Retorna a data do próximo dia útil (seg–sex, sem feriados) em ``YYYY-MM-DD``.

    Reutiliza ``calendar_engine.listar_feriados`` para não divergir do ``dias_uteis``
    do cálculo mensal: fins de semana **e** feriados (nacionais + municipais SP) são
    pulados, garantindo que a consulta OTP caia num dia com serviço real.

    Args:
        uf: UF para resolução de feriados municipais (default ``"SP"``).
        municipio: Município para resolução de feriados (default ``"São Paulo"``).
        data_base: Data de referência opcional (default: hoje em America/Sao_Paulo).

    Returns:
        str: Data ``YYYY-MM-DD`` do primeiro dia útil a partir de ``data_base``.
    """
    from src.services.calendar_engine import listar_feriados

    d = data_base or datetime.now(TIMEZONE_RMSP).date()
    feriados_cache: dict[int, set[date]] = {}

    for _ in range(30):  # teto de segurança
        if d.weekday() >= 5:  # sábado/domingo
            d += timedelta(days=1)
            continue
        if d.year not in feriados_cache:
            res = listar_feriados(d.year, uf, municipio)
            feriados_cache[d.year] = {f["data"] for f in res.get("feriados", [])}
        if d in feriados_cache[d.year]:
            d += timedelta(days=1)
            continue
        return d.isoformat()
    return d.isoformat()


def _montar_data_hora(data_ref: str, horario: str) -> str:
    """Combina data ``YYYY-MM-DD`` + ``HH:MM`` em ISO tz-aware America/Sao_Paulo.

    Args:
        data_ref: Data no formato ``YYYY-MM-DD``.
        horario: Horário no formato ``HH:MM`` (validado no schema).

    Returns:
        str: ``YYYY-MM-DDTHH:MM:00-03:00``.
    """
    hh, mm = horario.split(":")
    dt = datetime.combine(
        date.fromisoformat(data_ref),
        time(hour=int(hh), minute=int(mm)),
        tzinfo=TIMEZONE_RMSP,
    )
    return dt.isoformat(timespec="seconds")


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


def _montar_consulta_otp(
    origem_lat,
    origem_lon,
    destino_lat,
    destino_lon,
    data_hora: str | None = None,
    arrive_by: bool = False,
):
    """Monta a consulta GraphQL compatível com OTP 2.x — apenas pernas e rotas.

    O campo ``fare`` é intencionalmente omitido: o schema do OTP 2.x não garante
    esse campo no tipo ``Itinerary`` quando o grafo não é buildado com
    ``fare_attributes.txt``, e a query inteira falha. A tarifa é resolvida
    exclusivamente em ``fare_engine.py`` (GTFS > catálogo RMSP > base).

    Args:
        origem_lat/origem_lon/destino_lat/destino_lon: Coordenadas WGS84.
        data_hora: ISO tz-aware (default: agora em America/Sao_Paulo).
        arrive_by: ``True`` monta ``latestArrival`` (chegar até o horário — ida);
            ``False`` monta ``earliestDeparture`` (sair a partir do horário — volta).

    Returns:
        str: Documento GraphQL.
    """
    if data_hora is None:
        data_hora = datetime.now(TIMEZONE_RMSP).isoformat(timespec="minutes")
    campo_data = "latestArrival" if arrive_by else "earliestDeparture"
    return f"""
    {{
      planConnection(
        origin: {{ location: {{ coordinate: {{ latitude: {origem_lat}, longitude: {origem_lon} }} }} }}
        destination: {{ location: {{ coordinate: {{ latitude: {destino_lat}, longitude: {destino_lon} }} }} }}
        dateTime: {{ {campo_data}: \"{data_hora}\" }}
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
              startTime
              endTime
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


def _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Compat: monta a consulta GraphQL com partida imediata (``earliestDeparture``)."""
    return _montar_consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon)


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
    enriched["horario_inicio"] = _normalizar_instante(leg.get("startTime"))
    enriched["horario_fim"] = _normalizar_instante(leg.get("endTime"))
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

        horario_partida = (legs[0].get("horario_inicio") if legs else None)
        horario_chegada = (legs[-1].get("horario_fim") if legs else None)

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
                "horario_partida": horario_partida,
                "horario_chegada": horario_chegada,
            }
        )

    if not itinerarios:
        raise RuntimeError("OTP retornou somente percurso a pé.")
    return itinerarios


@st_cache_data(ttl=600, show_spinner=False)
def resolver_itinerario_com_otp(origem_lat, origem_lon, destino_lat, destino_lon):
    """Obtém itinerários reais dos feeds GTFS carregados no OTP local. Cache 10min."""
    response = requests.post(
        OTP_GRAPHQL_URL,
        json={"query": _consulta_otp(origem_lat, origem_lon, destino_lat, destino_lon)},
        timeout=10,
    )
    response.raise_for_status()
    return _extrair_itinerario_otp(response.json())


@st_cache_data(ttl=600, show_spinner=False)
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


# -----------------------------------------------------------------------------
# Ida + Volta por horário real de jornada (Roteirizador Individual)
# -----------------------------------------------------------------------------
@st_cache_data(ttl=600, show_spinner=False)
def resolver_itinerarios_ida_volta(
    origem_lat,
    origem_lon,
    destino_lat,
    destino_lon,
    horario_entrada,
    horario_saida,
    data_referencia,
):
    """Obtém itinerários de ida e de volta via OTP usando horários reais de jornada.

    Executa **duas** consultas GraphQL sobre a mesma data útil de referência:
    - **Ida** (chegar até ``horario_entrada``): ``arrive_by=True`` → ``latestArrival``.
    - **Volta** (sair a partir de ``horario_saida``): ``arrive_by=False`` → ``earliestDeparture``.

    Cache 10min (TTL canônico de roteamento); a chave inclui ``data_referencia`` e
    horários para evitar colisão entre jornadas distintas.

    Args:
        origem_lat/origem_lon/destino_lat/destino_lon: Coordenadas WGS84.
        horario_entrada: ``"HH:MM"`` de chegada no trabalho.
        horario_saida: ``"HH:MM"`` de saída do trabalho.
        data_referencia: ``"YYYY-MM-DD"`` de um dia útil.

    Returns:
        dict: ``{"ida": list[dict], "volta": list[dict]}`` com até 3 itinerários cada.
    """
    data_hora_ida = _montar_data_hora(data_referencia, horario_entrada)
    data_hora_volta = _montar_data_hora(data_referencia, horario_saida)

    def _consultar(dh, arrive_by):
        resp = requests.post(
            OTP_GRAPHQL_URL,
            json={
                "query": _montar_consulta_otp(
                    origem_lat, origem_lon, destino_lat, destino_lon, data_hora=dh, arrive_by=arrive_by
                )
            },
            timeout=10,
        )
        resp.raise_for_status()
        return _extrair_todos_itinerarios_otp(resp.json())

    return {
        "ida": _consultar(data_hora_ida, arrive_by=True),
        "volta": _consultar(data_hora_volta, arrive_by=False),
    }


def _itinerario_fallback_sintetico(
    origem_lat,
    origem_lon,
    destino_lat,
    destino_lon,
    endereco_origem,
    endereco_destino,
):
    """Itinerário sintético de contingência (OTP offline) com legs enriquecidas.

    Garante que o ranqueador de opções não retorne ``sucesso=False`` em modo offline:
    produz um itinerário com uma única leg de ônibus entre os extremos reais,
    sem geometria (``geometria_fallback=True``), sinalizando estimativa provisória.

    Returns:
        dict: Itinerário no mesmo contrato de ``_extrair_todos_itinerarios_otp``.
    """
    leg = {
        "mode": "BUS",
        "linha": "Transporte público (estimativa)",
        "route": {"shortName": "Estimativa"},
        "distance": 1000,
        "duration": 1800,
        "from": {"name": endereco_origem, "lat": float(origem_lat), "lon": float(origem_lon)},
        "to": {"name": endereco_destino, "lat": float(destino_lat), "lon": float(destino_lon)},
        "pontos": [],
        "geometria_fallback": True,
        "codigo_linha": "",
        "agency": {"gtfsId": "", "name": ""},
    }
    return {
        "legs": [leg],
        "legs_transito": [leg],
        "linhas": [{"linha": "Transporte público (estimativa)", "valor_unitario": round(VT_TARIFA_PADRAO, 2), "quantidade_dia": 2, "codigo_linha": "", "operadora": "—"}],
        "distancia_km": 10.0,
        "caminhada_km": 0.0,
        "baldeacoes": 0,
        "duracao_min": 30,
        "duracao_total_min": 30,
        "resumo_trajeto": "Estimativa provisória de transporte público para validação manual.",
        "geometria_fallback": True,
        "horario_partida": None,
        "horario_chegada": None,
    }


def consultar_itinerarios_ida_volta_oficial(
    origem_lat,
    origem_lon,
    destino_lat,
    destino_lon,
    horario_entrada,
    horario_saida,
    endereco_origem="",
    endereco_destino="",
    uf="SP",
    municipio="São Paulo",
):
    """Consulta OTP para ida+volta por horário real, com fallback de contingência.

    Erro técnico fica apenas no logging do servidor; o usuário recebe mensagem
    genérica e o fluxo cai em estimativa provisória (LGPD stateless).

    Returns:
        dict: ``{"sucesso": bool, "ida": list, "volta": list, "fonte": str,
        "data_referencia": str, "erro": str|None}``.
    """
    data_referencia = _data_util_referencia(uf=uf, municipio=municipio)
    try:
        resultado = resolver_itinerarios_ida_volta(
            origem_lat, origem_lon, destino_lat, destino_lon,
            horario_entrada, horario_saida, data_referencia,
        )
        return {
            "sucesso": True,
            "fonte": "OpenTripPlanner (GTFS local)",
            "data_referencia": data_referencia,
            "ida": resultado["ida"],
            "volta": resultado["volta"],
            "erro": None,
        }
    except (requests.RequestException, requests.Timeout, requests.ConnectionError, ValueError, TypeError, RuntimeError) as exc:
        logger.warning(
            "Falha na consulta OTP ida/volta (%.5f,%.5f -> %.5f,%.5f): %s",
            origem_lat, origem_lon, destino_lat, destino_lon, exc, exc_info=True,
        )
        fallback = _itinerario_fallback_sintetico(
            origem_lat, origem_lon, destino_lat, destino_lon, endereco_origem, endereco_destino
        )
        return {
            "sucesso": False,
            "fonte": "Estimativa de contingência",
            "data_referencia": data_referencia,
            "ida": [fallback],
            "volta": [fallback],
            "erro": "Não foi possível obter a rota oficial agora. Exibindo estimativa provisória para validação manual.",
        }
