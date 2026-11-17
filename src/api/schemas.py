"""Modelos Pydantic v2 para requisições e respostas da API REST.

Tipagem estrita para validar inputs/outputs sem vazamento de stacktraces.
Todos os campos opcionais usam `None` como default para backward compatibility.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


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
    """Requisição para POST /routes/calculate (roteirizador individual VT)."""

    origem: str = Field(..., min_length=3, description="CEP ou endereço de origem (mínimo 3 caracteres)")
    destino: str = Field(..., min_length=3, description="CEP ou endereço de destino (mínimo 3 caracteres)")
    horario_entrada: str = Field("08:00", pattern=r"^\d{2}:\d{2}$", description="Horário de chegada no trabalho (HH:MM)")
    horario_saida: str = Field("18:00", pattern=r"^\d{2}:\d{2}$", description="Horário de saída do trabalho (HH:MM)")
    modalidade: Literal["Vale-Transporte", "Vale-Combustível", "Comparativo Completo"] = Field(
        "Vale-Transporte", description="Modalidade de cálculo (default: Vale-Transporte)"
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
    origem_lat: Optional[float] = Field(None, ge=-90, le=90, description="Latitude explícita de origem (pino arrastado)")
    origem_lon: Optional[float] = Field(None, ge=-180, le=180, description="Longitude explícita de origem (pino arrastado)")
    destino_lat: Optional[float] = Field(None, ge=-90, le=90, description="Latitude explícita de destino (pino arrastado)")
    destino_lon: Optional[float] = Field(None, ge=-180, le=180, description="Longitude explícita de destino (pino arrastado)")

    @field_validator("horario_entrada", "horario_saida")
    @classmethod
    def _validar_horario(cls, v: str) -> str:
        hh, mm = v.split(":")
        if not (0 <= int(hh) <= 23 and 0 <= int(mm) <= 59):
            raise ValueError("horário deve estar em HH:MM (00:00-23:59)")
        return v

    @model_validator(mode="after")
    def _validar_ordem_horarios(self) -> "RouteCalculateRequest":
        if self.horario_entrada >= self.horario_saida:
            raise ValueError("horario_entrada deve ser anterior a horario_saida")
        return self


class SentidoRota(BaseModel):
    """Roteirização + tarifa de um único sentido (ida ou volta)."""

    legs: list[dict[str, Any]] = Field(default_factory=list, description="Pernas enriquecidas (modo, geometria, horários)")
    legs_transito: list[dict[str, Any]] = Field(default_factory=list, description="Pernas de trânsito (com linha)")
    linhas: list[dict[str, Any]] = Field(default_factory=list, description="Linhas consolidadas (legado)")
    distancia_km: float = 0.0
    caminhada_km: float = 0.0
    baldeacoes: int = 0
    duracao_min: int = 0
    resumo_trajeto: str = ""
    geometria_fallback: bool = True
    horario_partida: Optional[str] = None
    horario_chegada: Optional[str] = None
    custo_trecho: float = 0.0
    detalhes: list[dict[str, Any]] = Field(default_factory=list, description="Detalhamento tarifário por condução")
    detalhamento_tarifario: list[str] = Field(default_factory=list)
    alertas_tarifa: list[str] = Field(default_factory=list)
    fonte: Optional[str] = None


class OpcaoRota(BaseModel):
    """Opção ranqueada de jornada (ida + volta) com custo consolidado."""

    tipo: Literal["mais_economica", "mais_rapida", "menor_caminhada"]
    categorias: list[str] = Field(default_factory=list, description="Categorias vencidas (multi-badge)")
    ida: SentidoRota
    volta: SentidoRota
    custo_diario: float = 0.0
    custo_mensal: float = 0.0
    tempo_total_min: int = 0
    baldeacoes_total: int = 0
    caminhada_total_km: float = 0.0
    resumo: str = ""


class RouteCalculateResponse(BaseModel):
    """Resposta do endpoint POST /routes/calculate."""

    sucesso: bool = Field(..., description="Indica se o cálculo foi bem-sucedido")
    opcoes: list[OpcaoRota] = Field(default_factory=list, description="Opções ranqueadas (até 3) para Vale-Transporte")
    viabilidade_clt: Optional[dict[str, Any]] = Field(None, description="Análise CLT 6% (Lei 7.418/85) quando salario_base > 0")
    coords: Optional[tuple[float, float, float, float]] = Field(None, description="Coordenadas (lat_o, lon_o, lat_d, lon_d)")
    origem_label: Optional[str] = Field(None, description="Endereço de origem formatado")
    destino_label: Optional[str] = Field(None, description="Endereço de destino formatado")
    dias_uteis: Optional[int] = Field(None, description="Dias úteis efetivos do cálculo")
    horario_entrada: Optional[str] = Field(None, description="Horário de entrada usado na consulta")
    horario_saida: Optional[str] = Field(None, description="Horário de saída usado na consulta")
    data_referencia: Optional[str] = Field(None, description="Data útil de referência usada no OTP (YYYY-MM-DD)")
    # Campos legados (preenchidos apenas em VC/Comparativo Completo)
    principal: Optional[dict[str, Any]] = Field(None, description="Resultado principal (legado VC)")
    vt: Optional[dict[str, Any]] = Field(None, description="Resultado Vale-Transporte (legado)")
    vc: Optional[dict[str, Any]] = Field(None, description="Resultado Vale-Combustível (legado)")
    comparativo: Optional[dict[str, Any]] = Field(None, description="Comparativo rápida vs econômica (legado)")
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
        "Vale-Transporte", description="Tipo de benefício"
    )
    dados_calculo: dict[str, Any] = Field(..., description="Dados completos do cálculo (origem, destino, custos, detalhes)")
    coords: Optional[tuple[float, float, float, float]] = Field(None, description="Coordenadas para o mapa (lat_o, lon_o, lat_d, lon_d)")
    dados_assinatura: Optional[dict[str, Any]] = Field(None, description="Dados para o bloco de assinatura (nome, cargo, cpf)")
    opcao_selecionada: Optional[dict[str, Any]] = Field(None, description="Opção selecionada (ida/volta) para o comprovante VT")


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
