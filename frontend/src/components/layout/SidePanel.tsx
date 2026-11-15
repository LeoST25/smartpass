/**
 * Painel lateral com busca e resultados (scroll interno).
 */

import type { ReactNode } from 'react';

interface SidePanelProps {
  children: ReactNode;
}

export function SidePanel({ children }: SidePanelProps) {
  return (
    <aside className="fixed top-16 left-0 w-full lg:w-[420px] lg:top-20 lg:left-4 bottom-0 lg:bottom-4 bg-white lg:rounded-xl lg:shadow-lg border-r lg:border border-slate-200 z-10 flex flex-col">
      <div className="flex-1 overflow-y-auto scroll-smooth p-4 space-y-4">
        {children}
      </div>
    </aside>
  );
}
