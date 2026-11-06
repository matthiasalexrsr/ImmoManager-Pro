import { useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useAuth, useCanWrite } from '../../contexts/AuthContext';
import StatusBadge from '../../components/StatusBadge';
import RelatedPageLinks from '../../components/RelatedPageLinks';
import NotificationArrival from '../../components/NotificationArrival';
import { PartyLink } from '../partyWorkspace/PartyWorkspace';
import QuickMessageComposer from '../communication/QuickMessageComposer';
import ReminderPlanner from '../communication/ReminderPlanner';
import { entityHref } from '../../utils/entityLinks';
import { formatDate, formatMoney } from '../../utils/format';
import './contractOverview.css';

// Resolve the record independently of object, status and saved-view filters.
// An empty or failed list response does not establish a direct link's existence.
export default function ContractOverview({ contractId, properties = [], units = [], tenants = [],
  refreshKey = 0, onEdit, canEdit = true, onClose }) {
  const actorId = useAuth()?.user?.id;
  const [response, setResponse] = useState(null);
  const [attempt, setAttempt] = useState(0);
  const [composer, setComposer] = useState(false);
  const [reminder, setReminder] = useState(false);
  const heading = useRef(null);
  const focused = useRef(false);
  const headingId = useId();
  const canWrite = useCanWrite('/contracts');
  const requestKey = JSON.stringify([actorId, contractId, refreshKey, attempt]);
  const current = response?.key === requestKey ? response : null;
  const record = current?.record;

  useEffect(() => {
    const controller = new AbortController();
    const invalidate = () => {
      controller.abort();
      setResponse({ key: requestKey, error: new Error('Die Sitzung wurde geändert. Bitte den Vertrag erneut laden.') });
    };
    window.addEventListener('workspace-owner', invalidate);
    window.addEventListener('workspace-logout', invalidate);
    (async () => {
      const same = api.captureSession();
      const value = await api.get(`/contracts/${encodeURIComponent(contractId)}`, { signal: controller.signal });
      same();
      if (!value || value.id !== contractId) throw new Error('Der Server hat keinen eindeutigen Vertrag geliefert.');
      if (!controller.signal.aborted) setResponse({ key: requestKey, record: value });
    })().catch(error => {
      if (!controller.signal.aborted) setResponse({ key: requestKey, error,
        unavailable: [403, 404].includes(error.statusCode || error.status) });
    });
    return () => {
      controller.abort();
      window.removeEventListener('workspace-owner', invalidate);
      window.removeEventListener('workspace-logout', invalidate);
    };
  }, [contractId, requestKey]);

  useEffect(() => { focused.current = false; }, [actorId]);

  useEffect(() => {
    if (record && !focused.current) { heading.current?.focus(); focused.current = true; }
  }, [record]);

  const close = <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Vertragsübersicht schließen</button>;
  if (!current) return <section className="card contract-overview" aria-label="Vertragsübersicht">
    <p role="status">Vertrag wird geladen …</p>{close}
  </section>;
  if (current.error) return <section className="card contract-overview" aria-label="Vertragsübersicht">
    <div role="alert"><strong>{current.unavailable ? 'Vertrag nicht verfügbar' : 'Vertrag konnte nicht geladen werden'}</strong>
      <p>{current.unavailable ? 'Der Vertrag wurde entfernt oder ist für dieses Konto nicht zugänglich.' : current.error.message}</p>
    </div>
    <div className="contract-overview-actions"><button type="button" className="btn btn-secondary btn-sm"
      onClick={() => setAttempt(value => value + 1)}>Vertrag erneut laden</button>{close}</div>
  </section>;

  const property = properties.find(item => item.id === record.property_id);
  const unit = units.find(item => item.id === record.unit_id);
  const tenant = tenants.find(item => item.id === record.tenant_id);
  const taskQuery = new URLSearchParams();
  if (record.property_id) taskQuery.set('property_id', record.property_id);
  if (record.unit_id) taskQuery.set('unit_id', record.unit_id);
  return <section className="card contract-overview" aria-labelledby={headingId}>
    <div className="contract-overview-heading"><div><p className="contract-overview-eyebrow">Vertragsübersicht</p>
      <h2 id={headingId} ref={heading} tabIndex={-1}>{record.contract_number || 'Mietvertrag'}</h2></div>
      <StatusBadge status={record.status} />
    </div>
    <dl className="contract-overview-facts">
      <div><dt>Immobilie</dt><dd>{record.property_id ? <Link to={entityHref('property', record.property_id)}>{property?.name || 'Immobilienakte öffnen'}</Link> : 'Nicht zugeordnet'}</dd></div>
      <div><dt>Einheit</dt><dd>{record.unit_id ? <Link to={entityHref('unit', record.unit_id)}>{unit?.label || 'Einheitenakte öffnen'}</Link> : 'Nicht zugeordnet'}</dd></div>
      <div><dt>Mietpartei</dt><dd>{record.tenant_id ? <PartyLink tenantId={record.tenant_id}>{tenant?.full_name || 'Parteiakte öffnen'}</PartyLink> : 'Nicht zugeordnet'}</dd></div>
      <div><dt>Vertragsbeginn</dt><dd>{formatDate(record.start_date)}</dd></div>
      <div><dt>Vertragsende</dt><dd>{record.end_date ? formatDate(record.end_date) : 'Unbefristet'}</dd></div>
      <div><dt>Kündigungsfrist</dt><dd>{record.notice_period || 'Nicht hinterlegt'}</dd></div>
      <div><dt>Vereinbarte Kaution</dt><dd>{record.deposit_amount == null ? 'Nicht hinterlegt' : formatMoney(record.deposit_amount)}</dd></div>
      <div><dt>Mietmodell</dt><dd>{{ index: 'Indexmiete', stepped: 'Staffelmiete', fixed: 'Festmiete' }[record.index_rent] || 'Nicht hinterlegt'}</dd></div>
      {record.ledger_start && <div><dt>Mietkonto hier geführt ab</dt><dd>{formatDate(record.ledger_start)}</dd></div>}
      {record.ledger_start && record.carried_balance != null && <div><dt>Übernommener Saldo</dt><dd>{formatMoney(record.carried_balance)}</dd></div>}
    </dl>
    {record.notes && <p className="contract-overview-notes">{record.notes}</p>}
    <RelatedPageLinks items={[
      { to: `/documents?contract_id=${encodeURIComponent(record.id)}`, label: 'Vertragsdokumente' },
      ...(record.tenant_id ? [{ to: entityHref('tenantAccount', record.tenant_id), label: 'Mietkonto der Partei' }] : []),
      ...(taskQuery.size ? [{ to: `/tasks?${taskQuery}`, label: record.unit_id ? 'Aufgaben zur Einheit' : 'Aufgaben zur Immobilie' }] : []),
    ]} />
    <div className="contract-overview-actions">{canWrite && onEdit && <button type="button" className="btn btn-secondary btn-sm"
      disabled={!canEdit} onClick={() => onEdit(record)}>Vertrag bearbeiten</button>}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setComposer(true)}>Nachricht schreiben</button>
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => setReminder(true)}>Erinnerung einstellen</button>{close}</div>
    {composer && <QuickMessageComposer phone={tenant?.phone || ''} email={tenant?.email || ''} recipientName={tenant?.full_name || ''}
      subject={`Mietvertrag ${record.contract_number || ''}`.trim()} sourceKind="contract" sourceId={record.id}
      dueDate={record.end_date} onClose={() => setComposer(false)} />}
    {reminder && <ReminderPlanner sourceKind="contract" sourceId={record.id} sourceTitle={record.contract_number || 'Mietvertrag'}
      dueDate={record.end_date} onClose={() => setReminder(false)} />}
    <NotificationArrival record={record} />
  </section>;
}
