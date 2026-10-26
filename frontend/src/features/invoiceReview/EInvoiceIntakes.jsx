import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import useLookupChoices from '../../hooks/useLookupChoices';
import { formatDate, formatMoney } from '../../utils/format';
import { filenameOf, saveBlob } from '../documentShare/documentShare';
import { Empty, Modal, Pill } from '../maintenanceProject/ProjectUi';
import './eInvoiceIntakes.css';

const BASE = '/e-invoice-intakes';
const labels = { queued: 'Prüfung ausstehend', valid: 'Gültig', warning: 'Mit Warnungen', invalid: 'Ungültiger Beleg',
  technical_error: 'Technischer Prüffehler', accepted: 'Übernommen' };
const tone = { valid: 'green', warning: 'orange', invalid: 'red', technical_error: 'red', accepted: 'green' };
const key = () => crypto.randomUUID();

export default function EInvoiceIntakes({ properties, choicesReady, onAccepted, initialIntake, onIntakeClosed }) {
  const canWrite = useCanWrite(BASE);
  const [page, setPage] = useState(null);
  const [skip, setSkip] = useState(0);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState(initialIntake || null);
  useEffect(() => { if (initialIntake) setSelected(initialIntake); }, [initialIntake]);
  const [property, setProperty] = useState('');
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState('');
  const uploadKey = useRef(key());
  const fileInput = useRef(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    const load = async () => {
      try {
        const result = await api.get(`${BASE}?skip=${skip}&limit=25`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setPage(result);
        if (result.items.some(row => row.state === 'queued')) timer = setTimeout(load, 3000);
      } catch (failure) { if (!controller.signal.aborted) setError(failure.message); }
    };
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [skip, reload]);
  const upload = async event => {
    event.preventDefault();
    if (!file || !property || busy) return;
    setBusy(true); setError(null); setNotice('');
    try {
      const data = new FormData();
      data.set('property_id', property); data.set('file', file);
      const row = await api.upload(BASE, data, { idempotencyKey: uploadKey.current });
      setSelected(row.id); setSkip(0); setReload(value => value + 1);
      setFile(null); if (fileInput.current) fileInput.current.value = '';
      uploadKey.current = key();
      setNotice('Original gespeichert. Der Prüfstatus wird automatisch aktualisiert.');
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return <section aria-label="E-Rechnungseingang" className="ei-intakes">
    <p>XRechnung und ZUGFeRD EN 16931: Original einlesen, Prüfbericht und Zuordnung prüfen, anschließend in die Rechnungsprüfung übernehmen.</p>
    {canWrite && <form onSubmit={upload} className="ei-upload">
      <label className="form-group">Immobilie
        <select required value={property} disabled={!choicesReady || busy} onChange={event => { setProperty(event.target.value); uploadKey.current = key(); }}>
          <option value="">Bitte zuordnen</option>{properties.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      <label className="form-group">Originalbeleg (XML oder PDF, bis 25 MiB)
        <input ref={fileInput} required type="file" accept=".xml,.pdf,application/xml,application/pdf" disabled={busy}
          onChange={event => { setFile(event.target.files?.[0] || null); uploadKey.current = key(); }} />
      </label>
      <button className="btn btn-primary" disabled={busy || !file || !property || !choicesReady}>{busy ? 'Wird gespeichert …' : 'Beleg einlesen'}</button>
    </form>}
    {error && <p className="alert-error" role="alert">{error} <button className="btn btn-secondary btn-sm" type="button"
      onClick={() => { setError(null); setReload(value => value + 1); }}>Status neu laden</button></p>}
    {notice && <p role="status">{notice}</p>}
    {!page ? <p role="status">Eingänge werden geladen …</p> : !page.items.length ? <Empty>Noch keine strukturierten Rechnungseingänge.</Empty> : <>
      <ul className="ir-list">{page.items.map(row => <li className="ir-row" key={row.id}>
        <button type="button" className="ei-open" onClick={() => setSelected(row.id)}>
          <span><strong>{row.reading.supplier || row.filename}</strong><br />{row.reading.number || 'Auswertung ausstehend'} · {properties.find(p => p.id === row.property_id)?.name || 'Immobilie'}</span>
          <span>{row.reading.due ? formatMoney(Number(row.reading.due)) : '—'}</span>
          <Pill tone={tone[row.state]}>{labels[row.state] || row.state}</Pill>
        </button>
        {!!row.blockers.length && <p className="ei-blocker">Übernahme gesperrt: {row.blockers.join(' ')}</p>}
      </li>)}</ul>
      <div className="ir-paging"><button className="btn btn-secondary btn-sm" type="button" disabled={!skip} onClick={() => setSkip(Math.max(0, skip - 25))}>Zurück</button>
        <span>{skip + 1}–{skip + page.items.length} von {page.total}</span>
        <button className="btn btn-secondary btn-sm" type="button" disabled={skip + page.items.length >= page.total} onClick={() => setSkip(skip + 25)}>Weiter</button></div>
    </>}
    {selected && <IntakeDetail id={selected} properties={properties} canWrite={canWrite} onClose={() => { setSelected(null); onIntakeClosed?.(); }}
      onChanged={() => { setReload(value => value + 1); onAccepted?.(); }} />}
  </section>;
}

function IntakeDetail({ id, properties, canWrite, onClose, onChanged }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [form, setForm] = useState({ unit_id: '', credit_for_invoice_id: '', warning_reason: '', acknowledge_warnings: false,
    accept_duplicate: false, duplicate_reason: '' });
  const commands = useRef({});
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    const load = async () => {
      try {
        const result = await api.get(`${BASE}/${encodeURIComponent(id)}`, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setData(result);
        if (result.state === 'queued') timer = setTimeout(load, 3000);
      } catch (failure) { if (!controller.signal.aborted) setError(failure.message); }
    };
    load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, reload]);
  const choices = useLookupChoices({ units: `/units?property_id=${encodeURIComponent(data?.property_id || '')}`,
    invoices: `/invoices?property_id=${encodeURIComponent(data?.property_id || '')}` }, Boolean(data?.property_id && data.state !== 'accepted'), id);
  const set = (name, value) => setForm(current => ({ ...current, [name]: value }));
  const act = async operation => {
    if (busy) return;
    setBusy(true); setError(null);
    const payload = { expected_revision: data.revision, ...(operation === 'accept' ? {
      ...form, unit_id: form.unit_id || null, credit_for_invoice_id: form.credit_for_invoice_id || null,
      warning_reason: form.warning_reason || null, duplicate_reason: form.duplicate_reason || null } : {}) };
    const fingerprint = JSON.stringify([operation, payload]);
    commands.current[fingerprint] ||= key();
    try {
      await api.post(`${BASE}/${encodeURIComponent(id)}/${operation}`, { ...payload, idempotency_key: commands.current[fingerprint] });
      setReload(value => value + 1); onChanged();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const download = async suffix => {
    try {
      const { blob, headers } = await api.getFile(`${BASE}/${encodeURIComponent(id)}/${suffix}`);
      saveBlob(blob, filenameOf(headers, 'Rechnungsbeleg'));
    } catch (failure) { setError(failure.message); }
  };
  const r = data?.reading;
  const ready = data && ['valid', 'warning'].includes(data.state) && !data.blockers.length && choices.ready;
  return <Modal wide title="E-Rechnung prüfen und zuordnen" onClose={onClose}>
    {error && <p className="alert-error" role="alert">{error} <button className="btn btn-secondary btn-sm" type="button" onClick={() => setReload(value => value + 1)}>Stand erneut laden</button></p>}
    {!data ? <p role="status">Eingang wird geladen …</p> : <div className="ei-detail">
      <div className="mp-actions"><Pill tone={tone[data.state]}>{labels[data.state]}</Pill>
        <button type="button" className="btn btn-secondary btn-sm" onClick={() => download('original')}>Original herunterladen</button>
        {data.format && <button type="button" className="btn btn-secondary btn-sm" onClick={() => download('xml')}>Rechnungs-XML</button>}
        {canWrite && !['queued', 'accepted'].includes(data.state) && <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => act('validate')}>Erneut prüfen</button>}
      </div>
      {!!data.blockers.length && <div className="alert-error"><strong>Übernahme gesperrt</strong><ul>{data.blockers.map((reason, i) => <li key={i}>{reason}</li>)}</ul></div>}
      {data.state === 'queued' && <p role="status">Die lokale Prüfung ist eingeplant. Sie können dieses Fenster schließen und später fortfahren.</p>}
      {r?.number && <>
        <h3>Lesefassung · {r.kind === 'credit_note' ? 'Gutschrift' : `Belegart ${r.type_code}`}</h3>
        <dl className="ei-facts">
          <div><dt>Aussteller</dt><dd>{r.supplier}</dd></div><div><dt>Rechnungsnummer</dt><dd>{r.number}</dd></div>
          <div><dt>Rechnungsdatum</dt><dd>{formatDate(r.issued_on)}</dd></div><div><dt>Fälligkeit</dt><dd>{formatDate(r.due_on)}</dd></div>
          <div><dt>Leistungszeitraum</dt><dd>{formatDate(r.performance_start)} – {formatDate(r.performance_end)}</dd></div>
          <div><dt>Empfänger / Referenz</dt><dd>{r.buyer || '—'} · {r.buyer_reference || '—'}</dd></div>
          <div><dt>Währung / Zahlbetrag</dt><dd>{r.currency} · {r.due}</dd></div><div><dt>Rundung / Vorauszahlung</dt><dd>{r.rounding} / {r.prepaid}</dd></div>
          <div><dt>Zahlungsbedingungen</dt><dd>{r.payment_terms || '—'}</dd></div><div><dt>Verwendungszweck</dt><dd>{r.payment_reference || '—'}</dd></div>
          <div><dt>Ursprungsbezug</dt><dd>{r.original_reference || '—'}</dd></div><div><dt>Immobilie</dt><dd>{properties.find(p => p.id === data.property_id)?.name || data.property_id}</dd></div>
        </dl>
        <div className="ei-table"><table><caption>Steueraufschlüsselung</caption><thead><tr><th>Steuergruppe</th><th>Satz</th><th>Netto</th><th>Steuer</th><th>Befreiungsgrund</th></tr></thead>
          <tbody>{r.taxes.map((tax, i) => <tr key={i}><td>{tax.category}</td><td>{tax.rate} %</td><td>{tax.net}</td><td>{tax.vat}</td><td>{tax.exemption_reason || tax.exemption_code || '—'}</td></tr>)}</tbody></table></div>
        {!!r.lines?.length && <details><summary>Rechnungspositionen ({r.lines.length})</summary><ol>{r.lines.map((line, i) => <li key={i}><strong>{line.name}</strong> · {line.quantity} {line.unit} · {line.net} {r.currency}<p>{line.description}</p></li>)}</ol></details>}
        {!!r.bank_accounts?.length && <div><h4>Bankdaten aus dem Beleg</h4><p>Diese Angaben benötigen eine gesonderte Empfängerprüfung.</p>
          {r.bank_accounts.map((account, i) => <p key={i}>{account.name || r.supplier} · {account.iban} · {account.bic}</p>)}</div>}
      </>}
      {!!data.validations.length && <div><h3>Prüfläufe</h3>{data.validations.map(run => <details key={run.id} open={run.number === data.validation_number}>
        <summary>Prüfung {run.number}: {labels[run.state]} · {run.engine} {run.engine_version}</summary>
        {!!run.messages.length && <ul>{run.messages.map((message, i) => <li key={i}>{message.code && <strong>{message.code}: </strong>}{message.text}</li>)}</ul>}
        {run.report_sha256 !== 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855' &&
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => download(`validations/${run.number}/report`)}>Vollständigen Prüfbericht herunterladen</button>}
      </details>)}</div>}
      {data.state === 'accepted' ? <p role="status">Übernommen. <Link to={`/invoice-review/${encodeURIComponent(data.invoice_id)}`} onClick={onClose}>Rechnungsprüfung öffnen</Link></p> : canWrite && <form onSubmit={event => { event.preventDefault(); act('accept'); }}>
        {choices.error && <p role="alert" className="alert-error">{choices.error} <button type="button" onClick={choices.reload}>Auswahl neu laden</button></p>}
        <label className="form-group">Einheit (optional)<select value={form.unit_id} disabled={!choices.ready || busy} onChange={event => set('unit_id', event.target.value)}>
          <option value="">Gesamte Immobilie</option>{(choices.data.units || []).filter(u => u.property_id === data.property_id).map(u => <option key={u.id} value={u.id}>{u.label}</option>)}</select></label>
        {r?.kind === 'credit_note' && <label className="form-group">Geminderte Rechnung<select required value={form.credit_for_invoice_id} disabled={!choices.ready || busy} onChange={event => set('credit_for_invoice_id', event.target.value)}>
          <option value="">Ursprungsrechnung auswählen</option>{(choices.data.invoices || []).filter(i => i.property_id === data.property_id).map(i => <option key={i.id} value={i.id}>{i.invoice_number || i.id} · {i.supplier}</option>)}</select></label>}
        {data.state === 'warning' && <><label><input type="checkbox" checked={form.acknowledge_warnings} onChange={event => set('acknowledge_warnings', event.target.checked)} required /> Ich habe die Warnungen fachlich geprüft.</label>
          <label className="form-group">Begründung zur Übernahme trotz Warnungen<textarea required minLength={10} maxLength={2000} value={form.warning_reason} onChange={event => set('warning_reason', event.target.value)} /></label></>}
        <details><summary>Begründete Ausnahme bei einer Dublette</summary><label><input type="checkbox" checked={form.accept_duplicate} onChange={event => set('accept_duplicate', event.target.checked)} /> Bekannte Dublette bewusst übernehmen</label>
          {form.accept_duplicate && <label className="form-group">Begründung<textarea required maxLength={2000} value={form.duplicate_reason} onChange={event => set('duplicate_reason', event.target.value)} /></label>}</details>
        <button className="btn btn-primary" disabled={!ready || busy}>{busy ? 'Wird verarbeitet …' : 'Zuordnung bestätigen und übernehmen'}</button>
      </form>}
    </div>}
  </Modal>;
}
