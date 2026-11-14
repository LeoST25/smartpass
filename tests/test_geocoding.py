from unittest.mock import MagicMock, patch

import pytest

from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco


@pytest.fixture(autouse=True)
def clear_cache():
    from src.services.geocoding import _consultar_nominatim, buscar_coordenadas_por_cep_ou_endereco

    try:
        _consultar_nominatim.clear()
    except Exception:
        pass
    try:
        buscar_coordenadas_por_cep_ou_endereco.clear()
    except Exception:
        pass
    yield
    try:
        _consultar_nominatim.clear()
    except Exception:
        pass
    try:
        buscar_coordenadas_por_cep_ou_endereco.clear()
    except Exception:
        pass


def _mock_resp(json_data, status=200):
    m = MagicMock()
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    m.status_code = status
    return m


def test_buscar_por_cep_via_viacep_e_nominatim_sucesso():
    viacep_data = {
        "logradouro": "Rua Teste",
        "bairro": "Centro",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    nominatim_data = [{"lat": "-23.5228", "lon": "-46.8355", "display_name": "Rua Teste, Carapicuíba, SP"}]

    with patch("src.services.geocoding.requests.get") as mock_get:
        # 1 ViaCEP, 2 Nominatim query completa
        mock_get.side_effect = [
            _mock_resp(viacep_data),
            _mock_resp(nominatim_data),
        ]
        res = buscar_coordenadas_por_cep_ou_endereco("06326-000")
        assert res["sucesso"] is True
        assert res["lat"] == pytest.approx(-23.5228)
        assert res["lon"] == pytest.approx(-46.8355)


def test_buscar_por_cep_fallback_bairro():
    viacep_data = {
        "logradouro": "Rua Inexistente XYZ",
        "bairro": "Centro",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    with patch("src.services.geocoding.requests.get") as mock_get:
        # ViaCEP ok, Nominatim query completa falha ([]), fallback bairro ok
        mock_get.side_effect = [
            _mock_resp(viacep_data),
            _mock_resp([]),
            _mock_resp([{"lat": "-23.5", "lon": "-46.8", "display_name": "Centro, Carapicuíba"}]),
        ]
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")
        assert res["sucesso"] is True
        assert res["lat"] == pytest.approx(-23.5)


def test_buscar_texto_livre_sucesso():
    nominatim_data = [{"lat": "-23.55", "lon": "-46.63", "display_name": "Av Paulista, São Paulo"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(nominatim_data)
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000")
        assert res["sucesso"] is True
        assert "endereco_encontrado" in res


def test_buscar_endereco_nao_localizado():
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp([])
        res = buscar_coordenadas_por_cep_ou_endereco("Endereco Inexistente 999999")
        assert res["sucesso"] is False
        assert "erro" in res


def test_buscar_entrada_vazia_retorna_erro():
    res = buscar_coordenadas_por_cep_ou_endereco("   ")
    assert res["sucesso"] is False
    assert "erro" in res


def test_buscar_cep_geral_municipio_sem_logradouro_fallback_estruturado():
    """CEP geral (ex: 06310-000) com logradouro vazio deve cair para 'Carapicuíba, SP, Brasil'."""
    viacep_data = {
        "cep": "06310-000",
        "logradouro": "",
        "complemento": "",
        "bairro": "",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    with patch("src.services.geocoding.requests.get") as mock_get:
        # ViaCEP ok, Nominatim query completa falha, fallback município ok
        mock_get.side_effect = [
            _mock_resp(viacep_data),
            _mock_resp([]),  # query completa "Carapicuíba, SP, Brasil" falha na tentativa A (duplicada lógica testará deduplicação)
            _mock_resp([{"lat": "-23.522", "lon": "-46.836", "display_name": "Carapicuíba, SP, Brasil"}]),
        ]
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")
        assert res["sucesso"] is True
        assert res["lat"] == pytest.approx(-23.522)
        # garante que a última chamada usou o fallback estruturado
        chamadas = [str(c) for c in mock_get.call_args_list]
        # a query município deve ter sido consultada (verifica params q ou postalcode)
        assert any("Carapicu" in str(c) for c in chamadas)


def test_nominatim_timeout_retorna_falha():
    import requests

    with patch("src.services.geocoding.requests.get", side_effect=requests.RequestException("timeout")):
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000")
        assert res["sucesso"] is False
