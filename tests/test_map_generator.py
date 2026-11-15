"""Testes do serviço de cartografia (mapa interativo e imagem estática para PDF).

Todos os testes usam mocks para rede — nenhum acesso real a tiles, OTP ou OSRM.
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from src.services.map_generator import (
    CORES_MODAL,
    gerar_imagem_mapa_rota,
    gerar_mapa_interativo,
)
from src.services.transit_api import decodificar_polyline


# ---------------------------------------------------------------------------
# Polyline OTP — decodificação (feliz / bordas / falhas)
# ---------------------------------------------------------------------------
def test_decodificar_polyline_exemplo_otp():
    """Polyline canônica do Google decode para os pontos esperados."""
    pontos = decodificar_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert len(pontos) == 3
    assert pontos[0] == pytest.approx((38.5, -120.2), abs=1e-5)
    assert pontos[1] == pytest.approx((40.7, -120.95), abs=1e-5)
    assert pontos[2] == pytest.approx((43.252, -126.453), abs=1e-5)


def test_decodificar_polyline_dentro_da_rmsp():
    """Polyline codificada dentro da RMSP decodifica para as coordenadas esperadas."""
    pontos = decodificar_polyline("~vpnC~l{|Gf^g^v|Aw|A")
    assert pontos[0] == pytest.approx((-23.52, -46.84), abs=1e-5)
    assert pontos[-1] == pytest.approx((-23.54, -46.82), abs=1e-5)


def test_decodificar_polyline_vazia_e_none():
    """Entradas vazias retornam lista vazia sem exceção."""
    assert decodificar_polyline("") == []
    assert decodificar_polyline(None) == []


def test_decodificar_polyline_caractere_invalido():
    """Payload corrompido sinalizado com ValueError (fallback do serviço)."""
    with pytest.raises(ValueError):
        decodificar_polyline("@@@!")


def test_decodificar_polyline_truncada():
    """Polyline com bloco incompleto é rejeitada."""
    with pytest.raises(ValueError):
        decodificar_polyline("_p~iF")


def test_leg_com_legGeometry_fora_da_rmsp_e_descartado():
    """Pontos fora do bbox da RMSP são descartados pelo enricher."""
    from src.services.transit_api import _enriquecer_leg

    leg = {
        "mode": "BUS",
        "from": {"name": "A", "lat": -23.5, "lon": -46.8},
        "to": {"name": "B", "lat": -23.6, "lon": -46.7},
        "legGeometry": {"points": decodificar_polyline("_p~iF~ps|U") and "_p~iF~ps|U"},
    }
    enrichecida = _enriquecer_leg(leg)
    # a polyline de exemplo está fora da RMSP → nenhum ponto é aceito
    assert enrichecida["pontos"] == []
    assert enrichecida["geometria_fallback"] is True


def test_leg_com_legGeometry_dentro_da_rmsp_e_decodificado():
    """Polyline dentro da RMSP é decodificada em pontos (lat, lon)."""
    from src.services.transit_api import _enriquecer_leg

    leg = {
        "mode": "BUS",
        "from": {"name": "A", "lat": -23.5, "lon": -46.8},
        "to": {"name": "B", "lat": -23.6, "lon": -46.7},
        "legGeometry": {"points": "~ylnC~rs|Gn}@o}@"},
    }
    enrichecida = _enriquecer_leg(leg)
    assert enrichecida["geometria_fallback"] is False
    assert enrichecida["pontos"]
    for lat, lon in enrichecida["pontos"]:
        assert -24.1 <= lat <= -23.1
        assert -47.2 <= lon <= -45.7


# ---------------------------------------------------------------------------
# Mapa interativo (Folium)
# ---------------------------------------------------------------------------
@pytest.fixture
def rota_com_legs():
    """Rota simulada com caminhada, ônibus e metrô."""
    return {
        "sucesso": True,
        "legs": [
            {
                "mode": "WALK",
                "distance": 300,
                "from": {"name": "Casa", "lat": -23.5200, "lon": -46.8400},
                "to": {"name": "Parada", "lat": -23.5250, "lon": -46.8350},
                "route": None,
                "pontos": [
                    (-23.5200, -46.8400),
                    (-23.5220, -46.8380),
                    (-23.5250, -46.8350),
                ],
            },
            {
                "mode": "BUS",
                "distance": 5000,
                "from": {"name": "Parada", "lat": -23.5250, "lon": -46.8350},
                "to": {"name": "Estação", "lat": -23.5400, "lon": -46.8200},
                "route": {"shortName": "300", "longName": "Terminal Leme"},
                "pontos": [
                    (-23.5250, -46.8350),
                    (-23.5300, -46.8300),
                    (-23.5400, -46.8200),
                ],
            },
            {
                "mode": "SUBWAY",
                "distance": 3000,
                "from": {"name": "Estação", "lat": -23.5400, "lon": -46.8200},
                "to": {"name": "Empresa", "lat": -23.5600, "lon": -46.8100},
                "route": {"shortName": "1", "longName": "Azul"},
                "pontos": [
                    (-23.5400, -46.8200),
                    (-23.5500, -46.8150),
                    (-23.5600, -46.8100),
                ],
            },
        ],
    }


def test_gerar_mapa_interativo_cria_mapa_com_polilinhas_e_marcadores(rota_com_legs):
    """Mapa interativo contém polilinhas por trecho e marcadores de origem/destino."""
    mapa = gerar_mapa_interativo(rota_com_legs, "Casa", "Empresa")
    assert mapa is not None

    html = mapa.get_root().render()
    # uma polilinha por perna (3 pernas)
    assert html.count("L.polyline") == 3
    # marcadores de origem, baldeação e destino
    assert html.count("L.marker") == 3


def test_gerar_mapa_interativo_usa_cores_por_modal(rota_com_legs):
    """Cada modal recebe cor distinta e caminhada é pontilhada."""
    mapa = gerar_mapa_interativo(rota_com_legs, "Casa", "Empresa")
    html = mapa.get_root().render()

    assert CORES_MODAL["WALK"] in html
    assert CORES_MODAL["BUS"] in html
    assert CORES_MODAL["SUBWAY"] in html
    assert "dashArray" in html  # caminhada pontilhada


def test_gerar_mapa_interativo_tem_tiles_urbanos_e_layer_control(rota_com_legs):
    """Mapa usa tiles urbanos (OSM/Esri) e permite alternar camadas."""
    mapa = gerar_mapa_interativo(rota_com_legs, "Casa", "Empresa")
    html = mapa.get_root().render()

    assert "tile.openstreetmap.org" in html
    assert "arcgisonline.com" in html
    assert "L.control.layers" in html


def test_gerar_mapa_interativo_faz_fit_bounds(rota_com_legs):
    """O mapa enquadra automaticamente todo o trajeto."""
    mapa = gerar_mapa_interativo(rota_com_legs, "Casa", "Empresa")
    html = mapa.get_root().render()
    assert "fitBounds" in html


def test_gerar_mapa_interativo_sem_legs_nao_quebra():
    """Rota vazia devolve mapa sem exceção (fallback de renderização)."""
    mapa = gerar_mapa_interativo({"legs": []}, "Casa", "Empresa")
    assert mapa is not None
    assert mapa.get_root().render()


def test_gerar_mapa_interativo_simplifica_polyline_longa():
    """Polyline com muitos pontos é simplificada para manter o carregamento rápido."""
    pontos = [(-23.5 + i * 0.00005, -46.8 + i * 0.00005) for i in range(1500)]
    rota = {
        "legs": [
            {
                "mode": "BUS",
                "from": {"name": "A", "lat": pontos[0][0], "lon": pontos[0][1]},
                "to": {"name": "B", "lat": pontos[-1][0], "lon": pontos[-1][1]},
                "route": {"shortName": "500"},
                "pontos": pontos,
            }
        ]
    }
    mapa = gerar_mapa_interativo(rota, "A", "B")
    html = mapa.get_root().render()
    # a polyline original tinha 1500 pontos; após simplificação o HTML é menor
    assert html.count("L.polyline") == 1
    assert "1500" not in html


def test_gerar_mapa_interativo_leg_sem_geometria_usa_fallback_osrm():
    """Leg sem polyline consulta o OSRM (com timeout) em vez de quebrar."""
    rota = {
        "legs": [
            {
                "mode": "BUS",
                "from": {"name": "A", "lat": -23.52, "lon": -46.84},
                "to": {"name": "B", "lat": -23.55, "lon": -46.82},
                "route": {"shortName": "500"},
                "pontos": [],
                "geometria_fallback": True,
            }
        ]
    }
    resposta = MagicMock()
    resposta.json.return_value = {
        "code": "Ok",
        "routes": [{"geometry": {"coordinates": [[-46.84, -23.52], [-46.82, -23.55]]}}],
    }
    with patch("src.services.map_generator.requests.get", return_value=resposta) as mock_get:
        mapa = gerar_mapa_interativo(rota, "A", "B")
    assert mapa is not None
    assert mock_get.called
    assert mock_get.call_args.kwargs.get("timeout", 0) <= 10


# ---------------------------------------------------------------------------
# Imagem estática para o PDF
# ---------------------------------------------------------------------------
def test_gerar_imagem_mapa_rota_com_tiles_mock_retorna_bytesio(rota_com_legs):
    """Com tiles disponíveis, o gerador devolve PNG em BytesIO (sem eixos)."""
    resposta = MagicMock()
    resposta.content = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    resposta.raise_for_status = MagicMock()

    with patch("src.services.map_generator._renderizar_com_tiles", return_value=b"\x89PNG\r\n\x1a\n"):
        buffer = gerar_imagem_mapa_rota(
            -23.52, -46.84, -23.56, -46.81, rota_dados=rota_com_legs
        )

    assert isinstance(buffer, io.BytesIO)
    assert buffer.getvalue().startswith(b"\x89PNG")
    assert buffer.tell() == 0 or buffer.seekable()


def test_gerar_imagem_mapa_rota_fallback_offline_dos_tiles(rota_com_legs):
    """Servidor de tiles offline devolve PNG via matplotlib, sem quebrar."""
    with patch(
        "src.services.map_generator._renderizar_com_tiles",
        side_effect=OSError("tiles offline"),
    ):
        buffer = gerar_imagem_mapa_rota(
            -23.52, -46.84, -23.56, -46.81, rota_dados=rota_com_legs
        )

    assert isinstance(buffer, io.BytesIO)
    assert buffer.getvalue().startswith(b"\x89PNG")


def test_gerar_imagem_mapa_rota_fallback_quando_staticmap_levanta_runtime_error(rota_com_legs):
    """O staticmap levanta RuntimeError quando o download dos tiles falha.

    Regressão: o RuntimeError precisa ser capturado para o PDF não quebrar
    quando o servidor de tiles estiver offline.
    """
    with patch(
        "src.services.map_generator._renderizar_com_tiles",
        side_effect=RuntimeError("could not download 24 tiles"),
    ):
        buffer = gerar_imagem_mapa_rota(
            -23.52, -46.84, -23.56, -46.81, rota_dados=rota_com_legs
        )

    assert isinstance(buffer, io.BytesIO)
    assert buffer.getvalue().startswith(b"\x89PNG")


def test_gerar_imagem_mapa_rota_fallback_offline_com_requests_mockado(rota_com_legs):
    """Tiles inacessíveis via requests ainda produzem PNG (fallback offline)."""
    import requests

    with patch("requests.get", side_effect=requests.ConnectionError("tiles offline")):
        buffer = gerar_imagem_mapa_rota(
            -23.52, -46.84, -23.56, -46.81, rota_dados=rota_com_legs
        )

    assert isinstance(buffer, io.BytesIO)
    assert buffer.getvalue().startswith(b"\x89PNG")


def test_gerar_imagem_mapa_rota_fallback_sem_rota():
    """Chamada legada (só 4 coords) continua funcionando."""
    buffer = gerar_imagem_mapa_rota(-23.52, -46.84, -23.56, -46.81)
    assert isinstance(buffer, io.BytesIO)
    assert buffer.getvalue().startswith(b"\x89PNG")


def test_gerar_imagem_mapa_rota_nao_escreve_em_disco():
    """Nenhuma escrita em disco — tudo em memória (LGPD stateless)."""
    with patch("builtins.open", side_effect=AssertionError("escrita em disco proibida")):
        buffer = gerar_imagem_mapa_rota(-23.52, -46.84, -23.56, -46.81)
    assert isinstance(buffer, io.BytesIO)


def test_gerar_imagem_mapa_rota_tem_margem_para_eixos_desligados(rota_com_legs):
    """Fallback matplotlib não exibe rótulos numéricos de eixo."""
    with patch(
        "src.services.map_generator._renderizar_com_tiles",
        side_effect=OSError("tiles offline"),
    ):
        buffer = gerar_imagem_mapa_rota(
            -23.52, -46.84, -23.56, -46.81, rota_dados=rota_com_legs
        )
    assert buffer.getvalue().startswith(b"\x89PNG")
