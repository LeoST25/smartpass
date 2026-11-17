/**
 * Seletor discreto de direção (Ida / Volta) exibido sobre o mapa.
 * Evita sobrepor as duas linhas quando ida e volta usam ruas diferentes.
 */

import { Sun, Moon } from 'lucide-react';
import { useAppState } from '../../state/AppContext';

export function DirectionToggle() {
  const { state, dispatch } = useAppState();

  const hasResult = state.result?.opcoes && state.result.opcoes.length > 0;
  if (!hasResult) return null;

  const options = [
    { value: 'ida', label: 'Ida', icon: Sun },
    { value: 'volta', label: 'Volta', icon: Moon },
  ] as const;

  return (
    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-[1000] bg-white rounded-full shadow-lg border border-slate-200 p-1 flex gap-1">
      {options.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          onClick={() => dispatch({ type: 'SET_MAP_DIRECTION', payload: value })}
          className={`flex items-center gap-1.5 px-4 py-1.5 rounded-full text-sm font-medium transition-colors ${
            state.mapDirection === value
              ? 'bg-smartpass-600 text-white'
              : 'text-slate-600 hover:bg-slate-100'
          }`}
          aria-pressed={state.mapDirection === value}
        >
          <Icon className="w-4 h-4" />
          <span>{label}</span>
        </button>
      ))}
    </div>
  );
}
