"""Processamento de lote em memória (LGPD stateless).

Extração do loop de lote de ``src/app.py:560-628`` para reúso pela API REST
(``POST /batch/simulate``) e pela UI Streamlit. Processa CSV/XLSX em memória,
aplica geocodificação + roteirização VT + análise CLT 6%, e retorna resultados
estruturados com CPF mascarado para auditoria.

Zero persistência em disco: todo processamento é feito via ``io.BytesIO`` /
``io.StringIO`` / ``UploadFile`` (em memória).
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

from src.services.benefit_calculator import analisar_viabilidade_clt, parse_salario_brasileiro
from src.services.geocoding import buscar_coordenadas_por_cep_ou_endereco
from src.services.routing import roteirizar_vale_transporte_automatico


def _recalcular_vt_com_parametros(resultado_vt: dict, tarifa: float | None, dias_uteis: int) -> dict:
    """Recalcula custo VT com tarifa override (compat legada).

    Se tarifa é None ou 0, mantém tarifas oficiais por linha/operadora.
    Quando tarifa >0, aplica override RH com trilha auditável.
    """
    if not resultado_vt or not resultado_vt.get("sucesso"):
        return resultado_vt
    if tarifa is None or float(tarifa) <= 0:
        if dias_uteis and resultado_vt.get("custo_diario") is not None:
            novo = dict(resultado_vt)
            novo["custo_mensal"] = round(float(resultado_vt["custo_diario"]) * int(dias_uteis), 2)
            novo["dias_uteis"] = int(dias_uteis)
            return novo
        return resultado_vt
    linhas = resultado_vt.get("detalhes") or []
    if not linhas:
        linhas_src = resultado_vt.get("linhas") or [{"linha": "Transporte público", "valor_unitario": float(tarifa), "quantidade_dia": 2}]
    else:
        linhas_src = [{"linha": d.get("linha", "Linha"), "valor_unitario": float(tarifa), "quantidade_dia": d.get("quantidade_dia", 2)} for d in linhas]
    from src.services.routing import calcular_vale_transporte
    recalc = calcular_vale_transporte(linhas_src)
    recalc["custo_mensal"] = round(recalc["custo_diario"] * dias_uteis, 2)
    novo = {**resultado_vt, **recalc}
    novo["detalhes"] = recalc["detalhes"]
    novo["override_tarifa"] = float(tarifa)
    novo["memoria_calculo"] = (resultado_vt.get("memoria_calculo") or []) + [f"Override RH: tarifa unitária R$ {float(tarifa):.2f} aplicada a todos os trechos (convênio)"]
    return novo


def processar_lote(
    df: pd.DataFrame,
    dias_uteis: int = 22,
    tarifa_override: float | None = None,
) -> dict:
    """Processa lote de colaboradores em memória (geocodificação + VT + CLT 6%).

    Args:
        df: DataFrame com colunas ``origem``, ``destino``, ``nome`` (opcional),
            ``cpf`` (opcional), ``salario_base`` (opcional).
        dias_uteis: Dias úteis do mês para cálculo mensal (default 22).
        tarifa_override: Override de tarifa unitária (None = usar oficial por linha).

    Returns:
        dict: {"sucesso": bool, "resultados": list[dict], "totals": dict,
               "memoria_calculo": list[str], "erro": str | None}
    """
    try:
        if df.empty:
            return {
                "sucesso": False,
                "resultados": [],
                "totals": {"n_alta": 0, "n_media": 0, "n_baixa": 0},
                "memoria_calculo": ["Lote vazio — nenhum registro para processar."],
                "erro": "DataFrame vazio.",
            }

        resultados: list[dict] = []

        for idx, row in df.iterrows():
            # Detecta colunas origem/destino de forma flexível
            origem_lote = row.get("origem") or row.get("endereco") or row.get("cep_origem") or row.get("residencia")
            destino_lote = row.get("destino") or row.get("empresa") or row.get("cep_destino") or row.get("unidade")

            if pd.isna(origem_lote) or pd.isna(destino_lote):
                resultados.append({
                    "linha": idx + 1,
                    "origem": str(origem_lote),
                    "destino": str(destino_lote),
                    "erro": "Origem/Destino ausente",
                    "nivel_precisao": "BAIXA",
                    "semaforo": "🔴 Revisar Endereço",
                    "motivo_precisao": "Origem/Destino ausente — revisão obrigatória",
                })
                continue

            # Detecta salario_base opcional
            salario_raw = None
            for cand in ["salario_base", "salario", "salario base", "salary", "salario_base_r$"]:
                if cand in df.columns:
                    salario_raw = row.get(cand)
                    break
            salario_lote = parse_salario_brasileiro(salario_raw) if salario_raw is not None and not pd.isna(salario_raw) else None

            # Detecta CPF para mascaramento no JSON (LGPD)
            cpf_raw = None
            for cand in ["cpf", "documento", "cpf_numero"]:
                if cand in df.columns:
                    cpf_raw = row.get(cand)
                    break
            cpf_mascarado = _mascarar_cpf(str(cpf_raw) if cpf_raw is not None and not pd.isna(cpf_raw) else "")

            try:
                res_geo_o = buscar_coordenadas_por_cep_ou_endereco(str(origem_lote))
                res_geo_d = buscar_coordenadas_por_cep_ou_endereco(str(destino_lote))

                if not res_geo_o.get("sucesso") or not res_geo_d.get("sucesso"):
                    nivel_falha = "BAIXA"
                    motivo_falha = res_geo_o.get("erro") if not res_geo_o.get("sucesso") else res_geo_d.get("erro", "Geocodificação falhou")
                    resultados.append({
                        "linha": idx + 1,
                        "origem": str(origem_lote),
                        "destino": str(destino_lote),
                        "cpf_mascarado": cpf_mascarado,
                        "erro": "Geocodificação falhou",
                        "nivel_precisao": nivel_falha,
                        "semaforo": "🔴 Revisar Endereço",
                        "motivo_precisao": str(motivo_falha)[:180],
                    })
                    continue

                # Semáforo: pior nível entre origem e destino
                _ordem = {"BAIXA": 3, "MEDIA": 2, "ALTA": 1}
                nivel_o = res_geo_o.get("nivel_precisao", "MEDIA")
                nivel_d = res_geo_d.get("nivel_precisao", "MEDIA")
                nivel_lote = nivel_o if _ordem.get(nivel_o, 0) >= _ordem.get(nivel_d, 0) else nivel_d
                semaforo_lote = res_geo_o.get("semaforo") if nivel_lote == nivel_o else res_geo_d.get("semaforo")

                motivo_o = res_geo_o.get("motivo_precisao", "")
                motivo_d = res_geo_d.get("motivo_precisao", "")
                motivo_lote = f"Origem: {motivo_o} | Destino: {motivo_d}" if motivo_o or motivo_d else ""

                vt = roteirizar_vale_transporte_automatico(
                    res_geo_o["lat"], res_geo_o["lon"], res_geo_d["lat"], res_geo_d["lon"], str(origem_lote), str(destino_lote)
                )
                vt_adj = _recalcular_vt_com_parametros(vt, tarifa_override, int(dias_uteis))
                custo_m = vt_adj.get("custo_mensal", 0) or 0
                viab_lote = analisar_viabilidade_clt(float(custo_m), salario_lote)

                if salario_lote is None or salario_lote <= 0:
                    status_clt = "NAO_INFORMADO"
                elif viab_lote.get("vt_vantajoso"):
                    status_clt = "VANTAJOSO"
                else:
                    status_clt = "NAO_VANTAJOSO"

                resultados.append({
                    "linha": idx + 1,
                    "origem": str(origem_lote),
                    "destino": str(destino_lote),
                    "cpf_mascarado": cpf_mascarado,
                    "distancia_km": vt_adj.get("distancia_km"),
                    "custo_diario": vt_adj.get("custo_diario"),
                    "custo_mensal": custo_m,
                    "fonte": vt_adj.get("fonte"),
                    "teto_6_pct": viab_lote.get("teto_desconto_6_pct", 0.0),
                    "desconto_colaborador": viab_lote.get("desconto_colaborador", 0.0),
                    "subsidio_empresa": viab_lote.get("custeio_empresa", 0.0),
                    "status_viabilidade_clt": status_clt,
                    "nivel_precisao": nivel_lote,
                    "semaforo": semaforo_lote,
                    "motivo_precisao": motivo_lote,
                })
            except Exception as exc:
                resultados.append({
                    "linha": idx + 1,
                    "origem": str(origem_lote),
                    "destino": str(destino_lote),
                    "cpf_mascarado": cpf_mascarado,
                    "erro": str(exc)[:180],
                    "nivel_precisao": "BAIXA",
                    "semaforo": "🔴 Revisar Endereço",
                    "motivo_precisao": str(exc)[:180],
                })

        # Totais de semáforo
        n_alta = sum(1 for r in resultados if r.get("nivel_precisao") == "ALTA")
        n_media = sum(1 for r in resultados if r.get("nivel_precisao") == "MEDIA")
        n_baixa = sum(1 for r in resultados if r.get("nivel_precisao") == "BAIXA")

        memoria = [
            f"Lote processado: {len(resultados)} registro(s), {len(df)} no DataFrame original.",
            f"Semáforo: {n_alta} exatos, {n_media} aproximados, {n_baixa} para revisão.",
            "CPF mascarado em todos os registros (LGPD stateless).",
        ]

        return {
            "sucesso": True,
            "total": len(resultados),
            "resultados": resultados,
            "totals": {"n_alta": n_alta, "n_media": n_media, "n_baixa": n_baixa},
            "memoria_calculo": memoria,
            "erro": None,
        }

    except Exception as exc:
        return {
            "sucesso": False,
            "resultados": [],
            "totals": {"n_alta": 0, "n_media": 0, "n_baixa": 0},
            "memoria_calculo": [f"Falha no processamento do lote: {exc}"],
            "erro": str(exc),
        }


def _mascarar_cpf(cpf: str) -> str:
    """Mascara CPF preservando 6 dígitos centrais. LGPD stateless."""
    import re
    try:
        s = re.sub(r"\D", "", str(cpf))
        if len(s) != 11:
            return "***.***.***-**"
        meio1 = s[3:6]
        meio2 = s[6:9]
        return f"***.{meio1}.{meio2}-**"
    except Exception:
        return "***.***.***-**"


def ler_arquivo_lote(content: bytes, filename: str) -> pd.DataFrame:
    """Lê CSV/XLSX em memória (sem escrita em disco).

    Args:
        content: Conteúdo do arquivo em bytes.
        filename: Nome do arquivo para detectar formato (csv, xlsx, xls).

    Returns:
        pd.DataFrame: DataFrame com colunas normalizadas (lower, trim).
    """
    nome = filename.lower()
    bio = io.BytesIO(content)

    if nome.endswith(".csv"):
        try:
            df = pd.read_csv(bio)
        except UnicodeDecodeError:
            bio.seek(0)
            df = pd.read_csv(bio, encoding="latin-1")
    elif nome.endswith((".xlsx", ".xls")):
        df = pd.read_excel(bio)
    else:
        raise ValueError(f"Formato não suportado: {filename}. Use CSV, XLSX ou XLS.")

    df.columns = [str(c).strip().lower() for c in df.columns]
    return df
