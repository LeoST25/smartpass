"""Cálculo de viabilidade CLT — Lei do Vale-Transporte (Lei 7.418/85).

Regra: desconto máximo de 6% sobre salário-base. Empresa subsidia excedente.
Função pura, sem I/O, sem Streamlit, retorno padronizado {"sucesso": bool}.
LGPD stateless: não persiste dados.
"""

from __future__ import annotations


def _parse_float(value) -> float | None:
    """Tenta converter value para float, retornando None se inválido."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except Exception:
            return None
    # string: sanitiza padrão BR "R$ 2.500,00"
    s = str(value).strip()
    if not s:
        return None
    # remove símbolo monetário e espaços
    s = s.replace("R$", "").replace("r$", "").strip()
    # se contém vírgula como separador decimal, remove pontos de milhar
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    # remove espaços restantes
    s = s.replace(" ", "")
    try:
        return float(s)
    except Exception:
        return None


def analisar_viabilidade_clt(custo_mensal_vt: float, salario_base: float | None) -> dict:
    """Analisa viabilidade do Vale-Transporte pela regra CLT 6% (Lei 7.418/85 art.4º).

    Args:
        custo_mensal_vt: Custo mensal total do VT (ida+volta * dias úteis). Deve ser >=0.
        salario_base: Salário-base do colaborador. None ou <=0 significa não informado.

    Returns:
        dict: Em sucesso ``{"sucesso": True, "teto_desconto_6_pct": float,
            "desconto_colaborador": float, "custeio_empresa": float,
            "vt_vantajoso": bool, "recomendacao": str,
            "memoria_calculo": list[str], "justificativa": str}``.
            Ajuste aprovado: quando salário omitido (None/<=0) retorna
            teto 0.0, desconto 0.0, custeio 0.0 e vt_vantajoso False com
            recomendação de não aplicável.
            Em falha de validação ``{"sucesso": False, "erro": str, "memoria_calculo": [...]}``.
    """
    try:
        custo = _parse_float(custo_mensal_vt)
        if custo is None:
            return {
                "sucesso": False,
                "erro": "custo_mensal_vt inválido: informe valor numérico >= 0.",
                "memoria_calculo": ["Falha: custo_mensal_vt não numérico — cálculo CLT não aplicável."],
                "justificativa": "Custo mensal inválido.",
            }
        if custo < 0:
            return {
                "sucesso": False,
                "erro": "custo_mensal_vt não pode ser negativo.",
                "memoria_calculo": [f"Falha: custo_mensal_vt R$ {custo:.2f} negativo."],
                "justificativa": "Custo mensal negativo.",
            }
        custo = round(custo, 2)

        # salario_base pode ser None, string BR, ou numérico
        salario_raw = salario_base
        salario = _parse_float(salario_raw) if salario_raw is not None else None

        # Caso omitido / não informado / <=0 — ajuste pontual #1
        if salario is None or salario <= 0:
            # se veio valor negativo explícito, tratar como erro de validação
            if salario is not None and salario < 0:
                return {
                    "sucesso": False,
                    "erro": "salario_base não pode ser negativo.",
                    "memoria_calculo": [f"Falha: salario_base R$ {salario:.2f} negativo — Lei 7.418/85 não aplicável."],
                    "justificativa": "Salário base negativo.",
                }
            memoria = [
                "Lei 7.418/85 art.4º parágrafo único: desconto CLT de até 6% sobre salário-base.",
                f"Custo mensal VT: R$ {custo:.2f}.",
                "Salário base não informado — rateio CLT não calculado (teto 6% = R$ 0,00).",
            ]
            justificativa = "Salário base não informado; viabilidade CLT não aplicável — rateio zerado."
            recomendacao = "Salário base não informado — rateio CLT não aplicável (informe o salário para calcular o teto de 6%)."
            return {
                "sucesso": True,
                "teto_desconto_6_pct": 0.0,
                "desconto_colaborador": 0.0,
                "custeio_empresa": 0.0,
                "vt_vantajoso": False,
                "recomendacao": recomendacao,
                "memoria_calculo": memoria,
                "justificativa": justificativa,
            }

        salario = round(salario, 2)
        teto = round(salario * 0.06, 2)
        desconto_colaborador = round(min(custo, teto), 2)
        custeio_empresa = round(max(0.0, custo - teto), 2)
        vt_vantajoso = custo > teto

        if vt_vantajoso:
            recomendacao = f"VT Vantajoso: empresa subsidia R$ {custeio_empresa:.2f}/mês (teto 6% = R$ {teto:.2f} sobre salário R$ {salario:.2f})"
        else:
            recomendacao = (
                f"Alerta RH: custo do VT (R$ {custo:.2f}) é inferior aos 6% do salário (R$ {teto:.2f} sobre R$ {salario:.2f}); "
                "custeio integral seria do colaborador"
            )

        memoria = [
            "Lei 7.418/85 art.4º parágrafo único: desconto CLT limitado a 6% do salário-base.",
            f"Salário-base R$ {salario:.2f} → teto 6% = R$ {teto:.2f}.",
            f"Custo mensal VT R$ {custo:.2f} vs teto R$ {teto:.2f}.",
            f"Desconto colaborador: R$ {desconto_colaborador:.2f} | Subsídio empresa: R$ {custeio_empresa:.2f}.",
            f"VT vantajoso: {'Sim' if vt_vantajoso else 'Não'} (custo {'>' if vt_vantajoso else '<='} teto).",
        ]
        justificativa = (
            f"Teto 6% R$ {teto:.2f} sobre salário R$ {salario:.2f}; "
            f"custo VT R$ {custo:.2f} → colaborador R$ {desconto_colaborador:.2f}, empresa R$ {custeio_empresa:.2f}."
        )

        return {
            "sucesso": True,
            "teto_desconto_6_pct": teto,
            "desconto_colaborador": desconto_colaborador,
            "custeio_empresa": custeio_empresa,
            "vt_vantajoso": vt_vantajoso,
            "recomendacao": recomendacao,
            "memoria_calculo": memoria,
            "justificativa": justificativa,
        }

    except Exception as exc:
        return {
            "sucesso": False,
            "erro": str(exc),
            "memoria_calculo": [f"Falha no cálculo CLT: {exc}"],
            "justificativa": "Erro inesperado na análise de viabilidade.",
        }


def parse_salario_brasileiro(valor) -> float | None:
    """Converte string monetária BR (ex: 'R$ 2.500,00') para float.

    Args:
        valor: String ou numérico com formato brasileiro.

    Returns:
        float | None: Valor convertido ou None se inválido/vazio.
    """
    return _parse_float(valor)
