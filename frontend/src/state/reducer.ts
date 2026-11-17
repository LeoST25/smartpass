/**
 * Reducer para gerenciar estado global da aplicação.
 * Todo estado em memória React (LGPD stateless).
 */

import type {
  CandidatoGeocoding,
  HealthResponse,
  RouteCalculateResponse,
} from '../types/api';

export type ViewMode = 'map' | 'panel';
export type MapDirection = 'ida' | 'volta';

export interface AppState {
  // View (mobile)
  viewMode: ViewMode;

  // Search
  origem: CandidatoGeocoding | null;
  destino: CandidatoGeocoding | null;

  // Jornada
  horarioEntrada: string;
  horarioSaida: string;
  escala: string;
  diasUteis: number | null; // null = auto (pela escala/município)
  salarioBase: number | null;

  // Results
  loading: boolean;
  error: string | null;
  result: RouteCalculateResponse | null;
  selectedOptionIndex: number | null;
  mapDirection: MapDirection;
  coordsEdited: boolean;

  // Health
  health: HealthResponse | null;
}

export type AppAction =
  | { type: 'SET_VIEW_MODE'; payload: ViewMode }
  | { type: 'SET_ORIGEM'; payload: CandidatoGeocoding | null }
  | { type: 'SET_DESTINO'; payload: CandidatoGeocoding | null }
  | { type: 'MOVE_MARKER'; payload: { which: 'origem' | 'destino'; lat: number; lon: number } }
  | { type: 'SET_HORARIO_ENTRADA'; payload: string }
  | { type: 'SET_HORARIO_SAIDA'; payload: string }
  | { type: 'SET_ESCALA'; payload: string }
  | { type: 'SET_DIAS_UTEIS'; payload: number | null }
  | { type: 'SET_SALARIO_BASE'; payload: number | null }
  | { type: 'CALCULATE_START' }
  | { type: 'CALCULATE_SUCCESS'; payload: RouteCalculateResponse }
  | { type: 'CALCULATE_ERROR'; payload: string }
  | { type: 'SET_SELECTED_OPTION_INDEX'; payload: number | null }
  | { type: 'SET_MAP_DIRECTION'; payload: MapDirection }
  | { type: 'SET_HEALTH'; payload: HealthResponse }
  | { type: 'CLEAR_RESULT' };

export const initialState: AppState = {
  viewMode: 'panel',
  origem: null,
  destino: null,
  horarioEntrada: '08:00',
  horarioSaida: '18:00',
  escala: '5x2',
  diasUteis: null,
  salarioBase: null,
  loading: false,
  error: null,
  result: null,
  selectedOptionIndex: null,
  mapDirection: 'ida',
  coordsEdited: false,
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

    case 'MOVE_MARKER': {
      const { which, lat, lon } = action.payload;
      const key = which === 'origem' ? 'origem' : 'destino';
      const current = state[key];
      if (!current) return state;
      return {
        ...state,
        [key]: { ...current, lat, lon },
        coordsEdited: true,
      };
    }

    case 'SET_HORARIO_ENTRADA':
      return { ...state, horarioEntrada: action.payload };

    case 'SET_HORARIO_SAIDA':
      return { ...state, horarioSaida: action.payload };

    case 'SET_ESCALA':
      return { ...state, escala: action.payload };

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
        selectedOptionIndex: action.payload.opcoes.length > 0 ? 0 : null,
        mapDirection: 'ida',
        error: null,
      };

    case 'CALCULATE_ERROR':
      return { ...state, loading: false, error: action.payload };

    case 'SET_SELECTED_OPTION_INDEX':
      return { ...state, selectedOptionIndex: action.payload };

    case 'SET_MAP_DIRECTION':
      return { ...state, mapDirection: action.payload };

    case 'SET_HEALTH':
      return { ...state, health: action.payload };

    case 'CLEAR_RESULT':
      return {
        ...state,
        result: null,
        selectedOptionIndex: null,
        error: null,
      };

    default:
      return state;
  }
}
