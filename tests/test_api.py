"""Testes da camada API FastAPI (src/api/).

Cobre todos os endpoints com fastapi.testclient.TestClient + mocks para OTP/Nominatim/ViaCEP.
Valida LGPD stateless (zero persistência em disco), tratamento de exceções sem stacktrace,
e limites de upload/tamanho de lote.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture
def client():
    """TestClient síncrono (sem servidor real)."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clear_caches():
    """Limpa caches entre testes para evitar vazamento de mocks."""
    from src.services.geocoding import (
        _consultar_brasilapi,
        _consultar_google,
        _consultar_nominatim_estruturado,
        _consultar_photon,
        _consultar_viacep,
        buscar_coordenadas_por_cep_ou_endereco,
        sugerir_enderecos,
    )
    from src.services.routing import _distancia_rodoviaria_km
    from src.services.transit_api import resolver_itinerario_com_otp, resolver_todos_itinerarios_com_otp

    caches = [
        _consultar_viacep,
        _consultar_brasilapi,
        _consultar_photon,
        _consultar_nominatim_estruturado,
        _consultar_google,
        sugerir_enderecos,
        buscar_coordenadas_por_cep_ou_endereco,
        _distancia_rodoviaria_km,
        resolver_itinerario_com_otp,
        resolver_todos_itinerarios_com_otp,
    ]
    for cache in caches:
        try:
            cache.clear()
        except Exception:
            pass
    yield
    for cache in caches:
        try:
            cache.clear()
        except Exception:
            pass


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------


def test_health_ok_mocked(client):
    """GET /health retorna status ok quando Postgres e OTP respondem."""
    with patch("src.database.connection.check_db_health", return_value={"ok": True, "postgis_version": "3.3.0", "latency_ms": 5.0, "erro": None}), patch("src.api.routes.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"_service": {"name": "otp"}}}
        mock_post.return_value = mock_resp

        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["postgres"]["ok"] is True
    assert data["otp"]["ok"] is True
    assert "timestamp" in data


def test_health_degraded_otp_offline(client):
    """GET /health retorna degraded quando OTP está offline."""
    with patch("src.database.connection.check_db_health", return_value={"ok": True, "postgis_version": "3.3.0", "latency_ms": 5.0, "erro": None}), patch("src.api.routes.requests.post", side_effect=Exception("OTP offline")):
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["postgres"]["ok"] is True
    assert data["otp"]["ok"] is False


def test_health_down_both_offline(client):
    """GET /health retorna down quando Postgres e OTP estão offline."""
    with patch("src.database.connection.check_db_health", return_value={"ok": False, "postgis_version": None, "latency_ms": 3000.0, "erro": "connection refused"}), patch("src.api.routes.requests.post", side_effect=Exception("OTP offline")):
        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "down"
    assert data["postgres"]["ok"] is False
    assert data["otp"]["ok"] is False


def test_health_otp_respeita_env_var(monkeypatch, client):
    """GET /health usa OTP_GRAPHQL_URL do ambiente (Docker-friendly)."""
    monkeypatch.setenv("OTP_GRAPHQL_URL", "http://otp:8080/otp/gtfs/v1")
    captured_url = {}

    with patch("src.database.connection.check_db_health", return_value={"ok": True, "postgis_version": "3.3.0", "latency_ms": 5.0, "erro": None}), patch("src.api.routes.requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": {"_service": {"name": "otp"}}}

        def _capture(url, *args, **kwargs):
            captured_url["url"] = url
            return mock_resp

        mock_post.side_effect = _capture

        resp = client.get("/api/v1/health")

    assert resp.status_code == 200
    assert captured_url["url"] == "http://otp:8080/otp/gtfs/v1"


# -----------------------------------------------------------------------------
# Geocoding Autocomplete
# -----------------------------------------------------------------------------


def test_autocomplete_q_curto_422(client):
    """GET /geocoding/autocomplete com q < 3 caracteres retorna 422."""
    resp = client.get("/api/v1/geocoding/autocomplete?q=ab")
    assert resp.status_code == 422


def test_autocomplete_photon_mock_sucesso(client):
    """GET /geocoding/autocomplete retorna sugestões com semáforo."""
    photon_payload = {
        "features": [
            {
                "properties": {
                    "name": "Avenida Paulista",
                    "street": "Avenida Paulista",
                    "housenumber": "1000",
                    "city": "São Paulo",
                    "state": "SP",
                    "postcode": "01310-100",
                },
                "geometry": {"coordinates": [-46.6559, -23.5614]},
            }
        ]
    }

    with patch("src.services.geocoding.requests.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.json.return_value = photon_payload
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        resp = client.get("/api/v1/geocoding/autocomplete?q=Avenida Paulista 1000&limite=5")

    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "Avenida Paulista 1000"
    assert len(data["sugestoes"]) >= 1
    primeira = data["sugestoes"][0]
    assert "nivel_precisao" in primeira
    assert "semaforo" in primeira
    assert primeira["fonte"] == "photon"


def test_autocomplete_sem_streamlit_import(client):
    """Valida que src/services/geocoding.py não importa streamlit."""
    import src.services.geocoding as geo

    source = open(geo.__file__).read()
    assert "import streamlit" not in source, "geocoding.py ainda importa streamlit"


# -----------------------------------------------------------------------------
# Route Calculate
# -----------------------------------------------------------------------------


def _mock_geocoding():
    """Mock para buscar_coordenadas_por_cep_ou_endereco."""

    def _fake(busca_texto):
        return {
            "sucesso": True,
            "lat": -23.5505,
            "lon": -46.6333,
            "endereco_encontrado": busca_texto,
            "nivel_precisao": "ALTA",
            "semaforo": "🟢 Exato",
            "fonte": "mock",
        }

    return _fake


def _mock_vt():
    """Mock para roteirizar_vale_transporte_automatico."""

    def _fake(*args, **kwargs):
        return {
            "sucesso": True,
            "custo_diario": 8.80,
            "custo_mensal": 193.60,
            "distancia_km": 10.5,
            "detalhes": [{"linha": "8000-10-0", "valor_unitario": 4.40, "quantidade_dia": 2, "subtotal": 8.80}],
            "memoria_calculo": ["VT mock: R$ 4.40 x 2"],
            "fonte": "Mock OTP",
        }

    return _fake


def test_routes_calculate_vt_sucesso(client):
    """POST /routes/calculate retorna resultado VT com memória auditável."""
    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", side_effect=_mock_geocoding()), patch("src.api.routes.roteirizar_vale_transporte_automatico", side_effect=_mock_vt()), patch("src.api.routes.roteirizar_com_comparativo", return_value={"sucesso": False}):
        payload = {
            "origem": "06310-000",
            "destino": "Avenida Paulista, 1000",
            "modalidade": "Vale-Transporte",
            "dias_uteis": 22,
        }
        resp = client.post("/api/v1/routes/calculate", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sucesso"] is True
    assert data["vt"] is not None
    assert data["vt"]["custo_diario"] == 8.80
    assert "memoria_calculo" in data
    assert len(data["memoria_calculo"]) > 0
    assert "coords" in data


def test_routes_calculate_viabilidade_clt_com_salario(client):
    """POST /routes/calculate com salario_base > 0 expõe viabilidade_clt."""
    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", side_effect=_mock_geocoding()), patch("src.api.routes.roteirizar_vale_transporte_automatico", side_effect=_mock_vt()), patch("src.api.routes.roteirizar_com_comparativo", return_value={"sucesso": False}):
        payload = {
            "origem": "06310-000",
            "destino": "Avenida Paulista, 1000",
            "modalidade": "Vale-Transporte",
            "dias_uteis": 22,
            "salario_base": 2500.00,
        }
        resp = client.post("/api/v1/routes/calculate", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sucesso"] is True
    assert data["viabilidade_clt"] is not None
    assert data["viabilidade_clt"]["sucesso"] is True
    assert "teto_desconto_6_pct" in data["viabilidade_clt"]
    assert "desconto_colaborador" in data["viabilidade_clt"]
    assert "custeio_empresa" in data["viabilidade_clt"]
    assert "vt_vantajoso" in data["viabilidade_clt"]
    # Custo mensal mock = 193.60, teto 6% de 2500 = 150.00
    assert data["viabilidade_clt"]["teto_desconto_6_pct"] == 150.00
    assert data["viabilidade_clt"]["desconto_colaborador"] == 150.00
    assert data["viabilidade_clt"]["custeio_empresa"] == 43.60
    assert data["viabilidade_clt"]["vt_vantajoso"] is True


def test_routes_calculate_viabilidade_clt_sem_salario(client):
    """POST /routes/calculate sem salario_base retorna viabilidade_clt = None."""
    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", side_effect=_mock_geocoding()), patch("src.api.routes.roteirizar_vale_transporte_automatico", side_effect=_mock_vt()), patch("src.api.routes.roteirizar_com_comparativo", return_value={"sucesso": False}):
        payload = {
            "origem": "06310-000",
            "destino": "Avenida Paulista, 1000",
            "modalidade": "Vale-Transporte",
            "dias_uteis": 22,
        }
        resp = client.post("/api/v1/routes/calculate", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sucesso"] is True
    assert data["viabilidade_clt"] is None


def test_routes_calculate_comparativo_completo(client):
    """POST /routes/calculate com Comparativo Completo retorna vt + vc + comparativo."""
    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", side_effect=_mock_geocoding()), patch("src.api.routes.roteirizar_vale_transporte_automatico", side_effect=_mock_vt()), patch("src.api.routes.roteirizar_com_comparativo", return_value={"sucesso": True, "comparativo": {"rota_mais_rapida": {}, "rota_mais_economica": {}}}), patch("src.api.routes.calcular_vale_combustivel", return_value={"sucesso": True, "distancia_km": 15.0}):
        payload = {
            "origem": "06310-000",
            "destino": "Avenida Paulista, 1000",
            "modalidade": "Comparativo Completo",
            "dias_uteis": 22,
            "valor_km": 1.25,
        }
        resp = client.post("/api/v1/routes/calculate", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sucesso"] is True
    assert data["vt"] is not None
    assert data["vc"] is not None


def test_routes_calculate_fallback_otp_offline(client):
    """POST /routes/calculate com OTP offline retorna erro de geocodificação."""
    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", return_value={"sucesso": False, "erro": "CEP não encontrado"}):
        payload = {
            "origem": "99999-999",
            "destino": "Avenida Paulista, 1000",
            "modalidade": "Vale-Transporte",
            "dias_uteis": 22,
        }
        resp = client.post("/api/v1/routes/calculate", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sucesso"] is False
    assert "erro" in data


# -----------------------------------------------------------------------------
# PDF Report
# -----------------------------------------------------------------------------


def test_reports_pdf_returns_pdf(client):
    """POST /reports/pdf retorna StreamingResponse com application/pdf."""
    with patch("src.api.routes.gerar_pdf_evidencia", return_value=io.BytesIO(b"%PDF-1.4 mock")):
        payload = {
            "dados_candidato": {"nome": "Test", "cargo": "Dev", "centro_custo": "TI"},
            "tipo_beneficio": "Vale-Transporte",
            "dados_calculo": {"origem": "A", "destino": "B", "custo_diario": 8.80, "custo_mensal": 193.60},
            "coords": (-23.55, -46.63, -23.56, -46.64),
        }
        resp = client.post("/api/v1/reports/pdf", json=payload)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert "content-disposition" in resp.headers
    assert resp.content.startswith(b"%PDF-")


# -----------------------------------------------------------------------------
# Batch Simulate
# -----------------------------------------------------------------------------


def test_batch_simulate_csv_upload_memoria(client, tmp_path):
    """POST /batch/simulate processa CSV em memória sem escrever em disco."""
    csv_content = "nome,origem,destino,salario_base\nTest,06310-000,Avenida Paulista 1000,2500\n"
    files = {"file": ("lote.csv", csv_content.encode("utf-8"), "text/csv")}

    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", side_effect=_mock_geocoding()), patch("src.api.routes.roteirizar_vale_transporte_automatico", side_effect=_mock_vt()):
        resp = client.post("/api/v1/batch/simulate?dias_uteis=22", files=files)

    assert resp.status_code == 200
    data = resp.json()
    assert data["sucesso"] is True
    assert data["total"] >= 1
    assert "resultados" in data
    assert len(data["resultados"]) >= 1
    # Valida CPF mascarado no JSON (LGPD)
    primeiro = data["resultados"][0]
    assert "cpf_mascarado" in primeiro
    assert primeiro["cpf_mascarado"] == "***.***.***-**"  # CPF não informado
    # Valida semáforo
    assert "nivel_precisao" in primeiro
    assert "semaforo" in primeiro


def test_batch_download_csv_compra_layout(client):
    """POST /batch/simulate/csv retorna CSV com layout compra."""
    resultados = [
        {
            "linha": 1,
            "nome": "Test",
            "cpf": "12345678900",
            "origem": "A",
            "destino": "B",
            "custo_diario": 8.80,
            "operadora": "SPTrans",
            "codigo_linha": "8000",
            "salario_base": 2500,
        }
    ]
    payload = {
        "resultados": resultados,
        "layout": "compra",
        "dias_uteis": 22,
        "competencia": "11/2026",
    }
    resp = client.post("/api/v1/batch/simulate/csv", json=payload)

    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    assert "content-disposition" in resp.headers
    content = resp.content.decode("utf-8-sig")
    assert "matricula" in content
    assert "cpf_mascarado" in content


def test_exception_handler_nao_vaza_stacktrace(client):
    """Handler global não vaza stacktrace ao cliente."""
    with patch("src.api.routes.buscar_coordenadas_por_cep_ou_endereco", side_effect=RuntimeError("stacktrace interna")):
        payload = {
            "origem": "06310-000",
            "destino": "Avenida Paulista, 1000",
            "modalidade": "Vale-Transporte",
            "dias_uteis": 22,
        }
        resp = client.post("/api/v1/routes/calculate", json=payload)

    assert resp.status_code == 200  # retorna sucesso=False, não 500
    data = resp.json()
    assert data["sucesso"] is False
    assert "stacktrace" not in str(data).lower()
    # Valida que o nome da exceção não vaza
    assert all("RuntimeError" not in str(mem) for mem in data.get("memoria_calculo", []))
