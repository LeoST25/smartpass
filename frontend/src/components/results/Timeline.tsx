/**
 * Timeline passo a passo da rota com detalhes de cada trecho.
 */

import { MapPin, ArrowRight } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { formatCurrency, formatDistance } from '../../lib/format';
import type { Leg } from '../../types/api';

export function Timeline() {
  const { state } = useAppState();

  if (!state.result?.vt?.legs) return null;

  const legs = state.result.vt.legs;

  // Determina qual rota usar (se toggle ativo)
  const selectedLegs =
    state.selectedRoute === 'economica' && state.result.comparativo?.rota_mais_economica
      ? state.result.comparativo.rota_mais_economica.legs
      : state.selectedRoute === 'rapida' && state.result.comparativo?.rota_mais_rapida
        ? state.result.comparativo.rota_mais_rapida.legs
        : legs;

  // Detalhes tarifários (apenas para legs de trânsito)
  const detalhes =
    state.selectedRoute === 'economica' && state.result.comparativo?.rota_mais_economica
      ? state.result.comparativo.rota_mais_economica.detalhes
      : state.result.vt.detalhes || [];

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-medium text-slate-700">Detalhes do trajeto</h3>
      <div className="relative">
        {selectedLegs.map((leg: Leg, idx: number) => {
          const isWalk = leg.mode.toUpperCase() === 'WALK';
          const distanceKm = (leg.distance || 0) / 1000;

          // Busca detalhe correspondente (só para trânsito)
          const detalhe = !isWalk ? detalhes.find((d) => d.linha === leg.linha || d.codigo_linha === leg.codigo_linha) : null;

          return (
            <div key={`timeline-${idx}`} className="relative pl-8 pb-4 last:pb-0">
              {/* Linha vertical */}
              {idx < selectedLegs.length - 1 && (
                <div className="absolute left-3 top-3 bottom-0 w-0.5 bg-slate-200" />
              )}

              {/* Ícone */}
              <div
                className={`absolute left-0 top-1 w-6 h-6 rounded-full flex items-center justify-center ${
                  isWalk ? 'bg-slate-200' : 'bg-smartpass-600'
                }`}
              >
                {isWalk ? (
                  <ArrowRight className="w-3 h-3 text-slate-600" />
                ) : (
                  <MapPin className="w-3 h-3 text-white" />
                )}
              </div>

              {/* Conteúdo */}
              <div className="bg-slate-50 rounded-lg p-3 border border-slate-200">
                {isWalk ? (
                  <div className="text-sm text-slate-700">
                    <span className="font-medium">Caminhada</span>{' '}
                    <span className="text-slate-500">({formatDistance(distanceKm)})</span>
                  </div>
                ) : (
                  <div className="space-y-1">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1">
                        <div className="text-sm font-medium text-slate-900">
                          {leg.route?.shortName || leg.linha || 'Linha'}
                        </div>
                        {leg.route?.longName && (
                          <div className="text-xs text-slate-600 mt-0.5">{leg.route.longName}</div>
                        )}
                        {leg.agency?.name && (
                          <div className="text-xs text-slate-500 mt-0.5">{leg.agency.name}</div>
                        )}
                      </div>
                      {detalhe && (
                        <div className="text-right">
                          <div className="text-sm font-semibold text-smartpass-600">
                            {formatCurrency(detalhe.valor_unitario)}
                          </div>
                          {!detalhe.tarifa_confirmada && (
                            <div className="text-xs text-amber-600">Estimativa</div>
                          )}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-3 text-xs text-slate-600 pt-1 border-t border-slate-200">
                      <span>
                        De: <span className="text-slate-900">{leg.from.name}</span>
                      </span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-slate-600">
                      <span>
                        Para: <span className="text-slate-900">{leg.to.name}</span>
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
