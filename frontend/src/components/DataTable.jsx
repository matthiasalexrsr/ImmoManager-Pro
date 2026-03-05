import { useState, useMemo, useCallback } from 'react';
import { PlusIcon, EditIcon, TrashIcon } from './Icons';
import { useTranslation } from '../i18n';

const PAGE_SIZES = [10, 25, 50, 100];

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
          return val && String(val).toLowerCase().includes(q);
        })
      );
    }

    for (const col of columns) {
      const fv = columnFilters[col.key];
      if (!fv) continue;
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
          return val && String(val).toLowerCase().includes(q);
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
    const headers = visibleColumns.map(c => c.label);
    const rows = sorted.map(row =>
      visibleColumns.map(col => {
        const v = row[col.key];
        const s = v == null ? '' : String(v);
        return s.includes(',') || s.includes('"') || s.includes('\n')
          ? `"${s.replace(/"/g, '""')}"` : s;
      })
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
        const vals = new Set(data.map(r => r[col.key]).filter(Boolean));
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
    <div className="data-table-wrapper">
      <div className="table-header">
        <h2>{title}</h2>
        <div className="table-actions">
          <input
            type="text"
            placeholder={t('comp.dataTable.search')}
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(0); }}
            className="search-input"
          />
          <div className="table-btn-group">
            {hasActiveFilters && (
              <button onClick={() => { setColumnFilters({}); setPage(0); }} className="btn btn-sm btn-secondary">
                {t('comp.dataTable.clearFilter')}
              </button>
            )}
            <div className="col-menu-wrapper">
              <button onClick={() => setShowColMenu(!showColMenu)} className="btn btn-sm btn-secondary">
                {t('comp.dataTable.columns')}
              </button>
              {showColMenu && (
                <>
                  <div className="col-menu-backdrop" onClick={() => setShowColMenu(false)} />
                  <div className="col-menu-dropdown">
                    {columns.map(col => (
                      <label key={col.key} className="col-menu-item">
                        <input
                          type="checkbox"
                          checked={!hiddenCols[col.key]}
                          onChange={() => setHiddenCols(prev => ({ ...prev, [col.key]: !prev[col.key] }))}
                        />
                        {col.label}
                      </label>
                    ))}
                  </div>
                </>
              )}
            </div>
            <button onClick={exportCsv} className="btn btn-sm btn-secondary">{t('comp.dataTable.csv')}</button>
            {onAdd && (
              <button onClick={onAdd} className="btn btn-primary">
                <PlusIcon size={16} /> {t('comp.dataTable.new')}
              </button>
            )}
          </div>
        </div>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {visibleColumns.map(col => (
                <th
                  key={col.key}
                  className={col.sortable !== false ? 'sortable-th' : ''}
                  onClick={() => col.sortable !== false && handleSort(col.key)}
                >
                  <span className="th-content">
                    {col.label}
                    {col.sortable !== false && (
                      <span className="sort-indicator">
                        {sortKey === col.key ? (sortDir === 'asc' ? ' \u25B2' : ' \u25BC') : ''}
                      </span>
                    )}
                  </span>
                </th>
              ))}
              {(onEdit || onDelete) && <th className="th-actions">{t('comp.dataTable.actions')}</th>}
            </tr>
            {/* Column filter row */}
            {columns.some(c => c.filterType) && (
              <tr className="filter-row">
                {visibleColumns.map(col => (
                  <th key={`f-${col.key}`} className="filter-cell">
                    {col.filterType === 'select' ? (
                      <select
                        value={columnFilters[col.key] || ''}
                        onChange={e => setFilter(col.key, e.target.value || '')}
                        className="filter-select"
                      >
                        <option value="">{t('comp.dataTable.all')}</option>
                        {(selectOptions[col.key] || []).map(v => (
                          <option key={v} value={v}>{v}</option>
                        ))}
                      </select>
                    ) : col.filterType === 'dateRange' ? (
                      <div className="filter-date-range">
                        <input
                          type="date"
                          value={(columnFilters[col.key] || ['', ''])[0]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [e.target.value, cur[1]]);
                          }}
                          className="filter-date"
                          title={t('comp.dataTable.filterFrom')}
                        />
                        <input
                          type="date"
                          value={(columnFilters[col.key] || ['', ''])[1]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [cur[0], e.target.value]);
                          }}
                          className="filter-date"
                          title={t('comp.dataTable.filterTo')}
                        />
                      </div>
                    ) : col.filterType === 'numberRange' ? (
                      <div className="filter-number-range">
                        <input
                          type="number"
                          placeholder={t('comp.dataTable.filterMin')}
                          value={(columnFilters[col.key] || ['', ''])[0]}
                          onChange={e => {
                            const cur = columnFilters[col.key] || ['', ''];
                            setFilter(col.key, [e.target.value, cur[1]]);
                          }}
                          className="filter-number"
                        />
                        <input
                          type="number"
                          placeholder={t('comp.dataTable.filterMax')}
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
                        placeholder={t('comp.dataTable.filterText')}
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
              <tr><td colSpan={colSpan} className="table-empty">
                {data.length === 0 ? t('comp.dataTable.noEntries') : t('comp.dataTable.noEntriesFiltered')}
              </td></tr>
            ) : (
              pageData.map(row => (
                <tr key={row.id} onClick={() => onRowClick?.(row)} className={onRowClick ? 'clickable-row' : ''}>
                  {visibleColumns.map(col => (
                    <td key={col.key} className={col.align === 'right' ? 'text-right' : ''}>
                      {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '\u2014')}
                    </td>
                  ))}
                  {(onEdit || onDelete) && (
                    <td className="action-cell" onClick={e => e.stopPropagation()}>
                      {onEdit && (
                        <button onClick={() => onEdit(row)} className="btn btn-sm btn-ghost" title={t('comp.dataTable.edit')}>
                          <EditIcon size={15} />
                        </button>
                      )}
                      {onDelete && (
                        <button onClick={() => onDelete(row)} className="btn btn-sm btn-ghost" title={t('comp.dataTable.delete')} style={{ color: 'var(--color-danger)' }}>
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
        <div className="table-footer-info">
          {t('comp.dataTable.showing', { start: startRow, end: endRow, total: sorted.length })}
          {filtered.length !== data.length && ` ${t('comp.dataTable.totalFiltered', { total: data.length })}`}
        </div>
        <div className="table-footer-controls">
          <select
            value={pageSize}
            onChange={e => { setPageSize(Number(e.target.value)); setPage(0); }}
            className="page-size-select"
          >
            {PAGE_SIZES.map(s => <option key={s} value={s}>{s} {t('comp.dataTable.perPage')}</option>)}
          </select>
          <div className="pagination-btns">
            <button disabled={safePage === 0} onClick={() => setPage(0)} className="btn btn-sm btn-secondary">{'\u00AB'}</button>
            <button disabled={safePage === 0} onClick={() => setPage(p => p - 1)} className="btn btn-sm btn-secondary">{'\u2039'}</button>
            <span className="page-indicator">{safePage + 1} / {totalPages}</span>
            <button disabled={safePage >= totalPages - 1} onClick={() => setPage(p => p + 1)} className="btn btn-sm btn-secondary">{'\u203A'}</button>
            <button disabled={safePage >= totalPages - 1} onClick={() => setPage(totalPages - 1)} className="btn btn-sm btn-secondary">{'\u00BB'}</button>
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
