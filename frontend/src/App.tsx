/**
 * Componente principal da aplicação SmartPass — Roteirizador Individual de VT.
 */

import { AppProvider, useAppState } from './state/AppContext';
import { AppHeader } from './components/layout/AppHeader';
import { SidePanel } from './components/layout/SidePanel';
import { MobileViewToggle } from './components/layout/MobileViewToggle';
import { SearchForm } from './components/search/SearchForm';
import { ResultsPanel } from './components/results/ResultsPanel';
import { RouteMap } from './components/map/RouteMap';
import { Legend } from './components/map/Legend';
import { DirectionToggle } from './components/map/DirectionToggle';

function AppContent() {
  const { state } = useAppState();

  return (
    <div className="flex flex-col h-screen bg-slate-100">
      <AppHeader />

      <div className="flex-1 relative overflow-hidden">
        {/* Mapa (sempre visível no desktop, condicional no mobile) */}
        <div
          className={`absolute inset-0 ${
            state.viewMode === 'map' ? 'block' : 'hidden lg:block'
          }`}
        >
          <RouteMap />
          <DirectionToggle />
          <Legend />
        </div>

        {/* Painel lateral — fixo (z-[1000]), não bloqueia o mapa no desktop */}
        <div className={state.viewMode === 'panel' ? 'block' : 'hidden lg:block'}>
          <SidePanel>
            <SearchForm />
            <div className="border-t border-slate-200 pt-4">
              <ResultsPanel />
            </div>
          </SidePanel>
        </div>
      </div>

      <MobileViewToggle />
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
