/**
 * Helpers para o mapa (fitBounds, cores por modal, classificador visual).
 */

import type { Leg } from '../types/api';

/**
 * Calcula os bounds (lat/lon) a partir de um array de pontos [lat, lon][].
 */
export function calculateBounds(points: [number, number][]): {
  minLat: number;
  maxLat: number;
  minLon: number;
  maxLon: number;
} | null {
  if (points.length === 0) return null;

  let minLat = Infinity;
  let maxLat = -Infinity;
  let minLon = Infinity;
  let maxLon = -Infinity;

  for (const [lat, lon] of points) {
    if (lat < minLat) minLat = lat;
    if (lat > maxLat) maxLat = lat;
    if (lon < minLon) minLon = lon;
    if (lon > maxLon) maxLon = lon;
  }

  return { minLat, maxLat, minLon, maxLon };
}

/**
 * Cor da polyline baseada no mode da leg (classificador visual).
 * Lógica similar a fare_engine._classificar_leg, mas apenas para cores.
 */
export function getLegColor(leg: Leg): string {
  const mode = leg.mode.toUpperCase();
  const agency = (leg.agency?.name || '').toUpperCase();

  // Caminhada: cinza
  if (mode === 'WALK') {
    return '#94A3B8'; // slate-400
  }

  // EMTU/intermunicipal: laranja
  if (mode === 'BUS' && (agency.includes('EMTU') || agency.includes('INTERMUNICIPAL'))) {
    return '#EA580C'; // orange-600
  }

  // Trilho (metrô/trem): verde
  if (['RAIL', 'SUBWAY', 'TRAM'].includes(mode)) {
    return '#16A34A'; // green-600
  }

  // Ônibus urbano: azul
  return '#2563EB'; // blue-600
}

/**
 * Estilo da polyline (dashArray para caminhada).
 */
export function getLegDashArray(leg: Leg): string | null {
  if (leg.mode.toUpperCase() === 'WALK') {
    return '10, 10';
  }
  return null;
}

/**
 * Coleta todos os pontos de um array de legs para fitBounds.
 */
export function collectPointsFromLegs(legs: Leg[]): [number, number][] {
  const points: [number, number][] = [];
  for (const leg of legs) {
    if (leg.pontos && leg.pontos.length > 0) {
      points.push(...leg.pontos);
    }
  }
  return points;
}
