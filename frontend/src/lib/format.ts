/**
 * Utilitários de formatação (moeda BRL, tempo, distância).
 */

/**
 * Formata valor em moeda BRL (R$ 1.234,56).
 */
export function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return 'R$ 0,00';
  }
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Formata tempo em minutos para "Xh Ymin" ou "Ymin".
 */
export function formatDuration(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined || Number.isNaN(minutes)) {
    return '0min';
  }
  const m = Math.round(minutes);
  if (m < 60) {
    return `${m}min`;
  }
  const hours = Math.floor(m / 60);
  const remainingMinutes = m % 60;
  return remainingMinutes === 0 ? `${hours}h` : `${hours}h ${remainingMinutes}min`;
}

/**
 * Formata distância em km com 2 casas decimais.
 */
export function formatDistance(km: number | null | undefined): string {
  if (km === null || km === undefined || Number.isNaN(km)) {
    return '0,00 km';
  }
  return `${km.toFixed(2).replace('.', ',')} km`;
}

/**
 * Formata número com separadores BR (1.234,56).
 */
export function formatNumber(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '0';
  }
  return new Intl.NumberFormat('pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}
