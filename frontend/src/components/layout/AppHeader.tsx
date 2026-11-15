/**
 * Header da aplicação com logo e indicador de status do sistema.
 */

import { useEffect } from 'react';
import { Activity } from 'lucide-react';
import { api, ApiError } from '../../lib/api';
import { useAppState } from '../../state/AppContext';

export function AppHeader() {
  const { state, dispatch } = useAppState();
  const health = state.health;

  useEffect(() => {
    let mounted = true;

    async function fetchHealth() {
      try {
        const data = await api.health();
        if (mounted) {
          dispatch({ type: 'SET_HEALTH', payload: data });
        }
      } catch (error: unknown) {
        if (mounted && error instanceof ApiError) {
          console.warn('[Health]', error.message);
        }
      }    }

    fetchHealth();
    const interval = setInterval(fetchHealth, 30000); // poll 30s

    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, [dispatch]);

  const getStatusColor = () => {
    if (!health) return 'bg-slate-300';
    switch (health.status) {
      case 'ok':
        return 'bg-green-500';
      case 'degraded':
        return 'bg-amber-500';
      case 'down':
        return 'bg-red-500';
      default:
        return 'bg-slate-300';
    }
  };

  const getStatusText = () => {
    if (!health) return 'Verificando...';
    switch (health.status) {
      case 'ok':
        return 'Sistema disponível';
      case 'degraded':
        return 'Sistema parcialmente indisponível';
      case 'down':
        return 'Sistema indisponível';
      default:
        return 'Status desconhecido';
    }
  };

  return (
    <header className="bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <div className="w-8 h-8 bg-smartpass-600 rounded-lg flex items-center justify-center">
          <span className="text-white font-bold text-sm">SP</span>
        </div>
        <h1 className="text-lg font-semibold text-slate-900">SmartPass</h1>
      </div>

      <div className="flex items-center gap-2 text-sm" title={getStatusText()}>
        <Activity className="w-4 h-4 text-slate-500" />
        <div className={`w-2 h-2 rounded-full ${getStatusColor()}`} />
        <span className="text-slate-600 hidden sm:inline">{getStatusText()}</span>
      </div>
    </header>
  );
}
