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
        # semáforo ALTA
        assert res["nivel_precisao"] == "ALTA"
        assert res["semaforo"] == "🟢 Exato"
        assert "motivo_precisao" in res
        assert "06326-000" in res["motivo_precisao"] or "Rua Teste" in res["motivo_precisao"]


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
        assert res["nivel_precisao"] == "MEDIA"
        assert res["semaforo"] == "🟡 Aproximado"
        assert "bairro" in res["motivo_precisao"].lower() or "Centro" in res["motivo_precisao"]


def test_buscar_texto_livre_sucesso():
    nominatim_data = [{"lat": "-23.55", "lon": "-46.63", "display_name": "Av Paulista, São Paulo"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(nominatim_data)
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000")
        assert res["sucesso"] is True
        assert "endereco_encontrado" in res
        # com número => ALTA
        assert res["nivel_precisao"] == "ALTA"
        assert res["semaforo"] == "🟢 Exato"


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
        # ViaCEP ok, Nominatim query município sucede direto (BAIXA) — evita dedup de cache
        mock_get.side_effect = [
            _mock_resp(viacep_data),
            _mock_resp([{"lat": "-23.522", "lon": "-46.836", "display_name": "Carapicuíba, SP, Brasil"}]),
        ]
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")
        assert res["sucesso"] is True
        assert res["lat"] == pytest.approx(-23.522)
        # semáforo BAIXA para CEP geral
        assert res["nivel_precisao"] == "BAIXA"
        assert res["semaforo"] == "🔴 Revisar Endereço"
        assert "centralizada" in res["motivo_precisao"].lower() or "geral" in res["motivo_precisao"].lower()
        # garante que a última chamada usou o fallback estruturado
        chamadas = [str(c) for c in mock_get.call_args_list]
        # a query município deve ter sido consultada (verifica params q ou postalcode)
        assert any("Carapicu" in str(c) for c in chamadas)


def test_buscar_cep_geral_fallback_postalcode_quando_municipio_falha():
    """CEP geral com falha no Nominatim município deve cair no postalcode como BAIXA."""
    viacep_data = {
        "cep": "06310-000",
        "logradouro": "",
        "complemento": "",
        "bairro": "",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_resp(viacep_data),
            _mock_resp([]),  # query município falha
            _mock_resp([{"lat": "-23.522", "lon": "-46.836", "display_name": "06310-000, Carapicuíba"}]),  # postalcode sucede
        ]
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")
        assert res["sucesso"] is True
        assert res["nivel_precisao"] == "BAIXA"
        assert res["semaforo"] == "🔴 Revisar Endereço"


def test_nominatim_timeout_retorna_falha():
    import requests

    with patch("src.services.geocoding.requests.get", side_effect=requests.RequestException("timeout")):
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000")
        assert res["sucesso"] is False


# --- Novos testes semáforo 3 níveis ---


def test_nivel_alta_cep_especifico_com_logradouro():
    """ALTA: CEP específico com logradouro retornado pelo ViaCEP."""
    viacep_data = {
        "logradouro": "Avenida Inocêncio Seráfico",
        "bairro": "Centro",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    nominatim_data = [{"lat": "-23.52", "lon": "-46.84", "display_name": "Avenida Inocêncio Seráfico, Carapicuíba"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.side_effect = [_mock_resp(viacep_data), _mock_resp(nominatim_data)]
        res = buscar_coordenadas_por_cep_ou_endereco("06326-050")
        assert res["nivel_precisao"] == "ALTA"
        assert res["semaforo"] == "🟢 Exato"
        assert "motivo_precisao" in res and len(res["motivo_precisao"]) > 10


def test_nivel_media_apenas_logradouro_sem_numero_ou_bairro():
    """MEDIA: texto livre logradouro sem número ou fallback bairro."""
    nominatim_data = [{"lat": "-23.5", "lon": "-46.8", "display_name": "Rua Teste, Centro, Carapicuíba"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(nominatim_data)
        res = buscar_coordenadas_por_cep_ou_endereco("Rua Teste, Centro, Carapicuíba")
        assert res["nivel_precisao"] == "MEDIA"
        assert res["semaforo"] == "🟡 Aproximado"
        assert "motivo_precisao" in res


def test_nivel_baixa_texto_municipio_apenas():
    """BAIXA: texto livre apenas município/UF sem logradouro/bairro/número."""
    nominatim_data = [{"lat": "-23.52", "lon": "-46.83", "display_name": "Carapicuíba, São Paulo, Brasil"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(nominatim_data)
        res = buscar_coordenadas_por_cep_ou_endereco("Carapicuíba, SP")
        assert res["sucesso"] is True
        assert res["nivel_precisao"] == "BAIXA"
        assert res["semaforo"] == "🔴 Revisar Endereço"
        assert "centralizada" in res["motivo_precisao"].lower() or "município" in res["motivo_precisao"].lower()


def test_nivel_baixa_municipio_sem_numero_sem_logradouro():
    """BAIXA: outro exemplo de município isolado."""
    nominatim_data = [{"lat": "-23.55", "lon": "-46.63", "display_name": "São Paulo, SP, Brasil"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(nominatim_data)
        res = buscar_coordenadas_por_cep_ou_endereco("São Paulo")
        assert res["nivel_precisao"] == "BAIXA"
        assert res["semaforo"] == "🔴 Revisar Endereço"


def test_nivel_alta_texto_livre_com_numero():
    """ALTA: texto livre com número deve ser exato."""
    nominatim_data = [{"lat": "-23.55", "lon": "-46.64", "display_name": "Avenida Paulista, 1000, São Paulo"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.return_value = _mock_resp(nominatim_data)
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000, São Paulo")
        assert res["nivel_precisao"] == "ALTA"
        assert res["semaforo"] == "🟢 Exato"


def test_nivel_media_cep_postalcode_fallback():
    """MEDIA: CEP que falha ViaCEP mas sucede via postalcode Nominatim."""
    viacep_data = {"erro": True}
    nominatim_cep = [{"lat": "-23.5", "lon": "-46.8", "display_name": "06310-000, Carapicuíba"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.side_effect = [
            _mock_resp(viacep_data),
            _mock_resp(nominatim_cep),
        ]
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")
        # ViaCEP erro=True cai para postalcode -> MEDIA
        assert res["sucesso"] is True
        assert res["nivel_precisao"] == "MEDIA"
        assert res["semaforo"] == "🟡 Aproximado"


def test_retorno_padronizado_contem_chaves_obrigatorias():
    """Todo sucesso deve conter lat/lon/endereco_encontrado + semáforo."""
    viacep_data = {
        "logradouro": "Rua A",
        "bairro": "Bairro B",
        "localidade": "Osasco",
        "uf": "SP",
    }
    nominatim_data = [{"lat": "-23.5", "lon": "-46.7", "display_name": "Rua A, Osasco"}]
    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_get.side_effect = [_mock_resp(viacep_data), _mock_resp(nominatim_data)]
        res = buscar_coordenadas_por_cep_ou_endereco("06000-000")
        for k in ["sucesso", "lat", "lon", "endereco_encontrado", "nivel_precisao", "semaforo", "motivo_precisao"]:
            assert k in res, f"chave {k} ausente"
        assert res["nivel_precisao"] in ("ALTA", "MEDIA", "BAIXA")
