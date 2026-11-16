/**
 * Painel lateral com busca e resultados (scroll interno).
 * Flutuante sobre o mapa com z-index elevado para garantir visibilidade.
 */

import type { ReactNode } from 'react';

interface SidePanelProps {
  children: ReactNode;
}

export function SidePanel({ children }: SidePanelProps) {
  return (
    <aside
      className="fixed top-16 left-0 w-full h-[calc(100vh-4rem)] lg:h-auto lg:w-[420px] lg:top-20 lg:left-4 lg:bottom-4 bg-white shadow-xl lg:rounded-xl border-r lg:border border-slate-200 z-[1000] flex flex-col"
      role="complementary"
      aria-label="Painel de busca e resultados"
    >
      <div className="flex-1 overflow-y-auto scroll-smooth p-4 space-y-4">
        {children}
      </div>
    </aside>
  );
}
