"""Migração de teste_ai_routing.py para pytest com mocks (sem chamada real ao OTP/OSRM)."""

from unittest.mock import patch

import pytest

from src.services.routing import roteirizar_vale_transporte_automatico
from src.services.transit_api import _extrair_itinerario_otp


@pytest.fixture(autouse=True)
def clear_caches():
    from src.services.routing import _distancia_rodoviaria_km
    from src.services.transit_api import resolver_itinerario_com_otp

    for fn in (_distancia_rodoviaria_km, resolver_itinerario_com_otp):
        try:
            fn.clear()
        except Exception:
            pass
    yield
    for fn in (_distancia_rodoviaria_km, resolver_itinerario_com_otp):
        try:
            fn.clear()
        except Exception:
            pass


def test_conversao_resposta_otp():
    exemplo = _extrair_itinerario_otp(
        {
            "data": {
                "planConnection": {
                    "edges": [
                        {
                            "node": {
                                "legs": [
                                    {"mode": "WALK", "distance": 300, "from": {"name": "Casa"}, "to": {"name": "Estação"}, "route": None},
                                    {
                                        "mode": "RAIL",
                                        "distance": 24100,
                                        "from": {"name": "Estação Carapicuíba"},
                                        "to": {"name": "Luz"},
                                        "route": {"shortName": "8-Diamante", "longName": "Júlio Prestes"},
                                    },
                                ]
                            }
                        }
                    ]
                }
            }
        }
    )
    assert exemplo["linhas"][0]["linha"].startswith("Rail 8-Diamante")
    assert exemplo["linhas"][0]["quantidade_dia"] == 2
    assert exemplo["distancia_km"] == pytest.approx(24.4)


def test_roteirizar_vale_transporte_contingencia_sem_otp():
    """Valida contingência VT quando OTP está indisponível (sem rede)."""
    # Mock distância OSRM e forçar OTP offline → fallback deve ser usado
    with patch("src.services.routing._distancia_rodoviaria_km", return_value=18.7):
        with patch(
            "src.services.routing.consultar_linhas_transporte_oficial",
            return_value={"sucesso": False, "fonte": "Estimativa de contingência", "erro": "OTP offline", "detalhes": []},
        ):
            resultado = roteirizar_vale_transporte_automatico(
                -23.5228, -46.8355, -23.5505, -46.6333, "Carapicuíba, SP", "Avenida Paulista, 1000, São Paulo, SP"
            )
            assert resultado["sucesso"] is True
            assert resultado["detalhes"]
            assert resultado["distancia_km"] > 0
            assert resultado["custo_diario"] > 0
            assert resultado["resumo_trajeto"]
            assert resultado["fonte"] == "Estimativa de contingência"
            assert "aviso" in resultado


def test_roteirizar_vale_transporte_com_otp_mockado():
    mock_itinerario = {
        "sucesso": True,
        "fonte": "OpenTripPlanner (GTFS local)",
        "linhas": [{"linha": "Rail 8-Diamante — Júlio Prestes", "valor_unitario": 5.0, "quantidade_dia": 2}],
        "distancia_km": 24.4,
        "resumo_trajeto": "Rail 8-Diamante (Estação Carapicuíba → Luz)",
    }
    with patch("src.services.routing._distancia_rodoviaria_km", return_value=24.4):
        with patch("src.services.routing.consultar_linhas_transporte_oficial", return_value=mock_itinerario):
            resultado = roteirizar_vale_transporte_automatico(
                -23.5228, -46.8355, -23.5505, -46.6333, "Carapicuíba, SP", "Avenida Paulista, 1000, São Paulo, SP"
            )
            assert resultado["sucesso"] is True
            assert resultado["fonte"] == "OpenTripPlanner (GTFS local)"
            assert resultado["distancia_km"] == pytest.approx(24.4)
