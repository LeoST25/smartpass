/**
 * Formulário de busca com origem, destino e parâmetros avançados.
 */

import { MapPin, Navigation } from 'lucide-react';
import { AddressAutocomplete } from './AddressAutocomplete';
import { AdvancedParams } from './AdvancedParams';
import { useAppState } from '../../state/AppContext';
import { api } from '../../lib/api';
import type { CandidatoGeocoding } from '../../types/api';

export function SearchForm() {
  const { state, dispatch } = useAppState();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    if (!state.origem || !state.destino) {
      return;
    }

    dispatch({ type: 'CALCULATE_START' });

    try {
      const data = await api.calculateRoute({
        origem: state.origem.label_exibicao,
        destino: state.destino.label_exibicao,
        modalidade: state.modalidade,
        dias_uteis: state.diasUteis,
        salario_base: state.salarioBase ?? undefined,
      });

      if (data.sucesso) {
        dispatch({ type: 'CALCULATE_SUCCESS', payload: data });
      } else {
        dispatch({
          type: 'CALCULATE_ERROR',
          payload: data.erro || 'Não foi possível calcular a rota.',
        });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : 'Erro ao calcular rota.';
      dispatch({ type: 'CALCULATE_ERROR', payload: message });
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <div className="flex items-center gap-2 mb-2">
          <MapPin className="w-5 h-5 text-smartpass-600" />
          <h2 className="text-lg font-semibold text-slate-900">Calcular rota</h2>
        </div>
        <p className="text-sm text-slate-600 mb-4">
          Informe o endereço de residência (origem) e o local de trabalho (destino) para calcular o benefício de transporte.
        </p>
      </div>

      <AddressAutocomplete
        label="Endereço de residência"
        value={state.origem}
        onChange={(candidate: CandidatoGeocoding | null) =>
          dispatch({ type: 'SET_ORIGEM', payload: candidate })
        }
      />

      <AddressAutocomplete
        label="Local de trabalho"
        value={state.destino}
        onChange={(candidate: CandidatoGeocoding | null) =>
          dispatch({ type: 'SET_DESTINO', payload: candidate })
        }
      />

      <AdvancedParams />

      <button
        type="submit"
        disabled={!state.origem || !state.destino || state.loading}
        className="w-full bg-smartpass-600 hover:bg-smartpass-700 disabled:bg-slate-300 disabled:cursor-not-allowed text-white font-medium py-2.5 px-4 rounded-lg transition-colors flex items-center justify-center gap-2"
      >
        {state.loading ? (
          <>
            <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
            <span>Calculando...</span>
          </>
        ) : (
          <>
            <Navigation className="w-4 h-4" />
            <span>Calcular rota</span>
          </>
        )}
      </button>
    </form>
  );
}
