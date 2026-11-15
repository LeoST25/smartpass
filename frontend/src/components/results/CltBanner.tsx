/**
 * Banner de viabilidade CLT (6%) — exibido somente quando salario_base > 0.
 */

import { AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { formatCurrency } from '../../lib/format';

export function CltBanner() {
  const { state } = useAppState();

  // Só exibe se salario_base informado e viabilidade calculada
  if (!state.salarioBase || !state.result?.viabilidade_clt) {
    return null;
  }

  const clt = state.result.viabilidade_clt;

  if (!clt.sucesso) {
    return null;
  }

  const isVantajoso = clt.vt_vantajoso;

  return (
    <div
      className={`rounded-lg p-4 border-2 ${
        isVantajoso
          ? 'bg-green-50 border-green-200'
          : 'bg-amber-50 border-amber-200'
      }`}
    >
      <div className="flex items-start gap-3">
        {isVantajoso ? (
          <CheckCircle2 className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
        ) : (
          <AlertCircle className="w-5 h-5 text-amber-600 flex-shrink-0 mt-0.5" />
        )}
        <div className="flex-1 space-y-2">
          <div>
            <h3 className={`text-sm font-semibold ${isVantajoso ? 'text-green-900' : 'text-amber-900'}`}>
              Viabilidade do benefício (Lei 7.418/85)
            </h3>
            <p className={`text-xs mt-0.5 ${isVantajoso ? 'text-green-700' : 'text-amber-700'}`}>
              {clt.recomendacao}
            </p>
          </div>

          <div className="grid grid-cols-3 gap-2 text-xs">
            <div>
              <div className="text-slate-600">Teto 6%</div>
              <div className="font-semibold text-slate-900">
                {formatCurrency(clt.teto_desconto_6_pct)}
              </div>
            </div>
            <div>
              <div className="text-slate-600">Desconto colaborador</div>
              <div className="font-semibold text-slate-900">
                {formatCurrency(clt.desconto_colaborador)}
              </div>
            </div>
            <div>
              <div className="text-slate-600">Subsídio empresa</div>
              <div className={`font-semibold ${isVantajoso ? 'text-green-700' : 'text-amber-700'}`}>
                {formatCurrency(clt.custeio_empresa)}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
