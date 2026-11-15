import { describe, it, expect } from 'vitest';
import { calculateBounds, getLegColor, getLegDashArray, collectPointsFromLegs } from '../lib/geo';
import type { Leg } from '../types/api';

describe('calculateBounds', () => {
  it('calcula bounds de um array de pontos', () => {
    const points: [number, number][] = [
      [-23.5, -46.6],
      [-23.6, -46.5],
      [-23.4, -46.7],
    ];
    const bounds = calculateBounds(points);
    expect(bounds).toEqual({
      minLat: -23.6,
      maxLat: -23.4,
      minLon: -46.7,
      maxLon: -46.5,
    });
  });

  it('retorna null para array vazio', () => {
    expect(calculateBounds([])).toBeNull();
  });
});

describe('getLegColor', () => {
  it('retorna cinza para caminhada', () => {
    const leg = { mode: 'WALK', distance: 0, duration: 0, from: { name: '', lat: 0, lon: 0 }, to: { name: '', lat: 0, lon: 0 }, pontos: [] } as Leg;
    expect(getLegColor(leg)).toBe('#94A3B8');
  });

  it('retorna azul para ônibus urbano', () => {
    const leg = { mode: 'BUS', distance: 0, duration: 0, from: { name: '', lat: 0, lon: 0 }, to: { name: '', lat: 0, lon: 0 }, pontos: [], agency: { name: 'SPTrans' } } as Leg;
    expect(getLegColor(leg)).toBe('#2563EB');
  });

  it('retorna laranja para ônibus EMTU', () => {
    const leg = { mode: 'BUS', distance: 0, duration: 0, from: { name: '', lat: 0, lon: 0 }, to: { name: '', lat: 0, lon: 0 }, pontos: [], agency: { name: 'EMTU' } } as Leg;
    expect(getLegColor(leg)).toBe('#EA580C');
  });

  it('retorna verde para trilho', () => {
    const leg = { mode: 'SUBWAY', distance: 0, duration: 0, from: { name: '', lat: 0, lon: 0 }, to: { name: '', lat: 0, lon: 0 }, pontos: [] } as Leg;
    expect(getLegColor(leg)).toBe('#16A34A');
  });
});

describe('getLegDashArray', () => {
  it('retorna dash para caminhada', () => {
    const leg = { mode: 'WALK' } as Leg;
    expect(getLegDashArray(leg)).toBe('10, 10');
  });

  it('retorna null para outros modais', () => {
    const leg = { mode: 'BUS' } as Leg;
    expect(getLegDashArray(leg)).toBeNull();
  });
});

describe('collectPointsFromLegs', () => {
  it('coleta pontos de múltiplas legs', () => {
    const legs = [
      { pontos: [[-23.5, -46.6], [-23.55, -46.65]] },
      { pontos: [[-23.6, -46.7]] },
    ] as unknown as Leg[];
    const points = collectPointsFromLegs(legs);
    expect(points).toHaveLength(3);
  });

  it('ignora legs sem pontos', () => {
    const legs = [
      { pontos: [] },
      { pontos: [[-23.5, -46.6]] },
    ] as unknown as Leg[];
    const points = collectPointsFromLegs(legs);
    expect(points).toHaveLength(1);
  });
});
