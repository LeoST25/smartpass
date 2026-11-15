"""Motor de calendário — cálculo de dias úteis por escala e município (LGPD stateless).

Regras:
- Escalas suportadas: 5x2, 6x1, 12x36, Híbrido 3x2 (Seg-Qua).
- Desconta feriados nacionais fixos (inclui 20/11 Lei 14.759/2023) + móveis
  (Carnaval, Sexta Santa, Corpus Christi) + municipais Grande SP
  (São Paulo 25/01, Carapicuíba 26/03, Osasco 19/02, Barueri 11/03 incl. Alphaville, Cotia 02/04).
- Feriado municipal aplicado apenas quando uf==SP e município_destino coincide.
- Override manual: dias_override tem precedência mas gera auditoria.
- Parâmetros opcionais: dia_inicio_escala, dia_folga_semana, dias_presenciais, considerar_ponto_facultativo.
- Retorno padronizado {"sucesso": True/False} com memoria_calculo/justificativa para UI e PDF.
- Sem I/O em disco; puro cálculo em memória.
"""

from __future__ import annotations

import calendar
import unicodedata
from datetime import date, timedelta


# ---------------------------------------------------------------------------
# Helpers de normalização
# ---------------------------------------------------------------------------
def _normalizar_municipio(nome: str) -> str:
    """Normaliza município: lower, sem acento, trim. Alphaville -> barueri."""
    if not nome:
        return ""
    s = str(nome).strip().lower()
    # remove acentos
    s = "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")
    s = " ".join(s.split())
    if s == "alphaville":
        return "barueri"
    return s


def _normalizar_escala(escala: str) -> str | None:
    if not escala:
        return None
    s = str(escala).strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    # aliases
    mapping = {
        "5x2": "5x2",
        "5x2": "5x2",
        "6x1": "6x1",
        "12x36": "12x36",
        "12x3636": "12x36",
        "hibrido": "hibrido",
        "híbrido": "hibrido",
        "3x2": "hibrido",
        "hibrido3x2": "hibrido",
        "híbrido3x2": "hibrido",
    }
    # tenta direto
    if s in mapping:
        return mapping[s]
    # variações com parênteses
    if "hibrido" in s or "3x2" in s:
        return "hibrido"
    return None


def _pascoa(ano: int) -> date:
    """Algoritmo Anonymous Gregorian — calcula Domingo de Páscoa."""
    a = ano % 19
    b = ano // 100
    c = ano % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = ((h + l - 7 * m + 114) % 31) + 1
    return date(ano, mes, dia)


# ---------------------------------------------------------------------------
# Feriados
# ---------------------------------------------------------------------------
_FERIADOS_FIXOS_NACIONAIS = [
    (1, 1, "Confraternização Universal"),
    (4, 21, "Tiradentes"),
    (5, 1, "Dia do Trabalho"),
    (9, 7, "Independência do Brasil"),
    (10, 12, "Nossa Senhora Aparecida"),
    (11, 2, "Finados"),
    (11, 15, "Proclamação da República"),
    (11, 20, "Dia Nacional de Zumbi e da Consciência Negra (Lei 14.759/2023)"),
    (12, 25, "Natal"),
]

_FERIADOS_MUNICIPAIS_SP = {
    "sao paulo": (1, 25, "Aniversário de São Paulo"),
    "carapicuiba": (3, 26, "Aniversário de Carapicuíba"),
    "osasco": (2, 19, "Aniversário de Osasco"),
    "barueri": (3, 11, "Aniversário de Barueri (Alphaville)"),
    "cotia": (4, 2, "Aniversário de Cotia"),
}


def listar_feriados(
    ano: int,
    uf: str,
    municipio_destino: str,
    considerar_ponto_facultativo: bool = True,
) -> dict:
    """Lista feriados aplicáveis para o ano/UF/município.

    Args:
        ano: Ano de referência.
        uf: UF da unidade (ex: "SP"). Apenas SP aplica municipais Grande SP.
        municipio_destino: Município da unidade (grande SP).
        considerar_ponto_facultativo: Quando True inclui Carnaval, Sexta e Corpus.

    Returns:
        dict: {"sucesso": bool, "feriados": list[dict], "memoria_calculo": [...]}
    """
    try:
        if not isinstance(ano, int) or ano < 1900 or ano > 2100:
            return {"sucesso": False, "erro": "Ano inválido (1900-2100).", "memoria_calculo": ["Falha: ano fora do intervalo 1900-2100."]}
        uf_n = str(uf or "").strip().upper()
        mun_n = _normalizar_municipio(municipio_destino)

        feriados: list[dict] = []

        # Fixos nacionais
        for mes, dia, nome in _FERIADOS_FIXOS_NACIONAIS:
            try:
                d = date(ano, mes, dia)
                feriados.append({"data": d, "nome": nome, "tipo": "nacional_fixo", "mes": mes, "dia": dia})
            except ValueError:
                continue

        # Móveis
        try:
            pascoa = _pascoa(ano)
            carnaval = pascoa - timedelta(days=47)
            sexta = pascoa - timedelta(days=2)
            corpus = pascoa + timedelta(days=60)
            if considerar_ponto_facultativo:
                feriados.append({"data": carnaval, "nome": "Carnaval (ponto facultativo RMSP)", "tipo": "nacional_movel", "mes": carnaval.month, "dia": carnaval.day})
                feriados.append({"data": sexta, "nome": "Sexta-feira Santa", "tipo": "nacional_movel", "mes": sexta.month, "dia": sexta.day})
                feriados.append({"data": corpus, "nome": "Corpus Christi (ponto facultativo RMSP)", "tipo": "nacional_movel", "mes": corpus.month, "dia": corpus.day})
            else:
                # sem ponto facultativo: apenas Sexta e Corpus mantidos
                feriados.append({"data": sexta, "nome": "Sexta-feira Santa", "tipo": "nacional_movel", "mes": sexta.month, "dia": sexta.day})
                feriados.append({"data": corpus, "nome": "Corpus Christi", "tipo": "nacional_movel", "mes": corpus.month, "dia": corpus.day})
        except Exception:
            pass

        # Municipais Grande SP — apenas se UF SP
        if uf_n == "SP" and mun_n:
            info = _FERIADOS_MUNICIPAIS_SP.get(mun_n)
            if info:
                mes_m, dia_m, nome_m = info
                try:
                    d = date(ano, mes_m, dia_m)
                    feriados.append({"data": d, "nome": nome_m, "tipo": "municipal", "mes": mes_m, "dia": dia_m})
                except ValueError:
                    pass

        feriados.sort(key=lambda x: x["data"])
        memoria = [f"Feriados {ano} UF={uf_n} município={municipio_destino or '—'}: {len(feriados)} aplicáveis (inclui 20/11 Lei 14.759/2023)."]
        return {"sucesso": True, "feriados": feriados, "memoria_calculo": memoria, "justificativa": f"{len(feriados)} feriados aplicáveis para {ano}."}
    except Exception as exc:
        return {"sucesso": False, "erro": str(exc), "memoria_calculo": [f"Falha ao listar feriados: {exc}"], "justificativa": "Erro ao listar feriados."}


def calcular_dias_uteis(
    ano: int,
    mes: int,
    escala: str,
    uf: str,
    municipio_destino: str,
    dias_override: int | None = None,
    dia_inicio_escala: int = 1,
    dia_folga_semana: int = 6,
    dias_presenciais: tuple[int, ...] = (0, 1, 2),
    considerar_ponto_facultativo: bool = True,
) -> dict:
    """Calcula dias úteis por escala descontando feriados.

    Args:
        ano: Ano (1900-2100).
        mes: Mês 1-12.
        escala: Uma de "5x2", "6x1", "12x36", "Híbrido" / "3x2".
        uf: UF da unidade (ex: "SP"). Filtra municipais Grande SP.
        municipio_destino: Município da unidade (ex: "São Paulo", "Carapicuíba", "Alphaville").
        dias_override: Quando informado, sobrescreve cálculo (auditoria).
        dia_inicio_escala: Para 12x36 — dia do mês trabalhado por padrão (1).
        dia_folga_semana: Para 6x1 — weekday da folga (0=Seg ... 6=Dom).
        dias_presenciais: Para Híbrido 3x2 — weekdays presenciais (default Seg-Qua 0,1,2).
        considerar_ponto_facultativo: Se True considera Carnaval/Sexta/Corpus.

    Returns:
        dict: Em sucesso {"sucesso": True, "dias_uteis": int, "dias_brutos": int,
            "feriados_descontados": list[dict], "escala": str, "uf": str,
            "municipio_destino": str, "ano": int, "mes": int,
            "memoria_calculo": list[str], "justificativa": str,
            "dias_override_aplicado": bool}
            Em falha {"sucesso": False, "erro": str, "memoria_calculo": [...]}
    """
    try:
        # Validação ano/mes
        if not isinstance(ano, int) or ano < 1900 or ano > 2100:
            return {"sucesso": False, "erro": "Ano inválido: informe 1900-2100.", "memoria_calculo": [f"Falha: ano {ano} inválido (1900-2100)."], "justificativa": "Ano inválido."}
        if not isinstance(mes, int) or mes < 1 or mes > 12:
            return {"sucesso": False, "erro": "Mês inválido: informe 1-12.", "memoria_calculo": [f"Falha: mês {mes} inválido."], "justificativa": "Mês inválido."}

        escala_norm = _normalizar_escala(escala)
        if escala_norm is None:
            return {"sucesso": False, "erro": f"Escala inválida '{escala}': use 5x2, 6x1, 12x36 ou Híbrido 3x2.", "memoria_calculo": [f"Falha: escala '{escala}' não reconhecida."], "justificativa": "Escala inválida."}

        # Valida dia_folga e dias_presenciais
        if not isinstance(dia_folga_semana, int) or dia_folga_semana < 0 or dia_folga_semana > 6:
            dia_folga_semana = 6
        if not isinstance(dias_presenciais, (tuple, list)) or not dias_presenciais:
            dias_presenciais = (0, 1, 2)
        else:
            dias_presenciais = tuple(int(d) for d in dias_presenciais if 0 <= int(d) <= 6)
            if not dias_presenciais:
                dias_presenciais = (0, 1, 2)

        if not isinstance(dia_inicio_escala, int) or dia_inicio_escala < 1 or dia_inicio_escala > 31:
            dia_inicio_escala = 1

        # Override validação prévia
        if dias_override is not None:
            try:
                dias_override = int(dias_override)
            except Exception:
                return {"sucesso": False, "erro": "dias_override deve ser inteiro.", "memoria_calculo": ["Falha: dias_override não numérico."], "justificativa": "Override inválido."}
            if dias_override < 0 or dias_override > 31:
                return {"sucesso": False, "erro": "dias_override fora do intervalo 0-31.", "memoria_calculo": [f"Falha: dias_override {dias_override} fora de 0-31."], "justificativa": "Override fora do limite."}

        uf_n = str(uf or "").strip().upper() if uf else ""
        mun_orig = str(municipio_destino or "").strip()
        mun_n = _normalizar_municipio(mun_orig)

        # Datas do mês
        dias_no_mes = calendar.monthrange(ano, mes)[1]
        datas_mes = [date(ano, mes, d) for d in range(1, dias_no_mes + 1)]

        # Feriados aplicáveis
        res_fer = listar_feriados(ano, uf_n, mun_orig, considerar_ponto_facultativo=considerar_ponto_facultativo)
        if not res_fer.get("sucesso"):
            return {"sucesso": False, "erro": res_fer.get("erro", "Falha ao listar feriados."), "memoria_calculo": res_fer.get("memoria_calculo", []), "justificativa": "Falha ao obter feriados."}
        feriados: list[dict] = res_fer.get("feriados", [])
        feriados_set = {f["data"] for f in feriados}
        # mapa data->nome para auditoria
        feriado_nome = {f["data"]: f["nome"] + f" ({f['tipo']})" for f in feriados}

        dias_brutos = 0
        feriados_descontados: list[dict] = []
        memoria: list[str] = []

        if escala_norm == "5x2":
            # Seg-Sex
            brutos_list = [d for d in datas_mes if d.weekday() < 5]
            dias_brutos = len(brutos_list)
            for d in brutos_list:
                if d in feriados_set:
                    feriados_descontados.append({"data": d.isoformat(), "nome": feriado_nome[d], "data_obj": d})
            dias_uteis = dias_brutos - len(feriados_descontados)
            memoria.append(f"Escala 5x2 (Seg-Sex): {dias_brutos} dias de semana no mês {mes:02d}/{ano}.")
            if feriados_descontados:
                nomes = ", ".join(f"{x['data']} {x['nome']}" for x in feriados_descontados)
                memoria.append(f"Feriados descontados ({len(feriados_descontados)}): {nomes}.")
            else:
                memoria.append("Nenhum feriado em dia de semana no mês — sem desconto.")

        elif escala_norm == "6x1":
            # 6 trabalhados 1 folga fixa
            brutos_list = [d for d in datas_mes if d.weekday() != dia_folga_semana]
            dias_brutos = len(brutos_list)
            for d in brutos_list:
                if d in feriados_set:
                    feriados_descontados.append({"data": d.isoformat(), "nome": feriado_nome[d], "data_obj": d})
            dias_uteis = dias_brutos - len(feriados_descontados)
            folga_nome = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][dia_folga_semana]
            memoria.append(f"Escala 6x1 (folga fixa {folga_nome}): {dias_brutos} dias trabalhados brutos no mês {mes:02d}/{ano} (desconta folgas semanais).")
            if feriados_descontados:
                nomes = ", ".join(f"{x['data']} {x['nome']}" for x in feriados_descontados)
                memoria.append(f"Feriados em dia de trabalho descontados ({len(feriados_descontados)}): {nomes}. Feriado na folga não desconta.")
            else:
                memoria.append("Nenhum feriado em dia de trabalho — sem desconto adicional.")

        elif escala_norm == "12x36":
            # Ciclo 48h — dia_inicio_escala trabalhado
            brutos_list = []
            for d in datas_mes:
                dia_num = d.day
                # trabalhado se (dia - inicio) %2 ==0
                if (dia_num - dia_inicio_escala) % 2 == 0:
                    brutos_list.append(d)
            dias_brutos = len(brutos_list)
            for d in brutos_list:
                if d in feriados_set:
                    feriados_descontados.append({"data": d.isoformat(), "nome": feriado_nome[d], "data_obj": d})
            # Para VT: feriado em dia de escala ainda conta como deslocamento; desconta por padrão conforme regra solicitada
            dias_uteis = dias_brutos - len(feriados_descontados)
            memoria.append(f"Escala 12x36 (ciclo 48h, dia {dia_inicio_escala} trabalhado): {dias_brutos} dias brutos no mês {mes:02d}/{ano} (média 15-16/mês).")
            if feriados_descontados:
                nomes = ", ".join(f"{x['data']} {x['nome']}" for x in feriados_descontados)
                memoria.append(f"Feriados coincidentes com dia de escala descontados ({len(feriados_descontados)}): {nomes}. Ajuste: VT não pago em feriado de escala.")
            else:
                memoria.append("Nenhum feriado coincidiu com dia de escala — sem desconto.")
            memoria.append("Nota: 12x36 em feriado trabalhado normalmente recebe em dobro; para VT o dia é descontado (sem deslocamento).")

        elif escala_norm == "hibrido":
            # 3 presenciais/semana
            brutos_list = [d for d in datas_mes if d.weekday() in dias_presenciais]
            dias_brutos = len(brutos_list)
            for d in brutos_list:
                if d in feriados_set:
                    feriados_descontados.append({"data": d.isoformat(), "nome": feriado_nome[d], "data_obj": d})
            dias_uteis = dias_brutos - len(feriados_descontados)
            dias_nome = [["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][x] for x in dias_presenciais]
            memoria.append(f"Escala Híbrida 3x2 (presencial {', '.join(dias_nome)}): {dias_brutos} dias presenciais brutos no mês {mes:02d}/{ano}.")
            if feriados_descontados:
                nomes = ", ".join(f"{x['data']} {x['nome']}" for x in feriados_descontados)
                memoria.append(f"Feriados em dia presencial descontados ({len(feriados_descontados)}): {nomes}.")
            else:
                memoria.append("Nenhum feriado em dia presencial — sem desconto.")
            memoria.append("VT devido apenas nos dias presenciais (3/semana); home office não gera VT.")

        else:
            return {"sucesso": False, "erro": "Escala não suportada.", "memoria_calculo": ["Falha: escala não mapeada."], "justificativa": "Escala não suportada."}

        # Detalhe feriados aplicáveis no mês para auditoria
        feriados_mes = [f for f in feriados if f["data"].month == mes]
        if feriados_mes:
            memoria.append(f"Feriados aplicáveis no mês {mes:02d}/{ano}: " + ", ".join(f"{f['data'].isoformat()} {f['nome']} ({f['tipo']})" for f in feriados_mes) + ".")
        else:
            memoria.append(f"Nenhum feriado aplicável no mês {mes:02d}/{ano}.")

        # Override manual
        dias_override_aplicado = False
        dias_calc = dias_uteis
        if dias_override is not None:
            dias_override_aplicado = True
            memoria.append(f"Override manual aplicado: cálculo {dias_calc} → {dias_override} dias (ajuste do analista).")
            dias_uteis = dias_override
            justificativa = f"Escala {escala_norm} {mes:02d}/{ano} UF={uf_n} município={mun_orig or '—'}: {dias_calc} dias calculados, override para {dias_override} dias."
        else:
            justificativa = f"Escala {escala_norm} {mes:02d}/{ano} UF={uf_n} município={mun_orig or '—'}: {dias_uteis} dias úteis ({dias_brutos} brutos - {len(feriados_descontados)} feriados) — inclui 20/11 Lei 14.759/2023."

        # Sanitiza feriados_descontados para retorno (remove data_obj)
        feriados_out = [{"data": x["data"], "nome": x["nome"]} for x in feriados_descontados]

        return {
            "sucesso": True,
            "dias_uteis": int(dias_uteis),
            "dias_brutos": int(dias_brutos),
            "feriados_descontados": feriados_out,
            "dias_calculados_sem_override": int(dias_calc),
            "dias_override_aplicado": dias_override_aplicado,
            "escala": escala_norm,
            "escala_original": str(escala),
            "uf": uf_n,
            "municipio_destino": mun_orig,
            "municipio_normalizado": mun_n,
            "ano": int(ano),
            "mes": int(mes),
            "memoria_calculo": memoria,
            "justificativa": justificativa,
            "feriados_mes": [{"data": f["data"].isoformat(), "nome": f["nome"], "tipo": f["tipo"]} for f in feriados_mes],
        }

    except Exception as exc:
        return {"sucesso": False, "erro": str(exc), "memoria_calculo": [f"Falha no cálculo de dias úteis: {exc}"], "justificativa": "Erro inesperado no calendário."}
