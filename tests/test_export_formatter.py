import io

import pandas as pd
import pytest

from src.services.export_formatter import gerar_export_compra, gerar_export_rubrica, mascarar_cpf


# ---------------------------------------------------------------------------
# mascarar_cpf
# ---------------------------------------------------------------------------
def test_mascarar_cpf_formatado():
    assert mascarar_cpf("123.456.789-00") == "***.456.789-**"
    assert mascarar_cpf("12345678900") == "***.456.789-**"


def test_mascarar_cpf_invalido():
    assert mascarar_cpf(None) == "***.***.***-**"
    assert mascarar_cpf("") == "***.***.***-**"
    assert mascarar_cpf("123") == "***.***.***-**"
    assert mascarar_cpf("abc.def.ghi-jk") == "***.***.***-**"


def test_mascarar_cpf_preserva_meio():
    # 987.654.321-00 -> meio 654.321
    assert mascarar_cpf("98765432100") == "***.654.321-**"


# ---------------------------------------------------------------------------
# gerar_export_compra — feliz
# ---------------------------------------------------------------------------
def _dados_compra_base():
    return pd.DataFrame([
        {"matricula": "001", "nome": "Maria Silva", "cpf": "12345678900", "operadora": "SPTrans", "codigo_linha": "N802", "valor_diario": 8.80},
        {"matricula": "002", "nome": "João Souza", "cpf": "98765432100", "valor_diario": "R$ 4,40", "codigo_linha": "175T"},
    ])


def test_export_compra_feliz_bytesio_utf8sig():
    df = _dados_compra_base()
    res = gerar_export_compra(df, dias_uteis=22)
    assert res["sucesso"] is True
    assert isinstance(res["bytesio"], io.BytesIO)
    assert res["bytesio"].getvalue().startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM
    res["bytesio"].seek(0)
    conteudo = res["bytesio"].getvalue().decode("utf-8-sig")
    assert "matricula" in conteudo
    assert "cpf_mascarado" in conteudo
    assert "***.456.789-**" in conteudo
    assert "***.654.321-**" in conteudo
    # valor_total = 8.80*22=193.60 e 4.40*22=96.80
    assert "193.60" in conteudo
    assert "96.80" in conteudo
    assert "22" in conteudo
    # LGPD: cpf em claro não pode aparecer
    assert "12345678900" not in conteudo
    assert "98765432100" not in conteudo
    # sem escrita em disco
    assert res["filename"].endswith(".csv")
    assert "memoria_calculo" in res and len(res["memoria_calculo"]) >= 2


def test_export_compra_com_lista_dict():
    dados = [{"nome": "Ana", "cpf": "11122233344", "valor_diario": 5.00}]
    res = gerar_export_compra(dados, dias_uteis=20)
    assert res["sucesso"] is True
    assert "100.00" in res["bytesio"].getvalue().decode("utf-8-sig")


def test_export_compra_colunas_alias_brasileiro():
    df = pd.DataFrame([{"nome": "Beto", "cpf": "12345678900", "valor_dia": "R$ 2.500,00"}])
    # valor com ponto milhar -> 2500*22
    res = gerar_export_compra(df, dias_uteis=22)
    assert res["sucesso"] is True
    assert "55000.00" in res["bytesio"].getvalue().decode("utf-8-sig")


def test_export_compra_operadora_default_sptrans():
    df = pd.DataFrame([{"nome": "Cida", "cpf": "12345678900", "valor_diario": 4.40}])
    res = gerar_export_compra(df, dias_uteis=10)
    assert res["sucesso"] is True
    assert "SPTrans" in res["bytesio"].getvalue().decode("utf-8-sig")


# ---------------------------------------------------------------------------
# gerar_export_compra — bordas e falhas
# ---------------------------------------------------------------------------
def test_export_compra_dias_uteis_invalido():
    df = _dados_compra_base()
    assert gerar_export_compra(df, dias_uteis=0)["sucesso"] is False
    assert gerar_export_compra(df, dias_uteis=32)["sucesso"] is False
    assert gerar_export_compra(df, dias_uteis="22")["sucesso"] is False


def test_export_compra_dados_vazios():
    assert gerar_export_compra(pd.DataFrame(), dias_uteis=22)["sucesso"] is False
    assert gerar_export_compra([], dias_uteis=22)["sucesso"] is False


def test_export_compra_coluna_nome_faltando():
    df = pd.DataFrame([{"cpf": "12345678900", "valor_diario": 5.00}])
    assert gerar_export_compra(df, dias_uteis=22)["sucesso"] is False


def test_export_compra_coluna_cpf_faltando():
    df = pd.DataFrame([{"nome": "Ana", "valor_diario": 5.00}])
    assert gerar_export_compra(df, dias_uteis=22)["sucesso"] is False


def test_export_compra_coluna_valor_faltando():
    df = pd.DataFrame([{"nome": "Ana", "cpf": "12345678900"}])
    assert gerar_export_compra(df, dias_uteis=22)["sucesso"] is False


def test_export_compra_tipo_dados_invalido():
    assert gerar_export_compra("invalido", dias_uteis=22)["sucesso"] is False


# ---------------------------------------------------------------------------
# gerar_export_rubrica — feliz
# ---------------------------------------------------------------------------
def test_export_rubrica_feliz_com_salario():
    dados = [
        {"matricula": "001", "nome": "Maria", "cpf": "12345678900", "valor_diario": 8.80, "salario_base": 3000.00},
        {"matricula": "002", "nome": "João", "cpf": "98765432100", "valor_diario": 4.40, "salario_base": 1500.00},
    ]
    res = gerar_export_rubrica(dados, dias_uteis=22)
    assert res["sucesso"] is True
    assert isinstance(res["bytesio"], io.BytesIO)
    conteudo = res["bytesio"].getvalue().decode("utf-8-sig")
    assert "rubrica_provento" in conteudo
    assert "901-VT Provento" in conteudo
    assert "902-VT Desconto 6%" in conteudo
    assert "***.456.789-**" in conteudo
    # provento Maria 193.60
    assert "193.60" in conteudo
    # CPF claro não aparece
    assert "12345678900" not in conteudo
    assert res["filename"].endswith(".csv")


def test_export_rubrica_sem_salario_desconto_zero():
    dados = [{"nome": "Ana", "cpf": "11122233344", "valor_diario": 5.00}]
    res = gerar_export_rubrica(dados, dias_uteis=20)
    assert res["sucesso"] is True
    conteudo = res["bytesio"].getvalue().decode("utf-8-sig")
    # desconto 6% zerado quando salario não informado
    assert "0.00" in conteudo
    assert "100.00" in conteudo  # provento 5*20


def test_export_rubrica_bytesio_utf8sig_e_seek0():
    dados = [{"nome": "Bia", "cpf": "12345678900", "valor_diario": 4.40}]
    res = gerar_export_rubrica(dados, dias_uteis=22)
    assert res["bytesio"].tell() == 0
    assert res["bytesio"].getvalue().startswith(b"\xef\xbb\xbf")


def test_export_rubrica_com_dataframe():
    df = pd.DataFrame([{"nome": "Carlos", "cpf": "12345678900", "valor_diario": 10.00, "salario_base": "R$ 2.500,00"}])
    res = gerar_export_rubrica(df, dias_uteis=22)
    assert res["sucesso"] is True
    # 10*22=220, teto 150, desconto 150
    conteudo = res["bytesio"].getvalue().decode("utf-8-sig")
    assert "220.00" in conteudo
    assert "150.00" in conteudo


# ---------------------------------------------------------------------------
# gerar_export_rubrica — bordas/falhas
# ---------------------------------------------------------------------------
def test_export_rubrica_dias_uteis_invalido():
    dados = [{"nome": "Ana", "cpf": "12345678900", "valor_diario": 5.00}]
    assert gerar_export_rubrica(dados, dias_uteis=0)["sucesso"] is False


def test_export_rubrica_dados_vazios():
    assert gerar_export_rubrica([], dias_uteis=22)["sucesso"] is False
    assert gerar_export_rubrica(pd.DataFrame(), dias_uteis=22)["sucesso"] is False


def test_export_rubrica_colunas_obrigatorias():
    assert gerar_export_rubrica([{"cpf": "123", "valor_diario": 5}], dias_uteis=22)["sucesso"] is False
    assert gerar_export_rubrica([{"nome": "Ana", "valor_diario": 5}], dias_uteis=22)["sucesso"] is False


def test_export_rubrica_tipo_invalido():
    assert gerar_export_rubrica("invalido", dias_uteis=22)["sucesso"] is False


def test_export_rubrica_competencia_custom():
    dados = [{"nome": "Ana", "cpf": "12345678900", "valor_diario": 5.00}]
    res = gerar_export_rubrica(dados, dias_uteis=22, competencia="03/2026")
    assert res["competencia"] == "03/2026"
    assert "03-2026" in res["filename"]


def test_export_compra_competencia_custom():
    df = _dados_compra_base()
    res = gerar_export_compra(df, dias_uteis=22, competencia="03/2026")
    assert res["competencia"] == "03/2026"
    assert "03-2026" in res["filename"]
