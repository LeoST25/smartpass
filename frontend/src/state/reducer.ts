/**
 * Reducer para gerenciar estado global da aplicação.
 * Todo estado em memória React (LGPD stateless).
 */

import type {
  CandidatoGeocoding,
  HealthResponse,
  Modalidade,
  RouteCalculateResponse,
} from '../types/api';

export type ViewMode = 'map' | 'panel';

export interface AppState {
  // View (mobile)
  viewMode: ViewMode;

  // Search
  origem: CandidatoGeocoding | null;
  destino: CandidatoGeocoding | null;
  modalidade: Modalidade;
  diasUteis: number;
  salarioBase: number | null;

  // Results
  loading: boolean;
  error: string | null;
  result: RouteCalculateResponse | null;
  selectedRoute: 'rapida' | 'economica' | null;

  // Health
  health: HealthResponse | null;
}

export type AppAction =
  | { type: 'SET_VIEW_MODE'; payload: ViewMode }
  | { type: 'SET_ORIGEM'; payload: CandidatoGeocoding | null }
  | { type: 'SET_DESTINO'; payload: CandidatoGeocoding | null }
  | { type: 'SET_MODALIDADE'; payload: Modalidade }
  | { type: 'SET_DIAS_UTEIS'; payload: number }
  | { type: 'SET_SALARIO_BASE'; payload: number | null }
  | { type: 'CALCULATE_START' }
  | { type: 'CALCULATE_SUCCESS'; payload: RouteCalculateResponse }
  | { type: 'CALCULATE_ERROR'; payload: string }
  | { type: 'SET_SELECTED_ROUTE'; payload: 'rapida' | 'economica' }
  | { type: 'SET_HEALTH'; payload: HealthResponse }
  | { type: 'CLEAR_RESULT' };

export const initialState: AppState = {
  viewMode: 'panel',
  origem: null,
  destino: null,
  modalidade: 'Vale-Transporte',
  diasUteis: 22,
  salarioBase: null,
  loading: false,
  error: null,
  result: null,
  selectedRoute: null,
  health: null,
};

export function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_VIEW_MODE':
      return { ...state, viewMode: action.payload };

    case 'SET_ORIGEM':
      return { ...state, origem: action.payload };

    case 'SET_DESTINO':
      return { ...state, destino: action.payload };

    case 'SET_MODALIDADE':
      return { ...state, modalidade: action.payload };

    case 'SET_DIAS_UTEIS':
      return { ...state, diasUteis: action.payload };

    case 'SET_SALARIO_BASE':
      return { ...state, salarioBase: action.payload };

    case 'CALCULATE_START':
      return { ...state, loading: true, error: null, result: null };

    case 'CALCULATE_SUCCESS':
      return {
        ...state,
        loading: false,
        result: action.payload,
        selectedRoute: null,
        error: null,
      };

    case 'CALCULATE_ERROR':
      return { ...state, loading: false, error: action.payload };

    case 'SET_SELECTED_ROUTE':
      return { ...state, selectedRoute: action.payload };

    case 'SET_HEALTH':
      return { ...state, health: action.payload };

    case 'CLEAR_RESULT':
      return {
        ...state,
        result: null,
        selectedRoute: null,
        error: null,
      };

    default:
      return state;
  }
}
