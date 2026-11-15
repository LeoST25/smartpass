/**
 * Acordeão de parâmetros avançados (recolhido por padrão).
 */

import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import type { Modalidade } from '../../types/api';

export function AdvancedParams() {
  const [isOpen, setIsOpen] = useState(false);
  const { state, dispatch } = useAppState();

  const modalidades: Modalidade[] = ['Vale-Transporte', 'Vale-Combustível', 'Comparativo Completo'];

  return (
    <div className="border border-slate-200 rounded-lg">
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50 rounded-lg"
        aria-expanded={isOpen}
      >
        <span>Parâmetros avançados</span>
        {isOpen ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
      </button>

      {isOpen && (
        <div className="px-4 pb-4 space-y-3 border-t border-slate-200">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Modalidade</label>
            <select
              value={state.modalidade}
              onChange={(e) =>
                dispatch({ type: 'SET_MODALIDADE', payload: e.target.value as Modalidade })
              }
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500"
            >
              {modalidades.map((mod) => (
                <option key={mod} value={mod}>
                  {mod}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Dias úteis</label>
            <input
              type="number"
              min={1}
              max={31}
              value={state.diasUteis}
              onChange={(e) => dispatch({ type: 'SET_DIAS_UTEIS', payload: Number(e.target.value) })}
              className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">
              Salário-base (opcional)
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
              Preencha para analisar viabilidade CLT (6%)
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
