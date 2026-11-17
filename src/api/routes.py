"""Rotas REST da API SmartPass (prefix /api/v1).

Endpoints:
- GET  /health                    — status PostgreSQL/PostGIS + OTP
- GET  /geocoding/autocomplete?q  — sugestões de endereço com semáforo
- POST /routes/calculate          — cálculo completo (VT/VC/Comparativo)
- POST /reports/pdf               — PDF de evidência em memória (StreamingResponse)
- POST /batch/simulate            — lote via UploadFile (CSV/XLSX)
- POST /batch/simulate/csv        — download CSV do lote processado
"""

from __future__ import annotations

import io
import logging
import os
import time
from datetime import datetime

import pandas as pd
import requests
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse

from src.api.schemas import (
    BatchDownloadCSVRequest,
    BatchSimulateResponse,
    CandidatoGeocoding,
    GeocodingAutocompleteResponse,
    PDFReportRequest,
    RouteCalculateRequest,
    RouteCalculateResponse,
)
from src.services.benefit_calculator import analisar_viabilidade_clt
from src.services.calendar_engine import calcular_dias_uteis
from src.services.export_formatter import gerar_export_compra, gerar_export_rubrica
from src.services.fare_engine import ranquear_opcoes_ida_volta
from src.services.geocoding import (
    buscar_coordenadas_por_cep_ou_endereco,
    geocodificar_reverso,
    sugerir_enderecos,
)
from src.services.pdf_generator import gerar_pdf_comprovante, gerar_pdf_evidencia
from src.services.routing import (
    calcular_vale_combustivel,
    calcular_vale_transporte,
    roteirizar_com_comparativo,
    roteirizar_vale_transporte_automatico,
)
from src.services.transit_api import consultar_itinerarios_ida_volta_oficial

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# Limites LGPD / performance
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_BATCH_ROWS = 500
OTP_HEALTH_TIMEOUT = 3.0


# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@router.get("/health")
def health():
    """Status real do PostgreSQL/PostGIS e OTP.

    Returns:
        dict: {"status": "ok|degraded|down", "postgres": {...}, "otp": {...}, "timestamp": str}
    """
    # Postgres health
    try:
        from src.database.connection import check_db_health
        pg = check_db_health(timeout=3.0)
    except Exception as exc:
        pg = {"ok": False, "postgis_version": None, "latency_ms": None, "erro": str(exc)}

    # OTP health (minimal query com timeout curto)
    otp_url = os.getenv("OTP_GRAPHQL_URL", "http://localhost:8080/otp/gtfs/v1")
    otp_latency = None
    t0_otp = time.monotonic()
    try:
        resp_otp = requests.post(
            otp_url,
            json={"query": "{ feeds { feedId } }"},
            timeout=OTP_HEALTH_TIMEOUT,
        )
        otp_latency = round((time.monotonic() - t0_otp) * 1000, 2)
        otp_ok = resp_otp.status_code == 200 and not resp_otp.json().get("errors")
        otp = {"ok": otp_ok, "latency_ms": otp_latency, "erro": None}
    except Exception as exc:
        otp_latency = round((time.monotonic() - t0_otp) * 1000, 2)
        otp = {"ok": False, "latency_ms": otp_latency, "erro": str(exc)}

    # Status consolidado
    if pg.get("ok") and otp.get("ok"):
        status = "ok"
    elif pg.get("ok") or otp.get("ok"):
        status = "degraded"
    else:
        status = "down"

    return {
        "status": status,
        "postgres": pg,
        "otp": otp,
        "timestamp": datetime.now().isoformat(),
    }


# -----------------------------------------------------------------------------
# Geocoding
# -----------------------------------------------------------------------------
@router.get("/geocoding/autocomplete", response_model=GeocodingAutocompleteResponse)
def geocoding_autocomplete(
    q: str = Query(..., min_length=3, description="Query de busca (mínimo 3 caracteres)"),
    limite: int = Query(5, ge=1, le=10, description="Máximo de sugestões (1-10)"),
):
    """Sugestões de endereço com semáforo de precisão (RMSP).

    Args:
        q: Query de busca (CEP ou endereço, mínimo 3 caracteres).
        limite: Máximo de sugestões (default 5, max 10).

    Returns:
        GeocodingAutocompleteResponse: Lista de candidatos com semáforo.
    """
    try:
        sugestoes = sugerir_enderecos(q.strip(), limite=limite)
        candidatos = [CandidatoGeocoding(**s) for s in sugestoes]
        return GeocodingAutocompleteResponse(query=q, sugestoes=candidatos)
    except Exception as exc:
        logger.warning("Falha no autocomplete: %s", exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Serviço de geocodificação indisponível.") from exc


# -----------------------------------------------------------------------------
# Route Calculate
# -----------------------------------------------------------------------------
@router.post("/routes/calculate", response_model=RouteCalculateResponse)
def routes_calculate(req: RouteCalculateRequest):
    """Cálculo de rotas com motor ida+volta por horário real (VT) + CLT 6%.

    Para ``modalidade="Vale-Transporte"`` (default) executa duas consultas OTP:
    ida (chegar até ``horario_entrada``) e volta (sair a partir de ``horario_saida``),
    aplica o ``fare_engine`` separadamente por sentido e retorna até 3 opções
    ranqueadas (mais econômica, mais rápida, menor caminhada).

    Modalidades ``Vale-Combustível``/``Comparativo Completo`` mantêm o contrato
    legado (``vt``/``vc``/``comparativo``) para consumidores existentes da API.

    Args:
        req: RouteCalculateRequest com origem, destino, horários e parâmetros opcionais.

    Returns:
        RouteCalculateResponse: Opções ranqueadas (ou legado VC) com memória auditável.
    """
    try:
        # 1. Geocodificação (ou coordenadas explícitas do pino arrastado)
        tem_coords = all(
            v is not None
            for v in (req.origem_lat, req.origem_lon, req.destino_lat, req.destino_lon)
        )
        if tem_coords:
            lat_o, lon_o = float(req.origem_lat), float(req.origem_lon)
            lat_d, lon_d = float(req.destino_lat), float(req.destino_lon)
            endereco_origem = req.origem.strip()
            endereco_destino = req.destino.strip()

            rev_o = geocodificar_reverso(lat_o, lon_o)
            rev_d = geocodificar_reverso(lat_d, lon_d)
            if rev_o.get("sucesso"):
                endereco_origem = rev_o["endereco_encontrado"]
            if rev_d.get("sucesso"):
                endereco_destino = rev_d["endereco_encontrado"]
            geo_o = rev_o if rev_o.get("sucesso") else {
                "sucesso": True, "nivel_precisao": "MEDIA", "semaforo": "🟡 Aproximado",
                "fonte": "coordenada_arrastada", "motivo_precisao": "Coordenada arrastada no mapa (sem reverse geocoding).",
            }
            geo_d = rev_d if rev_d.get("sucesso") else {
                "sucesso": True, "nivel_precisao": "MEDIA", "semaforo": "🟡 Aproximado",
                "fonte": "coordenada_arrastada", "motivo_precisao": "Coordenada arrastada no mapa (sem reverse geocoding).",
            }
        else:
            res_geo_origem = buscar_coordenadas_por_cep_ou_endereco(req.origem.strip())
            res_geo_destino = buscar_coordenadas_por_cep_ou_endereco(req.destino.strip())

            if not res_geo_origem.get("sucesso"):
                return RouteCalculateResponse(
                    sucesso=False,
                    erro="Não foi possível localizar o endereço de origem. Revise o CEP ou o endereço informado.",
                    memoria_calculo=["Geocodificação de origem falhou."],
                )
            if not res_geo_destino.get("sucesso"):
                return RouteCalculateResponse(
                    sucesso=False,
                    erro="Não foi possível localizar o endereço de destino. Revise o CEP ou o endereço informado.",
                    memoria_calculo=["Geocodificação de destino falhou."],
                )
            lat_o, lon_o = res_geo_origem["lat"], res_geo_origem["lon"]
            lat_d, lon_d = res_geo_destino["lat"], res_geo_destino["lon"]
            endereco_origem = res_geo_origem.get("endereco_encontrado", req.origem)
            endereco_destino = res_geo_destino.get("endereco_encontrado", req.destino)
            geo_o, geo_d = res_geo_origem, res_geo_destino

        coords = (lat_o, lon_o, lat_d, lon_d)

        # 2. Calendário (dias úteis)
        now = datetime.now()
        ano = req.ano_ref or now.year
        mes = req.mes_ref or now.month
        escala = req.escala or "5x2"
        uf = req.uf_destino or "SP"
        mun = req.municipio_destino or "São Paulo"
        dias_override = int(req.dias_uteis) if req.dias_uteis and req.dias_uteis > 0 else None

        try:
            cal = calcular_dias_uteis(ano, mes, escala, uf, mun, dias_override=dias_override)
            dias_efetivos = int(cal["dias_uteis"]) if cal.get("sucesso") else (req.dias_uteis or 22)
            memoria_cal = cal.get("memoria_calculo", []) if cal.get("sucesso") else []
        except Exception:
            dias_efetivos = req.dias_uteis or 22
            memoria_cal = [f"Fallback: usando {dias_efetivos} dias úteis informados manualmente."]

        memoria_final: list[str] = list(memoria_cal)

        # 3. Roteirização
        if req.modalidade == "Vale-Transporte":
            # --- Motor ida+volta por horário real ---
            resp_rotas = consultar_itinerarios_ida_volta_oficial(
                lat_o, lon_o, lat_d, lon_d,
                req.horario_entrada, req.horario_saida,
                endereco_origem=endereco_origem,
                endereco_destino=endereco_destino,
                uf=uf, municipio=mun,
            )

            config_override = None
            if req.tarifa_override and req.tarifa_override > 0:
                ov = float(req.tarifa_override)
                config_override = {
                    "tarifa_padrao": ov,
                    "tarifa_onibus_sptrans": ov,
                    "tarifa_trilho": ov,
                    "tarifa_emtu": ov,
                    "tarifa_integracao_onibus_trilho": round(ov * 2, 2),
                }
                memoria_final.append(f"Override RH: tarifa unitária R$ {ov:.2f} aplicada a todos os trechos (convênio).")

            ranqueamento = ranquear_opcoes_ida_volta(
                resp_rotas.get("ida", []),
                resp_rotas.get("volta", []),
                dias_uteis=dias_efetivos,
                config=config_override,
            )
            opcoes = ranqueamento.get("opcoes", [])
            memoria_final.extend(ranqueamento.get("memoria_calculo", []))

            if not resp_rotas.get("sucesso"):
                memoria_final.append(f"Aviso: {resp_rotas.get('erro')}")

            # CLT sobre a opção mais econômica (opcoes[0])
            viabilidade_clt = None
            if req.salario_base and req.salario_base > 0 and opcoes:
                try:
                    viabilidade_clt = analisar_viabilidade_clt(
                        float(opcoes[0].get("custo_mensal", 0) or 0), float(req.salario_base)
                    )
                except Exception:
                    viabilidade_clt = None
            if viabilidade_clt and viabilidade_clt.get("memoria_calculo"):
                memoria_final.extend(viabilidade_clt["memoria_calculo"])

            memoria_final.append(
                f"Precisão geográfica (origem): {geo_o.get('nivel_precisao', '—')} — fonte {geo_o.get('fonte', '—')}"
            )
            memoria_final.append(
                f"Precisão geográfica (destino): {geo_d.get('nivel_precisao', '—')} — fonte {geo_d.get('fonte', '—')}"
            )

            justificativa = (
                f"Roteirizador individual VT ida ({req.horario_entrada}) + volta ({req.horario_saida}) "
                f"em {dias_efetivos} dias úteis ({escala} {mes:02d}/{ano} {uf}/{mun}), "
                f"data útil {resp_rotas.get('data_referencia')}, fonte {resp_rotas.get('fonte')}."
            )

            return RouteCalculateResponse(
                sucesso=True,
                opcoes=opcoes,
                viabilidade_clt=viabilidade_clt,
                coords=coords,
                origem_label=endereco_origem,
                destino_label=endereco_destino,
                dias_uteis=dias_efetivos,
                horario_entrada=req.horario_entrada,
                horario_saida=req.horario_saida,
                data_referencia=resp_rotas.get("data_referencia"),
                memoria_calculo=memoria_final,
                justificativa=justificativa,
            )

        # --- Legado: Vale-Combustível / Comparativo Completo (contrato preservado) ---
        resultado_vt = None
        resultado_vc = None
        comparativo = None

        if req.modalidade in ("Vale-Transporte", "Comparativo Completo"):
            vt_raw = roteirizar_vale_transporte_automatico(lat_o, lon_o, lat_d, lon_d, endereco_origem, endereco_destino)
            tarifa = req.tarifa_override if req.tarifa_override and req.tarifa_override > 0 else None
            if tarifa and vt_raw.get("sucesso"):
                resultado_vt = _recalcular_vt_com_parametros(vt_raw, tarifa, dias_efetivos)
            else:
                resultado_vt = vt_raw
                if resultado_vt and resultado_vt.get("sucesso"):
                    resultado_vt["custo_mensal"] = round(resultado_vt.get("custo_diario", 0) * dias_efetivos, 2)
                    resultado_vt["dias_uteis"] = dias_efetivos

            try:
                comp_raw = roteirizar_com_comparativo(lat_o, lon_o, lat_d, lon_d, dias_uteis=dias_efetivos)
                if comp_raw.get("sucesso") and comp_raw.get("comparativo"):
                    comparativo = comp_raw["comparativo"]
                    if comparativo.get("rota_mais_rapida") and resultado_vt:
                        resultado_vt["comparativo"] = comparativo
                        resultado_vt["fonte_comparativo"] = comp_raw.get("fonte")
            except Exception:
                comparativo = None

        if req.modalidade in ("Vale-Combustível", "Comparativo Completo"):
            valor_km = req.valor_km or 1.25
            vc_raw = calcular_vale_combustivel(lat_o, lon_o, lat_d, lon_d, valor_km)
            if vc_raw.get("sucesso"):
                diario = round(vc_raw["distancia_km"] * valor_km * 2, 2)
                mensal = round(diario * dias_efetivos, 2)
                resultado_vc = {
                    **vc_raw,
                    "custo_diario": diario,
                    "custo_mensal": mensal,
                    "valor_km": valor_km,
                    "origem": endereco_origem,
                    "destino": endereco_destino,
                }
            else:
                resultado_vc = vc_raw

        if req.modalidade == "Vale-Transporte":
            principal = resultado_vt
        elif req.modalidade == "Vale-Combustível":
            principal = resultado_vc
        else:
            principal = resultado_vt or resultado_vc

        viabilidade_clt = None
        if req.salario_base and req.salario_base > 0 and principal:
            custo_mensal = principal.get("custo_mensal") or 0
            try:
                viabilidade_clt = analisar_viabilidade_clt(float(custo_mensal), float(req.salario_base))
            except Exception:
                viabilidade_clt = None

        if resultado_vt and resultado_vt.get("memoria_calculo"):
            memoria_final.extend(resultado_vt["memoria_calculo"])
        if resultado_vc and resultado_vc.get("memoria_calculo"):
            memoria_final.extend(resultado_vc["memoria_calculo"])
        if viabilidade_clt and viabilidade_clt.get("memoria_calculo"):
            memoria_final.extend(viabilidade_clt["memoria_calculo"])

        memoria_final.append(
            f"Precisão geográfica (origem): {geo_o.get('nivel_precisao', '—')} — fonte {geo_o.get('fonte', '—')}"
        )
        memoria_final.append(
            f"Precisão geográfica (destino): {geo_d.get('nivel_precisao', '—')} — fonte {geo_d.get('fonte', '—')}"
        )

        justificativa = f"Cálculo {req.modalidade} com {dias_efetivos} dias úteis ({escala} {mes:02d}/{ano} {uf}/{mun})."

        return RouteCalculateResponse(
            sucesso=True,
            principal=principal,
            vt=resultado_vt,
            vc=resultado_vc,
            comparativo=comparativo,
            viabilidade_clt=viabilidade_clt,
            coords=coords,
            origem_label=endereco_origem,
            destino_label=endereco_destino,
            dias_uteis=dias_efetivos,
            memoria_calculo=memoria_final,
            justificativa=justificativa,
        )

    except Exception as exc:
        logger.error("Falha em routes_calculate: %s", exc, exc_info=True)
        return RouteCalculateResponse(
            sucesso=False,
            erro="Não foi possível concluir o cálculo. Tente novamente em instantes.",
            memoria_calculo=["Erro no processamento da rota."],
        )


def _recalcular_vt_com_parametros(resultado_vt: dict, tarifa: float | None, dias_uteis: int) -> dict:
    """Helper para routes_calculate (reutiliza lógica de batch_service)."""
    from src.services.batch_service import _recalcular_vt_com_parametros as _recalc
    return _recalc(resultado_vt, tarifa, dias_uteis)


# -----------------------------------------------------------------------------
# PDF Report
# -----------------------------------------------------------------------------
@router.post("/reports/pdf")
def reports_pdf(req: PDFReportRequest):
    """Gera PDF de evidência/comprovante em memória (StreamingResponse application/pdf).

    Para Vale-Transporte individual com ``opcao_selecionada``, gera o comprovante
    com timeline Ida/Volta e bloco de assinatura; caso contrário, mantém o legado.

    Args:
        req: PDFReportRequest com dados_candidato, tipo_beneficio, dados_calculo,
            coords e (opcional) opcao_selecionada/dados_assinatura.

    Returns:
        StreamingResponse: PDF em BytesIO com Content-Disposition attachment.
    """
    try:
        if req.opcao_selecionada:
            pdf_buffer = gerar_pdf_comprovante(
                req.dados_candidato,
                req.dados_calculo,
                coords=req.coords,
                opcao_selecionada=req.opcao_selecionada,
                dados_assinatura=req.dados_assinatura,
            )
        else:
            pdf_buffer = gerar_pdf_evidencia(
                req.dados_candidato,
                req.tipo_beneficio,
                req.dados_calculo,
                coords=req.coords,
            )
        # Normaliza para BytesIO
        if isinstance(pdf_buffer, io.BytesIO):
            pdf_buffer.seek(0)
        else:
            pdf_buffer = io.BytesIO(pdf_buffer if isinstance(pdf_buffer, (bytes, bytearray)) else bytes(pdf_buffer))
            pdf_buffer.seek(0)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        filename = f"Comprovante_SmartPass_{req.tipo_beneficio.replace(' ', '_')}_{timestamp}.pdf"

        return StreamingResponse(
            pdf_buffer,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as exc:
        logger.error("Falha em reports_pdf: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Não foi possível gerar o PDF.") from exc


# -----------------------------------------------------------------------------
# Batch Simulate
# -----------------------------------------------------------------------------
@router.post("/batch/simulate", response_model=BatchSimulateResponse)
async def batch_simulate(
    file: UploadFile = File(..., description="Arquivo CSV/XLSX com colunas origem, destino"),
    dias_uteis: int = Query(22, ge=1, le=31, description="Dias úteis do mês"),
    tarifa_override: float | None = Query(None, ge=0, description="Override de tarifa unitária"),
):
    """Processa lote de colaboradores via UploadFile (CSV/XLSX) em memória.

    Args:
        file: Arquivo CSV/XLSX com colunas origem, destino, nome (opcional), salario_base (opcional).
        dias_uteis: Dias úteis do mês (default 22).
        tarifa_override: Override de tarifa unitária (None = usar oficial).

    Returns:
        BatchSimulateResponse: Resultados consolidados com totais de semáforo.
    """
    try:
        # Valida tamanho do upload
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Arquivo muito grande (máximo {MAX_UPLOAD_BYTES // 1024 // 1024} MB).")

        # Lê arquivo em memória
        from src.services.batch_service import ler_arquivo_lote, processar_lote
        df = ler_arquivo_lote(content, file.filename)

        if len(df) > MAX_BATCH_ROWS:
            raise HTTPException(status_code=413, detail=f"Lote muito grande (máximo {MAX_BATCH_ROWS} registros).")

        # Processa lote
        resultado = processar_lote(df, dias_uteis=dias_uteis, tarifa_override=tarifa_override)

        return BatchSimulateResponse(
            sucesso=resultado["sucesso"],
            total=resultado["total"],
            resultados=resultado["resultados"],
            totals=resultado["totals"],
            memoria_calculo=resultado["memoria_calculo"],
            erro=resultado["erro"],
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Falha em batch_simulate: %s", exc, exc_info=True)
        return BatchSimulateResponse(
            sucesso=False,
            total=0,
            resultados=[],
            totals={"n_alta": 0, "n_media": 0, "n_baixa": 0},
            memoria_calculo=[f"Falha no processamento do lote: {exc}"],
            erro=str(exc),
        )


@router.post("/batch/simulate/csv")
async def batch_simulate_csv(req: BatchDownloadCSVRequest):
    """Gera CSV do lote processado em memória (StreamingResponse text/csv).

    Args:
        req: BatchDownloadCSVRequest com resultados, layout, dias_uteis, competencia.

    Returns:
        StreamingResponse: CSV em BytesIO com Content-Disposition attachment.
    """
    try:
        df_resultados = pd.DataFrame(req.resultados)

        if req.layout == "completo":
            # CSV completo com todos os campos
            sio = io.StringIO()
            df_resultados.to_csv(sio, index=False)
            csv_bytes = sio.getvalue().encode("utf-8-sig")
            filename = f"smartpass_lote_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        elif req.layout == "compra":
            # Layout Padrão Compra (SPTrans/TOP)
            res = gerar_export_compra(df_resultados, dias_uteis=req.dias_uteis, competencia=req.competencia)
            if not res.get("sucesso"):
                raise HTTPException(status_code=400, detail=res.get("erro", "Falha ao gerar CSV compra."))
            csv_bytes = res["bytesio"].getvalue()
            filename = res["filename"]
        elif req.layout == "rubrica":
            # Layout Rubrica Folha (eSocial/ERP)
            res = gerar_export_rubrica(df_resultados, dias_uteis=req.dias_uteis, competencia=req.competencia)
            if not res.get("sucesso"):
                raise HTTPException(status_code=400, detail=res.get("erro", "Falha ao gerar CSV rubrica."))
            csv_bytes = res["bytesio"].getvalue()
            filename = res["filename"]
        else:
            raise HTTPException(status_code=400, detail=f"Layout inválido: {req.layout}")

        return StreamingResponse(
            io.BytesIO(csv_bytes),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Falha em batch_simulate_csv: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Não foi possível gerar o CSV.") from exc
