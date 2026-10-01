import { useState, useEffect, useRef, useId } from 'react';
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

const ENTITY_LABELS = {
  property: 'navigation.main.properties',
  unit: 'units.list.title',
  tenant: 'tenantsContracts.tenants.title',
  contract: 'tenantsContracts.contracts.title',
  account: 'finance.accounts.title',
  booking: 'finance.bookings.title',
  invoice: 'finance.invoices.title',
  maintenance: 'navigation.main.maintenance',
  task: 'navigation.main.tasks',
  document: 'navigation.main.documents',
  meter: 'navigation.main.meters',
  statement: 'navigation.main.statements',
  contact: 'navigation.main.contacts',
  portfolio: 'navigation.main.portfolio',
  deposit: 'navigation.main.deposits',
  category: 'navigation.main.categories',
  insurance: 'navigation.main.insurances',
  lead: 'navigation.main.leads',
  listing: 'navigation.main.listings',
  integration: 'navigation.main.integrations',
  message: 'navigation.main.messages',
  receivable: 'navigation.main.receivables',
  rent_charge: 'navigation.main.rentCharges',
  allocation_key: 'navigation.main.allocationKeys',
  handover_protocol: 'navigation.main.handoverProtocols',
  escalation_rule: 'navigation.main.escalationRules',
  notification_template: 'navigation.main.notificationTemplates',
  budget: 'navigation.main.budgets',
  tax_rate: 'navigation.main.taxRates',
  calendar_event: 'navigation.main.calendar',
  viewing: 'navigation.main.viewings',
  rent_adjustment: 'navigation.main.rentAdjustments',
};

function searchResults(data) {
  if (!Array.isArray(data?.results)) return [];
  const unsafe = value => value.includes('\\') || [...value].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127);
  return data.results.flatMap(result => {
    const base = ENTITY_ROUTES[result?.entity_type];
    const route = result?.url || base;
    if (!base || typeof result?.display !== 'string' || !result.display.trim()
      || typeof route !== 'string' || !route.startsWith('/') || route.startsWith('//') || unsafe(route)) return [];
    try {
      const url = new URL(route, window.location.origin);
      const decodedPath = decodeURIComponent(url.pathname);
      if (url.origin !== window.location.origin || unsafe(decodedPath)
        || decodedPath.split('/').some(part => part === '.' || part === '..')
        || !(url.pathname === base || url.pathname.startsWith(`${base}/`))) return [];
      return [{
        entity_type: result.entity_type,
        display: result.display,
        detail: typeof result.detail === 'string' ? result.detail : '',
        url: `${url.pathname}${url.search}${url.hash}`,
      }];
    } catch {
      return [];
    }
  });
}

export default function SearchBar() {
  const { t } = useTranslation();
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState({ term: '', results: [], loading: false, error: null });
  const [revision, setRevision] = useState(0);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const listId = `${useId()}-search-results`;
  const navigate = useNavigate();
  const term = query.trim();
  const expanded = open && term.length >= 2;
  const currentSearch = search.term === term ? search : { results: [], loading: true, error: null };
  const grouped = new Map();
  if (expanded) currentSearch.results.forEach(result => {
    if (!grouped.has(result.entity_type)) grouped.set(result.entity_type, []);
    grouped.get(result.entity_type).push(result);
  });
  // The same order drives rendering, highlight and Enter selection.
  const options = [...grouped.values()].flat();
  const activeOptionId = expanded && activeIndex >= 0 && activeIndex < options.length ? `${listId}-${activeIndex}` : undefined;

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

  // Abort old requests and ignore their late completions even if a transport
  // ignores cancellation. Results from a previous term never enter the list.
  useEffect(() => {
    if (!open || term.length < 2) return;
    const controller = new AbortController();
    setSearch({ term, results: [], loading: true, error: null });
    const timer = setTimeout(() => {
      api.get(`/search?q=${encodeURIComponent(term)}`, { signal: controller.signal })
        .then(data => {
          if (controller.signal.aborted) return;
          setSearch({ term, results: searchResults(data), loading: false, error: null });
          setActiveIndex(-1);
        })
        .catch(error => {
          if (!controller.signal.aborted) setSearch({ term, results: [], loading: false, error: error?.message || true });
        });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [term, open, revision]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = event => {
      if (!rootRef.current?.contains(event.target)) {
        setOpen(false);
        setActiveIndex(-1);
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    return () => document.removeEventListener('pointerdown', onPointerDown);
  }, [open]);

  const handleSelect = result => {
    setOpen(false);
    setQuery('');
    setActiveIndex(-1);
    navigate(result.url);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (!expanded || options.length === 0) {
      return;
    }

    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault();
        setActiveIndex(prev => Math.min(prev + 1, options.length - 1));
        break;
      case 'ArrowUp':
        e.preventDefault();
        setActiveIndex(prev => Math.max(prev - 1, -1));
        break;
      case 'Enter':
        e.preventDefault();
        if (activeIndex >= 0 && activeIndex < options.length) {
          handleSelect(options[activeIndex]);
        }
        break;
    }
  };

  // Scroll active item into view
  useEffect(() => {
    if (activeIndex >= 0 && listRef.current) {
      const items = listRef.current.querySelectorAll('[role="option"]');
      items[activeIndex]?.scrollIntoView?.({ block: 'nearest' });
    }
  }, [activeIndex]);

  return (
    <div className="search-bar-global" role="search" aria-label={t('ui.form.search')} ref={rootRef}
      onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) { setOpen(false); setActiveIndex(-1); }
      }}>
      <div className="search-bar-input-wrapper">
        <span className="search-bar-icon" aria-hidden="true"><SearchIcon size={16} /></span>
        <input
          ref={inputRef}
          type="text"
          placeholder={`${t('ui.form.search')}...`}
          value={query}
          onChange={e => { setQuery(e.target.value); setOpen(true); setActiveIndex(-1); }}
          onFocus={() => setOpen(true)}
          onKeyDown={handleKeyDown}
          className="search-bar-input"
          role="combobox"
          aria-label={t('ui.form.search')}
          aria-autocomplete="list"
          aria-haspopup="listbox"
          aria-expanded={expanded}
          aria-controls={expanded ? listId : undefined}
          aria-activedescendant={activeOptionId}
        />
        {query ? (
          <button
            className="search-bar-clear"
            type="button"
            onClick={() => { setQuery(''); setActiveIndex(-1); inputRef.current?.focus(); }}
            aria-label={`${t('ui.form.search')}: ${t('ui.buttons.reset')}`}
          >
            <CloseIcon size={14} />
          </button>
        ) : (
          <span className="search-bar-shortcut" aria-hidden="true">Ctrl+K</span>
        )}
      </div>
      {expanded && (
        <div className="search-bar-dropdown">
          {currentSearch.loading && <div className="search-bar-loading" role="status">{t('ui.table.loading')}</div>}
          {currentSearch.error && <div className="search-bar-empty" role="alert">
            <p>{typeof currentSearch.error === 'string' ? currentSearch.error : t('toasts.error.generic')}</p>
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => setRevision(value => value + 1)}>{t('ui.buttons.retry')}</button>
          </div>}
          {!currentSearch.loading && !currentSearch.error && options.length === 0 && <div className="search-bar-empty" role="status">{t('search.global.noResults')}</div>}
          <div id={listId} role="listbox" ref={listRef} aria-label={t('ui.form.search')} aria-busy={currentSearch.loading}>
          {!currentSearch.loading && (() => {
            let globalIndex = 0;
            return [...grouped].map(([type, items]) => (
              <div key={type} role="group" aria-label={t(ENTITY_LABELS[type])}>
                <div className="search-bar-group-header" aria-hidden="true">{t(ENTITY_LABELS[type])}</div>
                {items.map(r => {
                  const idx = globalIndex++;
                  const EntityIcon = ENTITY_ICON_MAP[r.entity_type];
                  return (
                    <div
                      key={idx}
                      id={`${listId}-${idx}`}
                      className={`search-bar-result${idx === activeIndex ? ' search-bar-result-active' : ''}`}
                      onClick={() => handleSelect(r)}
                      onMouseDown={event => event.preventDefault()}
                      onMouseEnter={() => setActiveIndex(idx)}
                      role="option"
                      aria-label={`${r.display}${r.detail ? ` ${r.detail}` : ''}`}
                      aria-selected={idx === activeIndex}
                      tabIndex={-1}
                    >
                      <span className="search-bar-result-icon" aria-hidden="true">
                        {EntityIcon ? <EntityIcon size={16} /> : <SearchIcon size={16} />}
                      </span>
                      <div className="search-bar-result-text">
                        <span className="search-bar-result-title">{r.display}</span>
                        <span className="search-bar-result-detail">{r.detail || ''}</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            ));
          })()}
          </div>
        </div>
      )}
    </div>
  );
}
