import { useEffect, useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { api } from '../api';
import { formContext } from '../utils/workspaceClient';
import useWorkspaceLocation from '../hooks/useWorkspaceLocation';

const REASONS = { email: 'gleiche E-Mail-Adresse', phone: 'gleiche Telefonnummer', name_address: 'gleicher Name und Anschrift', same_number: 'gleiche Rechnungsnummer', similar: 'ähnliche Rechnungsdaten', same_content: 'gleicher Dateiinhalt' };
export default function DuplicateHints({ values, initial, context: explicitContext }) {
  const owner = useAuth()?.user?.id;
  const location = useWorkspaceLocation();
  const context = explicitContext || formContext(location.pathname);
  const kind = context === 'contacts' ? 'contact' : context === 'invoices' ? 'invoice' : context === 'documents' && values.file_url ? 'file' : null;
  const candidate = kind === 'contact' ? Object.fromEntries(['first_name', 'last_name', 'company_name', 'email', 'phone', 'mobile', 'street', 'zip_code'].map(key => [key, values[key] || '']))
    : kind === 'invoice' ? { supplier: values.supplier, invoice_date: values.invoice_date, invoice_number: values.invoice_number, gross_amount: values.gross_amount }
      : { file_url: values.file_url };
  const valid = kind === 'contact' ? candidate.email || candidate.phone || candidate.mobile || (candidate.street && candidate.zip_code && (candidate.last_name || candidate.company_name))
    : kind === 'invoice' ? candidate.supplier && candidate.invoice_date && candidate.gross_amount !== '' && candidate.gross_amount != null : Boolean(kind);
  const signature = JSON.stringify({ kind, candidate, exclude_id: initial?.id || null });
  const [state, setState] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!owner || !kind || !valid) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api.post('/work-center/duplicates/check', JSON.parse(signature), { signal: controller.signal }).then(page => {
        if (!controller.signal.aborted) setState({ signature, ...page });
      }).catch(failure => { if (!controller.signal.aborted) setState({ signature, error: failure.message }); });
    }, 500);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [owner, kind, valid, signature, attempt]);
  if (!owner || !valid || state?.signature !== signature) return null;
  if (state.error) return <p role="status">Dublettenprüfung derzeit nicht möglich. {state.error}<button type="button" className="btn btn-sm btn-ghost" onClick={() => setAttempt(value => value + 1)}>Erneut prüfen</button></p>;
  if (!state.items?.length && state.coverage?.complete !== false) return null;
  return <section className="draft-recovery" aria-label="Mögliche Dubletten"><strong>Mögliche Dubletten</strong>
    {state.coverage?.complete === false && <p role="status">{state.coverage.note || 'Noch nicht alle vorhandenen Dateien wurden auf ihren Inhalt geprüft.'}{' '}
      <a href={state.coverage.pending_href || '/document-queue'} target="_blank" rel="noopener noreferrer">Dateiprüfung fortsetzen</a></p>}
    <p>Prüfen Sie vorhandene Einträge. Berechtigte getrennte Vorgänge können gespeichert und anschließend unter „Dubletten prüfen“ mit Begründung als Ausnahme dokumentiert werden.</p>
    <ul>{(state.items || []).map(item => <li key={item.id}><a href={item.href} target="_blank" rel="noopener noreferrer">{item.title}</a> · {REASONS[item.reason] || 'übereinstimmende Merkmale'}{item.exception && ' · begründete Ausnahme vorhanden'}</li>)}</ul>
    {state.next_cursor && <button type="button" className="btn btn-sm btn-secondary" disabled={state.busy} onClick={async () => {
      setState(current => ({ ...current, busy: true }));
      try {
        const page = await api.post('/work-center/duplicates/check', { ...JSON.parse(signature), cursor: state.next_cursor });
        setState(current => current?.signature !== signature ? current : { ...current, busy: false, items: [...current.items, ...page.items], next_cursor: page.next_cursor });
      } catch (failure) { setState(current => current?.signature !== signature ? current : { ...current, busy: false, error: failure.message }); }
    }}>Weitere Hinweise</button>}
  </section>;
}
