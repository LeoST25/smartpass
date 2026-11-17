/**
 * Tipos TypeScript espelhando os schemas Pydantic da API FastAPI (src/api/schemas.py).
 * Mantém 1:1 para garantir type safety na integração frontend/backend.
 */

// -----------------------------------------------------------------------------
// Geocoding
// -----------------------------------------------------------------------------

export type NivelPrecisao = 'ALTA' | 'MEDIA' | 'BAIXA';

export interface CandidatoGeocoding {
  label_exibicao: string;
  lat: number;
  lon: number;
  nivel_precisao: NivelPrecisao;
  semaforo: string; // 🟢 Exato | 🟡 Aproximado | 🔴 Revisar
  motivo_precisao: string;
  fonte: string;
  cep?: string;
  logradouro?: string;
  numero?: string;
  bairro?: string;
  cidade?: string;
  uf?: string;
}

export interface GeocodingAutocompleteResponse {
  query: string;
  sugestoes: CandidatoGeocoding[];
}

// -----------------------------------------------------------------------------
// Route Calculate
// -----------------------------------------------------------------------------

export type Modalidade = 'Vale-Transporte' | 'Vale-Combustível' | 'Comparativo Completo';

export interface RouteCalculateRequest {
  origem: string;
  destino: string;
  horario_entrada?: string;
  horario_saida?: string;
  modalidade?: Modalidade;
  dias_uteis?: number;
  escala?: string;
  uf_destino?: string;
  municipio_destino?: string;
  ano_ref?: number;
  mes_ref?: number;
  salario_base?: number;
  tarifa_override?: number;
  valor_km?: number;
  origem_lat?: number;
  origem_lon?: number;
  destino_lat?: number;
  destino_lon?: number;
}

export interface DetalheTarifa {
  linha: string;
  codigo_linha?: string;
  operadora?: string;
  valor_unitario: number;
  valor_base?: number;
  quantidade_dia: number;
  subtotal: number;
  tipo?: string; // SPTRANS_ONIBUS | TRILHO | EMTU | OUTRO
  fonte?: string;
  tarifa_confirmada?: boolean;
}

export interface Leg {
  mode: string; // BUS | WALK | RAIL | SUBWAY | TRAM
  distance: number; // metros
  duration: number; // segundos
  startTime?: number | string;
  endTime?: number | string;
  from: { name: string; lat: number; lon: number };
  to: { name: string; lat: number; lon: number };
  route?: {
    gtfsId?: string;
    shortName?: string;
    longName?: string;
    agency?: { gtfsId?: string; name?: string };
  };
  pontos: [number, number][]; // lat, lon decodificados
  codigo_linha?: string;
  agency?: { gtfsId?: string; name?: string };
  geometria_fallback?: boolean;
  horario_inicio?: string;
  horario_fim?: string;
  linha?: string;
}

export interface LinhaOnibus {
  linha: string;
  valor_unitario: number;
  quantidade_dia: number;
  codigo_linha?: string;
  operadora?: string;
}

// -----------------------------------------------------------------------------
// Roteirizador Individual — Ida + Volta
// -----------------------------------------------------------------------------

export interface SentidoRota {
  legs: Leg[];
  legs_transito: Leg[];
  linhas: LinhaOnibus[];
  distancia_km: number;
  caminhada_km: number;
  baldeacoes: number;
  duracao_min: number;
  resumo_trajeto: string;
  geometria_fallback: boolean;
  horario_partida?: string | null;
  horario_chegada?: string | null;
  custo_trecho: number;
  detalhes: DetalheTarifa[];
  detalhamento_tarifario: string[];
  alertas_tarifa: string[];
  fonte?: string | null;
}

export type TipoOpcao = 'mais_economica' | 'mais_rapida' | 'menor_caminhada';

export interface OpcaoRota {
  tipo: TipoOpcao;
  categorias: string[];
  ida: SentidoRota;
  volta: SentidoRota;
  custo_diario: number;
  custo_mensal: number;
  tempo_total_min: number;
  baldeacoes_total: number;
  caminhada_total_km: number;
  resumo: string;
}

export interface ViabilidadeCLT {
  sucesso: boolean;
  teto_desconto_6_pct: number;
  desconto_colaborador: number;
  custeio_empresa: number;
  vt_vantajoso: boolean;
  recomendacao: string;
  memoria_calculo: string[];
  justificativa: string;
  erro?: string;
}

export interface RouteCalculateResponse {
  sucesso: boolean;
  opcoes: OpcaoRota[];
  viabilidade_clt: ViabilidadeCLT | null;
  coords: [number, number, number, number] | null; // lat_o, lon_o, lat_d, lon_d
  origem_label: string | null;
  destino_label: string | null;
  dias_uteis: number | null;
  horario_entrada: string | null;
  horario_saida: string | null;
  data_referencia: string | null;
  // Legado (VC/Comparativo Completo)
  principal: Record<string, unknown> | null;
  vt: Record<string, unknown> | null;
  vc: Record<string, unknown> | null;
  comparativo: Record<string, unknown> | null;
  memoria_calculo: string[];
  justificativa: string | null;
  erro: string | null;
}

// -----------------------------------------------------------------------------
// Health
// -----------------------------------------------------------------------------

export interface HealthResponse {
  status: 'ok' | 'degraded' | 'down';
  postgres: {
    ok: boolean;
    postgis_version?: string;
    latency_ms?: number;
    erro?: string;
  };
  otp: {
    ok: boolean;
    latency_ms?: number;
    erro?: string;
  };
  timestamp: string;
}

// -----------------------------------------------------------------------------
// Batch Simulate (legado — endpoint mantido na API, sem UI)
// -----------------------------------------------------------------------------

export interface BatchSimulateResponse {
  sucesso: boolean;
  total: number;
  resultados: Array<{
    linha: number;
    nome?: string;
    cpf_mascarado?: string;
    origem: string;
    destino: string;
    distancia_km?: number;
    custo_diario?: number;
    custo_mensal?: number;
    teto_6_pct?: number;
    desconto_colaborador?: number;
    subsidio_empresa?: number;
    status_viabilidade_clt?: string;
    nivel_precisao: NivelPrecisao;
    semaforo: string;
    motivo_precisao?: string;
    erro?: string;
  }>;
  totals: {
    n_alta: number;
    n_media: number;
    n_baixa: number;
  };
  memoria_calculo: string[];
  erro: string | null;
}

export interface PDFReportRequest {
  dados_candidato: {
    nome?: string;
    cargo?: string;
    centro_custo?: string;
    [key: string]: unknown;
  };
  tipo_beneficio: Modalidade;
  dados_calculo: Record<string, unknown>;
  coords?: [number, number, number, number];
  dados_assinatura?: {
    nome?: string;
    cargo?: string;
    cpf?: string;
    [key: string]: unknown;
  };
  opcao_selecionada?: OpcaoRota;
}
