/**
 * Botão único para gerar o Comprovante PDF (Assinatura) da jornada selecionada.
 */

import { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { api } from '../../lib/api';

export function DownloadPdfButton() {
  const { state } = useAppState();
  const [loading, setLoading] = useState(false);

  const result = state.result;
  const opcao = result?.opcoes?.[state.selectedOptionIndex ?? 0];
  if (!result || !opcao) return null;

  async function handleDownload() {
    if (!result || !opcao) return;
    setLoading(true);
    try {
      const blob = await api.generatePdf({
        dados_candidato: {
          nome: 'Colaborador',
          cargo: '',
          centro_custo: '',
        },
        tipo_beneficio: 'Vale-Transporte',
        dados_calculo: {
          origem: result.origem_label,
          destino: result.destino_label,
          dias_uteis: result.dias_uteis,
          horario_entrada: result.horario_entrada,
          horario_saida: result.horario_saida,
          custo_diario: opcao.custo_diario,
          custo_mensal: opcao.custo_mensal,
          salario_base: state.salarioBase ?? undefined,
          viabilidade_clt: result.viabilidade_clt,
          memoria_calculo: result.memoria_calculo,
          justificativa: result.justificativa,
        },
        coords: result.coords ?? undefined,
        opcao_selecionada: opcao,
      });

      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `Comprovante_SmartPass_Vale-Transporte_${new Date().toISOString().split('T')[0]}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('[PDF]', error);
      alert('Não foi possível gerar o PDF. Tente novamente.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <button
      type="button"
      onClick={handleDownload}
      disabled={loading}
      className="w-full bg-smartpass-600 hover:bg-smartpass-700 disabled:bg-slate-300 text-white font-medium py-3 px-4 rounded-lg transition-colors flex items-center justify-center gap-2"
    >
      {loading ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>Gerando comprovante...</span>
        </>
      ) : (
        <>
          <Download className="w-4 h-4" />
          <span>Gerar Comprovante PDF (Assinatura)</span>
        </>
      )}
    </button>
  );
}
