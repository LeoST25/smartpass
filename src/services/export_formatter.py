"""Formatter de exportação LGPD stateless — layouts SPTrans/TOP e eSocial/ERP.

- Gera CSV em io.BytesIO com utf-8-sig (sem escrita em disco).
- Mascaramento CPF: ***.456.789-** (preserva 6 dígitos centrais).
- Contratos padronizados {"sucesso": True/False}.
"""

from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime

import pandas as pd


def mascarar_cpf(cpf: str | None) -> str:
    """Mascara CPF preservando 6 dígitos centrais.

    Entrada aceita formatada ou não. Retorna "***.456.789-**".
    Se inválido/vazio retorna "***.***.***-**".
    """
    try:
        if cpf is None:
            return "***.***.***-**"
        s = re.sub(r"\D", "", str(cpf))
        if len(s) != 11:
            return "***.***.***-**"
        # preserva dígitos 4-9 (índices 3..8) -> formata ***.456.789-**
        meio1 = s[3:6]
        meio2 = s[6:9]
        return f"***.{meio1}.{meio2}-**"
    except Exception:
        return "***.***.***-**"


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza nomes de colunas: lower, sem acento, trim, underscore."""
    try:
        novos = []
        for c in df.columns:
            s = str(c).strip().lower()
            s = "".join(ch for ch in unicodedata.normalize("NFD", s) if unicodedata.category(ch) != "Mn")
            s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
            novos.append(s)
        df2 = df.copy()
        df2.columns = novos
        return df2
    except Exception:
        return df


def _resolver_col(df: pd.DataFrame, candidatos: list[str], default=None):
    for cand in candidatos:
        if cand in df.columns:
            return cand
    return default


def _valor_diario_to_float(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        try:
            return round(float(v), 2)
        except Exception:
            return 0.0
    s = str(v).strip().replace("R$", "").replace("r$", "").strip()
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    s = s.replace(" ", "")
    try:
        return round(float(s), 2)
    except Exception:
        return 0.0


def gerar_export_compra(
    dados: pd.DataFrame | list[dict],
    dias_uteis: int,
    competencia: str | None = None,
) -> dict:
    """Gera Layout Padrão Compra (SPTrans/TOP) em BytesIO CSV utf-8-sig.

    Colunas: matricula, nome, cpf_mascarado, operadora, codigo_linha, valor_diario, dias_uteis, valor_total_pedido.

    Args:
        dados: DataFrame ou lista de dicts com ao menos nome/cpf/valor_diario.
        dias_uteis: Dias úteis do mês (validado 1-31).
        competencia: Opcional "MM/AAAA" para auditoria.

    Returns:
        dict: {"sucesso": bool, "bytesio": BytesIO, "filename": str, "memoria_calculo": [...]}
    """
    try:
        if not isinstance(dias_uteis, int) or dias_uteis < 1 or dias_uteis > 31:
            return {"sucesso": False, "erro": "dias_uteis deve ser inteiro 1-31.", "memoria_calculo": [f"Falha: dias_uteis {dias_uteis} inválido."], "justificativa": "Dias úteis inválido."}

        # Normaliza dados para DataFrame
        if isinstance(dados, list):
            if len(dados) == 0:
                df = pd.DataFrame()
            else:
                df = pd.DataFrame(dados)
        elif isinstance(dados, pd.DataFrame):
            df = dados.copy()
        else:
            return {"sucesso": False, "erro": "dados deve ser DataFrame ou lista de dicts.", "memoria_calculo": ["Falha: tipo de dados inválido."], "justificativa": "Tipo de dados inválido."}

        if df.empty:
            return {"sucesso": False, "erro": "Nenhum colaborador informado para exportação.", "memoria_calculo": ["Falha: dados vazios — nenhum registro para exportar."], "justificativa": "Dados vazios."}

        df = _normalizar_colunas(df)

        # Mapeia colunas com aliases
        col_matricula = _resolver_col(df, ["matricula", "mat", "codigo", "id", "registro"], None)
        col_nome = _resolver_col(df, ["nome", "colaborador", "funcionario", "nome_completo"], None)
        col_cpf = _resolver_col(df, ["cpf", "cpf_mascarado", "documento", "cpf_numero"], None)
        col_operadora = _resolver_col(df, ["operadora", "operadora_transporte", "concessionaria", "empresa_operadora"], None)
        col_linha = _resolver_col(df, ["codigo_linha", "linha", "codigo", "linha_onibus", "codigo_linha_onibus"], None)
        col_valor = _resolver_col(df, ["valor_diario", "valor_dia", "tarifa", "valor_unitario", "valor", "custo_diario"], None)

        if col_nome is None:
            return {"sucesso": False, "erro": "Coluna 'nome' obrigatória não encontrada.", "memoria_calculo": ["Falha: coluna nome ausente."], "justificativa": "Coluna nome ausente."}
        if col_cpf is None:
            return {"sucesso": False, "erro": "Coluna 'cpf' obrigatória não encontrada.", "memoria_calculo": ["Falha: coluna cpf ausente."], "justificativa": "Coluna CPF ausente."}
        if col_valor is None:
            return {"sucesso": False, "erro": "Coluna 'valor_diario' obrigatória não encontrada.", "memoria_calculo": ["Falha: coluna valor_diario ausente."], "justificativa": "Coluna valor_diario ausente."}

        linhas = []
        for idx, row in df.iterrows():
            matricula = str(row[col_matricula]).strip() if col_matricula and pd.notna(row[col_matricula]) else str(idx + 1).zfill(4)
            nome = str(row[col_nome]).strip() if pd.notna(row[col_nome]) else ""
            cpf_raw = str(row[col_cpf]).strip() if pd.notna(row[col_cpf]) else ""
            cpf_masc = mascarar_cpf(cpf_raw)
            operadora = str(row[col_operadora]).strip() if col_operadora and pd.notna(row[col_operadora]) else "SPTrans"
            codigo_linha = str(row[col_linha]).strip() if col_linha and pd.notna(row[col_linha]) else "—"
            valor_diario = _valor_diario_to_float(row[col_valor])
            valor_total = round(valor_diario * dias_uteis, 2)
            linhas.append({
                "matricula": matricula,
                "nome": nome,
                "cpf_mascarado": cpf_masc,
                "operadora": operadora,
                "codigo_linha": codigo_linha,
                "valor_diario": f"{valor_diario:.2f}",
                "dias_uteis": int(dias_uteis),
                "valor_total_pedido": f"{valor_total:.2f}",
            })

        df_out = pd.DataFrame(linhas, columns=["matricula", "nome", "cpf_mascarado", "operadora", "codigo_linha", "valor_diario", "dias_uteis", "valor_total_pedido"])

        # Gera CSV em BytesIO utf-8-sig
        sio = io.StringIO()
        df_out.to_csv(sio, index=False)
        csv_str = sio.getvalue()
        bio = io.BytesIO(csv_str.encode("utf-8-sig"))
        bio.seek(0)

        comp = competencia or datetime.now().strftime("%m/%Y")
        filename = f"smartpass_compra_sptrans_top_{comp.replace('/', '-')}_{dias_uteis}du.csv"

        memoria = [
            f"Layout Padrão Compra (SPTrans/TOP): {len(df_out)} colaborador(es), {dias_uteis} dias úteis, competência {comp}.",
            f"Colunas: {', '.join(df_out.columns.tolist())}.",
            "CPF mascarado (***.456.789-**) — LGPD stateless, sem persistência em disco.",
            f"Valor total por colaborador = valor_diario × dias_uteis (ex: R$ {linhas[0]['valor_diario']} × {dias_uteis} = R$ {linhas[0]['valor_total_pedido']})." if linhas else "Sem linhas.",
        ]
        justificativa = f"Export compra gerado em BytesIO utf-8-sig com {len(df_out)} registros, {dias_uteis} dias úteis, CPF mascarado."

        return {"sucesso": True, "bytesio": bio, "filename": filename, "dataframe": df_out, "memoria_calculo": memoria, "justificativa": justificativa, "competencia": comp, "dias_uteis": int(dias_uteis)}

    except Exception as exc:
        return {"sucesso": False, "erro": str(exc), "memoria_calculo": [f"Falha no export compra: {exc}"], "justificativa": "Erro no layout compra."}


def gerar_export_rubrica(
    dados: pd.DataFrame | list[dict],
    dias_uteis: int,
    competencia: str | None = None,
) -> dict:
    """Gera Layout Rubrica Folha (eSocial/ERP) em BytesIO CSV utf-8-sig — consolidado proventos/descontos VT.

    Colunas: matricula, nome, cpf_mascarado, rubrica_provento, rubrica_desconto, valor_provento, desconto_6pct, subsidio_empresa, competencia, dias_uteis, observacao.

    Integra regra CLT 6% quando salario_base presente; caso contrário provento integral sem desconto.

    Args:
        dados: DataFrame/lista com nome, cpf, valor_diario e opcional salario_base.
        dias_uteis: Dias úteis do mês.
        competencia: "MM/AAAA".

    Returns:
        dict: {"sucesso": bool, "bytesio": BytesIO, ...}
    """
    try:
        if not isinstance(dias_uteis, int) or dias_uteis < 1 or dias_uteis > 31:
            return {"sucesso": False, "erro": "dias_uteis deve ser inteiro 1-31.", "memoria_calculo": [f"Falha: dias_uteis {dias_uteis} inválido."], "justificativa": "Dias úteis inválido."}

        if isinstance(dados, list):
            df = pd.DataFrame(dados) if dados else pd.DataFrame()
        elif isinstance(dados, pd.DataFrame):
            df = dados.copy()
        else:
            return {"sucesso": False, "erro": "dados deve ser DataFrame ou lista de dicts.", "memoria_calculo": ["Falha: tipo de dados inválido."], "justificativa": "Tipo de dados inválido."}

        if df.empty:
            return {"sucesso": False, "erro": "Nenhum colaborador para rubrica.", "memoria_calculo": ["Falha: dados vazios."], "justificativa": "Dados vazios."}

        df = _normalizar_colunas(df)

        col_matricula = _resolver_col(df, ["matricula", "mat", "codigo", "id", "registro"], None)
        col_nome = _resolver_col(df, ["nome", "colaborador", "funcionario"], None)
        col_cpf = _resolver_col(df, ["cpf", "cpf_mascarado", "documento"], None)
        col_valor = _resolver_col(df, ["valor_diario", "valor_dia", "tarifa", "valor_unitario", "valor", "custo_diario"], None)
        col_salario = _resolver_col(df, ["salario_base", "salario", "salario_base_r", "salary"], None)

        if col_nome is None or col_cpf is None or col_valor is None:
            return {"sucesso": False, "erro": "Colunas obrigatórias: nome, cpf, valor_diario.", "memoria_calculo": ["Falha: colunas obrigatórias ausentes."], "justificativa": "Colunas obrigatórias ausentes."}

        # Lazy import para evitar ciclo
        try:
            from src.services.benefit_calculator import analisar_viabilidade_clt
        except Exception:
            analisar_viabilidade_clt = None

        linhas = []
        for idx, row in df.iterrows():
            matricula = str(row[col_matricula]).strip() if col_matricula and pd.notna(row[col_matricula]) else str(idx + 1).zfill(4)
            nome = str(row[col_nome]).strip() if pd.notna(row[col_nome]) else ""
            cpf_masc = mascarar_cpf(str(row[col_cpf]) if pd.notna(row[col_cpf]) else "")
            valor_diario = _valor_diario_to_float(row[col_valor])
            valor_provento = round(valor_diario * dias_uteis, 2)

            salario_raw = row[col_salario] if col_salario and col_salario in df.columns and pd.notna(row[col_salario]) else None
            salario_f = None
            if salario_raw is not None and str(salario_raw).strip() != "":
                # reutiliza parse BR
                s = str(salario_raw).strip().replace("R$", "").strip()
                if "," in s:
                    s = s.replace(".", "").replace(",", ".")
                s = s.replace(" ", "")
                try:
                    salario_f = float(s)
                except Exception:
                    salario_f = None

            if analisar_viabilidade_clt and salario_f and salario_f > 0:
                viab = analisar_viabilidade_clt(float(valor_provento), float(salario_f))
                desconto = float(viab.get("desconto_colaborador", 0.0)) if viab.get("sucesso") else 0.0
                teto = float(viab.get("teto_desconto_6_pct", 0.0)) if viab.get("sucesso") else 0.0
                subsidio = float(viab.get("custeio_empresa", 0.0)) if viab.get("sucesso") else float(valor_provento)
                obs = viab.get("recomendacao", "")[:120] if viab.get("sucesso") else ""
            else:
                desconto = 0.0
                teto = 0.0
                subsidio = float(valor_provento)
                obs = "Salário não informado — provento integral sem desconto CLT."

            linhas.append({
                "matricula": matricula,
                "nome": nome,
                "cpf_mascarado": cpf_masc,
                "rubrica_provento": "901-VT Provento",
                "rubrica_desconto": "902-VT Desconto 6%",
                "valor_provento": f"{valor_provento:.2f}",
                "desconto_6pct": f"{desconto:.2f}",
                "subsidio_empresa": f"{subsidio:.2f}",
                "teto_6pct": f"{teto:.2f}",
                "competencia": competencia or datetime.now().strftime("%m/%Y"),
                "dias_uteis": int(dias_uteis),
                "observacao": obs,
            })

        df_out = pd.DataFrame(linhas, columns=["matricula", "nome", "cpf_mascarado", "rubrica_provento", "rubrica_desconto", "valor_provento", "desconto_6pct", "subsidio_empresa", "teto_6pct", "competencia", "dias_uteis", "observacao"])

        sio = io.StringIO()
        df_out.to_csv(sio, index=False)
        bio = io.BytesIO(sio.getvalue().encode("utf-8-sig"))
        bio.seek(0)

        comp = competencia or datetime.now().strftime("%m/%Y")
        filename = f"smartpass_rubrica_esocial_erp_{comp.replace('/', '-')}_{dias_uteis}du.csv"

        memoria = [
            f"Layout Rubrica Folha (eSocial/ERP): {len(df_out)} colaborador(es), {dias_uteis} dias úteis, competência {comp}.",
            "Consolidação proventos/descontos VT por colaborador — rubricas 901/902.",
            "Regra CLT 6% aplicada quando salário_base informado; caso contrário desconto zerado.",
            "CPF mascarado e BytesIO utf-8-sig — LGPD stateless.",
        ]
        justificativa = f"Rubrica folha gerada com {len(df_out)} registros, {dias_uteis} dias úteis, eSocial/ERP compatível."

        return {"sucesso": True, "bytesio": bio, "filename": filename, "dataframe": df_out, "memoria_calculo": memoria, "justificativa": justificativa, "competencia": comp, "dias_uteis": int(dias_uteis)}

    except Exception as exc:
        return {"sucesso": False, "erro": str(exc), "memoria_calculo": [f"Falha no export rubrica: {exc}"], "justificativa": "Erro no layout rubrica."}
