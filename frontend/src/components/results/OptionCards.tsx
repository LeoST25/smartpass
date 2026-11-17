/**
 * Cards clicáveis das opções ranqueadas (mais econômica / mais rápida / menor caminhada).
 */

import { Zap, PiggyBank, Footprints, ArrowRight } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { formatCurrency, formatDuration } from '../../lib/format';
import type { TipoOpcao } from '../../types/api';

const CONFIG: Record<
  TipoOpcao,
  { icon: typeof Zap; label: string; color: string; bg: string; border: string }
> = {
  mais_economica: {
    icon: PiggyBank,
    label: 'Mais Econômica',
    color: 'text-green-600',
    bg: 'bg-green-50',
    border: 'border-green-500',
  },
  mais_rapida: {
    icon: Zap,
    label: 'Mais Rápida',
    color: 'text-amber-600',
    bg: 'bg-amber-50',
    border: 'border-amber-500',
  },
  menor_caminhada: {
    icon: Footprints,
    label: 'Menor Caminhada',
    color: 'text-blue-600',
    bg: 'bg-blue-50',
    border: 'border-blue-500',
  },
};

export function OptionCards() {
  const { state, dispatch } = useAppState();

  if (!state.result?.opcoes || state.result.opcoes.length === 0) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold text-slate-700">Opções de jornada</h3>
      {state.result.opcoes.map((opcao, idx) => {
        const cfg = CONFIG[opcao.tipo];
        const Icon = cfg.icon;
        const selected = state.selectedOptionIndex === idx;

        return (
          <button
            key={`${opcao.tipo}-${idx}`}
            type="button"
            onClick={() => dispatch({ type: 'SET_SELECTED_OPTION_INDEX', payload: idx })}
            className={`w-full text-left rounded-lg border-2 p-3 transition-colors ${
              selected ? `${cfg.border} ${cfg.bg}` : 'border-slate-200 bg-white hover:border-slate-300'
            }`}
            aria-pressed={selected}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <Icon className={`w-4 h-4 ${cfg.color}`} />
                <span className="text-sm font-semibold text-slate-900">{cfg.label}</span>
              </div>
              {selected && <span className="text-xs font-medium text-smartpass-600">Selecionada</span>}
            </div>

            <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
              <div className="flex items-center gap-1.5 text-slate-700">
                <span className="text-slate-500 text-xs">Tempo</span>
                <span className="font-medium">{formatDuration(opcao.tempo_total_min)}</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-700">
                <span className="text-slate-500 text-xs">Baldeações</span>
                <span className="font-medium">{opcao.baldeacoes_total}</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-700">
                <span className="text-slate-500 text-xs">Diário</span>
                <span className="font-medium">{formatCurrency(opcao.custo_diario)}</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-700">
                <span className="text-slate-500 text-xs">Mensal</span>
                <span className="font-medium text-smartpass-700">
                  {formatCurrency(opcao.custo_mensal)}
                </span>
              </div>
            </div>

            <div className="mt-2 flex items-center gap-1.5 text-xs text-slate-500">
              <span>Ida {opcao.ida.duracao_min}min</span>
              <ArrowRight className="w-3 h-3" />
              <span>Volta {opcao.volta.duracao_min}min</span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
