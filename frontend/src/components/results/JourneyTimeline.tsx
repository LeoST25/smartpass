/**
 * Timeline separada de Ida e Volta com o valor oficial de cada condução.
 */

import { MapPin, ArrowRight, Sun, Moon } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { formatCurrency } from '../../lib/format';
import type { SentidoRota } from '../../types/api';

function SentidoTimeline({ sentido, titulo, icon: Icon }: { sentido: SentidoRota; titulo: string; icon: typeof Sun }) {
  const transito = sentido.legs_transito || [];
  const detalhes = sentido.detalhes || [];

  return (
    <div>
      <div className="flex items-center gap-2 mb-2">
        <Icon className="w-4 h-4 text-slate-500" />
        <h4 className="text-sm font-semibold text-slate-800">{titulo}</h4>
        {sentido.horario_partida && sentido.horario_chegada && (
          <span className="text-xs text-slate-500">
            {sentido.horario_partida} → {sentido.horario_chegada}
          </span>
        )}
      </div>

      {transito.length === 0 ? (
        <p className="text-xs text-slate-500">Sem condução neste sentido.</p>
      ) : (
        <ul className="space-y-2">
          {transito.map((leg, idx) => {
            const detalhe = detalhes[idx];
            const linha = leg.route?.shortName || leg.linha || leg.codigo_linha || 'Linha';
            const operadora = leg.agency?.name || leg.route?.agency?.name;

            return (
              <li
                key={`${titulo}-${idx}`}
                className="flex items-center gap-2 bg-slate-50 rounded-lg px-3 py-2 border border-slate-200"
              >
                <MapPin className="w-4 h-4 text-smartpass-600 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium text-slate-900 truncate">{linha}</div>
                  {operadora && <div className="text-xs text-slate-500 truncate">{operadora}</div>}
                  {leg.horario_inicio && (
                    <div className="text-xs text-slate-400">Partida {leg.horario_inicio}</div>
                  )}
                </div>
                <div className="text-right">
                  <div className="text-sm font-semibold text-smartpass-700">
                    {detalhe ? formatCurrency(detalhe.valor_unitario) : '—'}
                  </div>
                  {detalhe && !detalhe.tarifa_confirmada && (
                    <div className="text-xs text-amber-600">Estimativa</div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <div className="mt-2 flex items-center justify-between text-xs text-slate-600">
        <span>
          {sentido.duracao_min}min · {sentido.baldeacoes} baldeação(ões)
        </span>
        <span className="font-medium text-slate-700">
          {formatCurrency(sentido.custo_trecho)} / sentido
        </span>
      </div>
    </div>
  );
}

export function JourneyTimeline() {
  const { state } = useAppState();

  const opcao = state.result?.opcoes?.[state.selectedOptionIndex ?? 0];
  if (!opcao) return null;

  return (
    <div className="space-y-4 border-t border-slate-200 pt-4">
      <div className="flex items-center gap-2">
        <ArrowRight className="w-4 h-4 text-smartpass-600" />
        <h3 className="text-sm font-semibold text-slate-700">Detalhes da jornada</h3>
      </div>

      <SentidoTimeline sentido={opcao.ida} titulo="Ida" icon={Sun} />
      <SentidoTimeline sentido={opcao.volta} titulo="Volta" icon={Moon} />
    </div>
  );
}
