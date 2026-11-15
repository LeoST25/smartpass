/**
 * Modal para simulação em lote de colaboradores.
 */

import { useState } from 'react';
import { X, Upload, FileText, Download } from 'lucide-react';
import { api } from '../../lib/api';
import type { BatchSimulateResponse } from '../../types/api';
import { BatchDropzone } from './BatchDropzone';
import { BatchSummary } from './BatchSummary';

interface BatchModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function BatchModal({ isOpen, onClose }: BatchModalProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BatchSimulateResponse | null>(null);

  if (!isOpen) return null;

  async function handleFile(file: File) {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const data = await api.batchSimulate(file);
      if (data.sucesso) {
        setResult(data);
      } else {
        setError(data.erro || 'Erro ao processar o lote.');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao processar o arquivo.');
    } finally {
      setLoading(false);
    }
  }

  function handleClose() {
    setResult(null);
    setError(null);
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-slate-200">
          <div className="flex items-center gap-2">
            <Upload className="w-5 h-5 text-smartpass-600" />
            <h2 className="text-lg font-semibold text-slate-900">Simulação em lote</h2>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="p-1 hover:bg-slate-100 rounded-lg transition-colors"
            aria-label="Fechar"
          >
            <X className="w-5 h-5 text-slate-500" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 space-y-4">
          {!result ? (
            <>
              <BatchDropzone onFileSelect={handleFile} loading={loading} />

              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}

              <div className="bg-slate-50 rounded-lg p-4 border border-slate-200">
                <div className="flex items-start gap-3">
                  <FileText className="w-5 h-5 text-slate-500 flex-shrink-0 mt-0.5" />
                  <div className="text-sm text-slate-700">
                    <p className="font-medium mb-1">Formato do arquivo</p>
                    <p className="text-slate-600">
                      O arquivo CSV ou XLSX deve conter as colunas: <code className="bg-slate-200 px-1 rounded">origem</code>,{' '}
                      <code className="bg-slate-200 px-1 rounded">destino</code> e opcionalmente{' '}
                      <code className="bg-slate-200 px-1 rounded">nome</code>,{' '}
                      <code className="bg-slate-200 px-1 rounded">cpf</code>,{' '}
                      <code className="bg-slate-200 px-1 rounded">salario_base</code>.
                    </p>
                    <p className="text-xs text-slate-500 mt-2">
                      Limite: 500 registros · 10 MB
                    </p>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <BatchSummary result={result} />
          )}
        </div>

        {/* Footer */}
        {result && (
          <div className="flex items-center justify-end gap-3 p-6 border-t border-slate-200">
            <button
              type="button"
              onClick={handleClose}
              className="px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 rounded-lg transition-colors"
            >
              Fechar
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  const blob = await api.batchDownloadCsv(result.resultados, 'completo');
                  const url = window.URL.createObjectURL(blob);
                  const link = document.createElement('a');
                  link.href = url;
                  link.download = `smartpass_lote_${new Date().toISOString().split('T')[0]}.csv`;
                  document.body.appendChild(link);
                  link.click();
                  document.body.removeChild(link);
                  window.URL.revokeObjectURL(url);
                } catch (err) {
                  console.error('[CSV]', err);
                  alert('Erro ao gerar CSV.');
                }
              }}
              className="px-4 py-2 text-sm font-medium text-white bg-smartpass-600 hover:bg-smartpass-700 rounded-lg transition-colors flex items-center gap-2"
            >
              <Download className="w-4 h-4" />
              Baixar CSV
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
