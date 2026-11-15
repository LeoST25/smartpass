/**
 * Polilinhas da rota com cores por modal.
 */

import { Polyline, Tooltip } from 'react-leaflet';
import { useAppState } from '../../state/AppContext';
import { getLegColor, getLegDashArray } from '../../lib/geo';
import type { Leg } from '../../types/api';

export function RoutePolylines() {
  const { state } = useAppState();

  if (!state.result?.vt?.legs) return null;

  const legs = state.result.vt.legs;

  return (
    <>
      {legs.map((leg: Leg, idx: number) => {
        if (!leg.pontos || leg.pontos.length === 0) return null;

        const color = getLegColor(leg);
        const dashArray = getLegDashArray(leg);

        return (
          <Polyline
            key={`leg-${idx}`}
            positions={leg.pontos}
            pathOptions={{
              color,
              weight: 4,
              opacity: 0.8,
              dashArray: dashArray || undefined,
            }}
          >
            {leg.mode !== 'WALK' && (
              <Tooltip sticky>
                <div className="text-xs">
                  <div className="font-semibold">{leg.route?.shortName || leg.linha || 'Linha'}</div>
                  {leg.agency?.name && <div>{leg.agency.name}</div>}
                </div>
              </Tooltip>
            )}
          </Polyline>
        );
      })}
    </>
  );
}
