/**
 * Autocomplete de endereço com debounce 300ms e semáforo de precisão.
 */

import { useState, useEffect, useRef } from 'react';
import { Search, MapPin } from 'lucide-react';
import { api } from '../../lib/api';
import type { CandidatoGeocoding } from '../../types/api';

interface AddressAutocompleteProps {
  label: string;
  value: CandidatoGeocoding | null;
  onChange: (candidate: CandidatoGeocoding | null) => void;
}

export function AddressAutocomplete({ label, value, onChange }: AddressAutocompleteProps) {
  const [query, setQuery] = useState('');
  const [suggestions, setSuggestions] = useState<CandidatoGeocoding[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(-1);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Debounce 300ms para busca
  useEffect(() => {
    // Quando um candidato já foi selecionado, não refaz a busca (evita reabrir o dropdown).
    if (query.length < 3 || value) {
      setSuggestions([]);
      setIsOpen(false);
      return;
    }

    const timeoutId = setTimeout(async () => {
      setLoading(true);
      try {
        const data = await api.autocomplete(query);
        setSuggestions(data.sugestoes);
        setIsOpen(data.sugestoes.length > 0);
      } catch (error) {
        console.warn('[Autocomplete]', error);
        setSuggestions([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timeoutId);
  }, [query, value]);

  // Navegação por teclado
  useEffect(() => {
    if (!isOpen || !listRef.current) return;

    const items = listRef.current.querySelectorAll('li');
    items.forEach((item, idx) => {
      if (idx === selectedIndex) {
        item.setAttribute('aria-selected', 'true');
        item.scrollIntoView({ block: 'nearest' });
      } else {
        item.setAttribute('aria-selected', 'false');
      }
    });
  }, [selectedIndex, isOpen]);

  function handleSelect(candidate: CandidatoGeocoding) {
    onChange(candidate);
    setQuery(candidate.label_exibicao);
    setIsOpen(false);
    setSelectedIndex(-1);
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (!isOpen) return;

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % suggestions.length);
        break;
      case 'ArrowUp':
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + suggestions.length) % suggestions.length);
        break;
      case 'Enter':
        e.preventDefault();
        if (selectedIndex >= 0 && selectedIndex < suggestions.length) {
          handleSelect(suggestions[selectedIndex]);
        }
        break;
      case 'Escape':
        setIsOpen(false);
        setSelectedIndex(-1);
        break;
    }
  }

  function getSemaforoEmoji(nivel: string): string {
    switch (nivel) {
      case 'ALTA':
        return '🟢';
      case 'MEDIA':
        return '🟡';
      case 'BAIXA':
        return '🔴';
      default:
        return '⚪';
    }
  }

  function getSemaforoLabel(nivel: string): string {
    switch (nivel) {
      case 'ALTA':
        return 'Exato';
      case 'MEDIA':
        return 'Aproximado';
      case 'BAIXA':
        return 'Revisar';
      default:
        return 'Desconhecido';
    }
  }

  return (
    <div className="relative">
      <label className="block text-sm font-medium text-slate-700 mb-1">{label}</label>
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
        <input
          ref={inputRef}
          type="text"
          value={value ? value.label_exibicao : query}
          onChange={(e) => {
            setQuery(e.target.value);
            if (value) onChange(null);
          }}
          onFocus={() => {
            if (suggestions.length > 0) setIsOpen(true);
          }}
          onBlur={() => {
            // Delay para permitir clique na sugestão
            setTimeout(() => setIsOpen(false), 200);
          }}
          onKeyDown={handleKeyDown}
          placeholder="Digite CEP ou endereço..."
          className="w-full pl-10 pr-10 py-2 border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-smartpass-500 focus:border-transparent"
          role="combobox"
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          aria-controls="address-suggestions"
          aria-activedescendant={selectedIndex >= 0 ? `suggestion-${selectedIndex}` : undefined}
        />
        {loading && (
          <div className="absolute right-3 top-1/2 -translate-y-1/2">
            <div className="w-4 h-4 border-2 border-slate-300 border-t-smartpass-600 rounded-full animate-spin" />
          </div>
        )}
      </div>

      {value && (
        <div className="mt-1 flex items-center gap-1 text-xs text-slate-600">
          <MapPin className="w-3 h-3" />
          <span>
            {getSemaforoEmoji(value.nivel_precisao)} {getSemaforoLabel(value.nivel_precisao)}
          </span>
        </div>
      )}

      {isOpen && suggestions.length > 0 && (
        <ul
          ref={listRef}
          id="address-suggestions"
          role="listbox"
          className="absolute z-10 w-full mt-1 bg-white border border-slate-200 rounded-lg shadow-lg max-h-60 overflow-y-auto"
        >
          {suggestions.map((suggestion, idx) => (
            <li
              key={`${suggestion.lat}-${suggestion.lon}-${idx}`}
              id={`suggestion-${idx}`}
              role="option"
              aria-selected={idx === selectedIndex}
              className={`px-3 py-2 cursor-pointer hover:bg-slate-50 ${
                idx === selectedIndex ? 'bg-slate-100' : ''
              }`}
              onClick={() => handleSelect(suggestion)}
            >
              <div className="text-sm text-slate-900">{suggestion.label_exibicao}</div>
              <div className="text-xs text-slate-500 flex items-center gap-1">
                <span>{getSemaforoEmoji(suggestion.nivel_precisao)}</span>
                <span>{getSemaforoLabel(suggestion.nivel_precisao)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
