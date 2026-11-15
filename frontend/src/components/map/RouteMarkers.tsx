/**
 * Marcadores de origem, destino e baldeações.
 */

import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import { useAppState } from '../../state/AppContext';

/**
 * Ícone customizado para marcadores.
 */
function createIcon(color: string, label: string): L.DivIcon {
  return L.divIcon({
    className: 'custom-marker',
    html: `
      <div style="
        width: 32px;
        height: 32px;
        background: ${color};
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: bold;
        font-size: 14px;
        border: 3px solid white;
        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
      ">
        ${label}
      </div>
    `,
    iconSize: [32, 32],
    iconAnchor: [16, 16],
  });
}

function createTransferIcon(): L.DivIcon {
  return L.divIcon({
    className: 'custom-marker',
    html: `
      <div style="
        width: 24px;
        height: 24px;
        background: #64748b;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-size: 12px;
        border: 2px solid white;
        box-shadow: 0 2px 6px rgba(0,0,0,0.2);
      ">
        ↻
      </div>
    `,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

export function RouteMarkers() {
  const { state } = useAppState();

  if (!state.result?.coords) return null;

  const [latO, lonO, latD, lonD] = state.result.coords;
  const legs = state.result.vt?.legs_transito || [];

  // Marcadores de baldeação (entre legs de trânsito)
  const transfers = legs.slice(0, -1).map((leg, idx) => ({
    position: [leg.to.lat, leg.to.lon] as [number, number],
    linha: leg.route?.shortName || leg.linha || 'Linha',
    key: `transfer-${idx}`,
  }));

  return (
    <>
      {/* Origem */}
      <Marker position={[latO, lonO]} icon={createIcon('#16a34a', 'A')}>
        <Tooltip sticky>
          <div className="text-xs">
            <div className="font-semibold">Origem</div>
            {state.result.origem_label && (
              <div className="text-slate-600">{state.result.origem_label}</div>
            )}
          </div>
        </Tooltip>
      </Marker>

      {/* Destino */}
      <Marker position={[latD, lonD]} icon={createIcon('#dc2626', 'B')}>
        <Tooltip sticky>
          <div className="text-xs">
            <div className="font-semibold">Destino</div>
            {state.result.destino_label && (
              <div className="text-slate-600">{state.result.destino_label}</div>
            )}
          </div>
        </Tooltip>
      </Marker>

      {/* Baldeações */}
      {transfers.map((transfer) => (
        <Marker key={transfer.key} position={transfer.position} icon={createTransferIcon()}>
          <Tooltip sticky>
            <div className="text-xs">
              <div className="font-semibold">Baldeação</div>
              <div>{transfer.linha}</div>
            </div>
          </Tooltip>
        </Marker>
      ))}
    </>
  );
}
