import { useState, useMemo, useCallback, useEffect, useId, useRef } from 'react';
import { ArrowDown, ArrowUp, ArrowUpDown, Columns3, Download, Search, SearchX, X } from 'lucide-react';
import { useTranslation } from '../i18n';
import { PlusIcon, EditIcon, TrashIcon } from './Icons';
import './SharedComponents.css';

const PAGE_SIZES = [10, 25, 50, 100];
const escapeCsv = value => {
  const text = value == null ? '' : String(value);
  return /[,"\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
};

export default function DataTable({ columns, data, onEdit, onDelete, title, onAdd, onRowClick }) {
  const { t } = useTranslation();
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState(null);
  const [sortDir, setSortDir] = useState('asc');
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(25);
  const [columnFilters, setColumnFilters] = useState({});
  const [hiddenCols, setHiddenCols] = useState({});
  const [showColMenu, setShowColMenu] = useState(false);
  const [rowKeys] = useState(() => ({ keys: new WeakMap(), next: 0 }));
  const columnMenu = useRef(null);
  const columnToggle = useRef(null);
  const searchInput = useRef(null);
  const menuId = useId();

  useEffect(() => {
    if (!showColMenu) return;
    columnMenu.current?.querySelector('input:not(:disabled)')?.focus();
    const closeOutside = event => {
      if (!columnMenu.current?.contains(event.target) && !columnToggle.current?.contains(event.target)) setShowColMenu(false);
    };
    document.addEventListener('mousedown', closeOutside);
    document.addEventListener('focusin', closeOutside);
    return () => {
      document.removeEventListener('mousedown', closeOutside);
      document.removeEventListener('focusin', closeOutside);
    };
  }, [showColMenu]);

  const rowKey = row => {
    if (row.id !== undefined && row.id !== null) return `id:${row.id}`;
    if (!rowKeys.keys.has(row)) rowKeys.keys.set(row, `row:${rowKeys.next++}`);
    return rowKeys.keys.get(row);
  };
  const resetFilters = () => { setSearch(''); setColumnFilters({}); setPage(0); };

  const setFilter = useCallback((key, value) => {
    setColumnFilters(prev => ({ ...prev, [key]: value }));
    setPage(0);
  }, []);

  // Sort: asc → desc → none
  const handleSort = useCallback((key) => {
    if (sortKey === key) {
      if (sortDir === 'asc') setSortDir('desc');
      else { setSortKey(null); setSortDir('asc'); }
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
    setPage(0);
  }, [sortKey, sortDir]);

  const visibleColumns = useMemo(
    () => columns.filter(col => !hiddenCols[col.key]),
    [columns, hiddenCols]
  );

  // Filter
  const filtered = useMemo(() => {
    let items = data;

    if (search) {
      const q = search.toLowerCase();
      items = items.filter(row =>
        columns.some(col => {
          const val = row[col.key];
          return val != null && String(val).toLowerCase().includes(q);
        })
      );
    }

    for (const col of columns) {
      const fv = columnFilters[col.key];
      if (!fv) continue;
      if (Array.isArray(fv) && fv.every(value => value === '' || value == null)) continue;
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
          if (row[col.key] == null || row[col.key] === '') return false;
          const n = Number(row[col.key]);
          if (isNaN(n)) return false;
          if (min !== '' && n < Number(min)) return false;
          if (max !== '' && n > Number(max)) return false;
          return true;
        });
      } else {
        const q = fv.toLowerCase();
        items = items.filter(row => {
          const val = row[col.key];
          return val != null && String(val).toLowerCase().includes(q);
        });
      }
    }
    return items;
  }, [data, search, columnFilters, columns]);

  // Sort
  const sorted = useMemo(() => {
    if (!sortKey) return filtered;
    const col = columns.find(c => c.key === sortKey);
    return [...filtered].sort((a, b) => {
      let va = a[sortKey] ?? '';
      let vb = b[sortKey] ?? '';
      if (col?.type === 'number' || col?.type === 'currency') {
        const missingA = va === '' || !Number.isFinite(Number(va));
        const missingB = vb === '' || !Number.isFinite(Number(vb));
        if (missingA || missingB) return missingA === missingB ? 0 : missingA ? 1 : -1;
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
  }, [filtered, sortKey, sortDir, columns]);

  // Pagination
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);
  const pageData = sorted.slice(safePage * pageSize, (safePage + 1) * pageSize);
  const startRow = sorted.length === 0 ? 0 : safePage * pageSize + 1;
  const endRow = Math.min((safePage + 1) * pageSize, sorted.length);

  // CSV export
  const exportCsv = useCallback(() => {
    const headers = visibleColumns.map(c => escapeCsv(c.label));
    const rows = sorted.map(row =>
      visibleColumns.map(col => escapeCsv(row[col.key]))
    );
    const csv = [headers.join(','), ...rows.map(r => r.join(','))].join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${(title || 'export').replace(/\s+/g, '_')}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [sorted, visibleColumns, title]);

  // Unique values for select filters
  const selectOptions = useMemo(() => {
    const opts = {};
    for (const col of columns) {
      if (col.filterType === 'select') {
        const vals = new Set(data.map(r => r[col.key]).filter(value => value != null && value !== ''));
        opts[col.key] = [...vals].sort();
      }
    }
    return opts;
  }, [columns, data]);

  const hasActiveFilters = Object.values(columnFilters).some(v => {
    if (Array.isArray(v)) return v.some(x => x !== '');
    return v !== '' && v != null;
  });

  const colSpan = visibleColumns.length + (onEdit || onDelete ? 1 : 0);

  return (
    <div className="data-table-wrapper shared-data-table" onKeyDown={event => {
      if (event.key === 'Enter' && event.target.matches('.shared-table-search input, .filter-row input')) event.preventDefault();
    }}>
      <div className="table-header">
        <h2>{title}</h2>
        <div className="table-actions">
          <div className="shared-table-search"><Search size={16} aria-hidden="true" /><input
            ref={searchInput}
            type="text"
            aria-label={`${t('ui.form.search')} ${title || ''}`.trim()}
            placeholder={`${t('ui.form.search')}...`}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0); }}
            className="search-input"
          />{search && <button type="button" onClick={() => { setSearch(''); setPage(0); searchInput.current?.focus(); }} aria-label={t('ui.table.clearSearch')}><X size={15} aria-hidden="true" /></button>}</div>
          <div className="table-btn-group">
            {hasActiveFilters && (
              <button type="button" onClick={() => { setColumnFilters({}); setPage(0); }} className="btn btn-sm btn-secondary">
                {t('ui.buttons.filter')} ✕
              </button>
            )}
            <div className="col-menu-wrapper">
              <button type="button" ref={columnToggle} aria-expanded={showColMenu} aria-controls={menuId}
                onClick={() => setShowColMenu(!showColMenu)} className="btn btn-sm btn-secondary">
                <Columns3 size={15} aria-hidden="true" />{t('ui.table.adjustColumns')}
              </button>
              {showColMenu && (
                  <div className="col-menu-dropdown" id={menuId} ref={columnMenu} role="group" aria-label={t('ui.table.adjustColumns')}
                    onKeyDown={event => {
                      if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setShowColMenu(false); columnToggle.current?.focus(); }
                    }}>
                    {columns.map(col => (
                      <label key={col.key} className="col-menu-item">
                        <input
                          type="checkbox"
                          checked={!hiddenCols[col.key]}
                          disabled={!hiddenCols[col.key] && visibleColumns.length === 1}
                          onChange={() => setHiddenCols(prev => ({ ...prev, [col.key]: !prev[col.key] }))}
                        />
                        {col.label}
                      </label>
                    ))}
                    <button type="button" className="shared-table-reset-columns" onClick={() => setHiddenCols({})}>{t('ui.table.resetColumns')}</button>
                  </div>
              )}
            </div>
            <button type="button" onClick={exportCsv} className="btn btn-sm btn-secondary"><Download size={15} aria-hidden="true" />CSV</button>
            {onAdd && (
              <button type="button" onClick={onAdd} className="btn btn-primary">
                <PlusIcon size={16} /> {t('ui.buttons.new')}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="table-scroll">
        <table className="data-table" aria-label={title}>
          <thead>
            <tr>
              {visibleColumns.map(col => (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={col.sortable === false ? undefined : sortKey === col.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}
                  className={col.sortable !== false ? 'sortable-th' : ''}
                  onClick={() => col.sortable !== false && handleSort(col.key)}
                >
                  {col.sortable !== false ? <button type="button" className="shared-table-sort">
                    <span>{col.label}</span>
                    {sortKey !== col.key ? <ArrowUpDown size={13} aria-hidden="true" /> : sortDir === 'asc' ? <ArrowUp size={13} aria-hidden="true" /> : <ArrowDown size={13} aria-hidden="true" />}
                  </button> : <span className="th-content">{col.label}</span>}
                </th>
              ))}
              {(onEdit || onDelete) && <th className="th-actions">{t('ui.buttons.edit')}</th>}
            </tr>
            {/* Column filter row */}
            {columns.some(c => c.filterType) && (
              <tr className="filter-row">
                {visibleColumns.map(col => (
                  <th key={`f-${col.key}`} className="filter-cell" role="cell">
                    {col.filterType === 'select' ? (
                      <select
                        aria-label={`${t('ui.buttons.filter')} · ${col.label}`}
                        value={columnFilters[col.key] || ''}
                        onChange={e => setFilter(col.key, e.target.value || '')}
                        className="filter-select"
                      >
                        <option value="">—</option>
                        {(selectOptions[col.key] || []).map(v => (
                          <option key={String(v)} value={v}>{String(v)}</option>
                        ))}
                      </select>
                    ) : col.filterType === 'dateRange' ? (
                      <div className="filter-date-range">
                        <input
                          type="date"
                          aria-label={`${col.label} · ${t('comp.dataTable.filterFrom')}`}
                          value={(columnFilters[col.key] || ['', ''])[0]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [e.target.value, cur[1]]);
                          }}
                          className="filter-date"
                          title={t('comp.dataTable.filterFrom') || 'Von'}
                        />
                        <input
                          type="date"
                          aria-label={`${col.label} · ${t('comp.dataTable.filterTo')}`}
                          value={(columnFilters[col.key] || ['', ''])[1]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [cur[0], e.target.value]);
                          }}
                          className="filter-date"
                          title={t('comp.dataTable.filterTo') || 'Bis'}
                        />
                      </div>
                    ) : col.filterType === 'numberRange' ? (
                      <div className="filter-number-range">
                        <input
                          type="number"
                          aria-label={`${col.label} · ${t('comp.dataTable.filterMin')}`}
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
                          aria-label={`${col.label} · ${t('comp.dataTable.filterMax')}`}
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
                        aria-label={`${t('ui.buttons.filter')} · ${col.label}`}
                        placeholder={t('comp.dataTable.filterText') || 'Filter…'}
                        value={columnFilters[col.key] || ''}
                        onChange={e => setFilter(col.key, e.target.value)}
                        className="filter-text"
                      />
                    ) : null}
                  </th>
                ))}
                {(onEdit || onDelete) && <th />}
              </tr>
            )}
          </thead>
          <tbody>
            {pageData.length === 0 ? (
              <tr><td colSpan={Math.max(1, colSpan)} className="table-empty"><div className="shared-table-empty"><SearchX size={28} strokeWidth={1.4} aria-hidden="true" /><p>{t('ui.table.noResults')}</p>
                <span>{t(search || hasActiveFilters ? 'ui.table.emptyFilteredHint' : 'ui.table.emptyDataHint')}</span>
                {(search || hasActiveFilters) && <button type="button" className="btn btn-sm btn-secondary" onClick={resetFilters}>{t('ui.buttons.reset')}</button>}
              </div></td></tr>
            ) : (
              pageData.map(row => (
                <tr key={rowKey(row)} onClick={event => {
                  if (!event.target.closest('button, a, input, select, textarea, label, summary, [role="button"], [role="link"], [contenteditable="true"]')) onRowClick?.(row);
                }} tabIndex={onRowClick ? 0 : undefined}
                  onKeyDown={event => { if (onRowClick && event.target === event.currentTarget && ['Enter', ' '].includes(event.key)) { event.preventDefault(); onRowClick(row); } }}
                  className={onRowClick ? 'clickable-row' : ''} style={onRowClick ? { cursor: 'pointer' } : undefined}>
                  {visibleColumns.map(col => (
                    <td key={col.key} className={col.align === 'right' || ['number', 'currency'].includes(col.type) ? 'text-right shared-table-number' : ''}>
                      {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '\u2014')}
                    </td>
                  ))}
                  {(onEdit || onDelete) && (
                    <td className="action-cell" onClick={e => e.stopPropagation()}>
                      {onEdit && (
                        <button type="button" onClick={() => onEdit(row)} className="btn btn-sm btn-ghost" aria-label={t('ui.buttons.edit')} title={t('ui.buttons.edit')}>
                          <EditIcon size={15} />
                        </button>
                      )}
                      {onDelete && (
                        <button type="button" onClick={() => onDelete(row)} className="btn btn-sm btn-ghost" aria-label={t('ui.buttons.delete')} title={t('ui.buttons.delete')} style={{ color: 'var(--color-danger)' }}>
                          <TrashIcon size={15} />
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {sorted.length > 0 && (
      <div className="table-footer">
        <div className="table-footer-info" role="status" aria-live="polite">
          {`${startRow}–${endRow} / ${sorted.length}`}
          {filtered.length !== data.length && ` (${data.length})`}
        </div>
        <div className="table-footer-controls">
          <select
            aria-label={t('ui.table.rowsPerPage')}
            value={pageSize}
            onChange={e => { setPageSize(Number(e.target.value)); setPage(0); }}
            className="page-size-select"
          >
            {PAGE_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
          <div className="pagination-btns" role="navigation" aria-label={t('ui.table.pagination') || 'Pagination'}>
            <button type="button" disabled={safePage === 0} onClick={() => setPage(0)} className="btn btn-sm btn-secondary" aria-label={t('ui.table.firstPage') || 'First page'}>{'\u00AB'}</button>
            <button type="button" disabled={safePage === 0} onClick={() => setPage(Math.max(0, safePage - 1))} className="btn btn-sm btn-secondary" aria-label={t('ui.table.previousPage') || 'Previous page'}>{'\u2039'}</button>
            <span className="page-indicator" aria-current="page">{safePage + 1} / {totalPages}</span>
            <button type="button" disabled={safePage >= totalPages - 1} onClick={() => setPage(Math.min(totalPages - 1, safePage + 1))} className="btn btn-sm btn-secondary" aria-label={t('ui.table.nextPage') || 'Next page'}>{'\u203A'}</button>
            <button type="button" disabled={safePage >= totalPages - 1} onClick={() => setPage(totalPages - 1)} className="btn btn-sm btn-secondary" aria-label={t('ui.table.lastPage') || 'Last page'}>{'\u00BB'}</button>
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
