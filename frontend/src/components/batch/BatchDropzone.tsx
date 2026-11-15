/**
 * Zona de drag-and-drop para upload de arquivo.
 */

import { useState, useRef } from 'react';
import { Upload, Loader2 } from 'lucide-react';

interface BatchDropzoneProps {
  onFileSelect: (file: File) => void;
  loading: boolean;
}

export function BatchDropzone({ onFileSelect, loading }: BatchDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleDragOver(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(true);
  }

  function handleDragLeave(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      const file = files[0];
      if (file.name.match(/\.(csv|xlsx|xls)$/i)) {
        onFileSelect(file);
      } else {
        alert('Formato inválido. Use CSV ou XLSX.');
      }
    }
  }

  function handleFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (files && files.length > 0) {
      onFileSelect(files[0]);
    }
  }

  return (
    <div
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      onClick={() => !loading && inputRef.current?.click()}
      className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
        isDragging
          ? 'border-smartpass-600 bg-smartpass-50'
          : 'border-slate-300 hover:border-slate-400 hover:bg-slate-50'
      } ${loading ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".csv,.xlsx,.xls"
        onChange={handleFileInput}
        className="hidden"
        disabled={loading}
      />

      {loading ? (
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-12 h-12 text-smartpass-600 animate-spin" />
          <p className="text-sm text-slate-600">Processando arquivo...</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3">
          <Upload className="w-12 h-12 text-slate-400" />
          <div>
            <p className="text-sm font-medium text-slate-900">
              Arraste o arquivo aqui ou clique para selecionar
            </p>
            <p className="text-xs text-slate-500 mt-1">CSV ou XLSX · Máx. 10 MB</p>
          </div>
        </div>
      )}
    </div>
  );
}
