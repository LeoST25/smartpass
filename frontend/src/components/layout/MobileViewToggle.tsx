/**
 * Toggle para alternar entre Mapa e Painel no mobile.
 */

import { Map, List } from 'lucide-react';
import { useAppState } from '../../state/AppContext';

export function MobileViewToggle() {
  const { state, dispatch } = useAppState();

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-20 lg:hidden bg-white rounded-full shadow-lg border border-slate-200 p-1 flex gap-1">
      <button
        type="button"
        onClick={() => dispatch({ type: 'SET_VIEW_MODE', payload: 'map' })}
        className={`flex items-center gap-2 px-4 py-2 rounded-full transition-colors ${
          state.viewMode === 'map'
            ? 'bg-smartpass-600 text-white'
            : 'text-slate-600 hover:bg-slate-100'
        }`}
        aria-label="Ver mapa"
      >
        <Map className="w-4 h-4" />
        <span className="text-sm font-medium">Mapa</span>
      </button>
      <button
        type="button"
        onClick={() => dispatch({ type: 'SET_VIEW_MODE', payload: 'panel' })}
        className={`flex items-center gap-2 px-4 py-2 rounded-full transition-colors ${
          state.viewMode === 'panel'
            ? 'bg-smartpass-600 text-white'
            : 'text-slate-600 hover:bg-slate-100'
        }`}
        aria-label="Ver resultados"
      >
        <List className="w-4 h-4" />
        <span className="text-sm font-medium">Rota</span>
      </button>
    </div>
  );
}
