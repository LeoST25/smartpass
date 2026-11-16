/**
 * Mapa principal com polilinhas e marcadores da rota.
 */

import { useEffect } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { useAppState } from '../../state/AppContext';
import { collectPointsFromLegs } from '../../lib/geo';
import { RoutePolylines } from './RoutePolylines';
import { RouteMarkers } from './RouteMarkers';

/**
 * Componente para ajustar o mapa aos bounds da rota.
 */
function FitBounds() {
  const map = useMap();
  const { state } = useAppState();

  useEffect(() => {
    if (!state.result?.coords) return;

    const [latO, lonO, latD, lonD] = state.result.coords;
    const pontos: [number, number][] = [[latO, lonO], [latD, lonD]];

    // Adiciona pontos das legs se disponíveis
    if (state.result.vt?.legs) {
      pontos.push(...collectPointsFromLegs(state.result.vt.legs));
    }

    if (pontos.length > 0) {
      const lats = pontos.map((p) => p[0]);
      const lons = pontos.map((p) => p[1]);
      const bounds: L.LatLngBoundsExpression = [
        [Math.min(...lats), Math.min(...lons)],
        [Math.max(...lats), Math.max(...lons)],
      ];
      map.fitBounds(bounds, { padding: [50, 50] });
    }
  }, [map, state.result]);

  return null;
}

export function RouteMap() {
  const { state } = useAppState();

  // Centro padrão: São Paulo
  const center: [number, number] = state.result?.coords
    ? [state.result.coords[0], state.result.coords[1]]
    : [-23.5505, -46.6333];

  const zoom = state.result ? 13 : 11;

  return (
    <MapContainer
      center={center}
      zoom={zoom}
      className="w-full h-full"
      zoomControl={true}
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        maxZoom={19}
      />
      <FitBounds />
      <RoutePolylines />
      <RouteMarkers />
    </MapContainer>
  );
}
