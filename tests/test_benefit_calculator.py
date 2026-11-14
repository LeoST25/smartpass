import pytest

from src.services.benefit_calculator import analisar_viabilidade_clt, parse_salario_brasileiro


def test_salario_omitido_none():
    res = analisar_viabilidade_clt(300.0, None)
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == 0.0
    assert res["desconto_colaborador"] == 0.0
    assert res["custeio_empresa"] == 0.0
    assert res["vt_vantajoso"] is False
    assert "não informado" in res["recomendacao"].lower()
    assert "memoria_calculo" in res
    assert "justificativa" in res


def test_salario_omitido_zero():
    res = analisar_viabilidade_clt(250.0, 0.0)
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == 0.0
    assert res["desconto_colaborador"] == 0.0
    assert res["custeio_empresa"] == 0.0
    assert res["vt_vantajoso"] is False


def test_salario_omitido_zero_string():
    res = analisar_viabilidade_clt(250.0, "0")
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == 0.0
    assert res["custeio_empresa"] == 0.0


def test_salario_baixo_empresa_subsidia():
    # custo 300, salario 1500 => teto 90, custeio 210, vt vantajoso
    res = analisar_viabilidade_clt(300.0, 1500.0)
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == pytest.approx(90.0)
    assert res["desconto_colaborador"] == pytest.approx(90.0)
    assert res["custeio_empresa"] == pytest.approx(210.0)
    assert res["vt_vantajoso"] is True
    assert "VT Vantajoso" in res["recomendacao"]
    assert "R$ 210.00" in res["recomendacao"]


def test_salario_alto_vt_desvantajoso():
    # custo 200, salario 10000 => teto 600, desconto 200, custeio 0, vt False
    res = analisar_viabilidade_clt(200.0, 10000.0)
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == pytest.approx(600.0)
    assert res["desconto_colaborador"] == pytest.approx(200.0)
    assert res["custeio_empresa"] == pytest.approx(0.0)
    assert res["vt_vantajoso"] is False
    assert "Alerta RH" in res["recomendacao"]


def test_teto_igual_custo_empate():
    res = analisar_viabilidade_clt(180.0, 3000.0)  # teto 180 == custo
    assert res["teto_desconto_6_pct"] == pytest.approx(180.0)
    assert res["desconto_colaborador"] == pytest.approx(180.0)
    assert res["custeio_empresa"] == pytest.approx(0.0)
    assert res["vt_vantajoso"] is False


def test_custo_zero():
    res = analisar_viabilidade_clt(0.0, 3000.0)
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == pytest.approx(180.0)
    assert res["desconto_colaborador"] == pytest.approx(0.0)
    assert res["custeio_empresa"] == pytest.approx(0.0)
    assert res["vt_vantajoso"] is False


def test_salario_negativo_erro():
    res = analisar_viabilidade_clt(200.0, -1000.0)
    assert res["sucesso"] is False
    assert "erro" in res


def test_custo_negativo_erro():
    res = analisar_viabilidade_clt(-50.0, 3000.0)
    assert res["sucesso"] is False
    assert "erro" in res


def test_rounding_precisao():
    # 3333.33 *0.06 = 200.00 (199.9998 -> 200.00)
    res = analisar_viabilidade_clt(250.0, 3333.33)
    assert res["teto_desconto_6_pct"] == pytest.approx(200.0)
    # custo 250 > 200 => vt vantajoso, custeio 50
    assert res["custeio_empresa"] == pytest.approx(50.0)


def test_parse_salario_brasileiro_formatos():
    assert parse_salario_brasileiro("R$ 2.500,00") == pytest.approx(2500.0)
    assert parse_salario_brasileiro("2.500,50") == pytest.approx(2500.50)
    assert parse_salario_brasileiro("2500.00") == pytest.approx(2500.0)
    assert parse_salario_brasileiro("  R$ 1.200,00  ") == pytest.approx(1200.0)
    assert parse_salario_brasileiro(None) is None
    assert parse_salario_brasileiro("") is None


def test_custo_string_brasileiro():
    res = analisar_viabilidade_clt("R$ 300,00", "R$ 1.500,00")
    assert res["sucesso"] is True
    assert res["teto_desconto_6_pct"] == pytest.approx(90.0)
    assert res["custeio_empresa"] == pytest.approx(210.0)


def test_memoria_calculo_presente():
    res = analisar_viabilidade_clt(300, 1500)
    assert isinstance(res["memoria_calculo"], list)
    assert len(res["memoria_calculo"]) >= 3
    assert any("Lei 7.418" in m for m in res["memoria_calculo"])
