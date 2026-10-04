import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { revisionOptions } from '../../editRevision';
import { useAuth } from '../../contexts/AuthContext';
import { useConfirm } from '../../components/ConfirmDialog';
import useWriteAccess from '../../hooks/useWriteAccess';
import FormModal from '../../components/FormModal';
import { principalKey, errorMessage } from '../unitInventory/read';
import { useInventory } from '../inventory/useInventory';
import '../unitInventory/UnitInventory.css';

const roles = { tenant: 'Mieter', owner: 'Eigentümer', supplier: 'Dienstleister', manager: 'Verwalter' };
const configuration = {
  resource: 'contacts', filename: 'kontakte.csv', countFields: ['total', 'tenant', 'owner', 'supplier', 'manager', 'no_email', 'no_phone'],
  invalidMessage: 'Die Kontaktliste konnte nicht geprüft werden.',
  defaults: { search: '', contact_type: '', view: 'all', sort_by: 'display_name', sort_order: 'asc' },
};
const fields = [
  { key: 'first_name', label: 'Vorname' }, { key: 'last_name', label: 'Nachname' }, { key: 'company_name', label: 'Firma' },
  { key: 'email', label: 'E-Mail', type: 'email' }, { key: 'phone', label: 'Telefon' }, { key: 'mobile', label: 'Mobil' },
  { key: 'street', label: 'Straße' }, { key: 'zip_code', label: 'PLZ' }, { key: 'city', label: 'Stadt' },
  { key: 'country', label: 'Land', default: 'DE' }, { key: 'iban', label: 'IBAN' }, { key: 'bic', label: 'BIC' },
  { key: 'bank_name', label: 'Bank' }, { key: 'tax_id', label: 'Steuer-Nr.' }, { key: 'notes', label: 'Notizen', type: 'textarea' },
];

function Inventory({ principal }) {
  const listing = useInventory(principal, configuration);
  const { filters, change, state, page, failure, stats, summary } = listing;
  const confirm = useConfirm();
  const [modal, setModal] = useState(null); const [actionError, setActionError] = useState(null); const [opening, setOpening] = useState(false);
  const alive = useRef(true); const request = useRef(null);
  const { canWrite, isAllowed, requireWrite } = useWriteAccess('/contacts', () => setModal(null));
  useEffect(() => { alive.current = true; return () => { alive.current = false; request.current?.abort(); }; }, []);
  const open = async row => {
    if (!isAllowed()) return;
    request.current?.abort(); setActionError(null);
    if (!row) { setOpening(false); setModal('create'); return; }
    const controller = new AbortController(); request.current = controller; setOpening(true);
    try {
      const full = await api.get(`/contacts/${encodeURIComponent(row.id)}`, { signal: controller.signal });
      if (full?.id !== row.id) throw new Error('Der Kontakt konnte nicht geprüft werden.');
      if (!controller.signal.aborted && alive.current && isAllowed()) setModal(full);
    } catch (error) { if (!controller.signal.aborted && alive.current) setActionError(error); }
    finally { if (!controller.signal.aborted && alive.current) setOpening(false); }
  };
  const save = async data => {
    requireWrite(); if (!alive.current) throw new Error('Die Anmeldung wurde geändert.');
    if (modal === 'create') await api.post('/contacts', data);
    else await api.put(`/contacts/${encodeURIComponent(modal.id)}`, data, { ...revisionOptions(modal), ...revisionOptions(data) });
  };
  const remove = async row => {
    if (!isAllowed() || !await confirm(`„${row.display_name}“ wirklich löschen?`) || !alive.current || !isAllowed()) return;
    try { await api.del(`/contacts/${encodeURIComponent(row.id)}`, revisionOptions(row)); if (alive.current) listing.refresh(); }
    catch (error) { if (alive.current) setActionError(error); }
  };
  const changeFilter = (key, value) => { request.current?.abort(); setOpening(false); change(key, value); };
  const formFields = [{ key: 'contact_type', label: 'Rolle', type: 'select', default: 'tenant', required: true,
    options: Object.entries({ ...roles, ...(modal?.contact_type && !Object.hasOwn(roles, modal.contact_type) ? { [modal.contact_type]: modal.contact_type } : {}) }).map(([value, label]) => ({ value, label })) }, ...fields];
  return <div className="page unit-inventory">
    <header className="inventory-heading"><div><h1 className="page-title">Kontakte</h1><p className="text-muted">Personen und Unternehmen finden und ihre Angaben pflegen.</p></div>
      {canWrite && <button className="btn btn-primary" onClick={() => open(null)}>Kontakt anlegen</button>}</header>
    <section className="inventory-summary" aria-label="Kennzahlen der gefilterten Kontakte">
      {summary.loading ? <p role="status">Kennzahlen werden berechnet …</p> : stats ? [[stats.total, 'Kontakte'], [stats.tenant, 'Mieter'], [stats.owner, 'Eigentümer'], [stats.supplier, 'Dienstleister'], [stats.manager, 'Verwalter'], [stats.no_email, 'Ohne E-Mail'], [stats.no_phone, 'Ohne Telefon']].map(([value, label]) => <div className="panel" key={label}><strong>{value}</strong><span>{label}</span></div>)
        : <div role="alert">Kennzahlen nicht verfügbar. {errorMessage(summary.error)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    </section>
    <section className="panel inventory-filters" aria-label="Kontakte filtern">
      <label>Kontakte durchsuchen<input type="search" value={filters.search} onChange={event => changeFilter('search', event.target.value)} placeholder="Name, Firma, Ort oder Kontaktdaten" /></label>
      {[['contact_type', 'Rolle', [['', 'Alle Rollen'], ...Object.entries(roles)]],
        ['view', 'Prüfansicht', [['all', 'Alle Kontakte'], ['no_email', 'Ohne E-Mail'], ['no_phone', 'Ohne Telefon oder Mobilnummer'], ['unnamed', 'Ohne Name oder Firma']]],
        ['sort_by', 'Sortierung', [['display_name', 'Anzeigename'], ['last_name', 'Nachname'], ['first_name', 'Vorname'], ['company_name', 'Firma'], ['contact_type', 'Rolle'], ['city', 'Stadt'], ['email', 'E-Mail'], ['updated_at', 'Zuletzt geändert']]],
        ['sort_order', 'Reihenfolge', [['asc', 'Aufsteigend'], ['desc', 'Absteigend']]]].map(([key, label, values]) => <label key={key}>{label}<select aria-label={label} value={filters[key]} onChange={event => changeFilter(key, event.target.value)}>{values.map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></label>)}
      <button className="btn btn-secondary" onClick={listing.reset}>Filter zurücksetzen</button>
    </section>
    <div className="inventory-actions"><button className="btn btn-secondary" onClick={listing.refresh}>Aktualisieren</button><button className="btn btn-secondary" disabled={listing.exporting} onClick={listing.download}>{listing.exporting ? 'Export wird erstellt …' : 'Alle gefilterten Kontakte exportieren'}</button></div>
    {(actionError || listing.exportError) && <div role="alert" className="panel inventory-error">{errorMessage(actionError || listing.exportError)}</div>}
    {opening && <p role="status">Kontakt wird geöffnet …</p>}{state.loading && <p role="status">Kontakte werden geladen …</p>}
    {failure && <div role="alert" className="panel inventory-error">{errorMessage(failure)} <button className="btn btn-secondary" onClick={listing.refresh}>Erneut laden</button></div>}
    {page && <section className="panel inventory-results" aria-label="Gefilterte Kontakte">
      {!page.items.length ? <p>Keine passenden Kontakte auf dieser Seite.</p> : <div className="inventory-table-scroll" tabIndex={0} role="region" aria-label="Kontakttabelle horizontal scrollen"><table>
        <thead><tr>{['Name / Firma', 'Rolle', 'E-Mail', 'Telefon / Mobil', 'Ort', 'Aktionen'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead>
        <tbody>{page.items.map(row => <tr key={row.id}><th scope="row">{row.display_name}</th><td>{roles[row.contact_type] || row.contact_type}</td><td>{row.email || '—'}</td><td>{row.phone || '—'}{row.mobile && <p>Mobil: {row.mobile}</p>}</td>
          <td>{[row.zip_code, row.city, row.country].filter(Boolean).join(' ') || '—'}</td><td>{canWrite && <div className="inventory-actions"><button className="btn btn-secondary btn-sm" onClick={() => open(row)} aria-label={`${row.display_name} bearbeiten`}>Bearbeiten</button><button className="btn btn-secondary btn-sm" onClick={() => remove(row)} aria-label={`${row.display_name} löschen`}>Löschen</button></div>}</td></tr>)}</tbody>
      </table></div>}
      <nav className="inventory-pager" aria-label="Kontaktseiten"><button className="btn btn-secondary" disabled={listing.pageNumber === 1} onClick={listing.previous}>Vorherige Seite</button><span>Seite {listing.pageNumber}</span><button className="btn btn-secondary" disabled={!page.has_more} onClick={listing.next}>Nächste Seite</button></nav>
      <p className="text-muted">Kennzahlen und Export umfassen alle passenden Kontakte. Die CSV enthält allgemeine Kontaktdaten. Bankangaben, Steuerdaten und Notizen bleiben im jeweiligen Kontakt.</p>
    </section>}
    {modal && canWrite && <FormModal key={modal.id || 'create'} title={modal === 'create' ? 'Kontakt anlegen' : 'Kontakt bearbeiten'} fields={formFields} initial={modal === 'create' ? null : modal}
      draftConfig={{ collection: 'contacts' }} onSave={save} onSaved={() => { if (alive.current) listing.refresh(); }} onClose={() => setModal(null)} />}
  </div>;
}

export default function ContactInventory() {
  const principal = principalKey(useAuth()?.user);
  return <Inventory key={principal} principal={principal} />;
}
