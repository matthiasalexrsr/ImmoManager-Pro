import { useState } from 'react';
import { PlusIcon, EditIcon, TrashIcon } from './Icons';

export default function DataTable({ columns, data, onEdit, onDelete, title, onAdd }) {
  const [search, setSearch] = useState('');

  const filtered = data.filter(row =>
    columns.some(col => {
      const val = row[col.key];
      return val && String(val).toLowerCase().includes(search.toLowerCase());
    })
  );

  return (
    <div className="data-table-wrapper">
      <div className="table-header">
        <h2>{title}</h2>
        <div className="table-actions">
          <input
            type="text"
            placeholder="Suchen..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="search-input"
          />
          {onAdd && (
            <button onClick={onAdd} className="btn btn-primary">
              <PlusIcon size={16} /> Neu
            </button>
          )}
        </div>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map(col => <th key={col.key}>{col.label}</th>)}
              {(onEdit || onDelete) && <th style={{ textAlign: 'right' }}>Aktionen</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={columns.length + 1} className="empty-row">Keine Einträge</td></tr>
            ) : (
              filtered.map(row => (
                <tr key={row.id}>
                  {columns.map(col => (
                    <td key={col.key}>
                      {col.render ? col.render(row[col.key], row) : (row[col.key] ?? '\u2014')}
                    </td>
                  ))}
                  {(onEdit || onDelete) && (
                    <td className="action-cell">
                      {onEdit && (
                        <button onClick={() => onEdit(row)} className="btn btn-sm btn-ghost" title="Bearbeiten">
                          <EditIcon size={15} />
                        </button>
                      )}
                      {onDelete && (
                        <button onClick={() => onDelete(row)} className="btn btn-sm btn-ghost" title="Löschen" style={{ color: 'var(--color-danger)' }}>
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
      <div className="table-footer">{filtered.length} Einträge</div>
    </div>
  );
}
