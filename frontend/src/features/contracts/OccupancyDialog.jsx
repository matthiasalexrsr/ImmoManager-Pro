import { useCallback, useEffect, useState } from 'react';
import { api } from '../../api';
import { useTranslation } from '../../i18n';
import { formatDate } from '../../utils/format';

/**
 * Dated occupants of a contract: from which day how many persons live in the flat.
 * The person key of the utility statement counts person-days from these entries;
 * before the first entry the contract's household size applies.
 */
export default function OccupancyDialog({ contract, onClose }) {
  const { t } = useTranslation();
  const [entries, setEntries] = useState(null);
  const [form, setForm] = useState({ valid_from: '', persons: '', notes: '' });
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const path = `/contracts/${contract.id}/occupancies`;

  const load = useCallback(async () => {
    try {
      const list = await api.get(path);
      setEntries(Array.isArray(list) ? list : []);
    } catch (err) {
      setError(err.message);
      setEntries([]);
    }
  }, [path]);

  useEffect(() => { load(); }, [load]);

  const add = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.post(path, {
        contract_id: contract.id,
        valid_from: form.valid_from,
        persons: Number(form.persons),
        notes: form.notes || null,
      });
      setForm({ valid_from: '', persons: '', notes: '' });
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entry) => {
    setError(null);
    try {
      await api.del(`${path}/${entry.id}`);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const base = contract.persons ?? null;
  return (
    <div className="modal-overlay" onClick={onClose} role="presentation">
      <div className="modal modal-wide" role="dialog" aria-modal="true" aria-label={t('tenantsContracts.contracts.occupants.title')}
        onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h2>{t('tenantsContracts.contracts.occupants.title')} {contract.contract_number}</h2>
          <button onClick={onClose} className="btn-close" aria-label={t('tenantsContracts.contracts.occupants.close')}>✕</button>
        </div>
        <div className="modal-body">
          <p className="text-muted">
            {t('tenantsContracts.contracts.occupants.intro', {
              persons: base === null ? t('tenantsContracts.contracts.occupants.unknown') : base,
              start: formatDate(contract.start_date),
            })}
          </p>
          {error && <div className="alert-error" role="alert">{error}</div>}
          {entries === null ? <p role="status">{t('tenantsContracts.contracts.occupants.loading')}</p> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>{t('tenantsContracts.contracts.occupants.validFrom')}</th>
                  <th className="text-right">{t('tenantsContracts.contracts.occupants.persons')}</th>
                  <th>{t('tenantsContracts.contracts.occupants.notes')}</th>
                  <th aria-label={t('tenantsContracts.contracts.occupants.actions')}></th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 && (
                  <tr><td colSpan={4} className="text-muted">{t('tenantsContracts.contracts.occupants.empty')}</td></tr>
                )}
                {entries.map(entry => (
                  <tr key={entry.id}>
                    <td>{formatDate(entry.valid_from)}</td>
                    <td className="text-right td-num">{entry.persons}</td>
                    <td>{entry.notes || ''}</td>
                    <td>
                      <button type="button" className="btn btn-sm btn-secondary" onClick={() => remove(entry)}>
                        {t('tenantsContracts.contracts.occupants.remove')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <form onSubmit={add} style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginTop: '0.75rem', alignItems: 'flex-end' }}>
            <label>
              {t('tenantsContracts.contracts.occupants.validFrom')}
              <input type="date" required value={form.valid_from} min={contract.start_date}
                max={contract.end_date || undefined}
                onChange={e => setForm(f => ({ ...f, valid_from: e.target.value }))} />
            </label>
            <label>
              {t('tenantsContracts.contracts.occupants.persons')}
              <input type="number" required min={0} step={1} value={form.persons}
                onChange={e => setForm(f => ({ ...f, persons: e.target.value }))} />
            </label>
            <label>
              {t('tenantsContracts.contracts.occupants.notes')}
              <input type="text" value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
            </label>
            <button type="submit" className="btn btn-sm btn-primary" disabled={saving}>
              {t('tenantsContracts.contracts.occupants.add')}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
