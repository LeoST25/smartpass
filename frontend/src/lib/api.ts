/**
 * Cliente HTTP tipado para a API FastAPI.
 * Centraliza fetch + tratamento de erros com mensagens de negócio.
 */

import type {
  BatchSimulateResponse,
  GeocodingAutocompleteResponse,
  HealthResponse,
  PDFReportRequest,
  RouteCalculateRequest,
  RouteCalculateResponse,
} from '../types/api';

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1';

/**
 * Erro de API com mensagem amigável (nunca expõe stacktrace).
 */
export class ApiError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

/**
 * Wrapper genérico para chamadas fetch com tratamento de erros.
 */
async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000); // 30s timeout

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = 'Erro ao processar sua solicitação. Tente novamente.';
      if (response.status === 400) {
        message = 'Dados inválidos. Verifique as informações informadas.';
      } else if (response.status === 404) {
        message = 'Recurso não encontrado.';
      } else if (response.status === 413) {
        message = 'Arquivo muito grande. O limite é 10 MB.';
      } else if (response.status === 422) {
        message = 'Dados inválidos. Revise os campos e tente novamente.';
      } else if (response.status === 503) {
        message = 'Serviço temporariamente indisponível. Tente em instantes.';
      }

      throw new ApiError(message, response.status);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('Tempo limite excedido. Tente novamente.');
    }
    throw new ApiError('Falha na conexão. Verifique sua internet.');
  } finally {
    clearTimeout(timeoutId);
  }
}

/**
 * Wrapper para chamadas que retornam Blob (PDF/CSV).
 */
async function requestBlob(
  path: string,
  options?: RequestInit
): Promise<Blob> {
  const url = `${BASE_URL}${path}`;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    if (!response.ok) {
      let message = 'Erro ao gerar o arquivo. Tente novamente.';
      if (response.status === 503) {
        message = 'Serviço temporariamente indisponível.';
      }
      throw new ApiError(message, response.status);
    }

    return await response.blob();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('Tempo limite excedido.');
    }
    throw new ApiError('Falha na conexão.');
  } finally {
    clearTimeout(timeoutId);
  }
}

// -----------------------------------------------------------------------------
// API pública
// -----------------------------------------------------------------------------

export const api = {
  /**
   * Health check do sistema (Postgres + OTP).
   */
  health(): Promise<HealthResponse> {
    return request('/health');
  },

  /**
   * Autocomplete de endereços (geocoding).
   */
  autocomplete(q: string, limite = 5): Promise<GeocodingAutocompleteResponse> {
    const params = new URLSearchParams({ q, limite: String(limite) });
    return request(`/geocoding/autocomplete?${params}`);
  },

  /**
   * Calcular rota com VT/VC/Comparativo.
   */
  calculateRoute(data: RouteCalculateRequest): Promise<RouteCalculateResponse> {
    return request('/routes/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  /**
   * Gerar PDF de evidência (retorna Blob).
   */
  async generatePdf(data: PDFReportRequest): Promise<Blob> {
    return requestBlob('/reports/pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    });
  },

  /**
   * Simulação em lote (upload CSV/XLSX).
   */
  async batchSimulate(file: File, diasUteis = 22, tarifaOverride?: number): Promise<BatchSimulateResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const params = new URLSearchParams({
      dias_uteis: String(diasUteis),
    });
    if (tarifaOverride !== undefined) {
      params.append('tarifa_override', String(tarifaOverride));
    }

    const url = `${BASE_URL}/batch/simulate?${params}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 120000); // 2min para lote

    try {
      const response = await fetch(url, {
        method: 'POST',
        body: formData,
        signal: controller.signal,
      });

      if (!response.ok) {
        let message = 'Erro ao processar o lote. Tente novamente.';
        if (response.status === 413) {
          message = 'Arquivo muito grande ou com muitos registros.';
        }
        throw new ApiError(message, response.status);
      }

      return (await response.json()) as BatchSimulateResponse;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error instanceof Error && error.name === 'AbortError') {
        throw new ApiError('Tempo limite excedido.');
      }
      throw new ApiError('Falha na conexão.');
    } finally {
      clearTimeout(timeoutId);
    }
  },

  /**
   * Download CSV do lote processado (retorna Blob).
   */
  async batchDownloadCsv(
    resultados: BatchSimulateResponse['resultados'],
    layout: 'completo' | 'compra' | 'rubrica' = 'completo',
    diasUteis = 22,
    competencia?: string
  ): Promise<Blob> {
    const body = {
      resultados,
      layout,
      dias_uteis: diasUteis,
      competencia,
    };

    return requestBlob('/batch/simulate/csv', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  },
};
