import { describe, it, expect } from 'vitest';
import { formatCurrency, formatDuration, formatDistance, formatNumber } from '../lib/format';

describe('formatCurrency', () => {
  it('formata valores positivos em BRL', () => {
    expect(formatCurrency(1234.56)).toContain('1.234,56');
    expect(formatCurrency(0)).toContain('0,00');
    expect(formatCurrency(100)).toContain('100,00');
  });

  it('lida com null/undefined', () => {
    expect(formatCurrency(null)).toContain('0,00');
    expect(formatCurrency(undefined)).toContain('0,00');
  });

  it('lida com valores negativos', () => {
    expect(formatCurrency(-50.5)).toContain('50,50');
  });
});

describe('formatDuration', () => {
  it('formata minutos simples', () => {
    expect(formatDuration(30)).toBe('30min');
    expect(formatDuration(5)).toBe('5min');
  });

  it('formata horas e minutos', () => {
    expect(formatDuration(90)).toBe('1h 30min');
    expect(formatDuration(120)).toBe('2h');
    expect(formatDuration(61)).toBe('1h 1min');
  });

  it('lida com null/undefined', () => {
    expect(formatDuration(null)).toBe('0min');
    expect(formatDuration(undefined)).toBe('0min');
  });

  it('arredonda para inteiro', () => {
    expect(formatDuration(29.7)).toBe('30min');
    expect(formatDuration(30.3)).toBe('30min');
  });
});

describe('formatDistance', () => {
  it('formata distância em km', () => {
    expect(formatDistance(10.5)).toBe('10,50 km');
    expect(formatDistance(0.123)).toBe('0,12 km');
  });

  it('lida com null/undefined', () => {
    expect(formatDistance(null)).toBe('0,00 km');
    expect(formatDistance(undefined)).toBe('0,00 km');
  });
});

describe('formatNumber', () => {
  it('formata números inteiros', () => {
    expect(formatNumber(1234)).toBe('1.234');
    expect(formatNumber(0)).toBe('0');
  });

  it('formata com casas decimais', () => {
    expect(formatNumber(1234.56, 2)).toBe('1.234,56');
    expect(formatNumber(1234.5, 1)).toBe('1.234,5');
  });
});
