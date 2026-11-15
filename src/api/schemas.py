"""Modelos Pydantic v2 para requisições e respostas da API REST.

Tipagem estrita para validar inputs/outputs sem vazamento de stacktraces.
Todos os campos opcionais usam `None` como default para backward compatibility.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Geocoding
# -----------------------------------------------------------------------------
class CandidatoGeocoding(BaseModel):
    """Candidato de geocodificação com semáforo de precisão."""

    label_exibicao: str = Field(..., description="Endereço formatado para exibição")
    lat: float = Field(..., ge=-90, le=90, description="Latitude WGS84")
    lon: float = Field(..., ge=-180, le=180, description="Longitude WGS84")
    nivel_precisao: Literal["ALTA", "MEDIA", "BAIXA"] = Field(..., description="Nível de precisão geográfica")
    semaforo: str = Field(..., description="Semáforo visual (🟢 Exato | 🟡 Aproximado | 🔴 Revisar)")
    motivo_precisao: str = Field(..., description="Motivo técnico do nível de precisão")
    fonte: str = Field(..., description="Fonte da geocodificação (viacep, photon, nominatim, google)")
    cep: Optional[str] = Field(None, description="CEP (8 dígitos) quando aplicável")
    logradouro: Optional[str] = Field(None, description="Logradouro quando identificado")
    numero: Optional[str] = Field(None, description="Número quando identificado")
    bairro: Optional[str] = Field(None, description="Bairro quando identificado")
    cidade: Optional[str] = Field(None, description="Cidade quando identificada")
    uf: Optional[str] = Field(None, description="UF quando identificada")


class GeocodingAutocompleteResponse(BaseModel):
    """Resposta do endpoint GET /geocoding/autocomplete."""

    query: str = Field(..., description="Query original de busca")
    sugestoes: list[CandidatoGeocoding] = Field(default_factory=list, description="Lista de sugestões")


# -----------------------------------------------------------------------------
# Route Calculate
# -----------------------------------------------------------------------------
class RouteCalculateRequest(BaseModel):
    """Requisição para POST /routes/calculate."""

    origem: str = Field(..., min_length=3, description="CEP ou endereço de origem (mínimo 3 caracteres)")
    destino: str = Field(..., min_length=3, description="CEP ou endereço de destino (mínimo 3 caracteres)")
    modalidade: Literal["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"] = Field(
        ..., description="Modalidade de cálculo"
    )
    dias_uteis: Optional[int] = Field(None, ge=1, le=31, description="Override de dias úteis (1-31)")
    escala: Optional[str] = Field("5x2", description="Escala de trabalho (5x2, 6x1, 12x36, Híbrido)")
    uf_destino: Optional[str] = Field("SP", description="UF da unidade de destino")
    municipio_destino: Optional[str] = Field("São Paulo", description="Município da unidade de destino")
    ano_ref: Optional[int] = Field(None, description="Ano de referência (AAAA)")
    mes_ref: Optional[int] = Field(None, ge=1, le=12, description="Mês de referência (1-12)")
    salario_base: Optional[float] = Field(None, ge=0, description="Salário-base CLT (opcional)")
    tarifa_override: Optional[float] = Field(None, ge=0, description="Override de tarifa unitária (opcional)")
    valor_km: Optional[float] = Field(1.25, ge=0, description="Valor por KM para Vale-Combustível")


class RouteCalculateResponse(BaseModel):
    """Resposta do endpoint POST /routes/calculate."""

    sucesso: bool = Field(..., description="Indica se o cálculo foi bem-sucedido")
    principal: Optional[dict[str, Any]] = Field(None, description="Resultado principal (VT ou VC)")
    vt: Optional[dict[str, Any]] = Field(None, description="Resultado Vale-Transporte completo")
    vc: Optional[dict[str, Any]] = Field(None, description="Resultado Vale-Combustível completo")
    comparativo: Optional[dict[str, Any]] = Field(None, description="Comparativo rápida vs econômica")
    coords: Optional[tuple[float, float, float, float]] = Field(None, description="Coordenadas (lat_o, lon_o, lat_d, lon_d)")
    origem_label: Optional[str] = Field(None, description="Endereço de origem formatado")
    destino_label: Optional[str] = Field(None, description="Endereço de destino formatado")
    memoria_calculo: list[str] = Field(default_factory=list, description="Trilha auditável de cálculos")
    justificativa: Optional[str] = Field(None, description="Justificativa consolidada")
    erro: Optional[str] = Field(None, description="Mensagem de erro quando sucesso=False")


# -----------------------------------------------------------------------------
# PDF Report
# -----------------------------------------------------------------------------
class PDFReportRequest(BaseModel):
    """Requisição para POST /reports/pdf."""

    dados_candidato: dict[str, Any] = Field(..., description="Dados do colaborador (nome, cargo, centro_custo)")
    tipo_beneficio: Literal["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"] = Field(
        ..., description="Tipo de benefício"
    )
    dados_calculo: dict[str, Any] = Field(..., description="Dados completos do cálculo (origem, destino, custos, detalhes)")
    coords: Optional[tuple[float, float, float, float]] = Field(None, description="Coordenadas para o mapa (lat_o, lon_o, lat_d, lon_d)")


# -----------------------------------------------------------------------------
# Batch Simulate
# -----------------------------------------------------------------------------
class BatchSimulateResponse(BaseModel):
    """Resposta do endpoint POST /batch/simulate."""

    sucesso: bool = Field(..., description="Indica se o processamento foi bem-sucedido")
    total: int = Field(..., ge=0, description="Total de registros processados")
    resultados: list[dict[str, Any]] = Field(default_factory=list, description="Resultados por registro")
    totals: dict[str, int] = Field(
        default_factory=dict,
        description="Totais por nível de precisão (n_alta, n_media, n_baixa)",
    )
    memoria_calculo: list[str] = Field(default_factory=list, description="Trilha auditável do lote")
    erro: Optional[str] = Field(None, description="Mensagem de erro quando sucesso=False")


class BatchDownloadCSVRequest(BaseModel):
    """Requisição para POST /batch/simulate/csv."""

    resultados: list[dict[str, Any]] = Field(..., description="Resultados do lote")
    layout: Literal["completo", "compra", "rubrica"] = Field(
        "completo", description="Layout do CSV (completo, compra, rubrica)"
    )
    dias_uteis: int = Field(22, ge=1, le=31, description="Dias úteis do mês")
    competencia: Optional[str] = Field(None, description="Competência MM/AAAA")
