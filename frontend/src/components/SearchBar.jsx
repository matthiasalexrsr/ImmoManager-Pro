import { useState, useEffect, useRef, useId } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import { SearchIcon, CloseIcon, ENTITY_ICON_MAP } from './Icons';
import './SearchBar.css';

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

const PAGE_TEXT = {
  de: { previous: 'Vorherige Treffer', next: 'Weitere Treffer', page: 'Seite', restart: 'Suche neu starten', emptyPage: 'Auf dieser Seite sind aktuell keine Treffer vorhanden.', invalid: 'Die Suchantwort ist unvollständig. Bitte erneut versuchen.' },
  en: { previous: 'Previous results', next: 'More results', page: 'Page', restart: 'Restart search', emptyPage: 'There are currently no matches on this page.', invalid: 'The search response is incomplete. Please retry.' },
  es: { previous: 'Resultados anteriores', next: 'Más resultados', page: 'Página', restart: 'Reiniciar búsqueda', emptyPage: 'No hay resultados en esta página.', invalid: 'La respuesta de búsqueda está incompleta. Vuelva a intentarlo.' },
};

function SearchControl() {
  const { t, locale = 'de-DE' } = useTranslation();
  const copy = PAGE_TEXT[locale.slice(0, 2)] || PAGE_TEXT.de;
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState({ term: '', cursor: null, results: [], loading: false, error: null, next: null });
  const [pages, setPages] = useState([null]);
  const [revision, setRevision] = useState(0);
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const rootRef = useRef(null);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const listId = `${useId()}-search-results`;
  const navigate = useNavigate();
  const term = query.trim();
  const cursor = pages.at(-1);
  const expanded = open && term.length >= 2;
  const currentSearch = search.term === term && search.cursor === cursor ? search : { results: [], loading: true, error: null, next: null };
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
    setSearch({ term, cursor, results: [], loading: true, error: null, next: null });
    const timer = setTimeout(() => {
      api.get(`/search/page?q=${encodeURIComponent(term)}${cursor ? `&after=${encodeURIComponent(cursor)}` : ''}`, { signal: controller.signal })
        .then(data => {
          if (controller.signal.aborted) return;
          if (!Array.isArray(data?.results) || (data.has_more && (typeof data.next_after !== 'string' || !data.next_after))) throw new Error(copy.invalid);
          setSearch({ term, cursor, results: searchResults(data), loading: false, error: null, next: data.has_more ? data.next_after : null });
          setActiveIndex(-1);
        })
        .catch(error => {
          if (!controller.signal.aborted) setSearch({ term, cursor, results: [], loading: false, error: error?.message || true, next: null });
        });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [term, cursor, open, revision, copy.invalid]);

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
    setPages([null]);
    setActiveIndex(-1);
    navigate(result.url);
  };

  // Return focus before a loading update disables/removes the action button.
  // Otherwise the browser emits focusout with no destination and closes the
  // whole search while the requested next page is still pending.
  const searchAction = action => {
    inputRef.current?.focus();
    setActiveIndex(-1);
    action();
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
          onChange={e => { setQuery(e.target.value); setPages([null]); setOpen(true); setActiveIndex(-1); }}
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
            onClick={() => { setQuery(''); setPages([null]); setActiveIndex(-1); inputRef.current?.focus(); }}
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
            <button type="button" className="btn btn-sm btn-secondary" onClick={() => searchAction(() => setRevision(value => value + 1))}>{t('ui.buttons.retry')}</button>
            {pages.length > 1 && <button type="button" className="btn btn-sm btn-secondary" onClick={() => searchAction(() => setPages([null]))}>{copy.restart}</button>}
          </div>}
          {!currentSearch.loading && !currentSearch.error && options.length === 0 && <div className="search-bar-empty" role="status">{pages.length > 1 ? copy.emptyPage : t('search.global.noResults')}</div>}
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
          {(pages.length > 1 || currentSearch.next) && <nav className="search-bar-pages" aria-label={t('ui.form.search')}>
            <button type="button" className="btn btn-sm btn-secondary" disabled={currentSearch.loading || pages.length === 1}
              onClick={() => searchAction(() => setPages(value => value.slice(0, -1)))}>{copy.previous}</button>
            <span>{copy.page} {pages.length}</span>
            <button type="button" className="btn btn-sm btn-secondary" disabled={currentSearch.loading || !currentSearch.next}
              onClick={() => searchAction(() => setPages(value => [...value, currentSearch.next]))}>{copy.next}</button>
          </nav>}
        </div>
      )}
    </div>
  );
}

export default function SearchBar() {
  const auth = useAuth();
  const user = auth?.user;
  const principal = user ? JSON.stringify([user.id, user.role, user.portfolio_access,
    user.portfolio_access_origin, [...(user.portfolio_ids || [])].sort()]) : '';
  // A changed account or object scope discards private results synchronously.
  return <SearchControl key={principal} />;
}
