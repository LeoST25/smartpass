import pytest

from src.services.calendar_engine import calcular_dias_uteis, listar_feriados, _pascoa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_feriado_descontado(res, iso_date):
    return any(f["data"] == iso_date for f in res["feriados_descontados"])


# ---------------------------------------------------------------------------
# listar_feriados — cobertura nacional 20/11 e móveis
# ---------------------------------------------------------------------------
def test_listar_feriados_inclui_20_11_lei_14759():
    res = listar_feriados(2026, "SP", "São Paulo")
    assert res["sucesso"] is True
    datas = [f["data"] for f in res["feriados"]]
    # 20/11 deve existir
    assert any(d.month == 11 and d.day == 20 for d in datas)
    # 20/11 tipo nacional_fixo
    f20 = [f for f in res["feriados"] if f["data"].month == 11 and f["data"].day == 20][0]
    assert f20["tipo"] == "nacional_fixo"
    assert "14.759" in f20["nome"] or "Consciência Negra" in f20["nome"]


def test_listar_feriados_moveis_carnaval_sexta_corpus():
    # 2026: Pascoa 05/04 => Carnaval 17/02, Sexta 03/04, Corpus 04/06
    res = listar_feriados(2026, "SP", "São Paulo", considerar_ponto_facultativo=True)
    assert res["sucesso"] is True
    datas = {f["data"].isoformat(): f["nome"] for f in res["feriados"]}
    assert "2026-02-17" in datas  # carnaval
    assert "2026-04-03" in datas  # sexta
    assert "2026-06-04" in datas  # corpus


def test_listar_feriados_sem_ponto_facultativo():
    res_true = listar_feriados(2026, "SP", "São Paulo", considerar_ponto_facultativo=True)
    res_false = listar_feriados(2026, "SP", "São Paulo", considerar_ponto_facultativo=False)
    # com True tem carnaval, sem tem menos 1 (carnaval)
    assert len(res_true["feriados"]) == len(res_false["feriados"]) + 1
    assert not any(f["data"].isoformat() == "2026-02-17" for f in res_false["feriados"])


def test_listar_feriados_municipal_sp_only_when_sp():
    res_sp = listar_feriados(2026, "SP", "São Paulo")
    res_rj = listar_feriados(2026, "RJ", "São Paulo")
    # SP tem 25/01 municipal, RJ não
    assert any(f["tipo"] == "municipal" and f["data"].month == 1 and f["data"].day == 25 for f in res_sp["feriados"])
    assert not any(f["tipo"] == "municipal" for f in res_rj["feriados"])


def test_listar_feriados_alphaville_mapeado_barueri():
    res = listar_feriados(2026, "SP", "Alphaville")
    assert res["sucesso"] is True
    assert any(f["tipo"] == "municipal" and f["data"].month == 3 and f["data"].day == 11 for f in res["feriados"])


# ---------------------------------------------------------------------------
# calcular_dias_uteis — 5x2 feliz e feriados municipais Grande SP
# ---------------------------------------------------------------------------
def test_5x2_janeiro_sp_2026_desconta_25_01_domingo_nao_desconta():
    # Jan 2026: 25/01 cai domingo -> não deve descontar em 5x2 (Seg-Sex)
    res = calcular_dias_uteis(2026, 1, "5x2", "SP", "São Paulo")
    assert res["sucesso"] is True
    assert res["escala"] == "5x2"
    # dias brutos Seg-Sex em jan 2026: 22? Jan 2026 tem 31 dias, 1/1 qui, conta: 22
    assert res["dias_brutos"] == 22
    # 25/01 domingo não está em brutos, então 0 descontados? mas 01/01 qui desconta
    # 01/01/2026 qui -> desconta 1
    assert _is_feriado_descontado(res, "2026-01-01")
    assert not _is_feriado_descontado(res, "2026-01-25")
    assert res["dias_uteis"] == 21
    assert "memoria_calculo" in res and len(res["memoria_calculo"]) >= 2


def test_5x2_janeiro_carapicuiba_vs_sp_diferenca_25_01():
    # Carapicuíba não tem 25/01, então mesmo resultado que SP em jan (25/01 dom)
    # Mas testa que lista municipal difere
    res_sp = calcular_dias_uteis(2026, 1, "5x2", "SP", "São Paulo")
    res_car = calcular_dias_uteis(2026, 1, "5x2", "SP", "Carapicuíba")
    # ambos 01/01 descontado, nenhum 25/01
    assert res_sp["dias_uteis"] == res_car["dias_uteis"]
    # verifica feriados_mes contém municipal correto
    assert any("Carapicuíba" in f["nome"] for f in res_car["feriados_mes"]) is False  # jan sem carapicuíba
    # testa março onde Carapicuíba tem 26/03
    res_car_mar = calcular_dias_uteis(2026, 3, "5x2", "SP", "Carapicuíba")
    res_sp_mar = calcular_dias_uteis(2026, 3, "5x2", "SP", "São Paulo")
    # 26/03/2026 qui -> desconta só para Carapicuíba
    assert _is_feriado_descontado(res_car_mar, "2026-03-26")
    assert not _is_feriado_descontado(res_sp_mar, "2026-03-26")
    assert res_car_mar["dias_uteis"] == res_sp_mar["dias_uteis"] - 1


def test_5x2_marco_osasco_19_02_nao_afeta_marco():
    # Osasco 19/02 -> fev, não afeta março
    res = calcular_dias_uteis(2026, 3, "5x2", "SP", "Osasco")
    assert res["sucesso"] is True
    assert not _is_feriado_descontado(res, "2026-02-19")
    # março sem feriado Osasco
    assert all(f["data"] != "2026-02-19" for f in res["feriados_descontados"])


def test_5x2_fevereiro_osasco_19_02_quinta_desconta():
    # 19/02/2026 qui -> Osasco desconta
    res_osa = calcular_dias_uteis(2026, 2, "5x2", "SP", "Osasco")
    res_sp = calcular_dias_uteis(2026, 2, "5x2", "SP", "São Paulo")
    assert _is_feriado_descontado(res_osa, "2026-02-19")
    assert not _is_feriado_descontado(res_sp, "2026-02-19")
    assert res_osa["dias_uteis"] == res_sp["dias_uteis"] - 1


def test_5x2_barueri_11_03_e_alphaville_equivalentes():
    res_bar = calcular_dias_uteis(2026, 3, "5x2", "SP", "Barueri")
    res_alpha = calcular_dias_uteis(2026, 3, "5x2", "SP", "Alphaville")
    assert res_bar["dias_uteis"] == res_alpha["dias_uteis"]
    assert _is_feriado_descontado(res_bar, "2026-03-11")
    assert _is_feriado_descontado(res_alpha, "2026-03-11")


def test_5x2_cotia_02_04_desconta_abril():
    res_cotia = calcular_dias_uteis(2026, 4, "5x2", "SP", "Cotia")
    res_sp = calcular_dias_uteis(2026, 4, "5x2", "SP", "São Paulo")
    # 02/04/2026 qui -> Cotia desconta
    assert _is_feriado_descontado(res_cotia, "2026-04-02")
    assert not _is_feriado_descontado(res_sp, "2026-04-02")
    assert res_cotia["dias_uteis"] == res_sp["dias_uteis"] - 1


def test_5x2_novembro_20_11_desconta_2026():
    # 20/11/2026 sex -> 5x2 desconta nacional fixo novo
    res = calcular_dias_uteis(2026, 11, "5x2", "SP", "São Paulo")
    assert _is_feriado_descontado(res, "2026-11-20")
    # novembro 2026 tem 21 dias Seg-Sex brutos, desconta 02/11 seg, 15/11 dom(não), 20/11 sex => 2 descontados? 02/11 seg desconta, 20/11 desconta => 19?
    assert res["dias_uteis"] == res["dias_brutos"] - len(res["feriados_descontados"])
    assert any("20/11" in m or "2026-11-20" in m for m in res["memoria_calculo"])


# ---------------------------------------------------------------------------
# 6x1
# ---------------------------------------------------------------------------
def test_6x1_folga_domingo_fevereiro_2026():
    # Fev 2026: 28 dias, 4 domingos => 24 brutos; com ponto facultativo True, Carnaval 17/02 também desconta
    res = calcular_dias_uteis(2026, 2, "6x1", "SP", "São Paulo")
    assert res["sucesso"] is True
    assert res["escala"] == "6x1"
    assert res["dias_brutos"] == 24
    # São Paulo: desconta Carnaval 17/02 => 23
    assert _is_feriado_descontado(res, "2026-02-17")
    assert res["dias_uteis"] == 23
    # Osasco: desconta Carnaval 17/02 + 19/02 => 22
    res_osa = calcular_dias_uteis(2026, 2, "6x1", "SP", "Osasco")
    assert _is_feriado_descontado(res_osa, "2026-02-19")
    assert res_osa["dias_brutos"] == 24
    assert res_osa["dias_uteis"] == 22


def test_6x1_feriado_na_folga_nao_desconta():
    # 11/03/2026 qua -> Barueri; se folga=qua (3) então não desconta
    res_folga_qua = calcular_dias_uteis(2026, 3, "6x1", "SP", "Barueri", dia_folga_semana=2)  # qua=2
    res_folga_dom = calcular_dias_uteis(2026, 3, "6x1", "SP", "Barueri", dia_folga_semana=6)
    # folga qua: 11/03 cai na folga => não descontado
    assert not _is_feriado_descontado(res_folga_qua, "2026-03-11")
    assert _is_feriado_descontado(res_folga_dom, "2026-03-11")


def test_6x1_custom_folga_sabado():
    res = calcular_dias_uteis(2026, 1, "6x1", "SP", "São Paulo", dia_folga_semana=5)
    # folga sábado -> brutos = 31 - 5 sábados jan2026? Jan 2026: sáb 3,10,17,24,31 =>5 =>26
    assert res["dias_brutos"] == 26


# ---------------------------------------------------------------------------
# 12x36
# ---------------------------------------------------------------------------
def test_12x36_dia1_trabalhado_janeiro_2026():
    res = calcular_dias_uteis(2026, 1, "12x36", "SP", "São Paulo", dia_inicio_escala=1)
    assert res["sucesso"] is True
    assert res["escala"] == "12x36"
    # jan 31 dias, inicio 1 => ímpares trabalhados =16
    assert res["dias_brutos"] == 16
    # 01/01 ímpar trabalhado desconta
    assert _is_feriado_descontado(res, "2026-01-01")


def test_12x36_dia2_trabalhado_inverte():
    res1 = calcular_dias_uteis(2026, 1, "12x36", "SP", "São Paulo", dia_inicio_escala=1)
    res2 = calcular_dias_uteis(2026, 1, "12x36", "SP", "São Paulo", dia_inicio_escala=2)
    # inicio2 => pares trabalhados => 15 em jan (30 dias? 31->15 pares)
    assert res2["dias_brutos"] == 15
    assert res1["dias_brutos"] != res2["dias_brutos"]
    # 01/01 não é trabalhado quando inicio 2 => não descontado
    assert not _is_feriado_descontado(res2, "2026-01-01")


def test_12x36_fevereiro_media_14():
    res = calcular_dias_uteis(2026, 2, "12x36", "SP", "São Paulo", dia_inicio_escala=1)
    # fev 28 dias inicio1 => 14
    assert res["dias_brutos"] == 14


# ---------------------------------------------------------------------------
# Híbrido 3x2
# ---------------------------------------------------------------------------
def test_hibrido_3x2_seg_qua_janeiro_2026():
    res = calcular_dias_uteis(2026, 1, "Híbrido", "SP", "São Paulo", dias_presenciais=(0, 1, 2))
    assert res["escala"] == "hibrido"
    # jan 2026: Seg 5,12,19,26=4, Ter 6,13,20,27=4, Qua 7,14,21,28=4 =>12 brutos
    assert res["dias_brutos"] == 12
    # 01/01 qui não é presencial => não descontado
    assert not _is_feriado_descontado(res, "2026-01-01")


def test_hibrido_3x2_alias_3x2_e_hibrido():
    res_a = calcular_dias_uteis(2026, 1, "3x2", "SP", "São Paulo")
    res_b = calcular_dias_uteis(2026, 1, "Híbrido 3x2", "SP", "São Paulo")
    assert res_a["escala"] == "hibrido"
    assert res_b["escala"] == "hibrido"
    assert res_a["dias_uteis"] == res_b["dias_uteis"]


def test_hibrido_custom_dias_presenciais():
    # Qui-Sex-Sáb
    res = calcular_dias_uteis(2026, 1, "Híbrido", "SP", "São Paulo", dias_presenciais=(3, 4, 5))
    # Qui 1,8,15,22,29=5, Sex2,9,16,23,30=5, Sab3,10,17,24,31=5 =>15
    assert res["dias_brutos"] == 15
    # 01/01 qui presencial -> desconta
    assert _is_feriado_descontado(res, "2026-01-01")


# ---------------------------------------------------------------------------
# Override manual
# ---------------------------------------------------------------------------
def test_override_manual_prevalece():
    res = calcular_dias_uteis(2026, 1, "5x2", "SP", "São Paulo", dias_override=15)
    assert res["sucesso"] is True
    assert res["dias_uteis"] == 15
    assert res["dias_override_aplicado"] is True
    assert any("Override" in m for m in res["memoria_calculo"])


def test_override_zero_permitido():
    res = calcular_dias_uteis(2026, 1, "5x2", "SP", "São Paulo", dias_override=0)
    assert res["sucesso"] is True
    assert res["dias_uteis"] == 0


# ---------------------------------------------------------------------------
# Bordas e falhas
# ---------------------------------------------------------------------------
def test_ano_invalido():
    res = calcular_dias_uteis(1800, 1, "5x2", "SP", "São Paulo")
    assert res["sucesso"] is False
    assert "memoria_calculo" in res


def test_mes_invalido():
    res = calcular_dias_uteis(2026, 13, "5x2", "SP", "São Paulo")
    assert res["sucesso"] is False


def test_escala_invalida():
    res = calcular_dias_uteis(2026, 1, "9x9", "SP", "São Paulo")
    assert res["sucesso"] is False


def test_override_fora_limite():
    res = calcular_dias_uteis(2026, 1, "5x2", "SP", "São Paulo", dias_override=99)
    assert res["sucesso"] is False


def test_override_nao_numerico():
    res = calcular_dias_uteis(2026, 1, "5x2", "SP", "São Paulo", dias_override="abc")
    assert res["sucesso"] is False


def test_uf_vazia_sem_municipal():
    res = calcular_dias_uteis(2026, 1, "5x2", "", "São Paulo")
    assert res["sucesso"] is True
    # sem UF SP não aplica municipal, mas 01/01 nacional ainda desconta
    assert _is_feriado_descontado(res, "2026-01-01")
    assert not _is_feriado_descontado(res, "2026-01-25")


def test_fevereiro_bissexto_2024_5x2():
    res = calcular_dias_uteis(2024, 2, "5x2", "SP", "São Paulo")
    assert res["sucesso"] is True
    # fev 2024 bissexto 29 dias, 1/2 qui => Seg-Sex 21?
    assert res["dias_brutos"] == 21


def test_considerar_ponto_facultativo_false_remove_carnaval():
    res_true = calcular_dias_uteis(2026, 2, "5x2", "SP", "São Paulo", considerar_ponto_facultativo=True)
    res_false = calcular_dias_uteis(2026, 2, "5x2", "SP", "São Paulo", considerar_ponto_facultativo=False)
    # Carnaval 17/02 ter -> 5x2 desconta quando True
    assert _is_feriado_descontado(res_true, "2026-02-17")
    assert not _is_feriado_descontado(res_false, "2026-02-17")


def test_memoria_justificativa_sempre_presente():
    res = calcular_dias_uteis(2026, 3, "5x2", "SP", "Barueri")
    assert "memoria_calculo" in res and isinstance(res["memoria_calculo"], list)
    assert "justificativa" in res and isinstance(res["justificativa"], str)
    assert any("Barueri" in m or "barueri" in m.lower() for m in res["memoria_calculo"]) or "11/03" in str(res["memoria_calculo"])


def test_pascoa_2026():
    assert _pascoa(2026).isoformat() == "2026-04-05"


def test_normalizacao_municipio_acentos_e_caixa():
    r1 = calcular_dias_uteis(2026, 3, "5x2", "sp", "são paulo")
    r2 = calcular_dias_uteis(2026, 3, "5x2", "SP", "SAO PAULO")
    assert r1["dias_uteis"] == r2["dias_uteis"]
    assert r1["municipio_normalizado"] == r2["municipio_normalizado"]


def test_feriados_moveis_sexta_e_corpus_2026_5x2_descontam():
    # Sexta 03/04 sex -> 5x2 desconta
    res = calcular_dias_uteis(2026, 4, "5x2", "SP", "São Paulo")
    assert _is_feriado_descontado(res, "2026-04-03")
    # Corpus 04/06 qui -> 5x2 desconta
    res_jun = calcular_dias_uteis(2026, 6, "5x2", "SP", "São Paulo")
    assert _is_feriado_descontado(res_jun, "2026-06-04")
