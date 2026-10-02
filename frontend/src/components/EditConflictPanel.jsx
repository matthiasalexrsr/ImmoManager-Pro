import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import { snapshotRevision } from '../editRevision';
import { useTranslation } from '../i18n';
import './EditConflictPanel.css';

function comparable(value, field) {
  if (value === '' || value == null) return null;
  if (field.type === 'number') return Number(value);
  return Array.isArray(value) ? JSON.stringify(value) : String(value);
}

function display(value, field) {
  if (value === '' || value == null) return '—';
  if (Array.isArray(value)) return value.map(item => display(item, field)).join(', ');
  return field.options?.find(option => String(option.value) === String(value))?.label ?? String(value);
}

export default function EditConflictPanel({ error, fields, original, draft, onReconcile }) {
  const { t } = useTranslation();
  const [current, setCurrent] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState(null);
  const [choices, setChoices] = useState({});
  const request = useRef(null);
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current += 1; request.current?.abort(); }, []);

  const inspect = async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const ticket = ++sequence.current;
    setLoading(true);
    setLoadError(null);
    try {
      const record = await api.get(error.resourcePath, { signal: controller.signal });
      if (controller.signal.aborted || ticket !== sequence.current) return;
      if (!snapshotRevision(record)) throw new Error(t('editConflict.missingRevision'));
      setCurrent(record);
      setChoices({});
    } catch (failure) {
      if (failure.name === 'AbortError' || controller.signal.aborted || ticket !== sequence.current) return;
      setLoadError(failure.statusCode === 404 ? t('editConflict.deleted') : failure.message || t('editConflict.loadFailed'));
      setCurrent(null);
    } finally {
      if (!controller.signal.aborted && ticket === sequence.current) setLoading(false);
    }
  };

  const changes = current ? fields.map(field => {
    const mineChanged = comparable(draft[field.key], field) !== comparable(original?.[field.key], field);
    const serverChanged = comparable(current[field.key], field) !== comparable(original?.[field.key], field);
    const different = comparable(draft[field.key], field) !== comparable(current[field.key], field);
    return { field, mineChanged, serverChanged, collision: mineChanged && serverChanged && different };
  }) : [];
  const unresolved = changes.some(({ field, collision }) => collision && !choices[field.key]);

  const reconcile = () => {
    if (!current || unresolved || loading) return;
    const values = {};
    changes.forEach(({ field, mineChanged }) => {
      values[field.key] = choices[field.key] === 'server' || !mineChanged ? current[field.key] ?? '' : draft[field.key];
    });
    onReconcile(values, current);
  };

  return <section className="edit-conflict-panel" aria-label={t('editConflict.title')}>
    <h4>{t('editConflict.title')}</h4>
    <p>{t('editConflict.preserved')}</p>
    <button type="button" className="btn btn-secondary" onClick={inspect} disabled={loading || !error.resourcePath}>
      {loading ? t('editConflict.loading') : current ? t('editConflict.refresh') : t('editConflict.inspect')}
    </button>
    {loadError && <p role="alert" className="edit-conflict-load-error">{loadError}</p>}
    {current && <>
      <p>{t('editConflict.explanation')}</p>
      <div className="edit-conflict-fields">
        {changes.filter(change => change.mineChanged || change.serverChanged).map(({ field, collision }) => <div className="edit-conflict-field" key={field.key}>
          <strong>{field.label || field.key}</strong>
          <dl><div><dt>{t('editConflict.current')}</dt><dd>{display(current[field.key], field)}</dd></div>
            <div><dt>{t('editConflict.draft')}</dt><dd>{display(draft[field.key], field)}</dd></div></dl>
          {collision && <label>{t('editConflict.choose', { field: field.label || field.key })}
            <select aria-label={t('editConflict.choose', { field: field.label || field.key })} value={choices[field.key] || ''}
              onChange={event => setChoices(previous => ({ ...previous, [field.key]: event.target.value }))}>
              <option value="">{t('editConflict.choosePlaceholder')}</option>
              <option value="draft">{t('editConflict.keepDraft')}</option><option value="server">{t('editConflict.useCurrent')}</option>
            </select></label>}
        </div>)}
      </div>
      <button type="button" className="btn btn-primary" onClick={reconcile} disabled={unresolved || loading}>{t('editConflict.reconcile')}</button>
      <small>{t('editConflict.noAutoSave')}</small>
    </>}
  </section>;
}
