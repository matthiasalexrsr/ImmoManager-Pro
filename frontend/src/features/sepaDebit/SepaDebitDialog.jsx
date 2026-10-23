import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CloseIcon } from '../../components/Icons';
import { formatDate, formatDateTime, formatMoney } from '../../utils/format';
import { nextMonth, preselected, saveXml, sepaDebitService, totalOf } from './sepaDebitApi';
import './sepaDebit.css';

/** Writes the SEPA direct debit file of a month for one bank account. The file is only
 *  downloaded; the user uploads it to online banking. */
export default function SepaDebitDialog({ onClose, service = sepaDebitService }) {
  const id = useId();
  const ref = useRef(null);
  const close = useRef(onClose);
  useEffect(() => { close.current = onClose; });
  const [accounts, setAccounts] = useState(null);
  const [accountId, setAccountId] = useState('');
  const [month, setMonth] = useState(() => nextMonth());
  const [collectionDate, setCollectionDate] = useState('');
  const [preview, setPreview] = useState(null);
  const [chosen, setChosen] = useState(new Set());
  const [creditorId, setCreditorId] = useState('');
  const [creditorName, setCreditorName] = useState('');
  const [repeatChecked, setRepeatChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);
  const attempt = useRef(null);       // { text, key }: a retry of the same body keeps its key
  const selectionFor = useRef('');     // the account and month the selection was made for

  useEffect(() => {
    const previous = globalThis.document.activeElement;
    const onKey = event => { if (event.key === 'Escape') close.current(); };
    globalThis.document.addEventListener('keydown', onKey);
    return () => { globalThis.document.removeEventListener('keydown', onKey); previous?.focus?.(); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    service.accounts({ signal: controller.signal }).then(items => {
      if (controller.signal.aborted) return;
      const usable = (items || []).filter(item => item.iban);
      setAccounts(usable);
      setAccountId(current => current || usable[0]?.id || '');
    }).catch(failure => { if (!controller.signal.aborted) setError(failure.message || 'Die Konten konnten nicht geladen werden.'); });
    return () => controller.abort();
  }, [service]);

  useEffect(() => {
    if (!accountId || !/^\d{4}-\d{2}$/.test(month)) return undefined;
    const controller = new AbortController();
    setError('');
    const params = { account_id: accountId, month, ...(collectionDate ? { collection_date: collectionDate } : {}) };
    service.preview(params, { signal: controller.signal }).then(value => {
      if (controller.signal.aborted) return;
      setPreview(value);
      if (selectionFor.current !== `${accountId}|${month}`) {    // a new date keeps what was chosen
        selectionFor.current = `${accountId}|${month}`;
        setChosen(preselected(value.lines));
        setRepeatChecked(false);
      } else {
        setChosen(current => new Set([...current].filter(item => value.lines.some(line => line.contract_id === item && line.ready))));
      }
      setCollectionDate(current => current || value.collection_date);
      setCreditorId(current => current || value.creditor.creditor_id || '');
      setCreditorName(current => current || value.creditor.creditor_name || value.creditor.suggested_name || '');
    }).catch(failure => { if (!controller.signal.aborted) { setPreview(null); setError(failure.message || 'Die Vorschau konnte nicht geladen werden.'); } });
    return () => controller.abort();
  }, [accountId, month, collectionDate, service]);

  const lines = useMemo(() => preview?.lines || [], [preview]);
  const repeated = lines.filter(line => chosen.has(line.contract_id) && line.repeated);
  const total = totalOf(lines, chosen);
  const toggle = contractId => setChosen(current => {
    const next = new Set(current);
    if (next.has(contractId)) next.delete(contractId); else next.add(contractId);
    return next;
  });

  const submit = async event => {
    event.preventDefault();
    if (busy || !chosen.size) return;
    if (repeated.length && !repeatChecked) { setError('Bitte bestätigen Sie die erneute Aufnahme der bereits geschriebenen Lastschriften.'); return; }
    const body = { account_id: accountId, month, collection_date: collectionDate, creditor_id: creditorId.trim(),
      creditor_name: creditorName.trim(), contract_ids: [...chosen].sort(), allow_repeat: repeated.length > 0 };
    const text = JSON.stringify(body);
    if (attempt.current?.text !== text) attempt.current = { text, key: crypto.randomUUID() };
    setBusy(true); setError('');
    try {
      const result = await service.create({ ...body, idempotency_key: attempt.current.key });
      attempt.current = null;
      saveXml(result);
      setDone(result);
    } catch (failure) {
      setError(failure.message || 'Die Datei konnte nicht erstellt werden.');
    } finally { setBusy(false); }
  };

  return createPortal(
    <div className="modal-overlay" role="presentation" onClick={onClose}>
      <div ref={ref} className="modal modal-wide sepa-debit-dialog" role="dialog" aria-modal="true" aria-labelledby={`${id}-title`}
        onClick={event => event.stopPropagation()}>
        <div className="modal-header">
          <h3 id={`${id}-title`}>SEPA-Lastschriftdatei</h3>
          <button type="button" className="btn-close" aria-label="Schließen" onClick={onClose}><CloseIcon size={18} /></button>
        </div>
        <div className="modal-body">
          {done ? <div className="sepa-debit-done" role="status">
            <p><strong>Die Datei „{done.filename}“ wurde gespeichert.</strong> {done.count} Lastschrift{done.count === 1 ? '' : 'en'} über {formatMoney(Number(done.total))}, fällig am {formatDate(done.collection_date)}.</p>
            <p>Nichts wurde an die Bank gesendet. Laden Sie die Datei im Online-Banking als SEPA-Sammellastschrift hoch und prüfen Sie dort die Summe. Die Datei ist mit der Kennung {done.message_id} vermerkt; dieselben Sollstellungen werden beim nächsten Mal nicht vorausgewählt.</p>
            <div className="modal-footer">
              <button type="button" className="btn btn-secondary" onClick={() => saveXml(done)}>Datei erneut speichern</button>
              <button type="button" className="btn btn-primary" onClick={onClose}>Fertig</button>
            </div>
          </div> : <form onSubmit={submit}>
            <p className="text-muted sepa-debit-intro">Die Datei enthält für jeden gewählten Vertrag die offenen Sollstellungen des Monats. Sie wird nur erstellt, nicht gesendet. Die Mieter müssen die Lastschrift vorher angekündigt bekommen haben (Vorabankündigung, z. B. im Mietvertrag oder Mandat mit Betrag und Termin).</p>
            {accounts && !accounts.length && <p role="alert" className="alert alert-error">Es gibt noch kein Konto mit IBAN. Bitte zuerst unter Konten das Mietkonto mit IBAN anlegen.</p>}
            <div className="sepa-debit-fields">
              <label>Konto, auf das eingezogen wird
                <select value={accountId} onChange={event => { setAccountId(event.target.value); setCreditorId(''); setCreditorName(''); setCollectionDate(''); }}>
                  {(accounts || []).map(item => <option key={item.id} value={item.id}>{item.name} · {item.iban}</option>)}
                </select></label>
              <label>Monat
                <input type="month" value={month} onChange={event => { setMonth(event.target.value); setCollectionDate(''); }} required /></label>
              <label>Fälligkeit (Einzug am)
                <input type="date" value={collectionDate} onChange={event => setCollectionDate(event.target.value)} required /></label>
              <label>Gläubiger-ID
                <input value={creditorId} onChange={event => setCreditorId(event.target.value)} placeholder="z. B. DE98ZZZ09999999999" required maxLength={35} /></label>
              <label>Zahlungsempfänger
                <input value={creditorName} onChange={event => setCreditorName(event.target.value)} required maxLength={70} /></label>
            </div>
            {preview?.collection_date_problem && <p role="alert" className="alert alert-error">{preview.collection_date_problem}</p>}
            {preview && <div className="sepa-debit-table" role="region" aria-label="Lastschriften des Monats" tabIndex={0}>
              {!lines.length ? <p className="text-muted">Im Bestand dieses Kontos zahlt kein Mieter per Lastschrift. Die Zahlungsart und das Mandat stehen beim Mieter.</p>
                : <table>
                  <thead><tr><th scope="col"><span className="sr-only">Aufnehmen</span></th><th scope="col">Vertrag</th><th scope="col">Kontoinhaber</th>
                    <th scope="col">IBAN</th><th scope="col">Mandat</th><th scope="col" className="num">Betrag</th><th scope="col">Hinweis</th></tr></thead>
                  <tbody>{lines.map(line => <tr key={line.contract_id} className={line.ready ? '' : 'sepa-debit-blocked'}>
                    <td><input type="checkbox" aria-label={`${line.contract_number} aufnehmen`} disabled={!line.ready}
                      checked={chosen.has(line.contract_id)} onChange={() => toggle(line.contract_id)} /></td>
                    <td>{line.contract_number}<div className="text-muted">{line.property_name}{line.unit_label ? ` · ${line.unit_label}` : ''}</div></td>
                    <td>{line.account_holder}{line.account_holder !== line.tenant_name && <div className="text-muted">Mieter: {line.tenant_name}</div>}</td>
                    <td>{line.iban || '—'}</td>
                    <td>{line.mandate_reference || '—'}{line.mandate_date && <div className="text-muted">vom {formatDate(line.mandate_date)}</div>}</td>
                    <td className="num">{formatMoney(Number(line.amount))}</td>
                    <td>{line.problems.length ? line.problems.join(' ') : Number(line.amount) <= 0 ? 'Nichts offen in diesem Monat.'
                      : line.repeated ? `Schon in einer Datei vom ${formatDateTime(line.receivables.find(item => item.earlier.length)?.earlier[0]?.created_at)}.`
                        : line.receivables.map(item => item.description).join(', ')}</td>
                  </tr>)}</tbody>
                </table>}
            </div>}
            {repeated.length > 0 && <label className="sepa-debit-repeat"><input type="checkbox" checked={repeatChecked} onChange={event => setRepeatChecked(event.target.checked)} />
              {' '}Ich habe geprüft, dass die Bank {repeated.map(line => line.contract_number).join(', ')} aus der früheren Datei nicht eingezogen hat.</label>}
            {preview?.files?.length > 0 && <details className="sepa-debit-files"><summary>Frühere Dateien dieses Kontos</summary>
              <ul>{preview.files.map(item => <li key={item.message_id}>{formatDateTime(item.created_at)} · {item.month} · {item.count} Lastschriften · {formatMoney(Number(item.total))} · fällig {formatDate(item.collection_date)}</li>)}</ul></details>}
            {error && <p role="alert" className="alert alert-error">{error}</p>}
            <div className="modal-footer">
              <span className="sepa-debit-sum" role="status">{chosen.size} Lastschrift{chosen.size === 1 ? '' : 'en'} · {formatMoney(total)}</span>
              <button type="button" className="btn btn-secondary" onClick={onClose}>Abbrechen</button>
              <button type="submit" className="btn btn-primary" disabled={busy || !chosen.size || !preview || Boolean(preview.collection_date_problem)}>
                {busy ? 'Wird erstellt …' : 'Datei erstellen'}</button>
            </div>
          </form>}
        </div>
      </div>
    </div>, globalThis.document.body);
}
