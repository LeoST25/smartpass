/**
 * Legenda do mapa com cores por modal.
 */

export function Legend() {
  const items = [
    { color: '#2563EB', label: 'Ônibus urbano', dash: false },
    { color: '#EA580C', label: 'Ônibus intermunicipal', dash: false },
    { color: '#16A34A', label: 'Metrô/Trem', dash: false },
    { color: '#94A3B8', label: 'Caminhada', dash: true },
  ];

  return (
    <div className="absolute bottom-4 right-4 bg-white rounded-lg shadow-lg border border-slate-200 p-3 z-[1000] max-w-[200px]">
      <h3 className="text-xs font-semibold text-slate-900 mb-2">Legenda</h3>
      <ul className="space-y-1.5">
        {items.map((item) => (
          <li key={item.label} className="flex items-center gap-2">
            <svg width="24" height="4" className="flex-shrink-0">
              <line
                x1="0"
                y1="2"
                x2="24"
                y2="2"
                stroke={item.color}
                strokeWidth="3"
                strokeDasharray={item.dash ? '4,4' : 'none'}
              />
            </svg>
            <span className="text-xs text-slate-700">{item.label}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
