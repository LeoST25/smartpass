/**
 * Painel de resultados com cards, toggle, banner CLT, timeline e download.
 */

import { AlertCircle } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { SummaryCards } from './SummaryCards';
import { RouteToggle } from './RouteToggle';
import { CltBanner } from './CltBanner';
import { Timeline } from './Timeline';
import { DownloadPdfButton } from './DownloadPdfButton';

export function ResultsPanel() {
  const { state } = useAppState();

  // Estado de carregamento
  if (state.loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-center space-y-3">
          <div className="w-12 h-12 border-4 border-smartpass-200 border-t-smartpass-600 rounded-full animate-spin mx-auto" />
          <p className="text-sm text-slate-600">Calculando rota...</p>
        </div>
      </div>
    );
  }

  // Estado de erro
  if (state.error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-red-900">Não foi possível calcular a rota</h3>
            <p className="text-sm text-red-700 mt-1">{state.error}</p>
          </div>
        </div>
      </div>
    );
  }

  // Sem resultado ainda
  if (!state.result) {
    return null;
  }

  // Sem sucesso
  if (!state.result.sucesso) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-semibold text-red-900">Rota não encontrada</h3>
            <p className="text-sm text-red-700 mt-1">{state.result.erro || 'Tente revisar os endereços informados.'}</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 mb-1">Resultado da rota</h2>
        <p className="text-sm text-slate-600">
          {state.result.origem_label} → {state.result.destino_label}
        </p>
      </div>

      <SummaryCards />
      <RouteToggle />
      <CltBanner />
      <Timeline />
      <DownloadPdfButton />
    </div>
  );
}
