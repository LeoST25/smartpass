/**
 * Context + Provider para estado global da aplicação.
 */

import { createContext, useContext, useReducer, type ReactNode } from 'react';
import { appReducer, initialState, type AppState, type AppAction } from './reducer';

interface AppContextValue {
  state: AppState;
  dispatch: React.Dispatch<AppAction>;
}

const AppContext = createContext<AppContextValue | null>(null);

interface AppProviderProps {
  children: ReactNode;
}

export function AppProvider({ children }: AppProviderProps) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  return <AppContext.Provider value={{ state, dispatch }}>{children}</AppContext.Provider>;
}

/**
 * Hook para acessar o contexto da aplicação.
 */
export function useAppState(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) {
    throw new Error('useAppState deve ser usado dentro de AppProvider');
  }
  return context;
}
