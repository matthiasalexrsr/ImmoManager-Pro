import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';

export function ReportProvenance({ result }) {
  const proof = result.provenance;
  if (!proof) return null;
  return <div className="finance-proof" aria-label="Datenstand und Vollständigkeit">
    <p><strong>Datenstand:</strong> Abruf {result.generated_at ? new Date(result.generated_at).toLocaleString('de-DE') : 'nicht übermittelt'} · fachlicher Stichtag {proof.as_of}.</p>
    <p>{proof.source_records} beitragende Datensätze · {proof.verified_originals} geprüfte Originalbelege.
      {proof.latest_source_change && <> Letzte Änderung eines beitragenden Datensatzes: {new Date(proof.latest_source_change).toLocaleString('de-DE')}.</>}</p>
    <p>{proof.coverage}</p>
    {proof.completeness === 'review_required' && <p role="status"><strong>Prüfung erforderlich:</strong> {proof.invoices_without_verified_original} Rechnungen ohne geprüfte Originalfassung, {proof.unresolved_sources} nicht zugeordnete Quellen und {proof.warning_count} fachliche Hinweise.</p>}
    {proof.assumptions > 0 && <p>{proof.assumptions} Quellenpositionen beruhen auf ausdrücklichen Planungsannahmen.</p>}
  </div>;
}

export function SourceEvidence({ provenance }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(null);
  const original = provenance?.original;
  useEffect(() => () => { pending.current?.abort(); }, []);
  const download = async () => {
    if (pending.current) return;
    const controller = new AbortController();
    pending.current = controller;
    const current = api.captureSession();
    setBusy(true); setError('');
    try {
      const blob = await api.getBlob(`/documents/${encodeURIComponent(original.document_id)}/work/versions/${encodeURIComponent(original.version_id)}/download`, { signal: controller.signal });
      current();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = original.filename || 'Originalbeleg'; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (failure) { if (!controller.signal.aborted) setError(failure.message); }
    finally { if (!controller.signal.aborted) setBusy(false); pending.current = null; }
  };
  if (!provenance) return null;
  if (provenance.kind !== 'record') return <p className="finance-help">{provenance.message}</p>;
  return <div className="finance-help">
    {original?.status === 'verified_original' ? <>
      <button type="button" className="btn btn-sm btn-secondary" onClick={download} disabled={busy}
        aria-label={`Originalbeleg ${original.title}, Version ${original.version_number} herunterladen`}>
        {busy ? 'Original wird geprüft …' : `Original · Version ${original.version_number}`}
      </button>
      <span> {original.message}</span>
      <details><summary>Quellenprüfung</summary><p>Datensatz: {provenance.source_sha256}</p><p>Original: {original.sha256}</p><p>Version: {original.version_id}</p></details>
    </> : original ? <p>{original.message}</p> : null}
    {error && <p role="alert">{error}</p>}
  </div>;
}

