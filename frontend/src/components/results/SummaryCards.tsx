/**
 * Cards compactos com resumo da rota (tempo, distância, custos).
 */

import { Clock, Route, DollarSign, Calendar } from 'lucide-react';
import { formatDuration, formatDistance, formatCurrency } from '../../lib/format';
import { useAppState } from '../../state/AppContext';

export function SummaryCards() {
  const { state } = useAppState();

  if (!state.result?.vt) return null;

  const vt = state.result.vt;
  const duration = vt.duracao_min;
  const distance = vt.distancia_km;
  const dailyCost = vt.custo_diario;
  const monthlyCost = vt.custo_mensal;

  const cards = [
    {
      icon: Clock,
      label: 'Tempo total',
      value: formatDuration(duration),
      color: 'text-blue-600',
    },
    {
      icon: Route,
      label: 'Distância',
      value: formatDistance(distance),
      color: 'text-green-600',
    },
    {
      icon: DollarSign,
      label: 'Custo diário',
      value: formatCurrency(dailyCost),
      color: 'text-amber-600',
    },
    {
      icon: Calendar,
      label: 'Custo mensal',
      value: formatCurrency(monthlyCost),
      color: 'text-smartpass-600',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-2">
      {cards.map((card) => (
        <div
          key={card.label}
          className="bg-slate-50 rounded-lg p-3 border border-slate-200"
        >
          <div className="flex items-center gap-1.5 mb-1">
            <card.icon className={`w-4 h-4 ${card.color}`} />
            <span className="text-xs text-slate-600">{card.label}</span>
          </div>
          <div className="text-lg font-semibold text-slate-900">{card.value}</div>
        </div>
      ))}
    </div>
  );
}
