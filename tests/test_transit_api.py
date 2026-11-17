from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services.transit_api import (
    _consulta_otp,
    _data_util_referencia,
    _enriquecer_leg,
    _extrair_itinerario_otp,
    _montar_consulta_otp,
    consultar_linhas_transporte_oficial,
    decodificar_polyline,
    estimar_itinerario_fallback,
    resolver_itinerarios_ida_volta,
)


@pytest.fixture(autouse=True)
def clear_cache():
    from src.services.transit_api import resolver_itinerario_com_otp

    try:
        resolver_itinerario_com_otp.clear()
    except Exception:
        pass
    yield
    try:
        resolver_itinerario_com_otp.clear()
    except Exception:
        pass


def test_extrair_itinerario_otp_sucesso(otp_payload_completo):
    res = _extrair_itinerario_otp(otp_payload_completo)
    assert len(res["linhas"]) == 1
    assert res["linhas"][0]["linha"].startswith("Rail 8-Diamante")
    assert res["distancia_km"] == pytest.approx(24.4)
    assert "resumo_trajeto" in res


def test_extrair_itinerario_otp_erro_graphql():
    payload = {"errors": [{"message": "Validation error: Field 'fare' is undefined"}]}
    with pytest.raises(RuntimeError, match="rejeitou a consulta"):
        _extrair_itinerario_otp(payload)


def test_extrair_itinerario_otp_sem_edges(otp_payload_vazio):
    with pytest.raises(RuntimeError, match="não encontrou itinerários"):
        _extrair_itinerario_otp(otp_payload_vazio)


def test_extrair_itinerario_somente_a_pe():
    payload = {
        "data": {
            "planConnection": {
                "edges": [
                    {"node": {"legs": [{"mode": "WALK", "distance": 1000, "from": {"name": "A"}, "to": {"name": "B"}, "route": None}]}}
                ]
            }
        }
    }
    with pytest.raises(RuntimeError, match="somente percurso a pé"):
        _extrair_itinerario_otp(payload)


def test_consultar_linhas_transporte_oficial_sucesso(otp_payload_completo):
    mock_resp = MagicMock()
    mock_resp.json.return_value = otp_payload_completo
    mock_resp.raise_for_status = MagicMock()
    with patch("src.services.transit_api.requests.post", return_value=mock_resp):
        res = consultar_linhas_transporte_oficial(-23.5, -46.8, -23.55, -46.63)
        assert res["sucesso"] is True
        assert res["fonte"] == "OpenTripPlanner (GTFS local)"
        assert res["distancia_km"] > 0


def test_consulta_otp_nao_solicita_fare():
    query = _consulta_otp(-23.5, -46.8, -23.55, -46.63)
    assert "fare" not in query.lower()
    assert "planConnection" in query
    assert "legs" in query
    assert "gtfsId" in query


def test_consulta_otp_solicita_leg_geometry():
    """A query GraphQL deve pedir legGeometry{ points } para desenhar o traçado real."""
    query = _consulta_otp(-23.5, -46.8, -23.55, -46.63)
    assert "legGeometry" in query
    assert "points" in query


def test_enriquecer_leg_decodifica_leg_geometry_dentro_da_rmsp():
    """Leg com polyline válida na RMSP expõe pontos (lat, lon) decodificados."""
    leg = {
        "mode": "BUS",
        "from": {"name": "A", "lat": "-23.5000", "lon": "-46.8000"},
        "to": {"name": "B", "lat": "-23.6000", "lon": "-46.7000"},
        "legGeometry": {"points": "~ylnC~rs|Gn}@o}@"},
    }
    enriquecida = _enriquecer_leg(leg)

    assert enriquecida["geometria_fallback"] is False
    assert enriquecida["pontos"], "polyline dentro da RMSP deve gerar pontos"
    lat, lon = enriquecida["pontos"][0]
    assert -24.1 <= lat <= -23.1
    assert -47.2 <= lon <= -45.7


def test_enriquecer_leg_descarta_geometria_fora_da_rmsp():
    """Pontos fora da RMSP são descartados e sinalizados como fallback."""
    leg = {
        "mode": "BUS",
        "from": {"name": "A", "lat": -23.5, "lon": -46.8},
        "to": {"name": "B", "lat": -23.6, "lon": -46.7},
        "legGeometry": {"points": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},  # polyline dos EUA
    }
    enriquecida = _enriquecer_leg(leg)

    assert enriquecida["pontos"] == []
    assert enriquecida["geometria_fallback"] is True


def test_enriquecer_leg_sem_leg_geometry_marca_fallback():
    """OTP sem geometria não quebra: sinaliza fallback de traçado."""
    leg = {
        "mode": "WALK",
        "from": {"name": "A", "lat": -23.5, "lon": -46.8},
        "to": {"name": "B", "lat": -23.6, "lon": -46.7},
    }
    enriquecida = _enriquecer_leg(leg)
    assert enriquecida["pontos"] == []
    assert enriquecida["geometria_fallback"] is True


def test_extrair_itinerario_otp_propaga_geometria(otp_payload_completo):
    """O contrato do itinerário carrega as legs com geometria decodificada."""
    res = _extrair_itinerario_otp(otp_payload_completo)
    assert "legs" in res
    assert all("pontos" in leg for leg in res["legs"])
    assert "geometria_fallback" in res


def test_decodificar_polyline_vazia():
    assert decodificar_polyline("") == []
    assert decodificar_polyline(None) == []


def test_consultar_linhas_erro_tecnico_nao_vaza_para_usuario():
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"errors": [{"message": "Validation error: Field 'fare' in type 'Itinerary' is undefined"}]}
    mock_resp.raise_for_status = MagicMock()
    with patch("src.services.transit_api.requests.post", return_value=mock_resp):
        res = consultar_linhas_transporte_oficial(-23.5, -46.8, -23.55, -46.63)
    assert res["sucesso"] is False
    assert "Validation" not in res["erro"]
    assert "fare" not in res["erro"].lower()
    assert "estimativa provisória" in res["erro"].lower()


def test_consultar_linhas_transporte_oficial_fallback():
    with patch("src.services.transit_api.requests.post", side_effect=requests.RequestException("OTP offline")):
        res = consultar_linhas_transporte_oficial(-23.5, -46.8, -23.55, -46.63)
        assert res["sucesso"] is False
        assert res["fonte"] == "Estimativa de contingência"
        assert "erro" in res


def test_estimar_itinerario_fallback():
    res = estimar_itinerario_fallback(12.3)
    assert res["distancia_km"] == pytest.approx(12.3)
    assert len(res["linhas"]) == 1
    assert res["resumo_trajeto"]


# -----------------------------------------------------------------------------
# Motor Ida + Volta por horário real
# -----------------------------------------------------------------------------
def test_montar_consulta_otp_ida_usa_latest_arrival():
    query = _montar_consulta_otp(-23.5, -46.8, -23.55, -46.63, data_hora="2026-11-17T08:00:00-03:00", arrive_by=True)
    assert "latestArrival" in query
    assert "earliestDeparture" not in query


def test_montar_consulta_otp_volta_usa_earliest_departure():
    query = _montar_consulta_otp(-23.5, -46.8, -23.55, -46.63, data_hora="2026-11-17T18:00:00-03:00", arrive_by=False)
    assert "earliestDeparture" in query
    assert "latestArrival" not in query


def test_montar_consulta_otp_solicita_start_end_time():
    query = _montar_consulta_otp(-23.5, -46.8, -23.55, -46.63)
    assert "startTime" in query
    assert "endTime" in query


def test_data_util_referencia_ignora_fim_de_semana():
    # 2026-11-14 é sábado; deve pular para segunda 2026-11-16
    from datetime import date
    d = _data_util_referencia(uf="SP", municipio="São Paulo", data_base=date(2026, 11, 14))
    assert d == "2026-11-16"


def test_resolver_itinerarios_ida_volta_duas_consultas(otp_payload_completo):
    mock_resp = MagicMock()
    mock_resp.json.return_value = otp_payload_completo
    mock_resp.raise_for_status = MagicMock()

    with patch("src.services.transit_api.requests.post", return_value=mock_resp) as mock_post:
        res = resolver_itinerarios_ida_volta(
            -23.5, -46.8, -23.55, -46.63, "08:00", "18:00", "2026-11-17"
        )

    assert mock_post.call_count == 2
    assert "ida" in res and "volta" in res
    assert len(res["ida"]) >= 1
    assert len(res["volta"]) >= 1
