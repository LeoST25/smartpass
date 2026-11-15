/**
 * Botão para baixar relatório PDF da rota.
 */

import { useState } from 'react';
import { Download, Loader2 } from 'lucide-react';
import { useAppState } from '../../state/AppContext';
import { api } from '../../lib/api';
import type { Modalidade } from '../../types/api';

export function DownloadPdfButton() {
  const { state } = useAppState();
  const [loading, setLoading] = useState(false);

  if (!state.result || !state.result.vt) return null;

  async function handleDownload() {
    if (!state.result?.vt) return;

    setLoading(true);
    try {
      const blob = await api.generatePdf({
        dados_candidato: {
          nome: 'Colaborador',
          cargo: 'Cargo',
          centro_custo: 'Centro de Custo',
        },
        tipo_beneficio: state.modalidade as Modalidade,
        dados_calculo: state.result.vt,
        coords: state.result.coords || undefined,
      });

      // Cria URL temporário e dispara download
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `SmartPass_${state.modalidade.replace(/\s+/g, '_')}_${new Date().toISOString().split('T')[0]}.pdf`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      // Libera memória
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
      className="w-full bg-smartpass-600 hover:bg-smartpass-700 disabled:bg-slate-300 text-white font-medium py-2.5 px-4 rounded-lg transition-colors flex items-center justify-center gap-2"
    >
      {loading ? (
        <>
          <Loader2 className="w-4 h-4 animate-spin" />
          <span>Gerando PDF...</span>
        </>
      ) : (
        <>
          <Download className="w-4 h-4" />
          <span>Baixar relatório PDF</span>
        </>
      )}
    </button>
  );
}
