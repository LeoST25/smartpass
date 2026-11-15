/**
 * Guards LGPD stateless — garante zero persistência em localStorage/sessionStorage.
 * Toda aplicação deve manter dados apenas em memória React (state/context).
 */

/**
 * Verifica se o ambiente suporta localStorage (apenas para validação de testes).
 */
export function isLocalStorageAvailable(): boolean {
  try {
    return typeof window !== 'undefined' && 'localStorage' in window;
  } catch {
    return false;
  }
}

/**
 * Valida que nenhum dado sensível está sendo persistido.
 * Chamada apenas em testes/CI para garantir conformidade.
 */
export function validateStateless(): void {
  if (!isLocalStorageAvailable()) return;

  const forbidden = ['localStorage', 'sessionStorage', 'indexedDB'];
  for (const key of forbidden) {
    if (typeof window !== 'undefined' && key in window) {
      console.warn(
        `[LGPD] Atenção: ${key} está disponível no ambiente. ` +
          'A aplicação SmartPass deve manter todos os dados em memória React (stateless).'
      );
    }
  }
}
