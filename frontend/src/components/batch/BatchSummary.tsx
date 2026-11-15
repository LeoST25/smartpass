/**
 * Resumo da simulação em lote com semáforos e totais.
 */

import { CheckCircle2, AlertCircle, XCircle } from 'lucide-react';
import type { BatchSimulateResponse } from '../../types/api';

interface BatchSummaryProps {
  result: BatchSimulateResponse;
}

export function BatchSummary({ result }: BatchSummaryProps) {
  const { total, totals, resultados } = result;
  const { n_alta, n_media, n_baixa } = totals;

  const successCount = resultados.filter((r) => !r.erro).length;
  const errorCount = resultados.filter((r) => r.erro).length;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-slate-900 mb-2">Resultado do processamento</h3>
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-green-50 border border-green-200 rounded-lg p-3">
            <div className="flex items-center gap-2 mb-1">
              <CheckCircle2 className="w-4 h-4 text-green-600" />
              <span className="text-sm font-medium text-green-900">Processados</span>
            </div>
            <div className="text-2xl font-bold text-green-700">{successCount}</div>
          </div>
          {errorCount > 0 && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1">
                <XCircle className="w-4 h-4 text-red-600" />
                <span className="text-sm font-medium text-red-900">Com erro</span>
              </div>
              <div className="text-2xl font-bold text-red-700">{errorCount}</div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-slate-50 border border-slate-200 rounded-lg p-4">
        <h4 className="text-sm font-medium text-slate-900 mb-3">Precisão geográfica</h4>
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🟢</span>
              <span className="text-sm text-slate-700">Exato</span>
            </div>
            <span className="text-sm font-semibold text-slate-900">{n_alta}</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🟡</span>
              <span className="text-sm text-slate-700">Aproximado</span>
            </div>
            <span className="text-sm font-semibold text-slate-900">{n_media}</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-lg">🔴</span>
              <span className="text-sm text-slate-700">Revisar</span>
            </div>
            <span className="text-sm font-semibold text-slate-900">{n_baixa}</span>
          </div>
        </div>
        <div className="mt-3 pt-3 border-t border-slate-200">
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700">Total</span>
            <span className="text-sm font-bold text-slate-900">{total}</span>
          </div>
        </div>
      </div>

      {errorCount > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
            <div className="text-sm text-amber-800">
              <p className="font-medium mb-1">Atenção</p>
              <p>{errorCount} registro(s) não puderam ser processados. Verifique os endereços informados e tente novamente.</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
