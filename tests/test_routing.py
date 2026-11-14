from unittest.mock import MagicMock, patch

import pytest

from src.services.routing import calcular_vale_combustivel, calcular_vale_transporte, roteirizar_vale_transporte_automatico


@pytest.fixture(autouse=True)
def clear_cache():
    from src.services.routing import _distancia_rodoviaria_km

    try:
        _distancia_rodoviaria_km.clear()
    except Exception:
        pass
    yield
    try:
        _distancia_rodoviaria_km.clear()
    except Exception:
        pass


def _mock_osrm_ok(distancia_m=24500):
    m = MagicMock()
    m.json.return_value = {"code": "Ok", "routes": [{"distance": distancia_m}]}
    m.raise_for_status = MagicMock()
    return m


def test_calcular_vale_combustivel_sucesso():
    with patch("src.services.routing.requests.get", return_value=_mock_osrm_ok(24500)):
        res = calcular_vale_combustivel(-23.5228, -46.8355, -23.5505, -46.6333, 1.25)
        assert res["sucesso"] is True
        assert res["distancia_km"] == pytest.approx(24.5)
        assert res["custo_total"] == pytest.approx(30.62, rel=1e-2)


def test_calcular_vale_combustivel_falha_osrm():
    import requests

    with patch("src.services.routing.requests.get", side_effect=requests.RequestException("timeout")):
        res = calcular_vale_combustivel(-23.5, -46.8, -23.55, -46.63, 1.0)
        # Quando padrao=None e falha, retorna erro
        assert res["sucesso"] is False
        assert "erro" in res


def test_calcular_vale_transporte_soma_tarifas():
    linhas = [
        {"linha": "Linha 022 - Embu", "valor": 5.50, "quantidade_dia": 2},
        {"linha": "Metrô Linha 4", "valor": 5.00, "quantidade_dia": 2},
    ]
    res = calcular_vale_transporte(linhas)
    assert res["custo_diario"] == pytest.approx(21.0)
    assert res["custo_mensal"] == pytest.approx(462.0)
    assert len(res["detalhes"]) == 2


def test_roteirizar_vt_com_otp_sucesso():
    from src.services.routing import _distancia_rodoviaria_km

    mock_itinerario = {
        "sucesso": True,
        "fonte": "OpenTripPlanner (GTFS local)",
        "linhas": [{"linha": "Rail 8-Diamante", "valor_unitario": 5.0, "quantidade_dia": 2}],
        "distancia_km": 24.4,
        "resumo_trajeto": "Rail 8-Diamante (Casa → Estação)",
    }
    with patch("src.services.routing._distancia_rodoviaria_km", return_value=24.4):
        with patch("src.services.routing.consultar_linhas_transporte_oficial", return_value=mock_itinerario):
            res = roteirizar_vale_transporte_automatico(-23.5228, -46.8355, -23.5505, -46.6333, "Orig", "Dest")
            assert res["sucesso"] is True
            assert res["distancia_km"] == pytest.approx(24.4)
            assert res["custo_diario"] > 0
            assert res["fonte"] == "OpenTripPlanner (GTFS local)"


def test_roteirizar_vt_fallback_quando_otp_falha():
    resposta_erro = {"sucesso": False, "fonte": "Estimativa de contingência", "erro": "OTP offline", "detalhes": []}
    with patch("src.services.routing._distancia_rodoviaria_km", return_value=10.0):
        with patch("src.services.routing.consultar_linhas_transporte_oficial", return_value=resposta_erro):
            res = roteirizar_vale_transporte_automatico(-23.5, -46.8, -23.55, -46.63, "Orig", "Dest")
            assert res["sucesso"] is True
            assert res["distancia_km"] == pytest.approx(10.0)
            assert res["aviso"] == "OTP offline"
            assert "Estimativa" in res["fonte"]
