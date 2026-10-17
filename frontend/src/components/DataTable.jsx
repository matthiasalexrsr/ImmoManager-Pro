import NotificationArrival from './NotificationArrival';
import { useState, useMemo, useCallback, useEffect, useId, useRef } from 'react';
import { useInRouterContext, useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import { useTranslation } from '../i18n';
import { useCanWrite } from '../contexts/AuthContext';
import { PlusIcon, EditIcon, TrashIcon } from './Icons';
import StatusBadge from './StatusBadge';
import BulkBar from './BulkBar';
import EntityLink from './EntityLink';
import { formatDate, formatMoney, formatNumber, plainLabel } from '../utils/format';
import { codeLabel } from '../utils/codeLabels';
import { buildCsv } from '../utils/tableCsv';
import { readTableView, useStoredTableSettings, writeTableView } from '../utils/tableSettings';
import { NEW_ENTRY_EVENT, takeNewEntry } from '../utils/newEntry';
import './DataTable.css';
import NamedViews from './NamedViews';
import { formContext } from '../utils/workspaceClient';
import { markWorkspaceRow, readWorkspaceRow } from '../hooks/useNavigationState';
import useWorkspaceViewState from '../hooks/useWorkspaceViewState';

const PAGE_SIZES = [10, 25, 50, 100];
const NUMERIC_TYPES = new Set(['number', 'currency']);
const keyHash = value => { let hash = 2166136261; for (const char of value || '') hash = Math.imul(hash ^ char.charCodeAt(0), 16777619); return (hash >>> 0).toString(16); };

// link: { kind, idKey } (or just the kind) makes the shown name lead to its record; subLink does
// the same for the second line (the property under a unit). Default id keys follow the kind.
const ID_KEYS = { tenant: 'tenant_id', property: 'property_id', unit: 'unit_id', contract: 'contract_id',
  maintenance: 'id', serviceContract: 'service_contract_id', contact: 'contact_id', lead: 'lead_id', account: 'account_id' };
function linked(spec, row, text) {
  if (!spec || text == null || text === '' || text === '\u2014') return text;
  const { kind, idKey } = typeof spec === 'string' ? { kind: spec } : spec;
  return <EntityLink kind={kind} id={row[idKey || ID_KEYS[kind]]} text={String(text)}>{text}</EntityLink>;
}

// Cells keep to one line; long plain text is cut with an ellipsis and shown in full on hover.
function cellContent(col, row) {
  const value = row[col.key];
  if (col.render) return col.render(value, row);
  if (value == null || value === '') return '\u2014';
  if (col.type === 'currency') return formatMoney(value);
  if (col.type === 'date') return formatDate(value);
  if (col.type === 'status') return <StatusBadge status={value} />;
  const text = String(codeLabel(value));
  if (col.subKey) {
    // Two lines on purpose: the main value and its context (unit above, property below).
    const sub = row[col.subKey];
    const hasMain = text !== '\u2014';
    return (
      <span className="cell-stack">
        <span className="cell-text">{hasMain ? linked(col.link, row, text) : linked(col.subLink, row, sub || text)}</span>
        {hasMain && sub && sub !== '\u2014' && <span className="cell-text td-sub">{linked(col.subLink, row, sub)}</span>}
      </span>
    );
  }
  return <span className="cell-text" title={text.length > 30 ? text : undefined}>{linked(col.link, row, text)}</span>;
}


// What a person can search for: the stored value, and what the table shows for it
// (a status code as its German label, a date as it is written).
function searchText(col, value) {
  if (value == null || value === '') return '';
  const shown = col.type === 'date' ? formatDate(value) : codeLabel(value);
  return `${value} ${shown}`.toLowerCase();
}

// One stored setting per list, not per record: /properties/7 and /properties/9 share their tables.
function defaultSettingsKey(title, pathname) {
  if (typeof window === 'undefined' || !title) return null;
  const path = pathname.split('/').map(part => (/\d/.test(part) ? ':id' : part)).join('/');
  return `${path}|${title}`;
}

// Totals in whole cents, so 0.1 + 0.2 is 0.30 and long lists do not drift.
function centsTotal(rows, key) {
  return rows.reduce((total, row) => {
    const n = Number(row[key]);
    return Number.isFinite(n) ? total + Math.round(n * 100) : total;
  }, 0);
}

// sum: true retains cent-based money totals. Physical quantities opt into
// sum: 'number' and can supply formatTotal (e.g. m²), without cent rounding.
function sumValue(rows, col) {
  if (col.sum !== 'number') return centsTotal(rows, col.key) / 100;
  const values = rows.map(row => row[col.key]).filter(value => value != null && value !== '' && Number.isFinite(Number(value)));
  return values.length ? values.reduce((total, value) => total + Number(value), 0) : null;
}
function sumLabel(col, value) {
  return col.sum === 'number' ? (col.formatTotal ? col.formatTotal(value) : formatNumber(value, 2)) : formatMoney(value);
}

function cellClass(col) {
  return [
    col.align === 'right' || (col.align == null && NUMERIC_TYPES.has(col.type)) ? 'text-right td-num' : '',
    col.wrap ? 'td-wrap' : '',
  ].filter(Boolean).join(' ') || undefined;
}

export default function DataTable(props) {
  const routed = useInRouterContext();
  return routed ? <RoutedDataTable {...props} /> : <TableWithKey {...props}
    pathname={typeof window === 'undefined' ? '/' : window.location.pathname} />;
}

function RoutedDataTable(props) {
  const { pathname, search } = useLocation();
  const navigation = useNavigationType();
  const navigate = useNavigate();
  return <TableWithKey {...props} pathname={pathname} routeSearch={search} restoreLocationState={navigation === 'POP'} clearFocusedRow={() => {
    const query = new URLSearchParams(search); query.delete('focus_id'); navigate(`${pathname}${query.size ? `?${query}` : ''}`);
  }} />;
}

function TableWithKey(props) {
  const storageKey = props.settingsKey === undefined ? defaultSettingsKey(props.title, props.pathname) : props.settingsKey;
  // A different list owns different state. Remount before persistence effects can
  // copy the previous list's filters, selection or settings into the new key.
  return <TableView key={`${props.serverPaged ? 'server' : 'client'}:${storageKey ?? ''}`}
    {...props} resolvedSettingsKey={storageKey} />;
}

function TableView({ columns, data, onEdit: editHandler, onDelete: deleteHandler, title,
  onAdd: addHandler, onRowClick, rowActions: rowActionsFor, writeArea, serverPaged = false, loadExportData, hideTitle = false,
  resolvedSettingsKey: storageKey, pathname, routeSearch, bulkActions: bulkActionsFor, rowName, addLabel, hideAddButton = false, emptyText,
  viewConfig, onApplyView, viewAnchor, drilldownKey, clearFocusedRow, restoreLocationState = false }) {
  const { t } = useTranslation();
  const tr = (key, fallback) => { const text = t(key); return !text || text === key ? fallback : text; };
  const titleId = useId();
  // Roles that may not change this list do not get New/Edit/Delete (the server would refuse anyway).
  const canWrite = useCanWrite(writeArea);
  const onAdd = canWrite ? addHandler : undefined;
  const onEdit = canWrite ? editHandler : undefined;
  const onDelete = canWrite ? deleteHandler : undefined;
  const rowActions = rowActionsFor && (row => rowActionsFor(row).filter(a => canWrite || !a.write));
  // Several rows at once: a checkbox column appears only when the page offers actions this role may run.
  const bulkActions = (bulkActionsFor || []).filter(a => canWrite || !a.write);
  const selectable = bulkActions.length > 0;
  const [selectedIds, setSelectedIds] = useState(() => new Set());
  const [bulkReport, setBulkReport] = useState(null);
  const [bulkRunning, setBulkRunning] = useState(false);
  const lastToggled = useRef(null);
  // search, filters and page as left in this tab (server-paged lists keep their own state)
  const viewStorageKey = storageKey && routeSearch ? `${storageKey}|query:${routeSearch}` : storageKey;
  const [savedView] = useState(() => (serverPaged ? null : readTableView(viewStorageKey)));
  // A link to a list filtered to one record (/contacts?suche=Name) starts with that search.
  const [search, setSearch] = useState(() => {
    const linkedSearch = !serverPaged && typeof window !== 'undefined' ? new URLSearchParams(routeSearch ?? window.location.search).get('suche') : null;
    if (new URLSearchParams(routeSearch ?? window.location.search).size && (!restoreLocationState || !savedView)) return linkedSearch || '';
    return typeof savedView?.search === 'string' ? savedView.search : '';
  });
  // Sorting, rows per page and hidden columns are remembered per list in this browser.
  const [stored, setStored] = useStoredTableSettings(storageKey,
    { sortKey: null, sortDir: 'asc', pageSize: 25, hiddenCols: {} });
  const sortKey = !serverPaged && columns.some(c => c.key === stored.sortKey && c.sortable !== false) ? stored.sortKey : null;
  const sortDir = stored.sortDir === 'desc' ? 'desc' : 'asc';
  const pageSize = PAGE_SIZES.includes(stored.pageSize) ? stored.pageSize : 25;
  const hiddenCols = useMemo(() => {
    const hidden = {
      ...Object.fromEntries(columns.filter(c => c.hidden).map(c => [c.key, true])),
      ...Object.fromEntries(Object.entries(stored.hiddenCols || {}).filter(([, value]) => typeof value === 'boolean')),
    };
    // Old saved views or imported layouts may hide every column. Recover
    // a visible column without erasing any of the other stored preferences.
    if (columns.length && columns.every(col => hidden[col.key])) {
      hidden[(columns.find(col => !col.hidden) || columns[0]).key] = false;
    }
    return hidden;
  }, [columns, stored.hiddenCols]);
  const setSort = (key, dir) => setStored(current => ({ ...current, sortKey: key, sortDir: dir }));
  const setPageSize = size => setStored(current => ({ ...current, pageSize: size }));
  const toggleColumn = key => {
    // A stored view must never render a table without any data column.
    if (!hiddenCols[key] && columns.filter(col => !hiddenCols[col.key]).length <= 1) return;
    setStored(current => ({ ...current, hiddenCols: { ...hiddenCols, [key]: !hiddenCols[key] } }));
  };
  const [linkedOnMount] = useState(() => !serverPaged && typeof window !== 'undefined' && new URLSearchParams(routeSearch ?? window.location.search).size > 0);
  const [page, setPage] = useState(() => ((!linkedOnMount || restoreLocationState) && Number.isInteger(savedView?.page) && savedView.page > 0 ? savedView.page : 0));
  const [columnFilters, setColumnFilters] = useState(() => {
    const saved = savedView?.columnFilters;
    if (linkedOnMount && !restoreLocationState || !saved || typeof saved !== 'object') return {};
    // only filters of columns this list still has, in the shape their filter expects
    return Object.fromEntries(columns.filter(col => col.filterType && saved[col.key] != null).map(col => [col.key, saved[col.key]])
      .filter(([key, value]) => {
        const type = columns.find(col => col.key === key).filterType;
        return type === 'dateRange' || type === 'numberRange'
          ? Array.isArray(value) && value.length === 2 && value.every(endpoint => typeof endpoint === 'string')
          : typeof value === 'string';
      }));
  });
  useEffect(() => {
    if (!serverPaged) writeTableView(viewStorageKey, { search, columnFilters, page });
  }, [viewStorageKey, serverPaged, search, columnFilters, page]);
  const [showColMenu, setShowColMenu] = useState(false);
  const colToggleRef = useRef(null);
  const colMenuRef = useRef(null);
  const [showFilters, setShowFilters] = useState(false);
  const filterToggleRef = useRef(null);
  const searchInputRef = useRef(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const viewScope = viewAnchor ? `${storageKey}:${viewAnchor.kind}:${viewAnchor.id}` : storageKey;
  const viewContext = storageKey && formContext(pathname) ? `${formContext(pathname)}#${keyHash(viewScope)}` : null;
  const namedConfig = { search, sort: sortKey ? { key: sortKey, direction: sortDir } : null,
    visible_columns: columns.filter(col => !hiddenCols[col.key]).map(col => col.key), column_order: stored.columnOrder || columns.map(col => col.key), page_size: pageSize,
    ...viewConfig, column_filters: { ...columnFilters, ...viewConfig?.column_filters } };
  const applyView = config => {
    if (!serverPaged) {
      setSearch(typeof config.search === 'string' ? config.search : '');
      const filters = config.column_filters || {};
      setColumnFilters(Object.fromEntries(columns.filter(col => col.filterType && filters[col.key] != null).map(col => [col.key, filters[col.key]]).filter(([key, value]) => {
      const type = columns.find(col => col.key === key).filterType;
      return type === 'dateRange' || type === 'numberRange' ? Array.isArray(value) && value.length === 2 && value.every(v => typeof v === 'string') : typeof value === 'string';
      })));
    }
    setStored(current => ({ ...current, sortKey: config.sort?.key || null, sortDir: config.sort?.direction === 'desc' ? 'desc' : 'asc',
      pageSize: PAGE_SIZES.includes(config.page_size) ? config.page_size : 25,
      hiddenCols: Object.fromEntries(columns.map(col => [col.key, Array.isArray(config.visible_columns) ? !config.visible_columns.includes(col.key) : Boolean(col.hidden)])),
      columnOrder: Array.isArray(config.column_order) ? config.column_order.filter(key => columns.some(col => col.key === key)) : columns.map(col => col.key),
    }));
    setPage(0);
    onApplyView?.(config);
  };
  const lastDrilldown = useRef(drilldownKey);
  useEffect(() => {
    if (lastDrilldown.current === drilldownKey) return;
    lastDrilldown.current = drilldownKey;
    setSearch(''); setColumnFilters({}); setPage(0);
  }, [drilldownKey]);
  useWorkspaceViewState(!serverPaged && !linkedOnMount ? viewContext : null,
    { ...namedConfig, page_cursor: String(page) }, state => { if (savedView) return; applyView(state); if (/^\d+$/.test(state.page_cursor || '')) setPage(Number(state.page_cursor)); });
  const [rowMark, setRowMark] = useState(() => readWorkspaceRow(storageKey));
  const markRow = row => { markWorkspaceRow(storageKey, row.id); setRowMark(String(row.id)); };

  const setFilter = useCallback((key, value) => {
    setColumnFilters(prev => ({ ...prev, [key]: value }));
    setPage(0);
  }, []);

  // Sort: asc → desc → none
  const handleSort = useCallback((key) => {
    if (sortKey === key) {
      if (sortDir === 'asc') setSort(key, 'desc');
      else setSort(null, 'asc');
    } else {
      setSort(key, 'asc');
    }
    setPage(0);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortKey, sortDir]);

  const visibleColumns = useMemo(
    () => {
      const order = Array.isArray(stored.columnOrder) ? stored.columnOrder : [];
      return columns.filter(col => !hiddenCols[col.key]).sort((a, b) => {
        const ai = order.indexOf(a.key), bi = order.indexOf(b.key);
        return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
      });
    },
    [columns, hiddenCols, stored.columnOrder]
  );

  // Filter
  const filtered = useMemo(() => {
    if (serverPaged) return data;
    let items = data;
    const focusedId = new URLSearchParams(routeSearch ?? window.location.search).get('focus_id');
    if (focusedId) items = items.filter(row => String(row.id) === focusedId);

    if (search) {
      const q = search.toLowerCase();
      items = items.filter(row => columns.some(col => searchText(col, row[col.key]).includes(q)));
    }

    for (const col of columns) {
      const fv = columnFilters[col.key];
      // Clearing both ends of a range must turn the filter OFF entirely,
      // including for rows without a date or amount.
      if (fv == null || fv === '' || (Array.isArray(fv) && fv.every(part => part === ''))) continue;
      if (col.filterType === 'select') {
        items = items.filter(row => String(row[col.key] ?? '') === fv);
      } else if (col.filterType === 'dateRange') {
        const [from, to] = fv;
        items = items.filter(row => {
          const d = row[col.key];
          if (!d) return false;
          if (from && d < from) return false;
          if (to && d > to) return false;
          return true;
        });
      } else if (col.filterType === 'numberRange') {
        const [min, max] = fv;
        items = items.filter(row => {
          // Number(null) and Number('') are 0, but a missing amount is not
          // a legitimate zero-amount booking or balance.
          const raw = row[col.key];
          if (raw == null || raw === '') return false;
          const n = Number(raw);
          if (!Number.isFinite(n)) return false;
          if (min !== '' && n < Number(min)) return false;
          if (max !== '' && n > Number(max)) return false;
          return true;
        });
      } else {
        const q = fv.toLowerCase();
        items = items.filter(row => {
          const val = row[col.key];
          return val && String(val).toLowerCase().includes(q);
        });
      }
    }
    return items;
  }, [data, search, columnFilters, columns, serverPaged, routeSearch]);

  // Sort
  const sorted = useMemo(() => {
    if (serverPaged || !sortKey) return filtered;
    const col = columns.find(c => c.key === sortKey);
    return [...filtered].sort((a, b) => {
      let va = a[sortKey] ?? '';
      let vb = b[sortKey] ?? '';
      if (col?.type === 'number' || col?.type === 'currency') {
        va = Number(va) || 0;
        vb = Number(vb) || 0;
        return sortDir === 'asc' ? va - vb : vb - va;
      }
      if (col?.type === 'date') {
        va = va ? new Date(va).getTime() : 0;
        vb = vb ? new Date(vb).getTime() : 0;
        return sortDir === 'asc' ? va - vb : vb - va;
      }
      va = String(va).toLowerCase();
      vb = String(vb).toLowerCase();
      if (va < vb) return sortDir === 'asc' ? -1 : 1;
      if (va > vb) return sortDir === 'asc' ? 1 : -1;
      return 0;
    });
  }, [filtered, sortKey, sortDir, columns, serverPaged]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const pageData = serverPaged ? sorted : sorted.slice(safePage * pageSize, (safePage + 1) * pageSize);
  // Totals include every filtered row, independently of the visible page.
  const sumColumns = visibleColumns.filter(col => col.sum);
  const showTotals = !serverPaged && sumColumns.length > 0 && sorted.length > 0;
  const totals = useMemo(() => Object.fromEntries(sumColumns.map(col => [col.key, sumValue(sorted, col)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sorted, sumColumns.map(col => `${col.key}:${col.sum}`).join('|')]);
  const startRow = sorted.length === 0 ? 0 : safePage * pageSize + 1;
  const endRow = Math.min((safePage + 1) * pageSize, sorted.length);

  // CSV export
  const exportCsv = useCallback(async () => {
    if (exporting) return;
    setExporting(true);
    setExportError('');
    try {
      // A server page supplies only the visible slice; its loader owns the
      // complete selection and enrichment. A failed loader never falls back.
      const exportData = loadExportData ? await loadExportData() : sorted;
      if (!Array.isArray(exportData)) throw new Error('Exportdaten konnten nicht geladen werden.');
      const csv = buildCsv(visibleColumns, exportData);
      const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      try {
        const a = document.createElement('a');
        a.href = url;
        a.download = `${(title || 'export').replace(/\s+/g, '_')}.csv`;
        a.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (error) {
      setExportError(`CSV-Export fehlgeschlagen. ${error?.message || 'Bitte erneut versuchen.'}`);
    } finally {
      setExporting(false);
    }
  }, [sorted, visibleColumns, title, loadExportData, exporting]);

  // The global search's "Neue Buchung" and Alt+N ask the page for its New form (utils/newEntry).
  const addRef = useRef(onAdd);
  addRef.current = onAdd;
  useEffect(() => {
    // a request may carry values the New form starts with (onAdd(prefill))
    const answer = event => {
      if (!addRef.current || event.defaultPrevented) return;
      event.preventDefault();
      addRef.current(event.detail || undefined);
    };
    window.addEventListener(NEW_ENTRY_EVENT, answer);
    const held = addRef.current ? takeNewEntry(pathname) : null;
    if (held) addRef.current(held.prefill || undefined);
    return () => window.removeEventListener(NEW_ENTRY_EVENT, answer);
  }, [pathname]);

  useEffect(() => {
    if (!showColMenu) return;
    // A popover is not a modal: focus the first available control, then
    // allow Tab to leave it normally. Escape returns focus to its opener.
    const menu = colMenuRef.current;
    (menu?.querySelector('input[type="checkbox"]:not(:disabled)') || menu)?.focus();
    const close = event => {
      if (event.key !== 'Escape' ||
          !(menu?.contains(event.target) || colToggleRef.current?.contains(event.target))) return;
      event.preventDefault();
      event.stopPropagation();
      setShowColMenu(false);
      colToggleRef.current?.focus();
    };
    document.addEventListener('keydown', close);
    return () => document.removeEventListener('keydown', close);
  }, [showColMenu]);

  // Unique values for select filters
  const selectOptions = useMemo(() => {
    const opts = {};
    for (const col of columns) {
      if (col.filterType === 'select') {
        const vals = new Set(data.map(r => r[col.key]).filter(v => v != null && v !== ''));
        opts[col.key] = [...vals].sort((a, b) => String(a).localeCompare(String(b), 'de', { numeric: true }));
      }
    }
    return opts;
  }, [columns, data]);

  const hasActiveFilters = !serverPaged && columns.some(col => {
    if (!col.filterType) return false;
    const v = columnFilters[col.key];
    return Array.isArray(v) ? v.some(part => part !== '') : v != null && v !== '';
  });

  const hasActions = Boolean(onEdit || onDelete || rowActions);
  const colSpan = visibleColumns.length + (hasActions ? 1 : 0) + (selectable ? 1 : 0);

  // The selection follows what the list shows: rows that left it (deleted, or hidden by the search
  // or a filter) are not acted on, so nothing invisible is changed.
  const rowsById = useMemo(() => new Map(sorted.map(row => [row.id, row])), [sorted]);
  const selectedRows = [...selectedIds].map(id => rowsById.get(id)).filter(Boolean);
  const pageIds = pageData.map(row => row.id);
  const pageSelected = pageIds.length > 0 && pageIds.every(id => selectedIds.has(id));
  const pageSomeSelected = pageIds.some(id => selectedIds.has(id));
  const toggleRow = (row, event) => {
    if (bulkRunning) return;
    // Shift+click selects or clears the whole range since the last box on this page.
    const from = event?.shiftKey && lastToggled.current != null ? pageIds.indexOf(lastToggled.current) : -1;
    const to = pageIds.indexOf(row.id);
    const range = from >= 0 && to >= 0 ? pageIds.slice(Math.min(from, to), Math.max(from, to) + 1) : [row.id];
    const select = !selectedIds.has(row.id);
    lastToggled.current = row.id;
    if (selectedIds.size === 0) setBulkReport(null);
    setSelectedIds(current => {
      const next = new Set(current);
      range.forEach(id => (select ? next.add(id) : next.delete(id)));
      return next;
    });
  };
  const togglePage = () => {
    if (bulkRunning) return;
    if (selectedIds.size === 0) setBulkReport(null);
    setSelectedIds(current => {
      const next = new Set(current);
      pageIds.forEach(id => (pageSelected ? next.delete(id) : next.add(id)));
      return next;
    });
  };
  const bulkWords = {
    region: tr('comp.dataTable.bulk.region', 'Auswahl'),
    selected: n => tr('comp.dataTable.bulk.selected', '{{count}} ausgewählt').replace('{{count}}', n),
    selectAll: n => tr('comp.dataTable.bulk.selectAll', 'Alle {{count}} Treffer auswählen').replace('{{count}}', n),
    clear: tr('comp.dataTable.bulk.clear', 'Auswahl aufheben'),
    applies: n => tr('comp.dataTable.bulk.applies', 'Betrifft {{count}} der ausgewählten Einträge').replace('{{count}}', n),
    progress: r => `${r.label}: ${r.done} / ${r.count} …`,
    report: r => [
      tr('comp.dataTable.bulk.done', '{{label}}: {{count}} erledigt').replace('{{label}}', r.label).replace('{{count}}', r.succeeded),
      r.failed.length ? tr('comp.dataTable.bulk.failed', '{{count}} fehlgeschlagen').replace('{{count}}', r.failed.length) : null,
      r.skipped ? tr('comp.dataTable.bulk.skipped', '{{count}} nicht betroffen').replace('{{count}}', r.skipped) : null,
    ].filter(Boolean).join(' · '),
    more: n => tr('comp.dataTable.bulk.more', 'und {{count}} weitere').replace('{{count}}', n),
    dismiss: tr('ui.buttons.close', 'Schließen'),
    rowName: row => (rowName ? rowName(row) : String(row[visibleColumns[0]?.key] ?? row.id)),
  };
  const hasColumnFilters = !serverPaged && columns.some(c => c.filterType);
  // Show *every* active filter, including filters of columns that a saved
  // view currently hides. Otherwise a row can disappear for no visible reason.
  const activeColumnFilters = serverPaged ? [] : columns.flatMap(col => {
    const value = columnFilters[col.key];
    const active = Array.isArray(value) ? value.some(part => part !== '') : value != null && value !== '';
    if (!active) return [];
    const description = Array.isArray(value)
      ? [value[0] ? `${tr('comp.dataTable.rangeStart', 'ab')} ${value[0]}` : null,
        value[1] ? `${tr('comp.dataTable.rangeEnd', 'bis')} ${value[1]}` : null].filter(Boolean).join(' · ')
      : String(codeLabel(value));
    return [{ key: col.key, label: plainLabel(col.label), description }];
  });
  const activeFilterCount = activeColumnFilters.length;
  const removeColumnFilter = key => {
    setColumnFilters(current => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    setPage(0);
    filterToggleRef.current?.focus();
  };
  const clearTableFilters = () => {
    setSearch(''); setColumnFilters({}); setPage(0);
    if (new URLSearchParams(routeSearch ?? window.location.search).has('focus_id')) clearFocusedRow?.();
  };

  return (
    <div className={`data-table-wrapper data-table-workspace${hideTitle ? ' table-title-hidden' : ''}`}>
      <div className="table-header">
        <h2 id={titleId} className={hideTitle ? 'sr-only' : undefined}>{title}</h2>
        <div className="table-actions">
          {!serverPaged && <input
            ref={searchInputRef}
            type="text"
            aria-label={`${title || 'Tabelle'} durchsuchen`}
            placeholder={`${t('ui.form.search')}...`}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0); }}
            className="search-input"
          />}
          <div className="table-btn-group">
            {hasColumnFilters && (
              <button type="button" ref={filterToggleRef} onClick={() => setShowFilters(v => !v)} aria-pressed={showFilters || hasActiveFilters}
                      className={`btn btn-sm ${showFilters || hasActiveFilters ? 'btn-primary-soft' : 'btn-secondary'}`}>
                {t('ui.buttons.filter')}{activeFilterCount ? ` (${activeFilterCount})` : ''}
              </button>
            )}
            {hasActiveFilters && (
              <button type="button" onClick={() => { setColumnFilters({}); setPage(0); }} className="btn btn-sm btn-ghost"
                      aria-label={tr('comp.dataTable.clearFilter', 'Spaltenfilter zurücksetzen')}
                      title={tr('comp.dataTable.clearFilter', 'Spaltenfilter zurücksetzen')}>
                ✕
              </button>
            )}
            <div className="col-menu-wrapper">
              <button type="button" ref={colToggleRef} aria-controls={showColMenu ? `${titleId}-columns` : undefined}
                onClick={() => setShowColMenu(value => !value)} aria-expanded={showColMenu} className="btn btn-sm btn-secondary">
                {t('ui.table.adjustColumns')}
              </button>
              {showColMenu && (
                <>
                  <div className="col-menu-backdrop" onClick={() => setShowColMenu(false)} />
                  <div id={`${titleId}-columns`} ref={colMenuRef}
                    role="group" aria-label={tr('ui.table.adjustColumns', 'Spaltenauswahl')}
                    tabIndex={-1} className="col-menu-dropdown"
                    onBlur={event => {
                      if (!event.currentTarget.contains(event.relatedTarget) &&
                          event.relatedTarget !== colToggleRef.current) setShowColMenu(false);
                    }}>
                    {columns.map(col => (
                      <label key={col.key} className="col-menu-item">
                        <input
                          type="checkbox"
                          checked={!hiddenCols[col.key]}
                          disabled={!hiddenCols[col.key] && visibleColumns.length === 1}
                          title={!hiddenCols[col.key] && visibleColumns.length === 1 ? tr('comp.dataTable.keepColumn', 'Mindestens eine Spalte muss sichtbar bleiben') : undefined}
                          onChange={() => toggleColumn(col.key)}
                        />
                        {col.label}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
            <button onClick={exportCsv} disabled={exporting} aria-busy={exporting}
                    className="btn btn-sm btn-secondary">{exporting ? 'CSV …' : 'CSV'}</button>
            {onAdd && !hideAddButton && (
              <button onClick={() => onAdd()} className="btn btn-primary" data-table-add="">
                <PlusIcon size={16} /> {addLabel || t('ui.buttons.new')}
              </button>
            )}
          </div>
        </div>
      </div>

      {!serverPaged && (search || activeColumnFilters.length > 0) && (
        <div className="table-active-filters" role="group"
             aria-label={tr('comp.dataTable.activeFilters', 'Aktive Tabellenfilter')}>
          <span className="table-filter-summary">{tr('comp.dataTable.activeFilters', 'Aktive Filter')}:</span>
          {search && <button type="button" className="table-filter-chip"
            aria-label={tr('comp.dataTable.removeSearch', 'Suche entfernen')}
            onClick={() => { setSearch(''); setPage(0); searchInputRef.current?.focus(); }}>
            {tr('ui.form.search', 'Suche')}: {search}<span aria-hidden="true">×</span>
          </button>}
          {activeColumnFilters.map(item => (
            <button type="button" key={item.key} className="table-filter-chip"
              aria-label={`${tr('comp.dataTable.removeFilter', 'Filter entfernen')}: ${item.label}`}
              title={`${tr('comp.dataTable.removeFilter', 'Filter entfernen')}: ${item.label}`}
              onClick={() => removeColumnFilter(item.key)}>
              {item.label}: {item.description}<span aria-hidden="true">×</span>
            </button>
          ))}
        </div>
      )}
      {(!serverPaged || onApplyView) && <NamedViews context={viewContext} config={namedConfig} onApply={applyView} anchor={viewAnchor} />}
      {!serverPaged && new URLSearchParams(routeSearch ?? window.location.search).has('focus_id') && <p role="status">Ausgewählter Vorgang
        {clearFocusedRow && <button type="button" className="btn btn-sm btn-ghost" onClick={clearFocusedRow}>Alle Vorgänge anzeigen</button>}</p>}
      {exportError && <p className="error-message" role="alert">{exportError}</p>}
      {selectable && (selectedRows.length > 0 || bulkReport || bulkRunning) && (
        <BulkBar rows={selectedRows} report={bulkReport} setReport={setBulkReport} onRunningChange={setBulkRunning}
          sums={columns.filter(col => col.sum).map(col => ({ label: plainLabel(col.label), value: sumLabel(col, sumValue(selectedRows, col)) }))} total={sorted.length} allSelected={selectedRows.length >= sorted.length}
          actions={bulkActions} words={bulkWords}
          onSelectAll={() => setSelectedIds(new Set(sorted.map(row => row.id)))}
          onClear={() => setSelectedIds(new Set())}
          // rows that worked leave the selection; failed ones stay selected for another try
          onFinished={({ succeeded }) => setSelectedIds(current => {
            const next = new Set(current);
            succeeded.forEach(row => next.delete(row.id));
            return next;
          })} />
      )}

      <NotificationArrival rows={pageData} />
      <div className="table-scroll">
        <table className="data-table" aria-labelledby={title ? titleId : undefined}>
          <thead>
            <tr>
              {selectable && <th className="th-select">
                <input type="checkbox" checked={pageSelected} disabled={bulkRunning} aria-label={tr('comp.dataTable.bulk.selectPage', 'Alle Einträge dieser Seite auswählen')}
                  ref={el => { if (el) el.indeterminate = !pageSelected && pageSomeSelected; }} onChange={togglePage} />
              </th>}
              {visibleColumns.map(col => (
                <th
                  key={col.key}
                  className={[!serverPaged && col.sortable !== false ? 'sortable-th' : '', cellClass(col)].filter(Boolean).join(' ') || undefined}
                  onClick={!serverPaged && col.sortable !== false ? () => handleSort(col.key) : undefined}
                  aria-sort={!serverPaged && col.sortable !== false ? (sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none') : undefined}
                >
                  {!serverPaged && col.sortable !== false ? <button type="button" className="table-sort-button">
                    {plainLabel(col.label)}
                    <span className="sort-indicator" aria-hidden="true">{sortKey === col.key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ' ↕'}</span>
                  </button> :
                  <span className="th-content">
                    {plainLabel(col.label)}
                  </span>}
                </th>
              ))}
              {hasActions && <th className="th-actions"><span className="sr-only">{t('ui.buttons.edit')}</span></th>}
            </tr>
            {/* Column filter row */}
            {hasColumnFilters && (showFilters || hasActiveFilters) && (
              <tr className="filter-row">
                {selectable && <th />}
                {visibleColumns.map(col => (
                  <th key={`f-${col.key}`} className="filter-cell">
                    {col.filterType === 'select' ? (
                      <select
                        aria-label={`${plainLabel(col.label)} ${tr('comp.dataTable.filterBy', 'filtern')}`}
                        value={columnFilters[col.key] || ''}
                        onChange={e => setFilter(col.key, e.target.value || '')}
                        className="filter-select"
                      >
                        <option value="">—</option>
                        {(selectOptions[col.key] || []).map(v => (
                          <option key={String(v)} value={String(v)}>{String(codeLabel(v))}</option>
                        ))}
                      </select>
                    ) : col.filterType === 'dateRange' ? (
                      <div className="filter-date-range">
                        <input
                          type="date"
                          aria-label={`${plainLabel(col.label)}: ${tr('comp.dataTable.filterFrom', 'Von')}`}
                          value={(columnFilters[col.key] || ['', ''])[0]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [e.target.value, cur[1]]);
                          }}
                          className="filter-date"
                          title={tr('comp.dataTable.filterFrom', 'Von')}
                        />
                        <input
                          type="date"
                          aria-label={`${plainLabel(col.label)}: ${tr('comp.dataTable.filterTo', 'Bis')}`}
                          value={(columnFilters[col.key] || ['', ''])[1]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [cur[0], e.target.value]);
                          }}
                          className="filter-date"
                          title={tr('comp.dataTable.filterTo', 'Bis')}
                        />
                      </div>
                    ) : col.filterType === 'numberRange' ? (
                      <div className="filter-number-range">
                        <input
                          type="number"
                          aria-label={`${plainLabel(col.label)}: ${tr('comp.dataTable.filterFrom', 'Von')}`}
                          placeholder={t('comp.dataTable.filterMin') || 'Min'}
                          value={(columnFilters[col.key] || ['', ''])[0]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [e.target.value, cur[1]]);
                          }}
                          className="filter-number"
                        />
                        <input
                          type="number"
                          aria-label={`${plainLabel(col.label)}: ${tr('comp.dataTable.filterTo', 'Bis')}`}
                          placeholder={t('comp.dataTable.filterMax') || 'Max'}
                          value={(columnFilters[col.key] || ['', ''])[1]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [cur[0], e.target.value]);
                          }}
                          className="filter-number"
                        />
                      </div>
                    ) : col.filterType === 'text' ? (
                      <input
                        type="text"
                        aria-label={`${plainLabel(col.label)} ${tr('comp.dataTable.filterBy', 'filtern')}`}
                        placeholder={t('comp.dataTable.filterText') || 'Filter…'}
                        value={columnFilters[col.key] || ''}
                        onChange={e => setFilter(col.key, e.target.value)}
                        className="filter-text"
                      />
                    ) : null}
                  </th>
                ))}
                {hasActions && <th />}
              </tr>
            )}
          </thead>
          <tbody>
            {pageData.length === 0 ? (
              <tr><td colSpan={colSpan} className="table-empty">
                {serverPaged ? t('ui.table.noResults')
                  : data.length === 0 ? (
                    // nothing here (yet): offer the entry right here
                    <div className="table-empty-state">
                      <span>{emptyText || tr('comp.dataTable.empty', 'Keine Einträge vorhanden.')}</span>
                      {onAdd && <button type="button" className="btn btn-primary btn-sm" onClick={() => onAdd()}>
                        <PlusIcon size={14} /> {tr('comp.dataTable.addEntry', 'Neuen Eintrag anlegen')}
                      </button>}
                    </div>
                  ) : (
                    // the search or a filter hides every row: one click shows them again
                    <div className="table-empty-state">
                      <span>{tr('comp.dataTable.noMatches', 'Keine Treffer für diese Suche oder diese Filter.')}</span>
                      <button type="button" className="btn btn-secondary btn-sm"
                        onClick={clearTableFilters}>
                        {tr('comp.dataTable.resetSearch', 'Suche und Filter zurücksetzen')}
                      </button>
                    </div>
                  )}
              </td></tr>
            ) : (
              pageData.map(row => (
                <tr key={row.id} onClick={event => {
                  markRow(row);
                  // A link/button inside the row owns its action. Calling both
                  // would navigate twice and make Back reopen the same record.
                  if (!event.target?.closest?.('a, button, input, select, textarea, summary, [role="button"], [role="link"], [contenteditable]:not([contenteditable="false"])')) onRowClick?.(row);
                }} aria-selected={selectable ? selectedIds.has(row.id) : undefined}
                  className={[onRowClick ? 'clickable-row' : '', selectedIds.has(row.id) ? 'row-selected' : '', rowMark === String(row.id) ? 'workspace-row-mark' : ''].filter(Boolean).join(' ') || undefined}
                  style={onRowClick ? { cursor: 'pointer' } : undefined}>
                  {selectable && <td className="td-select" onClick={e => e.stopPropagation()}>
                    <input type="checkbox" checked={selectedIds.has(row.id)} disabled={bulkRunning} onChange={() => {}}
                      onClick={e => toggleRow(row, e)} aria-label={`${tr('comp.dataTable.bulk.selectRow', 'Auswählen')}: ${bulkWords.rowName(row)}`} />
                  </td>}
                  {visibleColumns.map(col => (
                    <td key={col.key} className={cellClass(col)}>
                      {cellContent(col, row)}
                    </td>
                  ))}
                  {hasActions && (
                    <td className="action-cell" onClick={e => e.stopPropagation()}>
                      {rowActions?.(row).map(action => (
                        <button key={action.label} onClick={event => action.onClick(row, event)} className="btn btn-sm btn-ghost"
                                aria-label={action.label} title={action.label}>
                          {action.icon}
                        </button>
                      ))}
                      {onEdit && (
                        <button onClick={() => { markRow(row); onEdit(row); }} className="btn btn-sm btn-ghost" aria-label={t('ui.buttons.edit')} title={t('ui.buttons.edit')}>
                          <EditIcon size={15} />
                        </button>
                      )}
                      {onDelete && (
                        <button onClick={() => onDelete(row)} className="btn btn-sm btn-ghost" aria-label={t('ui.buttons.delete')} title={t('ui.buttons.delete')} style={{ color: 'var(--color-danger)' }}>
                          <TrashIcon size={15} />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
          {showTotals && (
            <tfoot>
              <tr className="table-totals">
                {selectable && <td />}
                {visibleColumns.map((col, index) => (
                  <td key={col.key} className={cellClass(col)}>
                    {col.sum ? sumLabel(col, totals[col.key])
                      : index === 0 ? tr('comp.dataTable.total', 'Summe ({{count}})').replace('{{count}}', sorted.length) : null}
                  </td>
                ))}
                {hasActions && <td />}
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {!serverPaged && sorted.length > 0 && (
      <div className="table-footer">
        <div className="table-footer-info">
          {`${startRow}–${endRow} / ${sorted.length}`}
          {filtered.length !== data.length && ` (${data.length})`}
        </div>
        <div className="table-footer-controls">
          <select
            aria-label="Zeilen pro Seite"
            value={pageSize}
            onChange={e => { setPageSize(Number(e.target.value)); setPage(0); }}
            className="page-size-select"
          >
            {PAGE_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="pagination-btns" role="navigation" aria-label={t('ui.table.pagination') || 'Pagination'}>
            <button disabled={safePage === 0} onClick={() => setPage(0)} className="btn btn-sm btn-secondary" aria-label={t('ui.table.firstPage') || 'First page'}>{'\u00AB'}</button>
            <button disabled={safePage === 0} onClick={() => setPage(p => p - 1)} className="btn btn-sm btn-secondary" aria-label={t('ui.table.previousPage') || 'Previous page'}>{'\u2039'}</button>
            <span className="page-indicator" aria-current="page">{safePage + 1} / {totalPages}</span>
            <button disabled={safePage >= totalPages - 1} onClick={() => setPage(p => p + 1)} className="btn btn-sm btn-secondary" aria-label={t('ui.table.nextPage') || 'Next page'}>{'\u203A'}</button>
            <button disabled={safePage >= totalPages - 1} onClick={() => setPage(totalPages - 1)} className="btn btn-sm btn-secondary" aria-label={t('ui.table.lastPage') || 'Last page'}>{'\u00BB'}</button>
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
