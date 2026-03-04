import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { SearchIcon, CloseIcon, ENTITY_ICON_MAP } from './Icons';

const ENTITY_ROUTES = {
  property: '/properties',
  tenant: '/tenants',
  unit: '/units',
  contract: '/contracts',
  task: '/tasks',
  invoice: '/invoices',
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
      return;
    }
    const timer = setTimeout(() => {
      setLoading(true);
      api.get(`/search?q=${encodeURIComponent(query)}`)
        .then(data => setResults(data.results || []))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Clear results when query is too short
  const currentResults = query.length < 2 ? [] : results;

  const handleSelect = (result) => {
    setOpen(false);
    setQuery('');
    const route = ENTITY_ROUTES[result.entity_type] || '/';
    navigate(route);
  };

  return (
    <div className="search-bar-global">
      <div className="search-bar-input-wrapper">
        <span className="search-bar-icon"><SearchIcon size={16} /></span>
        <input
          ref={inputRef}
          type="text"
          placeholder="Suchen..."
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          className="search-bar-input"
        />
        {query ? (
          <button className="search-bar-clear" onClick={() => { setQuery(''); setResults([]); }}>
            <CloseIcon size={14} />
          </button>
        ) : (
          <span className="search-bar-shortcut">Ctrl+K</span>
        )}
      </div>
      {open && query.length >= 2 && (
        <div className="search-bar-dropdown">
          {loading && <div className="search-bar-loading">Suche...</div>}
          {!loading && currentResults.length === 0 && <div className="search-bar-empty">Keine Treffer</div>}
          {!loading && currentResults.map((r, i) => {
            const EntityIcon = ENTITY_ICON_MAP[r.entity_type];
            return (
              <div key={i} className="search-bar-result" onClick={() => handleSelect(r)}>
                <span className="search-bar-result-icon">
                  {EntityIcon ? <EntityIcon size={16} /> : <SearchIcon size={16} />}
                </span>
                <div className="search-bar-result-text">
                  <span className="search-bar-result-title">{r.display}</span>
                  <span className="search-bar-result-detail">{r.entity_type}{r.detail ? ` \u2014 ${r.detail}` : ''}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {open && <div className="search-bar-backdrop" onClick={() => setOpen(false)} />}
    </div>
  );
}
