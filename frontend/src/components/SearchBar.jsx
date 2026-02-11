import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';

const ENTITY_ROUTES = {
  property: '/properties',
  tenant: '/tenants',
  unit: '/units',
  contract: '/contracts',
  task: '/tasks',
  invoice: '/invoices',
};

const ENTITY_ICONS = {
  property: '\uD83C\uDFE0',
  tenant: '\uD83D\uDC64',
  unit: '\uD83D\uDEAA',
  contract: '\uD83D\uDCC4',
  task: '\u2705',
  invoice: '\uD83E\uDDFE',
};

export default function SearchBar() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  // Keyboard shortcut: Ctrl+K
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
      if (e.key === 'Escape') {
        setOpen(false);
        inputRef.current?.blur();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, []);

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setResults([]);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      api.get(`/search?q=${encodeURIComponent(query)}`)
        .then(data => setResults(data.results || []))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  const handleSelect = (result) => {
    setOpen(false);
    setQuery('');
    const route = ENTITY_ROUTES[result.entity_type] || '/';
    navigate(route);
  };

  return (
    <div className="search-bar-global">
      <div className="search-bar-input-wrapper">
        <span className="search-bar-icon">{'\uD83D\uDD0D'}</span>
        <input
          ref={inputRef}
          type="text"
          placeholder="Suchen... (Ctrl+K)"
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          className="search-bar-input"
        />
        {query && (
          <button className="search-bar-clear" onClick={() => { setQuery(''); setResults([]); }}>
            &times;
          </button>
        )}
      </div>
      {open && query.length >= 2 && (
        <div className="search-bar-dropdown">
          {loading && <div className="search-bar-loading">Suche...</div>}
          {!loading && results.length === 0 && <div className="search-bar-empty">Keine Treffer</div>}
          {!loading && results.map((r, i) => (
            <div key={i} className="search-bar-result" onClick={() => handleSelect(r)}>
              <span className="search-bar-result-icon">{ENTITY_ICONS[r.entity_type] || '\uD83D\uDCC1'}</span>
              <div className="search-bar-result-text">
                <span className="search-bar-result-title">{r.display}</span>
                <span className="search-bar-result-detail">{r.entity_type} {r.detail ? `\u2014 ${r.detail}` : ''}</span>
              </div>
            </div>
          ))}
        </div>
      )}
      {open && <div className="search-bar-backdrop" onClick={() => setOpen(false)} />}
    </div>
  );
}
