/**
 * Marcadores de origem, destino e baldeações — origem/destino arrastáveis.
 */

import { Marker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import { useAppState } from '../../state/AppContext';

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
  const { state, dispatch } = useAppState();

  const coords = state.result?.coords;
  const origemPos: [number, number] = [
    state.origem?.lat ?? coords?.[0] ?? -23.5505,
    state.origem?.lon ?? coords?.[1] ?? -46.6333,
  ];
  const destinoPos: [number, number] = [
    state.destino?.lat ?? coords?.[2] ?? -23.5505,
    state.destino?.lon ?? coords?.[3] ?? -46.6333,
  ];

  const opcao = state.result?.opcoes?.[state.selectedOptionIndex ?? 0];
  const sentido = state.mapDirection === 'ida' ? opcao?.ida : opcao?.volta;
  const legs = sentido?.legs_transito || [];

  const transfers = legs.slice(0, -1).map((leg, idx) => ({
    position: [leg.to.lat, leg.to.lon] as [number, number],
    linha: leg.route?.shortName || leg.linha || 'Linha',
    key: `transfer-${idx}`,
  }));

  function onMove(which: 'origem' | 'destino', latlng: L.LatLng) {
    dispatch({
      type: 'MOVE_MARKER',
      payload: { which, lat: latlng.lat, lon: latlng.lng },
    });
  }

  return (
    <>
      <Marker
        position={origemPos}
        icon={createIcon('#16a34a', 'A')}
        draggable
        eventHandlers={{
          dragend: (e) => onMove('origem', e.target.getLatLng()),
        }}
      >
        <Tooltip sticky>
          <div className="text-xs">
            <div className="font-semibold">Origem</div>
            {state.origem?.label_exibicao && (
              <div className="text-slate-600">{state.origem.label_exibicao}</div>
            )}
          </div>
        </Tooltip>
      </Marker>

      <Marker
        position={destinoPos}
        icon={createIcon('#dc2626', 'B')}
        draggable
        eventHandlers={{
          dragend: (e) => onMove('destino', e.target.getLatLng()),
        }}
      >
        <Tooltip sticky>
          <div className="text-xs">
            <div className="font-semibold">Destino</div>
            {state.destino?.label_exibicao && (
              <div className="text-slate-600">{state.destino.label_exibicao}</div>
            )}
          </div>
        </Tooltip>
      </Marker>

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
