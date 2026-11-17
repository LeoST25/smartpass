/**
 * Mapa principal com polilinhas e marcadores da rota (ida/volta alternável).
 */

import { useEffect } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import { useAppState } from '../../state/AppContext';
import { collectPointsFromLegs } from '../../lib/geo';
import { RoutePolylines } from './RoutePolylines';
import { RouteMarkers } from './RouteMarkers';

function FitBounds() {
  const map = useMap();
  const { state } = useAppState();

  useEffect(() => {
    const coords = state.result?.coords;
    if (!coords) return;

    const [latO, lonO, latD, lonD] = coords;
    const pontos: [number, number][] = [
      [state.origem?.lat ?? latO, state.origem?.lon ?? lonO],
      [state.destino?.lat ?? latD, state.destino?.lon ?? lonD],
    ];

    const opcao = state.result?.opcoes?.[state.selectedOptionIndex ?? 0];
    const sentido = state.mapDirection === 'ida' ? opcao?.ida : opcao?.volta;
    if (sentido?.legs) {
      pontos.push(...collectPointsFromLegs(sentido.legs));
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
  }, [map, state.result, state.origem, state.destino, state.selectedOptionIndex, state.mapDirection]);

  return null;
}

export function RouteMap() {
  const { state } = useAppState();

  const center: [number, number] = state.result?.coords
    ? [state.result.coords[0], state.result.coords[1]]
    : [-23.5505, -46.6333];

  const zoom = state.result ? 13 : 11;

  return (
    <MapContainer center={center} zoom={zoom} className="w-full h-full" zoomControl={true}>
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
