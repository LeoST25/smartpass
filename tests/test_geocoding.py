"""Testes da geocodificação multi-camada e autocomplete RMSP.

TDD: estes testes descrevem o contrato de ``src/services/geocoding.py``.
Todas as chamadas de rede são mockadas por URL (unittest.mock), sem tráfego real.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from src.services.geocoding import (
    _MAPA_SEMAFORO,
    _dentro_rmsp,
    _parse_termo,
    buscar_coordenadas_por_cep_ou_endereco,
    geocodificar_reverso,
    sugerir_enderecos,
)

# -----------------------------------------------------------------------------
# Fixtures / helpers
# -----------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Limpa todos os caches st.cache_data entre testes (evita vazamento de mock)."""
    import src.services.geocoding as geo

    funcoes = [
        getattr(geo, nome)
        for nome in (
            "sugerir_enderecos",
            "buscar_coordenadas_por_cep_ou_endereco",
            "geocodificar_reverso",
            "_consultar_viacep",
            "_consultar_brasilapi",
            "_consultar_photon",
            "_consultar_nominatim_estruturado",
            "_consultar_google",
        )
        if hasattr(geo, nome)
    ]
    for func in funcoes:
        try:
            func.clear()
        except Exception:
            pass
    yield
    for func in funcoes:
        try:
            func.clear()
        except Exception:
            pass


def _mock_resp(json_data, status=200):
    m = MagicMock()
    m.json.return_value = json_data
    m.raise_for_status = MagicMock()
    m.status_code = status
    return m


def _fake_get(handlers):
    """Cria um side_effect de requests.get roteando a resposta por fragmento de URL.

    Handlers podem ser dados JSON, exceções ou callables ``(params) -> json``.
    """
    chamadas = []

    def _get(url, params=None, headers=None, timeout=None, **kwargs):
        chamadas.append({"url": url, "params": params or {}, "timeout": timeout})
        for fragmento, resposta in handlers.items():
            if fragmento in url:
                if isinstance(resposta, Exception):
                    raise resposta
                dados = resposta(params or {}) if callable(resposta) else resposta
                if isinstance(dados, Exception):
                    raise dados
                return _mock_resp(dados)
        raise AssertionError(f"URL não mockada no teste: {url}")

    _get.chamadas = chamadas
    return _get


def _photon_payload(props, lon, lat):
    return {"features": [{"properties": props, "geometry": {"coordinates": [lon, lat]}}]}


# -----------------------------------------------------------------------------
# A) Autocomplete multi-camada (Photon / Nominatim / ViaCEP / BrasilAPI)
# -----------------------------------------------------------------------------


def test_sugerir_photon_bbox_rmsp():
    """Photon deve consultar bbox RMSP + foco São Paulo e priorizar o housenumber."""
    payload = _photon_payload(
        {
            "name": "Avenida Paulista",
            "street": "Avenida Paulista",
            "housenumber": "1000",
            "city": "São Paulo",
            "state": "SP",
            "postcode": "01310-100",
            "country": "Brasil",
        },
        lon=-46.6559,
        lat=-23.5614,
    )
    fake = _fake_get(
        {
            "photon.komoot.io": payload,
            "nominatim.openstreetmap.org": [],
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        resultados = sugerir_enderecos("Avenida Paulista, 1000, São Paulo", limite=5)

    assert resultados, "Photon deveria retornar ao menos uma sugestão"
    primeiro = resultados[0]
    assert primeiro["fonte"] == "photon"
    assert primeiro["nivel_precisao"] == "ALTA"
    assert primeiro["semaforo"] == _MAPA_SEMAFORO["ALTA"]
    assert "1000" in primeiro["label_exibicao"]
    assert primeiro["label_exibicao"]

    chamada_photon = next(c for c in fake.chamadas if "photon.komoot.io" in c["url"])
    assert chamada_photon["params"]["bbox"] == "-47.2,-24.1,-45.7,-23.1"
    assert chamada_photon["params"]["lat"] == pytest.approx(-23.5505)
    assert chamada_photon["params"]["lon"] == pytest.approx(-46.6333)
    assert chamada_photon["timeout"] == pytest.approx(3)


def test_cep_com_numero_viacep_e_preservacao():
    """CEP + número deve preservar o número no label e manter nível ALTA."""
    viacep = {
        "cep": "06320-290",
        "logradouro": "Rua Álvares de Azevedo",
        "bairro": "Vila Yara",
        "localidade": "Osasco",
        "uf": "SP",
    }
    nominatim = [
        {
            "lat": "-23.5324",
            "lon": "-46.7916",
            "display_name": "Rua Álvares de Azevedo, Vila Yara, Osasco - SP",
            "address": {
                "road": "Rua Álvares de Azevedo",
                "suburb": "Vila Yara",
                "city": "Osasco",
                "state_code": "SP",
                "postcode": "06320-290",
            },
        }
    ]
    fake = _fake_get(
        {
            "viacep.com.br": viacep,
            "nominatim.openstreetmap.org": nominatim,
            "photon.komoot.io": {"features": []},
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        resultados = sugerir_enderecos("06320-290, 1500", limite=5)

    assert resultados
    achado = resultados[0]
    assert achado["cep"] == "06320-290"
    assert achado["numero"] == "1500"
    assert ", 1500" in achado["label_exibicao"]
    assert "Álvares de Azevedo" in achado["label_exibicao"]
    assert achado["nivel_precisao"] == "ALTA"
    assert achado["semaforo"] == _MAPA_SEMAFORO["ALTA"]


def test_cep_brasilapi_fallback():
    """Falha/timeout do ViaCEP deve acionar a BrasilAPI /api/cep/v2/{cep}."""
    brasilapi = {
        "cep": "06320290",
        "state": "SP",
        "city": "Osasco",
        "neighborhood": "Vila Yara",
        "street": "Rua Álvares de Azevedo",
        "location": {"coordinates": {"longitude": "-46.7916", "latitude": "-23.5324"}},
    }
    fake = _fake_get(
        {
            "viacep.com.br": requests.Timeout("timeout viacep"),
            "brasilapi.com.br": brasilapi,
            "nominatim.openstreetmap.org": [],
            "photon.komoot.io": {"features": []},
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        resultados = sugerir_enderecos("06320-290, 1500", limite=5)

    assert resultados
    assert resultados[0]["fonte"] == "brasilapi"
    assert resultados[0]["nivel_precisao"] == "ALTA"
    assert resultados[0]["numero"] == "1500"
    assert resultados[0]["lat"] == pytest.approx(-23.5324)
    assert any("/api/cep/v2/06320290" in c["url"] for c in fake.chamadas)


def test_rejeita_homonimo_fora_rmsp():
    """Resultado homônimo fora da RMSP deve ser descartado por _dentro_rmsp."""
    fora_rj = {
        "lat": "-22.9068",
        "lon": "-43.1729",
        "display_name": "Rua das Flores, Rio de Janeiro - RJ",
        "address": {"road": "Rua das Flores", "city": "Rio de Janeiro", "state_code": "RJ"},
    }
    dentro_sp = {
        "lat": "-23.5505",
        "lon": "-46.6333",
        "display_name": "Rua das Flores, São Paulo - SP",
        "address": {"road": "Rua das Flores", "city": "São Paulo", "state_code": "SP"},
    }
    fake = _fake_get(
        {
            "photon.komoot.io": {"features": []},
            "nominatim.openstreetmap.org": [fora_rj, dentro_sp],
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        resultados = sugerir_enderecos("Rua das Flores, São Paulo", limite=5)

    assert resultados
    assert len(resultados) == 1
    assert resultados[0]["cidade"] == "São Paulo"
    for item in resultados:
        assert _dentro_rmsp(item["lat"], item["lon"]) is True
    assert all(not _dentro_rmsp(-22.9068, -43.1729) for _ in [0])


def test_semaforo_preservado_e_cache_ttl():
    """Semáforo deve seguir _MAPA_SEMAFORO e o cache de 1h não repetir requests."""
    fake = _fake_get(
        {
            "photon.komoot.io": _photon_payload(
                {"name": "Avenida Paulista", "street": "Avenida Paulista", "city": "São Paulo", "state": "SP"},
                lon=-46.6559,
                lat=-23.5614,
            ),
            "nominatim.openstreetmap.org": [],
        }
    )

    assert sugerir_enderecos._info.ttl == 3600
    assert sugerir_enderecos._info.show_spinner is False

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        primeira = sugerir_enderecos("Avenida Paulista, São Paulo", limite=5)
        chamadas_apos_primeira = len(fake.chamadas)
        segunda = sugerir_enderecos("Avenida Paulista, São Paulo", limite=5)

    assert primeira == segunda
    assert len(fake.chamadas) == chamadas_apos_primeira, "cache não deveria refazer requests"
    assert primeira
    for item in primeira:
        assert item["semaforo"] == _MAPA_SEMAFORO[item["nivel_precisao"]]


# -----------------------------------------------------------------------------
# B) Fachada legada — contrato buscar_coordenadas_por_cep_ou_endereco
# -----------------------------------------------------------------------------


def test_buscar_por_cep_via_viacep_e_nominatim_sucesso():
    viacep_data = {
        "logradouro": "Rua Teste",
        "bairro": "Centro",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    nominatim_data = [
        {
            "lat": "-23.5228",
            "lon": "-46.8355",
            "display_name": "Rua Teste, Carapicuíba, SP",
            "address": {"road": "Rua Teste", "suburb": "Centro", "city": "Carapicuíba", "state_code": "SP"},
        }
    ]
    fake = _fake_get(
        {
            "viacep.com.br": viacep_data,
            "nominatim.openstreetmap.org": nominatim_data,
            "photon.komoot.io": {"features": []},
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("06326-000")

    assert res["sucesso"] is True
    assert res["lat"] == pytest.approx(-23.5228)
    assert res["lon"] == pytest.approx(-46.8355)
    assert res["nivel_precisao"] == "ALTA"
    assert res["semaforo"] == "🟢 Exato"
    assert "06326-000" in res["motivo_precisao"] or "Rua Teste" in res["motivo_precisao"]


def test_buscar_por_cep_fallback_bairro():
    viacep_data = {
        "logradouro": "Rua Inexistente XYZ",
        "bairro": "Centro",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }

    def nominatim(params):
        if params.get("street"):
            return []
        return [{"lat": "-23.5", "lon": "-46.8", "display_name": "Centro, Carapicuíba"}]

    fake = _fake_get(
        {
            "viacep.com.br": viacep_data,
            "nominatim.openstreetmap.org": nominatim,
            "photon.komoot.io": {"features": []},
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")

    assert res["sucesso"] is True
    assert res["lat"] == pytest.approx(-23.5)
    assert res["nivel_precisao"] == "MEDIA"
    assert res["semaforo"] == "🟡 Aproximado"
    assert "bairro" in res["motivo_precisao"].lower() or "Centro" in res["motivo_precisao"]


def test_buscar_texto_livre_sucesso():
    nominatim_data = [
        {
            "lat": "-23.55",
            "lon": "-46.63",
            "display_name": "Av Paulista, 1000, São Paulo",
            "address": {"road": "Avenida Paulista", "house_number": "1000", "city": "São Paulo"},
        }
    ]
    fake = _fake_get(
        {
            "photon.komoot.io": {"features": []},
            "nominatim.openstreetmap.org": nominatim_data,
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000")

    assert res["sucesso"] is True
    assert "endereco_encontrado" in res
    assert res["nivel_precisao"] == "ALTA"
    assert res["semaforo"] == "🟢 Exato"


def test_buscar_endereco_nao_localizado():
    fake = _fake_get(
        {
            "photon.komoot.io": {"features": []},
            "nominatim.openstreetmap.org": [],
        }
    )
    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("Endereco Inexistente 999999")

    assert res["sucesso"] is False
    assert "erro" in res


def test_buscar_entrada_vazia_retorna_erro():
    res = buscar_coordenadas_por_cep_ou_endereco("   ")
    assert res["sucesso"] is False
    assert "erro" in res


def test_buscar_cep_geral_municipio_sem_logradouro_fallback_estruturado():
    """CEP geral (ex: 06310-000) com logradouro vazio deve cair para município (BAIXA)."""
    viacep_data = {
        "cep": "06310-000",
        "logradouro": "",
        "complemento": "",
        "bairro": "",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }
    nominatim_data = [
        {
            "lat": "-23.522",
            "lon": "-46.836",
            "display_name": "Carapicuíba, SP, Brasil",
            "address": {"city": "Carapicuíba", "state_code": "SP"},
        }
    ]
    fake = _fake_get(
        {
            "viacep.com.br": viacep_data,
            "nominatim.openstreetmap.org": nominatim_data,
            "photon.komoot.io": {"features": []},
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")

    assert res["sucesso"] is True
    assert res["lat"] == pytest.approx(-23.522)
    assert res["nivel_precisao"] == "BAIXA"
    assert res["semaforo"] == "🔴 Revisar Endereço"
    assert "centralizada" in res["motivo_precisao"].lower() or "geral" in res["motivo_precisao"].lower()


def test_buscar_cep_geral_fallback_postalcode_quando_municipio_falha():
    viacep_data = {
        "cep": "06310-000",
        "logradouro": "",
        "complemento": "",
        "bairro": "",
        "localidade": "Carapicuíba",
        "uf": "SP",
    }

    def nominatim(params):
        if params.get("postalcode"):
            return [
                {
                    "lat": "-23.522",
                    "lon": "-46.836",
                    "display_name": "06310-000, Carapicuíba",
                    "address": {"city": "Carapicuíba", "postcode": "06310-000"},
                }
            ]
        return []

    fake = _fake_get(
        {
            "viacep.com.br": viacep_data,
            "nominatim.openstreetmap.org": nominatim,
            "photon.komoot.io": {"features": []},
        }
    )

    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("06310-000")

    assert res["sucesso"] is True
    assert res["nivel_precisao"] == "BAIXA"
    assert res["semaforo"] == "🔴 Revisar Endereço"


def test_nominatim_timeout_retorna_falha():
    fake = _fake_get(
        {
            "photon.komoot.io": requests.Timeout("timeout photon"),
            "nominatim.openstreetmap.org": requests.Timeout("timeout nominatim"),
        }
    )
    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("Avenida Paulista, 1000")

    assert res["sucesso"] is False


def test_nivel_media_apenas_logradouro_sem_numero_ou_bairro():
    nominatim_data = [
        {
            "lat": "-23.5",
            "lon": "-46.8",
            "display_name": "Rua Teste, Centro, Carapicuíba",
            "address": {"road": "Rua Teste", "suburb": "Centro", "city": "Carapicuíba"},
        }
    ]
    fake = _fake_get(
        {
            "photon.komoot.io": {"features": []},
            "nominatim.openstreetmap.org": nominatim_data,
        }
    )
    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("Rua Teste, Centro, Carapicuíba")

    assert res["nivel_precisao"] == "MEDIA"
    assert res["semaforo"] == "🟡 Aproximado"


def test_nivel_baixa_texto_municipio_apenas():
    nominatim_data = [
        {
            "lat": "-23.52",
            "lon": "-46.83",
            "display_name": "Carapicuíba, São Paulo, Brasil",
            "address": {"city": "Carapicuíba", "state_code": "SP"},
        }
    ]
    fake = _fake_get(
        {
            "photon.komoot.io": {"features": []},
            "nominatim.openstreetmap.org": nominatim_data,
        }
    )
    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("Carapicuíba, SP")

    assert res["sucesso"] is True
    assert res["nivel_precisao"] == "BAIXA"
    assert res["semaforo"] == "🔴 Revisar Endereço"
    assert "centralizada" in res["motivo_precisao"].lower() or "município" in res["motivo_precisao"].lower()


def test_retorno_fachada_contem_chaves_obrigatorias():
    viacep_data = {
        "logradouro": "Rua A",
        "bairro": "Bairro B",
        "localidade": "Osasco",
        "uf": "SP",
    }
    nominatim_data = [
        {
            "lat": "-23.5",
            "lon": "-46.7",
            "display_name": "Rua A, Osasco",
            "address": {"road": "Rua A", "city": "Osasco", "state_code": "SP"},
        }
    ]
    fake = _fake_get(
        {
            "viacep.com.br": viacep_data,
            "nominatim.openstreetmap.org": nominatim_data,
            "photon.komoot.io": {"features": []},
        }
    )
    with patch("src.services.geocoding.requests.get", side_effect=fake):
        res = buscar_coordenadas_por_cep_ou_endereco("06000-000")

    for k in ["sucesso", "lat", "lon", "endereco_encontrado", "nivel_precisao", "semaforo", "motivo_precisao"]:
        assert k in res, f"chave {k} ausente"
    assert res["nivel_precisao"] in ("ALTA", "MEDIA", "BAIXA")


# -----------------------------------------------------------------------------
# C) Parsing de termo
# -----------------------------------------------------------------------------


def test_parse_termo_cep_com_numero():
    info = _parse_termo("06320-290, 1500")
    assert info["cep"] == "06320290"
    assert info["numero"] == "1500"
    assert info["texto"] == ""


def test_parse_termo_logradouro_com_numero():
    info = _parse_termo("Avenida Paulista, 1000")
    assert info["cep"] is None
    assert info["numero"] == "1000"
    assert "Avenida Paulista" in info["texto"]


# -----------------------------------------------------------------------------
# Geocodificação reversa (pino arrastado)
# -----------------------------------------------------------------------------
def test_geocodificar_reverso_sucesso():
    payload = {
        "lat": "-23.5614",
        "lon": "-46.6559",
        "display_name": "Avenida Paulista, 1000, São Paulo",
        "address": {
            "road": "Avenida Paulista",
            "house_number": "1000",
            "suburb": "Bela Vista",
            "city": "São Paulo",
            "state_code": "SP",
            "postcode": "01310-100",
        },
    }
    with patch("src.services.geocoding.requests.get", return_value=_mock_resp(payload)):
        res = geocodificar_reverso(-23.5614, -46.6559)

    assert res["sucesso"] is True
    assert res["fonte"] == "nominatim_reverse"
    assert res["nivel_precisao"] == "ALTA"
    assert "Avenida Paulista" in res["endereco_encontrado"]


def test_geocodificar_reverso_fora_rmsp():
    res = geocodificar_reverso(-30.0, -50.0)
    assert res["sucesso"] is False
    assert "fora da área" in res["erro"]


def test_geocodificar_reverso_offline():
    with patch("src.services.geocoding.requests.get", side_effect=requests.RequestException("timeout")):
        res = geocodificar_reverso(-23.5614, -46.6559)
    assert res["sucesso"] is False
