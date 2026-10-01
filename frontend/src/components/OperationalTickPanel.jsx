import { useEffect, useId, useState } from 'react';
import { api } from '../api';
import useWriteAccess from '../hooks/useWriteAccess';
import { useTranslation } from '../i18n';
import FormModal from './FormModal';

export default function OperationalTickPanel({ onCompleted }) {
  const { t } = useTranslation();
  const { canWrite, requireWrite } = useWriteAccess('/tasks/operational-tick', () => setOpen(false));
  const id = useId();
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [revision, setRevision] = useState(0);
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const text = key => t(`operational.${key}`);
  useEffect(() => {
    const controller = new AbortController();
    api.get('/tasks/operational-status', { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setStatus(data); setLoadError(null); }
    }).catch(error => { if (!controller.signal.aborted) setLoadError(error.message); });
    return () => controller.abort();
  }, [revision]);
  const fields = [
    { key: 'as_of', label: text('asOf'), type: 'date', required: true },
    { key: 'lookback_days', label: text('lookback'), type: 'number', required: true, min: 1, max: 3660, step: 1, default: 366 },
    { key: 'max_items', label: text('limit'), type: 'number', required: true, min: 1, max: 5000, step: 1, default: 500 },
    { key: 'full_catch_up', label: text('catchUp'), type: 'select', required: true, default: 'false',
      options: [{ value: 'false', label: text('oneOpen') }, { value: 'true', label: text('allDue') }], hint: text('catchUpHint') },
  ];
  const run = async values => {
    requireWrite();
    const data = await api.post('/tasks/operational-tick', { ...values, full_catch_up: values.full_catch_up === 'true' });
    if (!Number.isInteger(data?.tasks_created) || !Number.isInteger(data?.calendar_events_created)
      || !Number.isInteger(data?.notifications_generated) || !Array.isArray(data?.warnings)) throw new Error(text('invalidResult'));
    setResult(data);
    onCompleted?.();
  };
  return <section className="panel" aria-labelledby={`${id}-title`} style={{ padding: '1rem', marginBottom: '1rem' }}>
    <h2 id={`${id}-title`}>{text('title')}</h2>
    <p>{text('description')}</p>
    {status && <p>{text(status.automatic_running ? 'automaticRunning' : status.automatic_enabled ? 'automaticStopped' : 'automaticDisabled')}</p>}
    {loadError && <div role="alert">{loadError} <button type="button" className="btn btn-secondary" onClick={() => setRevision(value => value + 1)}>{text('retry')}</button></div>}
    {canWrite && <button type="button" className="btn btn-secondary" onClick={() => setOpen(true)}>{text('run')}</button>}
    {result && <div role="status"><p>{t('operational.result', { tasks: result.tasks_created, events: result.calendar_events_created, notifications: result.notifications_generated })}</p>
      {result.warnings.length > 0 && <ul>{result.warnings.map((warning, index) => <li key={`${warning.source_id}-${index}`}>{warning.error}</li>)}</ul>}
    </div>}
    {open && <FormModal title={text('run')} fields={fields} initial={{ as_of: new Date().toLocaleDateString('sv-SE') }}
      onSave={run} onClose={() => setOpen(false)} saveLabel={text('run')} />}
  </section>;
}
