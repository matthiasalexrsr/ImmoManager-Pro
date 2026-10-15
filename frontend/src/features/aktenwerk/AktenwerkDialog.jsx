import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CloseIcon } from '../../components/Icons';
import { useCanWrite } from '../../contexts/AuthContext';
import { formatDate, formatMoney } from '../../utils/format';
import { aktenwerkApi, KINDS, KIND_LABEL, sendAll } from './aktenwerkApi';
import './aktenwerk.css';

const PREVIEW_ROWS = 50;

// Choose documents for Aktenwerk (DMS): by year, kind and tax view; download them as an import
// package or hand them over to a connected Aktenwerk. Nothing leaves without a click here.
export default function AktenwerkDialog({ onClose, ready, initialYear = '' }) {
  const canSend = useCanWrite('/aktenwerk');
  const [year, setYear] = useState(initialYear);
  const [kinds, setKinds] = useState([]);
  const [taxRelevant, setTaxRelevant] = useState(false);
  const [deductible, setDeductible] = useState(false);
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [outcome, setOutcome] = useState(null);
  const closeRef = useRef(null);
  const filters = useMemo(() => ({ kinds, year, taxRelevant, deductible }), [kinds, year, taxRelevant, deductible]);
  // A previous selection is never actionable while the new preview is pending or failed.
  const manifest = preview?.filters === filters ? preview.data : null;

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    aktenwerkApi.manifest(filters, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) { setPreview({ filters, data }); setOutcome(null); } })
      .catch(err => { if (err.name !== 'AbortError') setError(err.message); });
    return () => controller.abort();
  }, [filters]);

  useEffect(() => {
    closeRef.current?.focus();
    const keydown = event => { if (event.key === 'Escape' && !busy) onClose(); };
    document.addEventListener('keydown', keydown);
    return () => document.removeEventListener('keydown', keydown);
  }, [onClose, busy]);

  const entries = manifest?.entries || [];
  const thisYear = new Date().getFullYear();
  const years = Array.from({ length: 8 }, (_, i) => String(thisYear - i));
  const toggleKind = kind => setKinds(current => (current.includes(kind) ? current.filter(k => k !== kind) : [...current, kind]));

  const download = async () => {
    setBusy('export'); setError(null);
    try {
      const blob = await aktenwerkApi.exportZip(filters);
      const url = URL.createObjectURL(blob);
      try {
        const link = document.createElement('a');
        link.href = url;
        link.download = `aktenwerk-export${year ? `-${year}` : ''}.zip`;
        link.click();
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };

  const send = async () => {
    setBusy('send'); setError(null); setOutcome(null);
    try {
      setOutcome(await sendAll(entries.map(entry => entry.exchange_id)));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  };

  const failed = outcome?.results?.filter(result => result.status === 'failed') || [];

  return (
    <div className="modal-overlay" role="presentation" onClick={event => { if (event.target === event.currentTarget && !busy) onClose(); }}>
      <div className="modal modal-wide aktenwerk-dialog" role="dialog" aria-modal="true" aria-labelledby="aktenwerk-title">
        <div className="modal-header">
          <h3 id="aktenwerk-title">Dokumente für Aktenwerk</h3>
          <button ref={closeRef} type="button" className="btn-close" onClick={onClose} disabled={Boolean(busy)} aria-label="Schließen"><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">
          <fieldset className="aktenwerk-filters" disabled={Boolean(busy)}>
            <legend className="sr-only">Auswahl</legend>
            <label>Jahr
              <select value={year} onChange={event => setYear(event.target.value)}>
                <option value="">Alle Jahre</option>
                {years.map(value => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <label className="aktenwerk-check"><input type="checkbox" checked={taxRelevant} onChange={event => setTaxRelevant(event.target.checked)} /> Steuerlich relevant</label>
            <label className="aktenwerk-check"><input type="checkbox" checked={deductible} onChange={event => setDeductible(event.target.checked)} /> Nur absetzbar (Werbungskosten)</label>
            <div className="aktenwerk-kinds" role="group" aria-label="Dokumentarten">
              {KINDS.map(([kind, label]) => (
                <button key={kind} type="button" aria-pressed={kinds.includes(kind)}
                  className={`btn btn-sm ${kinds.includes(kind) ? 'btn-primary' : 'btn-secondary'}`} onClick={() => toggleKind(kind)}>
                  {label}{manifest?.counts?.[kind] ? ` (${manifest.counts[kind]})` : ''}
                </button>
              ))}
            </div>
          </fieldset>

          {error && <div className="alert-error" role="alert">{error}</div>}
          {!manifest && !error && <p role="status">Dokumente werden zusammengestellt …</p>}
          {manifest && (
            <>
              <p className="aktenwerk-summary" role="status">
                {entries.length === 0 ? 'Keine Dokumente für diese Auswahl.' : `${entries.length} ${entries.length === 1 ? 'Dokument' : 'Dokumente'} ausgewählt.`}
              </p>
              {entries.length > 0 && (
                <div className="table-scroll aktenwerk-preview">
                  <table className="data-table">
                    <thead><tr><th>Datum</th><th>Art</th><th>Titel</th><th>Bezug</th><th className="text-right">Betrag</th><th>Steuer</th></tr></thead>
                    <tbody>
                      {entries.slice(0, PREVIEW_ROWS).map(entry => (
                        <tr key={entry.exchange_id}>
                          <td>{entry.date ? formatDate(entry.date) : '—'}</td>
                          <td>{KIND_LABEL[entry.kind] || entry.kind}</td>
                          <td className="td-wrap">{entry.title}</td>
                          <td className="td-wrap">{[entry.references?.property?.name, entry.references?.unit?.name, entry.references?.tenant?.name].filter(Boolean).join(' · ') || '—'}</td>
                          <td className="text-right td-num">{entry.finance?.gross ?? entry.finance?.amount ? formatMoney(entry.finance.gross ?? entry.finance.amount) : '—'}</td>
                          <td>{entry.tax?.deductible ? <span className="badge badge-green">absetzbar</span> : entry.tax?.relevant ? <span className="badge badge-blue">relevant</span> : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {entries.length > PREVIEW_ROWS && <p className="text-muted">… und {entries.length - PREVIEW_ROWS} weitere (alle im Paket).</p>}
                </div>
              )}
            </>
          )}

          {outcome && (
            <div className={failed.length ? 'alert-error' : 'alert-info'} role={failed.length ? 'alert' : 'status'}>
              {outcome.message}
              {failed.length > 0 && <ul>{failed.slice(0, 8).map(item => <li key={item.exchange_id}>{entries.find(e => e.exchange_id === item.exchange_id)?.title || item.exchange_id}: {item.reason}</li>)}</ul>}
            </div>
          )}
          {outcome?.history_warning && <div className="alert-error" role="alert">{outcome.history_warning}</div>}
          {!ready && (
            <p className="text-muted aktenwerk-hint">
              Ohne Verbindung lässt sich das Paket herunterladen und in Aktenwerk importieren. Für die direkte Übergabe
              Aktenwerk unter <Link to="/integrations" onClick={onClose}>Schnittstellen</Link> einrichten und aktivieren.
            </p>
          )}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={Boolean(busy)}>Schließen</button>
          <button type="button" className="btn btn-secondary" onClick={download} disabled={Boolean(busy) || entries.length === 0}>
            {busy === 'export' ? 'Paket wird erstellt …' : 'Exportpaket (ZIP)'}
          </button>
          {ready && canSend && (
            <button type="button" className="btn btn-primary" onClick={send} disabled={Boolean(busy) || entries.length === 0}>
              {busy === 'send' ? 'Wird übergeben …' : `An Aktenwerk übergeben (${entries.length})`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
