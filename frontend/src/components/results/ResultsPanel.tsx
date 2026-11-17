/**
 * Painel de resultados do roteirizador individual:
 * cards de opções, timeline Ida/Volta, banner CLT e download do comprovante.
 */

import { AlertCircle } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { OptionCards } from './OptionCards';
import { JourneyTimeline } from './JourneyTimeline';
import { CltBanner } from './CltBanner';
import { DownloadPdfButton } from './DownloadPdfButton';

export function ResultsPanel() {
  const { state } = useAppState();

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

  if (!state.result) return null;

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

      <OptionCards />
      <CltBanner />
      <JourneyTimeline />
      <DownloadPdfButton />
    </div>
  );
}
