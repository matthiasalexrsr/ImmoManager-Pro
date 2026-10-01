import { useEffect, useId, useRef, useState } from 'react';
import { Download, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import useWriteAccess from '../hooks/useWriteAccess';
import './TenantPrivacySection.css';

const RETAINED_LABELS = {
  contracts: 'Mietverträge', documents: 'Dokumente', deposits: 'Kautionen', receivables: 'Forderungen',
  rent_charges: 'Mietsollstellungen', rent_adjustments: 'Mietanpassungen', handover_protocols: 'Übergabeprotokolle',
  utility_statements: 'Einzelabrechnungen', message_threads: 'Gespräche', billing_settlements: 'Abrechnungsergebnisse',
  bookings: 'Buchungen', messages: 'Nachrichten', meter_readings: 'Zählerstände', payments: 'Zahlungsbelege',
};

export default function TenantPrivacySection({ tenants, onUpdated }) {
  const request = useRef(null);
  const [tenantId, setTenantId] = useState('');
  const [preview, setPreview] = useState(null);
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const id = useId();
  const tenant = tenants.find(row => row.id === tenantId);
  const { canWrite: allowed, isAllowed: hasAccess } = useWriteAccess('/admin', () => {
    request.current?.abort();
    setTenantId(''); setPreview(null); setConfirmation(''); setBusy(false); setError(''); setNotice('');
  });

  useEffect(() => {
    if (!allowed) request.current?.abort();
    return () => request.current?.abort();
  }, [allowed]);

  if (!allowed) return null;

  const selectTenant = event => {
    request.current?.abort();
    setTenantId(event.target.value);
    setPreview(null); setConfirmation(''); setError(''); setNotice(''); setBusy(false);
  };

  const run = async action => {
    if (!hasAccess() || !tenantId || busy) return;
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(''); setNotice('');
    try { await action(controller.signal); }
    catch (failure) { if (!controller.signal.aborted && hasAccess()) setError(failure.message || 'Aktion fehlgeschlagen.'); }
    finally { if (!controller.signal.aborted && hasAccess()) setBusy(false); }
  };

  const download = () => run(async signal => {
    const blob = await api.getBlob(`/admin/dsgvo/tenant/${encodeURIComponent(tenantId)}/export`, { signal });
    if (signal.aborted || !hasAccess()) return;
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = 'mieter-datenauskunft.json';
    document.body.append(anchor); anchor.click(); anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice('Datenauskunft wurde heruntergeladen.');
  });

  const loadPreview = () => run(async signal => {
    const result = await api.get(`/admin/dsgvo/tenant/${encodeURIComponent(tenantId)}/anonymization-preview`, { signal });
    if (signal.aborted || !hasAccess()) return;
    if (!result || result.tenant_id !== tenantId || result.scope !== 'tenant_profile_only' || !result.plan_hash) {
      throw new Error('Ungültige Anonymisierungsvorschau.');
    }
    setPreview(result);
  });

  const anonymize = event => {
    event.preventDefault();
    if (!preview?.can_anonymize || confirmation !== tenant?.full_name) return;
    run(async signal => {
      if (!hasAccess()) return;
      const result = await api.post(`/admin/dsgvo/tenant/${encodeURIComponent(tenantId)}/anonymize`, {
        plan_hash: preview.plan_hash, confirm_tenant_id: tenantId,
      }, { signal });
      if (signal.aborted || !hasAccess()) return;
      if (result?.status !== 'profile_anonymized') throw new Error('Die Anonymisierung wurde nicht bestätigt.');
      setPreview(null); setConfirmation('');
      setNotice('Mieterstammdaten wurden anonymisiert und archiviert. Verknüpfte Unterlagen und Belege bleiben erhalten.');
      onUpdated?.();
    });
  };

  return <details className="tenant-privacy panel">
    <summary><ShieldCheck size={18} aria-hidden="true" /> Datenauskunft und Stammdaten-Anonymisierung</summary>
    <div className="tenant-privacy-body" aria-busy={busy}>
      <p>Die Datenauskunft enthält die Mieterstammdaten und ausdrücklich mit den Mietverträgen verknüpfte Metadaten.
        Datei-Inhalte, gemeinsam genutzte Unterlagen und frei verknüpfte Datensätze sind im Exportumfang ausgewiesen.</p>
      <label htmlFor={`${id}-tenant`}>Mieter auswählen</label>
      <select id={`${id}-tenant`} value={tenantId} onChange={selectTenant} disabled={busy}>
        <option value="">Bitte auswählen</option>
        {tenants.map(row => <option key={row.id} value={row.id}>{row.full_name}{row.archived ? ' · Archiviert' : ''}</option>)}
      </select>
      <div className="tenant-privacy-actions">
        <button type="button" className="btn btn-secondary" onClick={download} disabled={!tenant || busy}>
          <Download size={16} aria-hidden="true" /> Datenauskunft herunterladen</button>
        <button type="button" className="btn btn-secondary" onClick={loadPreview} disabled={!tenant || busy}>
          {preview ? 'Vorschau neu laden' : 'Anonymisierung prüfen'}</button>
      </div>
      {error && <div role="alert" className="alert-error">{error}</div>}
      {notice && <p role="status">{notice}</p>}
      {preview && <form className="tenant-privacy-preview" onSubmit={anonymize}>
        <strong>Geprüfter Umfang: Mieterstammdaten</strong>
        <p>{preview.note}</p>
        <p>Name, Kontakt- und Adressdaten, Zahlungsart, SEPA-Mandatsreferenz und Profilnotizen werden entfernt;
          der Mieter erhält einen anonymisierten Namen und wird archiviert.</p>
        <dl>{Object.entries(preview.retained_collections || {}).filter(([, count]) => count > 0).map(([key, count]) =>
          <div key={key}><dt>{RETAINED_LABELS[key] || 'Weitere verknüpfte Daten'}</dt><dd>{count} Datensätze bleiben gespeichert</dd></div>)}</dl>
        {!preview.can_anonymize ? <p role="status">Es bestehen {preview.active_contracts} aktive Mietverträge.
          Beende diese Verträge vor der Stammdaten-Anonymisierung.</p> : <>
          <label htmlFor={`${id}-confirmation`}>Bestätigung: vollständigen Namen eingeben</label>
          <input id={`${id}-confirmation`} value={confirmation} onChange={event => setConfirmation(event.target.value)}
            autoComplete="off" disabled={busy} aria-describedby={`${id}-confirmation-help`} />
          <small id={`${id}-confirmation-help`}>{tenant?.full_name}</small>
          <button type="submit" className="btn btn-danger" disabled={busy || confirmation !== tenant?.full_name}>
            Stammdaten anonymisieren</button>
        </>}
      </form>}
    </div>
  </details>;
}
