import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { SearchIcon, CloseIcon, ENTITY_ICON_MAP } from './Icons';

const ENTITY_ROUTES = {
  property: '/properties',
  unit: '/units',
  tenant: '/tenants',
  contract: '/contracts',
  account: '/accounts',
  booking: '/bookings',
  invoice: '/invoices',
  maintenance: '/maintenance',
  task: '/tasks',
  document: '/documents',
  meter: '/meters',
  statement: '/statements',
  contact: '/contacts',
  portfolio: '/portfolios',
  deposit: '/deposits',
  category: '/categories',
  insurance: '/insurances',
  lead: '/leads',
  listing: '/listings',
  integration: '/integrations',
  message: '/messages',
  receivable: '/receivables',
  rent_charge: '/rent-charges',
  allocation_key: '/allocation-keys',
  handover_protocol: '/handover-protocols',
  escalation_rule: '/escalation-rules',
  notification_template: '/notification-templates',
  budget: '/budgets',
  tax_rate: '/tax-rates',
  calendar_event: '/calendar',
  viewing: '/viewings',
  rent_adjustment: '/rent-adjustments',
};

export default function SearchBar() {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const navigate = useNavigate();

  // Keyboard shortcut: Ctrl+K
  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
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
        .then(data => { setResults(data.results || []); setActiveIndex(-1); })
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Clear results when query is too short
  const currentResults = query.length < 2 ? [] : results;

  const handleSelect = useCallback((result) => {
    setOpen(false);
    setQuery('');
    setActiveIndex(-1);
    const route = result.url || ENTITY_ROUTES[result.entity_type] || '/';
    navigate(route);
  }, [navigate]);

  const handleKeyDown = (e) => {
    if (!open || currentResults.length === 0) {
      if (e.key === 'Escape') {
        setOpen(false);
        inputRef.current?.blur();
      }
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex(prev => Math.min(prev + 1, currentResults.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex(prev => Math.max(prev - 1, -1));
        break;
      case 'Enter':
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < currentResults.length) {
          handleSelect(currentResults[activeIndex]);
        }
        break;
      case 'Escape':
        e.preventDefault();
        setOpen(false);
        inputRef.current?.blur();
        setActiveIndex(-1);
        break;
    }
  };

  // Scroll active item into view
  useEffect(() => {
    if (activeIndex >= 0 && listRef.current) {
      const items = listRef.current.querySelectorAll('[role="option"]');
      items[activeIndex]?.scrollIntoView({ block: 'nearest' });
    }
  }, [activeIndex]);

  return (
    <div className="search-bar-global">
      <div className="search-bar-input-wrapper" role="combobox" aria-expanded={open && query.length >= 2} aria-haspopup="listbox" aria-owns="search-results-listbox">
        <span className="search-bar-icon" aria-hidden="true"><SearchIcon size={16} /></span>
        <input
          ref={inputRef}
          type="text"
          placeholder={`${t('ui.form.search')}...`}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="search-bar-input"
          role="searchbox"
          aria-label={t('ui.form.search')}
          aria-autocomplete="list"
          aria-activedescendant={activeIndex >= 0 ? `search-result-${activeIndex}` : undefined}
        />
        {query ? (
          <button
            className="search-bar-clear"
            onClick={() => { setQuery(''); setResults([]); setActiveIndex(-1); }}
            aria-label={t('ui.buttons.clear') || 'Clear search'}
          >
            <CloseIcon size={14} />
          </button>
        ) : (
          <span className="search-bar-shortcut" aria-hidden="true">Ctrl+K</span>
        )}
      </div>
      {open && query.length >= 2 && (
        <div className="search-bar-dropdown" id="search-results-listbox" role="listbox" ref={listRef} aria-label={t('ui.form.search')}>
          {loading && <div className="search-bar-loading" role="status">{t('ui.table.loading')}</div>}
          {!loading && currentResults.length === 0 && <div className="search-bar-empty" role="status">{t('search.global.noResults')}</div>}
          {!loading && currentResults.map((r, i) => {
            const EntityIcon = ENTITY_ICON_MAP[r.entity_type];
            return (
              <div
                key={i}
                id={`search-result-${i}`}
                className={`search-bar-result${i === activeIndex ? ' search-bar-result-active' : ''}`}
                onClick={() => handleSelect(r)}
                onMouseEnter={() => setActiveIndex(i)}
                role="option"
                aria-selected={i === activeIndex}
                tabIndex={-1}
              >
                <span className="search-bar-result-icon" aria-hidden="true">
                  {EntityIcon ? <EntityIcon size={16} /> : <SearchIcon size={16} />}
                </span>
                <div className="search-bar-result-text">
                  <span className="search-bar-result-title">{r.display}</span>
                  <span className="search-bar-result-detail">{r.entity_type}{r.detail ? ` — ${r.detail}` : ''}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {open && <div className="search-bar-backdrop" onClick={() => { setOpen(false); setActiveIndex(-1); }} aria-hidden="true" />}
    </div>
  );
}
