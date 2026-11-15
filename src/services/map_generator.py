"""Serviço de cartografia urbana para o SmartPass.

Responsabilidades:
    * Decodificar a geometria real de cada perna da rota (Google Encoded Polyline);
    * Renderizar o mapa interativo (Folium) com tiles urbanos, polilinhas por
      modal e marcadores de origem/destino/baldeação;
    * Renderizar a imagem estática (PNG em ``io.BytesIO``) usada no relatório PDF,
      com tiles urbanos e fallback offline que nunca quebra a geração do PDF.

Regras aplicadas (AGENTS.md / .clinerules):
    * Toda chamada externa tem ``timeout`` explícito (máx. 10s) e fallback;
    * Zero persistência em disco — PNG e PDF ficam somente em memória (LGPD);
    * Lógica de negócio isolada neste serviço; ``src/app.py`` apenas consome.

Nota de contrato: por ser um *renderer* visual, as funções públicas deste módulo
retornam artefatos (``folium.Map`` / ``io.BytesIO``) em vez do dicionário
``{"sucesso": bool}``. O contrato de sucesso da camada de roteamento permanece
em ``transit_api.py`` e ``routing.py``.
"""

import io
import logging
import math

import requests

from src.services.cache import st_cache_data
import matplotlib

matplotlib.use("Agg")  # Backend sem interface gráfica para servidores
import matplotlib.pyplot as plt

logger = logging.getLogger(__name__)

# --- Paleta de modais (consistente entre mapa interativo e PDF) -------------
CORES_MODAL = {
    "WALK": "#9CA3AF",     # cinza — caminhada
    "BUS": "#2563EB",      # azul — ônibus
    "SUBWAY": "#7C3AED",   # roxo — metrô
    "RAIL": "#DC2626",     # vermelho — trem
    "TRAM": "#059669",     # verde — bonde
    "FERRY": "#0891B2",    # ciano — balsa
    "BICYCLE": "#65A30D",  # verde-limão — bicicleta
    "CAR": "#475569",      # cinza-escuro — carro
}
COR_PADRAO = "#1E3A8A"

# --- Tiles urbanos ---------------------------------------------------------
# NOTA: CartoDB Positron passou a exigir API key (retorna o tile
# "API KEY REQUIRED"), por isso usamos OpenStreetMap como base e Esri
# Light/Street Map como camadas alternativas — todos sem chave e exibindo
# nomes de ruas, bairros e estabelecimentos.
TILE_OSM = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_ESRI_LIGHT = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/"
    "World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"
)
TILE_ESRI_STREET = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Street_Map/MapServer/tile/{z}/{y}/{x}"
)
TILE_OSM_SUBDOMINIO = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
ATRIBUICAO_OSM = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
ATRIBUICAO_ESRI = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; Esri'

# Limites do bbox da RMSP (gis-routing-otp/SKILL.md)
RMSN_LAT_MIN, RMSP_LAT_MAX = -24.1, -23.1
RMSP_LON_MIN, RMSP_LON_MAX = -47.2, -45.7

# Performance: acima deste volume a polyline é simplificada (pdf-map-reporting/SKILL.md)
MAX_PONTOS_POLYLINE = 800
EPSILON_SIMPLIFICACAO = 0.0001  # ~11 m

# Altura fixa do mapa interativo (px) — usada também no CSS injetado no Folium.
ALTURA_MAPA_PX = 480

TIMEOUT_TILES = 5
TIMEOUT_OSRM = 5


# ---------------------------------------------------------------------------
# Utilidades geográficas
# ---------------------------------------------------------------------------
def _coordenada_valida(lat, lon) -> bool:
    """Verifica se o par (lat, lon) é numericamente utilizável e está na RMSP."""
    try:
        lat_f = float(lat)
        lon_f = float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat_f) or math.isnan(lon_f):
        return False
    return (
        RMSN_LAT_MIN <= lat_f <= RMSP_LAT_MAX
        and RMSP_LON_MIN <= lon_f <= RMSP_LON_MAX
    )


def _simplificar_polyline(pontos: list, epsilon: float = EPSILON_SIMPLIFICACAO) -> list:
    """Simplifica uma polyline com o algoritmo Douglas-Peucker.

    Args:
        pontos: Lista de tuplas ``(lat, lon)`` na ordem do traçado.
        epsilon: Tolerância em graus (~11 m por padrão).

    Returns:
        list: Polyline simplificada. Se já estiver abaixo do limite de pontos
        ou tiver menos de 3 pontos, é devolvida sem alteração.
    """
    if not pontos or len(pontos) <= 2:
        return list(pontos or [])
    if len(pontos) <= MAX_PONTOS_POLYLINE:
        return list(pontos)

    def _distancia_perpendicular(ponto, inicio, fim) -> float:
        """Distância perpendicular de ``ponto`` à reta ``inicio``-``fim``."""
        (x0, y0), (x1, y1), (xp, yp) = inicio, fim, ponto
        dx, dy = x1 - x0, y1 - y0
        if dx == 0 and dy == 0:
            return math.hypot(xp - x0, yp - y0)
        return abs(dy * xp - dx * yp + x1 * y0 - y1 * x0) / math.hypot(dx, dy)

    def _douglas_peucker(pontos_rec, primeiro, ultimo) -> list[int]:
        """Índices dos pontos a preservar segundo Douglas-Peucker."""
        if ultimo <= primeiro + 1:
            return [primeiro]
        max_dist = 0.0
        indice_max = primeiro
        for i in range(primeiro + 1, ultimo):
            dist = _distancia_perpendicular(
                pontos_rec[i], pontos_rec[primeiro], pontos_rec[ultimo]
            )
            if dist > max_dist:
                max_dist = dist
                indice_max = i
        if max_dist > epsilon:
            return (
                _douglas_peucker(pontos_rec, primeiro, indice_max)[:-1]
                + _douglas_peucker(pontos_rec, indice_max, ultimo)
            )
        return [primeiro, ultimo]

    indices = _douglas_peucker(pontos, 0, len(pontos) - 1)
    simplificada = [pontos[i] for i in indices]
    # Garante os extremos originais (fit_bounds precisa incluir origem/destino).
    if simplificada and simplificada[0] != pontos[0]:
        simplificada.insert(0, pontos[0])
    if simplificada and simplificada[-1] != pontos[-1]:
        simplificada.append(pontos[-1])
    return simplificada


@st_cache_data(ttl=600, show_spinner=False, max_entries=256)
def _buscar_geometria_osrm(origem_lat, origem_lon, destino_lat, destino_lon):
    """Busca geometria da rota no OSRM com fallback para linha reta.

    Args:
        origem_lat: Latitude da origem.
        origem_lon: Longitude da origem.
        destino_lat: Latitude do destino.
        destino_lon: Longitude do destino.

    Returns:
        tuple[tuple[float, float], ...]: Lista de pontos ``(lat, lon)`` do
        traçado rodoviário; linha reta em caso de falha do serviço.
    """
    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{origem_lon},{origem_lat};{destino_lon},{destino_lat}?overview=full&geometries=geojson"
    )
    try:
        resp = requests.get(url, timeout=TIMEOUT_OSRM)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "Ok":
            coords = data["routes"][0]["geometry"]["coordinates"]
            pontos = [(float(c[1]), float(c[0])) for c in coords]
            if pontos:
                return pontos
    except (requests.RequestException, KeyError, IndexError, TypeError, ValueError):
        logger.warning("OSRM indisponível para fallback de geometria.", exc_info=True)
    return [(float(origem_lat), float(origem_lon)), (float(destino_lat), float(destino_lon))]


# ---------------------------------------------------------------------------
# Preparação das pernas da rota
# ---------------------------------------------------------------------------
def _modo_da_leg(leg: dict) -> str:
    """Retorna o modo normalizado (maiúsculo) de uma perna."""
    return str((leg or {}).get("mode") or "WALK").strip().upper()


def _cor_da_leg(leg: dict) -> str:
    """Retorna a cor do traçado conforme o modal da perna."""
    return CORES_MODAL.get(_modo_da_leg(leg), COR_PADRAO)


def _rotulo_leg(leg: dict) -> str:
    """Texto amigável da perna para tooltip/popup (sem jargão técnico)."""
    modo = _modo_da_leg(leg)
    rota = leg.get("route") or {}
    linha = (rota.get("shortName") or rota.get("longName") or "").strip()
    origem = ((leg.get("from") or {}).get("name") or "").strip()
    destino = ((leg.get("to") or {}).get("name") or "").strip()
    if modo == "WALK":
        return "Caminhada" + (f" · {origem} → {destino}" if origem and destino else "")
    nome = f"{modo.title()} {linha}".strip() if linha else modo.title()
    return nome + (f" · {origem} → {destino}" if origem and destino else "")


def _pontos_da_leg(leg: dict) -> list:
    """Resolve os pontos de uma perna, com fallback para OSRM quando necessário.

    Ordem de preferência:
        1. ``leg["pontos"]`` — geometria real decodificada do OTP;
        2. ``legGeometry.points`` — polyline crua (decodificada sob demanda);
        3. OSRM — traçado rodoviário da perna;
        4. Linha reta entre ``from`` e ``to``.

    Args:
        leg: Perna da rota.

    Returns:
        list: Lista de tuplas ``(lat, lon)`` (pode ser vazia em caso extremo).
    """
    pontos = leg.get("pontos") or []
    if pontos:
        return _simplificar_polyline(pontos)

    # Polyline crua, caso o chamador não tenha enriquecido a perna.
    geometry = leg.get("legGeometry") or {}
    encoded = geometry.get("points") if isinstance(geometry, dict) else None
    if encoded:
        try:
            from src.services.transit_api import decodificar_polyline

            decodificados = [
                (lat, lon)
                for lat, lon in decodificar_polyline(encoded)
                if _coordenada_valida(lat, lon)
            ]
            if decodificados:
                return _simplificar_polyline(decodificados)
        except (ValueError, TypeError) as exc:
            logger.warning("Polyline inválida ao montar o mapa: %s", exc)

    # Fallback OSRM a partir dos extremos da perna.
    origem = leg.get("from") or {}
    destino = leg.get("to") or {}
    if _coordenada_valida(origem.get("lat"), origem.get("lon")) and _coordenada_valida(
        destino.get("lat"), destino.get("lon")
    ):
        return list(
            _buscar_geometria_osrm(
                float(origem["lat"]),
                float(origem["lon"]),
                float(destino["lat"]),
                float(destino["lon"]),
            )
        )
    return []


def _extrair_legs(rota_dados: dict) -> list:
    """Obtém a lista de pernas de uma rota em qualquer formato do contrato.

    Aceita ``{"legs": [...]}``, ``{"legs_transito": [...]}`` ou uma lista direta.

    Args:
        rota_dados: Dados da rota.

    Returns:
        list[dict]: Lista de pernas (pode ser vazia).
    """
    if not rota_dados:
        return []
    if isinstance(rota_dados, list):
        return [leg for leg in rota_dados if isinstance(leg, dict)]
    if not isinstance(rota_dados, dict):
        return []
    legs = rota_dados.get("legs") or rota_dados.get("legs_transito") or []
    return [leg for leg in legs if isinstance(leg, dict)]


def _pontos_de_marcador(leg: dict, extremidade: str):
    """Extrai ``(lat, lon)`` do ponto ``from``/``to`` de uma perna."""
    ponto = leg.get(extremidade) or {}
    lat, lon = ponto.get("lat"), ponto.get("lon")
    if _coordenada_valida(lat, lon):
        return float(lat), float(lon)
    return None


# ---------------------------------------------------------------------------
# Mapa interativo (Folium)
# ---------------------------------------------------------------------------
def gerar_mapa_interativo(
    rota_dados: dict,
    origem_label: str = "Origem",
    destino_label: str = "Destino",
):
    """Monta o mapa urbano interativo da rota (Folium).

    Renderiza tiles urbanos (CartoDB Positron como base, OpenStreetMap
    alternável), a polilinha real de cada perna com cor por modal, marcadores
    de origem (casa), baldeações (paradas) e destino (empresa), e enquadra todo
    o trajeto automaticamente via ``fit_bounds``.

    Args:
        rota_dados: Resultado de roteirização contendo ``legs`` (cada perna com
            ``mode``, ``from``/``to`` e ``pontos`` ou ``legGeometry``).
        origem_label: Rótulo amigável da origem exibido no marcador.
        destino_label: Rótulo amigável do destino exibido no marcador.

    Returns:
        folium.Map | None: Objeto de mapa pronto para renderização, ou ``None``
        se a biblioteca ``folium`` não estiver disponível no ambiente.
    """
    try:
        import folium
    except ImportError:  # pragma: no cover - ambiente sem folium
        logger.warning("folium não instalado — mapa interativo indisponível.")
        return None

    legs = _extrair_legs(rota_dados)

    # Pré-carrega as geometrias (uma única vez por perna) para o fit_bounds.
    geometrias: list[tuple[dict, list]] = []
    todos_os_pontos: list[tuple[float, float]] = []
    for leg in legs:
        pontos = _pontos_da_leg(leg)
        if not pontos:
            continue
        geometrias.append((leg, pontos))
        todos_os_pontos.extend(pontos)

    # Marcadores de origem/destino (extremidades da rota).
    origem_ponto = None
    destino_ponto = None
    if legs:
        origem_ponto = _pontos_de_marcador(legs[0], "from")
        destino_ponto = _pontos_de_marcador(legs[-1], "to")
    if not todos_os_pontos:
        if origem_ponto:
            todos_os_pontos.append(origem_ponto)
        if destino_ponto:
            todos_os_pontos.append(destino_ponto)

    if not todos_os_pontos:
        # Sem nenhuma coordenada utilizável — centro padrão na RMSP.
        centro = [-23.55, -46.63]
        mapa = folium.Map(location=centro, zoom_start=12, tiles=None, control_scale=True)
    else:
        lats = [p[0] for p in todos_os_pontos]
        lons = [p[1] for p in todos_os_pontos]
        centro = [(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2]
        mapa = folium.Map(location=centro, zoom_start=13, tiles=None, control_scale=True)

    # --- Tiles urbanos (base + alternância) --------------------------------
    # OpenStreetMap como base: exibe nomes de ruas, bairros e estabelecimentos.
    folium.TileLayer(
        TILE_OSM_SUBDOMINIO,
        attr=ATRIBUICAO_OSM,
        name="OpenStreetMap",
        overlay=False,
        control=True,
    ).add_to(mapa)
    # Estilo claro (visual próximo ao Google Maps) como camada alternativa.
    folium.TileLayer(
        TILE_ESRI_LIGHT,
        attr=ATRIBUICAO_ESRI,
        name="Mapa claro",
        overlay=False,
        control=True,
    ).add_to(mapa)
    folium.TileLayer(
        TILE_ESRI_STREET,
        attr=ATRIBUICAO_ESRI,
        name="Ruas e bairros",
        overlay=False,
        control=True,
    ).add_to(mapa)

    # --- Polilinhas por perna, coloridas por modal --------------------------
    for leg, pontos in geometrias:
        modo = _modo_da_leg(leg)
        eh_caminhada = modo == "WALK"
        folium.PolyLine(
            [(float(lat), float(lon)) for lat, lon in pontos],
            color=_cor_da_leg(leg),
            weight=4 if eh_caminhada else 6,
            opacity=0.85 if eh_caminhada else 0.95,
            dash_array="6, 8" if eh_caminhada else None,
            tooltip=_rotulo_leg(leg),
            name=_rotulo_leg(leg),
        ).add_to(mapa)

    # --- Marcadores ---------------------------------------------------------
    if origem_ponto:
        folium.Marker(
            origem_ponto,
            tooltip=f"Origem — {origem_label}",
            popup=f"<b>Origem</b><br>{origem_label}",
            icon=folium.Icon(color="green", icon="home", prefix="fa"),
        ).add_to(mapa)
    if destino_ponto:
        folium.Marker(
            destino_ponto,
            tooltip=f"Destino — {destino_label}",
            popup=f"<b>Destino</b><br>{destino_label}",
            icon=folium.Icon(color="red", icon="building", prefix="fa"),
        ).add_to(mapa)

    # --- Baldeações (pontos de integração entre pernas de transporte) ------
    transito = [leg for leg in legs if (leg.get("route") or {})]
    for indice in range(len(transito) - 1):
        atual = transito[indice]
        proxima = transito[indice + 1]
        ponto = _pontos_de_marcador(atual, "to")
        if not ponto:
            continue
        nome = ((atual.get("to") or {}).get("name") or "Parada").strip()
        linha = (
            (proxima.get("route") or {}).get("shortName")
            or (proxima.get("route") or {}).get("longName")
            or ""
        ).strip()
        tooltip = f"Baldeação — {nome}" + (f" · linha {linha}" if linha else "")
        folium.Marker(
            ponto,
            tooltip=tooltip,
            popup=f"<b>Baldeação</b><br>{tooltip}",
            icon=folium.Icon(color="orange", icon="exchange", prefix="fa"),
        ).add_to(mapa)

    # --- Controle de camadas e enquadramento automático --------------------
    folium.LayerControl(collapsed=True, position="topright").add_to(mapa)

    # --- Altura fixa do mapa dentro do iframe do componente ----------------
    # O CSS padrão do Folium usa ``html, body { height: 100% }``, o que faz o
    # iframe do ``streamlit-folium`` crescer conforme o conteúdo. Injetamos uma
    # regra que fixa a altura do mapa em pixels e neutraliza o auto-ajuste.
    mapa.get_root().header.add_child(
        folium.Element(
            f"""
            <style>
              html, body {{
                height: {ALTURA_MAPA_PX}px !important;
                max-height: {ALTURA_MAPA_PX}px !important;
                overflow: hidden !important;
              }}
              .folium-map {{
                height: {ALTURA_MAPA_PX}px !important;
                width: 100% !important;
              }}
              #map {{
                height: {ALTURA_MAPA_PX}px !important;
                width: 100% !important;
              }}
            </style>
            """
        )
    )

    if todos_os_pontos:
        lats = [p[0] for p in todos_os_pontos]
        lons = [p[1] for p in todos_os_pontos]
        mapa.fit_bounds(
            [[min(lats), min(lons)], [max(lats), max(lons)]],
            padding=(30, 30),
            max_zoom=17,
        )

    return mapa


# ---------------------------------------------------------------------------
# Imagem estática para o PDF
# ---------------------------------------------------------------------------
def _renderizar_com_tiles(
    trechos: list,
    lats_marcadores: list,
    lons_marcadores: list,
    largura: int = 1400,
    altura: int = 700,
) -> bytes:
    """Renderiza o mapa estático sobre tiles urbanos usando ``staticmap``.

    Cada trecho é desenhado como uma linha independente, na cor do seu modal
    (caminhada, ônibus, metrô, trem), sobreposto aos tiles urbanos reais.

    Args:
        trechos: Lista de tuplas ``(pontos, cor)``, onde ``pontos`` é a lista de
            ``(lat, lon)`` do trecho e ``cor`` é a cor hex do modal.
        lats_marcadores: Latitudes dos marcadores (origem/baldeações/destino).
        lons_marcadores: Longitudes dos marcadores.
        largura: Largura do PNG em pixels (2x para nitidez no PDF).
        altura: Altura do PNG em pixels (2x para nitidez no PDF).

    Returns:
        bytes: Conteúdo PNG pronto para gravação em ``BytesIO``.

    Raises:
        OSError: Se os tiles não puderem ser baixados (servidor offline).
        ImportError: Se a biblioteca ``staticmap`` não estiver instalada.
    """
    from staticmap import CircleMarker, Line, StaticMap

    mapa_estatico = StaticMap(
        largura,
        altura,
        url_template=TILE_OSM,
        tile_request_timeout=TIMEOUT_TILES,
    )

    for pontos, cor in trechos:
        if not pontos:
            continue
        pontos_lonlat = [(float(lon), float(lat)) for lat, lon in pontos]
        # `add_line` (e não `add_marker`) — no staticmap, linhas e marcadores
        # são coleções separadas.
        mapa_estatico.add_line(Line(pontos_lonlat, cor, 5))

    # Marcadores: o primeiro é a origem (verde), o último é o destino (vermelho),
    # os intermediários são baldeações (laranja).
    total = len(lats_marcadores)
    for indice, (lat, lon) in enumerate(zip(lats_marcadores, lons_marcadores)):
        if indice == 0:
            cor, raio = "#16A34A", 14
        elif indice == total - 1:
            cor, raio = "#DC2626", 14
        else:
            cor, raio = "#F59E0B", 11
        mapa_estatico.add_marker(CircleMarker((float(lon), float(lat)), cor, raio))

    imagem = mapa_estatico.render(zoom=None)
    buffer = io.BytesIO()
    imagem.save(buffer, format="PNG")
    return buffer.getvalue()


def _renderizar_fallback_matplotlib(
    trechos: list,
    lats_marcadores: list,
    lons_marcadores: list,
) -> bytes:
    """Renderiza o mapa estático em modo offline (sem tiles e sem eixos).

    Args:
        trechos: Lista de tuplas ``(pontos, cor)`` por modal.
        lats_marcadores: Latitudes dos marcadores.
        lons_marcadores: Longitudes dos marcadores.

    Returns:
        bytes: Conteúdo PNG pronto para gravação em ``BytesIO``.
    """
    fig, ax = plt.subplots(figsize=(7, 3.5), dpi=150)
    try:
        todos_lons: list[float] = []
        todos_lats: list[float] = []
        for pontos, cor in trechos:
            if not pontos:
                continue
            lons_trecho = [float(lon) for _, lon in pontos]
            lats_trecho = [float(lat) for lat, _ in pontos]
            todos_lons.extend(lons_trecho)
            todos_lats.extend(lats_trecho)
            ax.plot(
                lons_trecho,
                lats_trecho,
                color=cor,
                linewidth=3,
                solid_capstyle="round",
                zorder=3,
            )

        total = len(lats_marcadores)
        if total >= 1:
            ax.scatter(
                lons_marcadores[:1],
                lats_marcadores[:1],
                color="#16A34A",
                s=140,
                zorder=5,
                edgecolors="white",
                linewidths=1.2,
            )
        if total >= 2:
            ax.scatter(
                lons_marcadores[-1:],
                lats_marcadores[-1:],
                color="#DC2626",
                s=140,
                zorder=5,
                edgecolors="white",
                linewidths=1.2,
            )
        if total > 2:
            ax.scatter(
                lons_marcadores[1:-1],
                lats_marcadores[1:-1],
                color="#F59E0B",
                s=90,
                zorder=4,
                edgecolors="white",
                linewidths=1.0,
            )
        ax.set_axis_off()
        if todos_lons and todos_lats:
            ax.set_xlim(min(todos_lons) - 0.002, max(todos_lons) + 0.002)
            ax.set_ylim(min(todos_lats) - 0.002, max(todos_lats) + 0.002)
        ax.margins(0.08)

        buffer = io.BytesIO()
        fig.savefig(
            buffer,
            format="png",
            bbox_inches="tight",
            pad_inches=0.05,
            facecolor="white",
        )
        buffer.seek(0)
        return buffer.getvalue()
    finally:
        plt.close(fig)


def gerar_imagem_mapa_rota(
    origem_lat,
    origem_lon,
    destino_lat,
    destino_lon,
    rota_dados: dict | None = None,
):
    """Gera a imagem PNG do trajeto para o relatório PDF.

    Usa tiles urbanos reais (OpenStreetMap) com o traçado de cada trecho
    destacado na cor do seu modal e os pinos de origem/destino/baldeação
    sobrepostos. Se o servidor de tiles estiver indisponível, degrada para uma
    renderização vetorial offline — a geração do PDF nunca quebra. O resultado
    é devolvido em memória, sem gravar arquivos em disco.

    Args:
        origem_lat: Latitude da origem.
        origem_lon: Longitude da origem.
        destino_lat: Latitude do destino.
        destino_lon: Longitude do destino.
        rota_dados: Opcional. Dados da rota (``legs``) para desenhar o traçado
            real por modal em vez da linha reta.

    Returns:
        io.BytesIO: Buffer PNG pronto para ser embutido no PDF.
    """
    legs = _extrair_legs(rota_dados)

    trechos: list[tuple[list, str]] = []
    lats: list[float] = []
    lons: list[float] = []
    lats_marcadores: list[float] = []
    lons_marcadores: list[float] = []

    if legs:
        for leg in legs:
            pontos = _pontos_da_leg(leg)
            if not pontos:
                continue
            trechos.append(([(float(lat), float(lon)) for lat, lon in pontos], _cor_da_leg(leg)))
            lats.extend(float(lat) for lat, _ in pontos)
            lons.extend(float(lon) for _, lon in pontos)

        # Marcadores: origem, baldeações (entre pernas de transporte) e destino.
        origem_ponto = _pontos_de_marcador(legs[0], "from")
        destino_ponto = _pontos_de_marcador(legs[-1], "to")
        transito = [leg for leg in legs if (leg.get("route") or {})]
        baldeacoes = [
            _pontos_de_marcador(transito[indice], "to")
            for indice in range(len(transito) - 1)
        ]
        baldeacoes = [ponto for ponto in baldeacoes if ponto]

        if origem_ponto:
            lats_marcadores.append(origem_ponto[0])
            lons_marcadores.append(origem_ponto[1])
        for ponto in baldeacoes:
            if ponto != origem_ponto:
                lats_marcadores.append(ponto[0])
                lons_marcadores.append(ponto[1])
        if destino_ponto and destino_ponto != origem_ponto:
            lats_marcadores.append(destino_ponto[0])
            lons_marcadores.append(destino_ponto[1])

    if not lats:
        lats = [float(origem_lat), float(destino_lat)]
        lons = [float(origem_lon), float(destino_lon)]
        trechos = [([(float(origem_lat), float(origem_lon)), (float(destino_lat), float(destino_lon))], COR_PADRAO)]
    if not lats_marcadores:
        lats_marcadores = [float(origem_lat), float(destino_lat)]
        lons_marcadores = [float(origem_lon), float(destino_lon)]

    # Caminho principal: tiles urbanos reais.
    try:
        conteudo = _renderizar_com_tiles(
            trechos, lats_marcadores, lons_marcadores
        )
    except (
        ImportError,
        OSError,
        RuntimeError,  # staticmap levanta RuntimeError quando o download dos tiles falha
        requests.RequestException,
        ValueError,
    ) as exc:
        logger.warning("Tiles indisponíveis para o mapa do PDF: %s", exc)
        conteudo = _renderizar_fallback_matplotlib(
            trechos, lats_marcadores, lons_marcadores
        )

    buffer = io.BytesIO(conteudo)
    buffer.seek(0)
    return buffer
