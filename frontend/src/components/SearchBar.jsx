import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { useTranslation } from '../i18n';
import { useAuth } from '../contexts/AuthContext';
import { SearchIcon, CloseIcon, PlusIcon, ENTITY_ICON_MAP } from './Icons';
import { NAV_SECTIONS, QUICK_ACTIONS } from './navigation';
import { mayWrite } from '../utils/permissions';

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

const LOAD_MORE_LIMIT = 25;

const ENTITY_LABELS = {
  property: 'Immobilien',
  unit: 'Einheiten',
  tenant: 'Mieter',
  contract: 'Verträge',
  account: 'Konten',
  booking: 'Buchungen',
  invoice: 'Rechnungen',
  maintenance: 'Wartung',
  task: 'Aufgaben',
  document: 'Dokumente',
  meter: 'Zähler',
  statement: 'Abrechnungen',
  contact: 'Kontakte',
  portfolio: 'Portfolios',
  deposit: 'Kautionen',
  category: 'Kategorien',
  insurance: 'Versicherungen',
  lead: 'Interessenten',
  listing: 'Inserate',
  integration: 'Schnittstellen',
  message: 'Nachrichten',
  receivable: 'Forderungen',
  rent_charge: 'Sollstellungen',
  allocation_key: 'Verteilerschlüssel',
  handover_protocol: 'Übergabeprotokolle',
  escalation_rule: 'Eskalationsregeln',
  budget: 'Budgets',
  tax_rate: 'Steuersätze',
  calendar_event: 'Kalender',
  viewing: 'Besichtigungen',
  rent_adjustment: 'Mietanpassungen',
};

const PAGE_LIMIT = 6;
const ACTION_LIMIT = 4;
const RECENT_LIMIT = 8;
const PAGES = NAV_SECTIONS.flatMap(section => section.items.map(item => ({ ...item, sectionKey: section.labelKey, sectionFallback: section.fallback })));
// "Uebergabe", "übergabe" and "Ubergabe" all find "Übergabeprotokolle"
const fold = text => String(text || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  .replace(/ae/g, 'a').replace(/oe/g, 'o').replace(/ue/g, 'u').replace(/ß/g, 'ss');

// The records a person opened from the search, kept per signed-in user in this browser only.
function readRecent(key) {
  if (!key) return [];
  try {
    const list = JSON.parse(window.localStorage.getItem(key) || '[]');
    return Array.isArray(list) ? list.filter(r => r && r.entity_type && r.id != null && r.display).slice(0, RECENT_LIMIT) : [];
  } catch {
    return [];
  }
}

function writeRecent(key, list) {
  if (!key) return;
  try { window.localStorage.setItem(key, JSON.stringify(list)); } catch { /* not kept */ }
}

export default function SearchBar() {
  const { t } = useTranslation();
  const tr = (key, fallback) => { const text = t(key); return !text || text === key ? fallback : text; };
  const auth = useAuth();
  const userId = auth?.user?.id;
  const recentKey = userId ? `recent_search:${userId}` : null;
  const [recent, setRecent] = useState(() => readRecent(recentKey));
  useEffect(() => { setRecent(readRecent(recentKey)); }, [recentKey]);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [groups, setGroups] = useState({});
  // the query the shown records belong to: while typing on, older records are not offered
  const [resultsFor, setResultsFor] = useState('');
  const [loadingMore, setLoadingMore] = useState(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const inputRef = useRef(null);
  const listRef = useRef(null);
  const navigate = useNavigate();

  // Keyboard shortcut: Ctrl+K
  useEffect(() => {
    const handler = (e) => {
      const typing = e.target instanceof HTMLElement
        && (e.target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName));
      // "/" as in many web apps, unless typing or inside a dialog
      const slash = e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey && !typing && !document.querySelector('[aria-modal="true"]');
      if (((e.ctrlKey || e.metaKey) && e.key === 'k') || slash) {
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
        .then(data => {
          setResults(data.results || []);
          setResultsFor(query);
          setGroups(Object.fromEntries((data.groups || []).map(g => [g.entity_type, g])));
          setActiveIndex(-1);
        })
        .catch(() => { setResults([]); setResultsFor(query); setGroups({}); })
        .finally(() => setLoading(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Clear results when query is too short
  const currentResults = query.length < 2 || resultsFor !== query ? [] : results;
  const awaitingResults = loading || (query.length >= 2 && resultsFor !== query);
  const searching = query.trim().length >= 2;
  const pageMatches = searching ? PAGES
    .map(page => ({ ...page, kind: 'page', label: tr(page.labelKey, page.fallback), section: tr(page.sectionKey, page.sectionFallback) }))
    .filter(page => fold(page.label).includes(fold(query.trim())))
    .slice(0, PAGE_LIMIT) : [];
  // "buchung" offers the page Buchungen and the action Neue Buchung; read-only roles get no actions
  const actionMatches = searching ? QUICK_ACTIONS
    .filter(action => !auth?.user || mayWrite(auth.write, action.area))
    .map(action => {
      const page = PAGES.find(p => p.to === action.area);
      return { ...action, kind: 'page', label: tr(action.labelKey, action.fallback), pageLabel: page ? tr(page.labelKey, page.fallback) : '' };
    })
    .filter(action => [action.label, action.pageLabel].some(text => fold(text).includes(fold(query.trim()))))
    .slice(0, ACTION_LIMIT) : [];
  const showRecent = !query && recent.length > 0;
  // one list for the arrow keys: pages first, then records (or the recently opened records)
  const options = showRecent ? recent : [...pageMatches, ...actionMatches, ...currentResults];
  const dropdownOpen = open && (query.length >= 2 || showRecent);

  // Next keyset page of one type, appended to its group
  const loadMore = useCallback((type) => {
    const cursor = groups[type]?.next_cursor;
    if (!cursor) return;
    setLoadingMore(type);
    api.get(`/search?q=${encodeURIComponent(query)}&type=${encodeURIComponent(type)}&limit=${LOAD_MORE_LIMIT}&cursor=${encodeURIComponent(cursor)}`)
      .then(data => {
        setResults(prev => {
          const seen = new Set(prev.map(r => `${r.entity_type}:${r.id}`));
          return [...prev, ...(data.results || []).filter(r => !seen.has(`${r.entity_type}:${r.id}`))];
        });
        setGroups(prev => ({ ...prev, [type]: { ...prev[type], ...(data.groups?.[0] || {}) } }));
      })
      .catch(() => {})
      .finally(() => setLoadingMore(null));
  }, [groups, query]);

  const handleSelect = useCallback((result) => {
    setOpen(false);
    setQuery('');
    setActiveIndex(-1);
    inputRef.current?.blur();
    if (result.kind === 'page') { navigate(result.to); return; }
    const route = result.url || ENTITY_ROUTES[result.entity_type] || '/';
    const entry = { entity_type: result.entity_type, id: result.id, display: result.display, detail: result.detail || '', url: route };
    setRecent(current => {
      const next = [entry, ...current.filter(r => !(r.entity_type === entry.entity_type && r.id === entry.id))].slice(0, RECENT_LIMIT);
      writeRecent(recentKey, next);
      return next;
    });
    navigate(route);
  }, [navigate, recentKey]);

  const clearRecent = () => {
    setRecent([]);
    writeRecent(recentKey, []);
    setActiveIndex(-1);
    inputRef.current?.focus();
  };

  const handleKeyDown = (e) => {
    if (!dropdownOpen || options.length === 0) {
      if (e.key === 'Escape') {
        setOpen(false);
        inputRef.current?.blur();
      }
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
        // Enter without choosing opens the first entry: "mahn" + Enter goes to the dunning page
        if (activeIndex >= 0 && activeIndex < options.length) handleSelect(options[activeIndex]);
        // pages and actions are known at once; records only count once they are loaded
        else if (!awaitingResults || pageMatches.length + actionMatches.length > 0) handleSelect(options[0]);
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
      <div className="search-bar-input-wrapper" role="combobox" aria-expanded={dropdownOpen} aria-haspopup="listbox" aria-owns="search-results-listbox">
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
      {dropdownOpen && (
        <div className="search-bar-dropdown" id="search-results-listbox" role="listbox" ref={listRef} aria-label={t('ui.form.search')}>
          {(() => {
            let globalIndex = 0;
            const option = (r, title, detail, Icon) => {
              const idx = globalIndex++;
              return (
                <div
                  key={`${r.kind || r.entity_type}:${r.to || r.id}`}
                  id={`search-result-${idx}`}
                  className={`search-bar-result${idx === activeIndex ? ' search-bar-result-active' : ''}`}
                  onClick={() => handleSelect(r)}
                  onMouseEnter={() => setActiveIndex(idx)}
                  role="option"
                  aria-selected={idx === activeIndex}
                  tabIndex={-1}
                >
                  <span className="search-bar-result-icon" aria-hidden="true">
                    {Icon ? <Icon size={16} /> : <SearchIcon size={16} />}
                  </span>
                  <div className="search-bar-result-text">
                    <span className="search-bar-result-title">{title}</span>
                    <span className="search-bar-result-detail">{detail || ''}</span>
                  </div>
                </div>
              );
            };
            if (showRecent) {
              return (
                <div>
                  <div className="search-bar-group-header search-bar-group-header-action">
                    <span>{tr('search.global.recentlyOpened', 'Zuletzt geöffnet')}</span>
                    <button type="button" className="search-bar-clear-recent" onClick={clearRecent}>{tr('search.global.clearRecent', 'Verlauf leeren')}</button>
                  </div>
                  {recent.map(r => option(r, r.display, r.detail || ENTITY_LABELS[r.entity_type], ENTITY_ICON_MAP[r.entity_type]))}
                </div>
              );
            }
            const grouped = {};
            currentResults.forEach(r => {
              const type = r.entity_type;
              if (!grouped[type]) grouped[type] = [];
              grouped[type].push(r);
            });
            return (
              <>
                {pageMatches.length > 0 && (
                  <div>
                    <div className="search-bar-group-header">{tr('search.global.pages', 'Seiten')}</div>
                    {pageMatches.map(page => option(page, page.label, page.section, page.icon))}
                  </div>
                )}
                {actionMatches.length > 0 && (
                  <div>
                    <div className="search-bar-group-header">{tr('search.global.actions', 'Aktionen')}</div>
                    {actionMatches.map(action => option(action, action.label, action.pageLabel, PlusIcon))}
                  </div>
                )}
                {awaitingResults && <div className="search-bar-loading" role="status">{t('ui.table.loading')}</div>}
                {!awaitingResults && currentResults.length === 0 && pageMatches.length === 0 && actionMatches.length === 0 && <div className="search-bar-empty" role="status">{t('search.global.noResults')}</div>}
                {!awaitingResults && Object.entries(grouped).map(([type, items]) => (
                  <div key={type}>
                    <div className="search-bar-group-header">
                      {ENTITY_LABELS[type] || type}
                      {groups[type]?.total > items.length && (
                        <span className="search-bar-group-count"> · {t('search.global.shownOf', { shown: items.length, total: groups[type].total })}</span>
                      )}
                    </div>
                    {items.map(r => option(r, r.display, r.detail, ENTITY_ICON_MAP[r.entity_type]))}
                    {groups[type]?.next_cursor && (
                      <button
                        type="button"
                        className="search-bar-load-more"
                        onClick={(e) => { e.stopPropagation(); loadMore(type); }}
                        disabled={loadingMore === type}
                      >
                        {loadingMore === type ? t('ui.table.loading') : t('search.global.loadMore')}
                      </button>
                    )}
                  </div>
                ))}
              </>
            );
          })()}
        </div>
      )}
      {open && <div className="search-bar-backdrop" onClick={() => { setOpen(false); setActiveIndex(-1); }} aria-hidden="true" />}
    </div>
  );
}
