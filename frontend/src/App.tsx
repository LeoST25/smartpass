/**
 * Componente principal da aplicação SmartPass.
 */

import { useState } from 'react';
import { FileUp } from 'lucide-react';
import { AppProvider, useAppState } from './state/AppContext';
import { AppHeader } from './components/layout/AppHeader';
import { SidePanel } from './components/layout/SidePanel';
import { MobileViewToggle } from './components/layout/MobileViewToggle';
import { SearchForm } from './components/search/SearchForm';
import { ResultsPanel } from './components/results/ResultsPanel';
import { RouteMap } from './components/map/RouteMap';
import { Legend } from './components/map/Legend';
import { BatchModal } from './components/batch/BatchModal';

function AppContent() {
  const { state } = useAppState();
  const [batchModalOpen, setBatchModalOpen] = useState(false);

  return (
    <div className="flex flex-col h-screen bg-slate-100">
      <AppHeader />

      {/* Botão Simulação em Lote */}
      <button
        type="button"
        onClick={() => setBatchModalOpen(true)}
        className="fixed top-20 right-4 z-20 bg-white hover:bg-slate-50 border border-slate-200 rounded-lg shadow-lg px-3 py-2 flex items-center gap-2 transition-colors"
        aria-label="Abrir simulação em lote"
      >
        <FileUp className="w-4 h-4 text-smartpass-600" />
        <span className="text-sm font-medium text-slate-700 hidden sm:inline">Simulação em lote</span>
      </button>

      <div className="flex-1 relative overflow-hidden">
        {/* Mapa (sempre visível no desktop, condicional no mobile) */}
        <div
          className={`absolute inset-0 ${
            state.viewMode === 'map' ? 'block' : 'hidden lg:block'
          }`}
        >
          <RouteMap />
          <Legend />
        </div>

        {/* Painel lateral (sempre visível no desktop, condicional no mobile) */}
        <div
          className={`absolute inset-0 ${
            state.viewMode === 'panel' ? 'block' : 'hidden lg:block'
          }`}
        >
          <SidePanel>
            <SearchForm />
            <div className="border-t border-slate-200 pt-4">
              <ResultsPanel />
            </div>
          </SidePanel>
        </div>
      </div>

      <MobileViewToggle />
      <BatchModal isOpen={batchModalOpen} onClose={() => setBatchModalOpen(false)} />
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <AppContent />
    </AppProvider>
  );
}
