import { useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { formatMoney } from '../../utils/format';
import useEntityFormDraft from '../../hooks/useEntityFormDraft';
import CustomDraftNotice from '../../components/CustomDraftNotice';

const DRAFT_FIELDS = ['account_id', 'amount', 'booking_date', 'payment_text'].map(key => ({ key }));

export default function RentPaymentDialog({ row, accounts, pending, onSubmit, onClose, onReload, today }) {
  const ref = useRef(null);
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  // the portfolio's only account is the one the money went to
  const [values, setValues] = useState(() => pending?.request || {
    account_id: (() => { const own = accounts.filter(account => account.portfolio_id === row.portfolio_id); return own.length === 1 ? own[0].id : ''; })(),
    amount: row.outstanding > 0 ? String(row.outstanding) : '', booking_date: today, payment_text: '',
  });
  const draft = useEntityFormDraft({ context: 'rent-payment', kind: 'contract', id: row.contract_id,
    fields: DRAFT_FIELDS, enabled: !pending });
  const draftBlocked = draft.enabled && (draft.loading || !draft.ready || Boolean(draft.recovery) || draft.status === 'changed');
  useModalDialog(ref, () => { if (!busyRef.current) onClose(); });
  const submit = async event => {
    event.preventDefault();
    if (busyRef.current || draftBlocked) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try { await draft.clear(); await onSubmit(values); }
    catch (failure) { setError(failure); if (!pending) draft.stage(values); }
    finally { busyRef.current = false; setBusy(false); }
  };
  const update = (key, value) => { const next = { ...values, [key]: value }; setValues(next); draft.stage(next); };
  const accountOptions = accounts.filter(account => account.portfolio_id === row.portfolio_id);
  return <div className="modal-overlay">
    <section ref={ref} className="modal rent-payment-dialog" role="dialog" aria-modal="true" aria-labelledby="rent-payment-title" tabIndex={-1}>
      <div className="modal-header"><h2 id="rent-payment-title">Zahlung zum Vertrag erfassen</h2>
        <button type="button" className="btn-close" aria-label="Schließen" disabled={busy} onClick={onClose}>×</button></div>
      <form onSubmit={submit}>
        <div className="modal-body">
          <p><strong>{row.tenant_name}</strong><br />{row.contract_number} · {row.unit_label}</p>
          <CustomDraftNotice draft={draft} currentValues={values} onRestore={saved => { setValues(saved); draft.stage(saved); }} />
          <p className="text-muted">Die Zahlung wird auf dem gewählten Konto gebucht und diesem Vertrag zugeordnet.
            Im Mietverlauf gleicht sie zuerst die ältesten offenen Mietmonate aus. Andere Forderungen behalten ihre eigene Bearbeitung.</p>
          {pending && <div className="alert alert-warning" role="status">Die Bestätigung dieser Buchung steht noch aus.
            „Buchung prüfen“ verwendet denselben Vorgang und legt die Zahlung höchstens einmal an.</div>}
          {error && <div className="alert alert-error" role="alert">{error.message || 'Die Buchung konnte nicht bestätigt werden.'}
            {error.code === 'RENT_PAYMENT_NOT_CREATED' && <button type="button" className="btn btn-secondary" onClick={onReload}>Mietübersicht neu laden</button>}
            {error.details?.booking_id && <Link to={`/bookings?booking_id=${encodeURIComponent(error.details.booking_id)}`}>Aktuelle Buchung ansehen</Link>}</div>}
          <fieldset disabled={busy || Boolean(pending) || draftBlocked}>
            <div className="form-group"><label htmlFor="rent-payment-account">Zahlungskonto</label>
              <select id="rent-payment-account" required value={values.account_id} onChange={e => update('account_id', e.target.value)}>
                <option value="">Bitte Konto wählen</option>
                {accountOptions.map(account => <option key={account.id} value={account.id}>{account.name}</option>)}
                {pending && !accountOptions.some(account => account.id === values.account_id)
                  && <option value={values.account_id}>Zuvor gewähltes Konto</option>}
              </select></div>
            <div className="form-group"><label htmlFor="rent-payment-amount">Zahlungsbetrag (€)</label>
              <input id="rent-payment-amount" type="number" min="0.01" step="0.01" max="9999999999.99" required
                value={values.amount} onChange={e => update('amount', e.target.value)} /></div>
            <div className="form-group"><label htmlFor="rent-payment-date">Tatsächlicher Zahlungseingang</label>
              <input id="rent-payment-date" type="date" required max={today}
                value={values.booking_date} onChange={e => update('booking_date', e.target.value)} /></div>
            <div className="form-group"><label htmlFor="rent-payment-note">Buchungstext / Bemerkung</label>
              <textarea id="rent-payment-note" maxLength={2000} value={values.payment_text} onChange={e => update('payment_text', e.target.value)} /></div>
          </fieldset>
          {!pending && accountOptions.length === 0 && <p role="alert">Für dieses Portfolio ist noch kein Zahlungskonto verfügbar.{' '}
            <Link to="/accounts?neu=1">Konto anlegen</Link></p>}
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" disabled={busy} onClick={onClose}>{pending ? 'Später prüfen' : 'Abbrechen'}</button>
          <button type="submit" className="btn btn-primary" disabled={busy || draftBlocked || ['RENT_PAYMENT_REMOVED', 'RENT_PAYMENT_CHANGED', 'RENT_PAYMENT_RECORDED_UNAVAILABLE'].includes(error?.code) || (!pending && accountOptions.length === 0)}>
            {busy ? 'Wird geprüft…' : pending ? 'Buchung prüfen' : `${formatMoney(values.amount || 0)} als Eingang buchen`}
          </button>
        </div>
      </form>
    </section>
  </div>;
}
