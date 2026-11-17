/**
 * Formulário do roteirizador individual:
 *  - Bloco 1 (Trajeto): Origem/Destino com autocomplete + inverter.
 *  - Bloco 2 (Jornada): Entrada/Saída, Dias Úteis, Escala e Salário Base.
 */

import { MapPin, ArrowUpDown, Navigation, Clock } from 'lucide-react';
import { AddressAutocomplete } from './AddressAutocomplete';
import { useAppState } from '../../state/AppContext';
import { api } from '../../lib/api';
import type { CandidatoGeocoding } from '../../types/api';

const ESCALAS = ['5x2', '6x1', '12x36'];

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
        horario_entrada: state.horarioEntrada,
        horario_saida: state.horarioSaida,
        escala: state.escala,
        dias_uteis: state.diasUteis ?? undefined,
        salario_base: state.salarioBase ?? undefined,
        // Coords explícitas quando o pino foi arrastado no mapa
        ...(state.coordsEdited && state.origem && state.destino
          ? {
              origem_lat: state.origem.lat,
              origem_lon: state.origem.lon,
              destino_lat: state.destino.lat,
              destino_lon: state.destino.lon,
            }
          : {}),
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

  function handleSwap() {
    const origem = state.origem;
    const destino = state.destino;
    dispatch({ type: 'SET_ORIGEM', payload: destino });
    dispatch({ type: 'SET_DESTINO', payload: origem });
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      {/* Bloco 1 — Trajeto */}
      <section>
        <div className="flex items-center gap-2 mb-3">
          <MapPin className="w-5 h-5 text-smartpass-600" />
          <h2 className="text-base font-semibold text-slate-900">Trajeto</h2>
        </div>

        <div className="space-y-2">
          <AddressAutocomplete
            label="Origem (Residência)"
            value={state.origem}
            onChange={(candidate: CandidatoGeocoding | null) =>
              dispatch({ type: 'SET_ORIGEM', payload: candidate })
            }
          />

          <div className="flex items-center justify-center -my-1 relative z-10">
            <button
              type="button"
              onClick={handleSwap}
              disabled={!state.origem || !state.destino}
              className="w-8 h-8 rounded-full bg-white border border-slate-200 shadow-sm flex items-center justify-center text-slate-500 hover:text-smartpass-600 hover:border-smartpass-300 disabled:opacity-40 transition-colors"
              aria-label="Inverter origem e destino"
              title="Inverter origem e destino"
            >
              <ArrowUpDown className="w-4 h-4" />
            </button>
          </div>

          <AddressAutocomplete
            label="Destino (Trabalho)"
            value={state.destino}
            onChange={(candidate: CandidatoGeocoding | null) =>
              dispatch({ type: 'SET_DESTINO', payload: candidate })
            }
          />
        </div>
      </section>

      {/* Bloco 2 — Jornada */}
      <section className="border-t border-slate-200 pt-4">
        <div className="flex items-center gap-2 mb-3">
          <Clock className="w-5 h-5 text-smartpass-600" />
          <h2 className="text-base font-semibold text-slate-900">Jornada</h2>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Entrada</label>
            <input
              type="time"
              value={state.horarioEntrada}
              onChange={(e) => dispatch({ type: 'SET_HORARIO_ENTRADA', payload: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Saída</label>
            <input
              type="time"
              value={state.horarioSaida}
              onChange={(e) => dispatch({ type: 'SET_HORARIO_SAIDA', payload: e.target.value })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 mt-3">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Dias úteis <span className="text-xs font-normal text-slate-400">(auto)</span>
            </label>
            <input
              type="number"
              min={1}
              max={31}
              value={state.diasUteis ?? ''}
              onChange={(e) =>
                dispatch({
                  type: 'SET_DIAS_UTEIS',
                  payload: e.target.value ? Number(e.target.value) : null,
                })
              }
              placeholder="Auto"
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Escala</label>
            <div className="grid grid-cols-3 gap-1 bg-slate-100 p-1 rounded-lg">
              {ESCALAS.map((escala) => (
                <button
                  key={escala}
                  type="button"
                  onClick={() => dispatch({ type: 'SET_ESCALA', payload: escala })}
                  className={`px-1 py-1.5 text-xs font-medium rounded-md transition-colors ${
                    state.escala === escala
                      ? 'bg-white text-smartpass-700 shadow-sm'
                      : 'text-slate-600 hover:bg-slate-50'
                  }`}
                >
                  {escala}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-3">
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Salário base (opcional)
          </label>
          <input
            type="number"
            min={0}
            step={0.01}
            value={state.salarioBase ?? ''}
            onChange={(e) =>
              dispatch({
                type: 'SET_SALARIO_BASE',
                payload: e.target.value ? Number(e.target.value) : null,
              })
            }
            placeholder="Ex: 2500.00"
            className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500"
          />
          <p className="text-xs text-slate-500 mt-1">
            Preencha para exibir o teto CLT 6% (Lei 7.418/85)
          </p>
        </div>
      </section>

      {state.coordsEdited && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs text-amber-700">
          Pino ajustado no mapa — clique em <strong>Calcular rota</strong> para aplicar as novas
          coordenadas.
        </div>
      )}

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
