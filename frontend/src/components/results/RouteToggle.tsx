/**
 * Toggle para alternar entre rota mais rápida e mais econômica.
 */

import { Zap, PiggyBank } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { formatCurrency } from '../../lib/format';

export function RouteToggle() {
  const { state, dispatch } = useAppState();

  if (!state.result?.comparativo) return null;

  const { rota_mais_rapida, rota_mais_economica, economia_mensal } = state.result.comparativo;

  // Só exibe se houver rota econômica diferente da rápida
  if (!rota_mais_rapida || !rota_mais_economica) return null;
  if (rota_mais_rapida === rota_mais_economica) return null;

  const selected = state.selectedRoute;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium text-slate-700">Escolha a rota</h3>
      <div className="grid grid-cols-2 gap-2">
        <button
          type="button"
          onClick={() => dispatch({ type: 'SET_SELECTED_ROUTE', payload: 'rapida' })}
          className={`flex flex-col items-start p-3 rounded-lg border-2 transition-colors ${
            selected === 'rapida'
              ? 'border-smartpass-600 bg-smartpass-50'
              : 'border-slate-200 bg-white hover:border-slate-300'
          }`}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <Zap className="w-4 h-4 text-amber-600" />
            <span className="text-sm font-medium text-slate-900">Mais rápida</span>
          </div>
          <div className="text-xs text-slate-600">
            {rota_mais_rapida.duracao_min}min · {formatCurrency(rota_mais_rapida.custo_mensal)}/mês
          </div>
        </button>

        <button
          type="button"
          onClick={() => dispatch({ type: 'SET_SELECTED_ROUTE', payload: 'economica' })}
          className={`flex flex-col items-start p-3 rounded-lg border-2 transition-colors ${
            selected === 'economica'
              ? 'border-smartpass-600 bg-smartpass-50'
              : 'border-slate-200 bg-white hover:border-slate-300'
          }`}
        >
          <div className="flex items-center gap-1.5 mb-1">
            <PiggyBank className="w-4 h-4 text-green-600" />
            <span className="text-sm font-medium text-slate-900">Mais econômica</span>
          </div>
          <div className="text-xs text-slate-600">
            {rota_mais_economica.duracao_min}min · {formatCurrency(rota_mais_economica.custo_mensal)}/mês
          </div>
          {economia_mensal > 0 && (
            <div className="text-xs font-medium text-green-600 mt-1">
              Economia: {formatCurrency(economia_mensal)}/mês
            </div>
          )}
        </button>
      </div>
    </div>
  );
}
