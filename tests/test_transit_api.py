from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services.transit_api import (
    _extrair_itinerario_otp,
    consultar_linhas_transporte_oficial,
    estimar_itinerario_fallback,
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
    payload = {"errors": [{"message": "OTP rejeitou a consulta."}]}
    with pytest.raises(RuntimeError, match="OTP rejeitou"):
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
