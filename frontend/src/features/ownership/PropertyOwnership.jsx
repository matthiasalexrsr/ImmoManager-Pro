import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useCanWrite } from '../../contexts/AuthContext';
import { useDataStore } from '../../contexts/DataStoreContext';
import FormModal from '../../components/FormModal';
import { useConfirm } from '../../components/ConfirmDialog';
import { formatDate } from '../../utils/format';

const percent = value => `${Number(value).toLocaleString('de-DE', { maximumFractionDigits: 4 })} %`;
const owned = rows => rows.map(row => `${row.name} ${percent(row.percent)}`).join(', ');
const KINDS = [['purchase', 'Kauf'], ['gift', 'Schenkung'], ['inheritance', 'Erbschaft'], ['division', 'Teilung'],
  ['sale_external', 'Verkauf an Dritte'], ['other', 'Sonstiger Wechsel']];
const ALL = '__all__';
const period = row => `${row.from ? `ab ${formatDate(row.from)}` : 'seit jeher'}${row.to ? ` bis ${formatDate(row.to)}` : ''}`;

// the receivers of a change: owner and their percentage of the part that changes hands
function receiversField(owners) {
  return function Receivers({ id, value, onChange, disabled }) {
    const rows = Array.isArray(value) && value.length ? value : [{ owner_contact_id: '', percent: 100 }];
    const set = (index, key, next) => onChange(rows.map((row, i) => (i === index ? { ...row, [key]: next } : row)));
    const total = rows.reduce((sum, row) => sum + Number(row.percent || 0), 0);
    return <fieldset id={id} className="checkbox-list" disabled={disabled}>
      {rows.map((row, index) => <div key={index} className="form-inline" style={{ display: 'flex', gap: '0.5rem', alignItems: 'center' }}>
        <select aria-label={`Empfänger ${index + 1}`} value={row.owner_contact_id} onChange={e => set(index, 'owner_contact_id', e.target.value)}>
          <option value="">Bitte wählen</option>{owners.map(owner => <option key={owner.id} value={owner.id}>{owner.name}</option>)}
        </select>
        <input aria-label={`Anteil von Empfänger ${index + 1} (%)`} type="number" min="0" max="100" step="0.0001" value={row.percent}
          onChange={e => set(index, 'percent', e.target.value)} style={{ width: '7rem' }} /> %
        {rows.length > 1 && <button type="button" className="btn btn-sm btn-ghost" onClick={() => onChange(rows.filter((_, i) => i !== index))}>Entfernen</button>}
      </div>)}
      <button type="button" className="btn btn-sm btn-secondary" onClick={() => onChange([...rows, { owner_contact_id: '', percent: 0 }])}>Empfänger hinzufügen</button>
      <span className={Math.abs(total - 100) > 0.00001 ? 'text-error' : 'text-muted'}> Zusammen {percent(total)} des übertragenen Teils</span>
    </fieldset>;
  };
}

const BASIS = {
  unit: 'eigene Anteile der Einheit', property: 'Anteile des Objekts', none: 'kein Eigentümer erfasst',
  area: 'nach Wohnfläche der Einheiten', units: 'gleich je Einheit (nicht alle Flächen erfasst)',
};

// Who owns the property and its units, and the shares behind it (services/ownership.py).
export default function PropertyOwnership({ propertyId, units }) {
  const canEdit = useCanWrite('/ownership-shares');
  const confirm = useConfirm();
  const store = useDataStore();
  const [state, setState] = useState({ loading: true, error: null, overview: null, shares: [], owners: [] });
  const [revision, setRevision] = useState(0);
  const [modal, setModal] = useState(null);
  const [changing, setChanging] = useState(false);
  const [asOf, setAsOf] = useState('');
  const [history, setHistory] = useState(null);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    const id = encodeURIComponent(propertyId);
    const day = asOf ? `&as_of=${encodeURIComponent(asOf)}` : '';
    Promise.all([api.get(`/ownership-shares/overview?property_id=${id}${day}`, options),
      api.list(`/ownership-shares?property_id=${id}`, options), api.list('/ownership-shares/owners', options),
      api.get(`/ownership-shares/history?property_id=${id}`, options)])
      .then(([overview, shares, owners, past]) => {
        if (controller.signal.aborted) return;
        setState({ loading: false, error: null, overview, shares, owners }); setHistory(past);
      })
      .catch(error => { if (!controller.signal.aborted) setState(current => ({ ...current, loading: false, error: error.message })); });
    return () => controller.abort();
  }, [propertyId, revision, asOf]);

  const refresh = () => { setRevision(value => value + 1); store?.invalidateRelated?.('owners'); };
  const { overview, shares, owners } = state;
  const ownerName = id => owners.find(owner => owner.id === id)?.name || 'Eigentümer';
  const unitLabel = id => (id ? units.find(unit => unit.id === id)?.label || 'Einheit' : 'Ganzes Objekt');
  const fields = [
    { key: 'owner_contact_id', label: 'Eigentümer', type: 'select', required: true,
      options: owners.map(owner => ({ value: owner.id, label: owner.name })),
      hint: owners.length ? 'Eigentümer sind Kontakte vom Typ „Eigentümer“ im Adressbuch.' : 'Zuerst im Adressbuch einen Kontakt vom Typ „Eigentümer“ anlegen.' },
    { key: 'unit_id', label: 'Gilt für', type: 'select',
      options: [{ value: '', label: 'Ganzes Objekt' }, ...units.map(unit => ({ value: unit.id, label: unit.label }))],
      hint: 'Eine Einheit mit eigenen Anteilen geht den Anteilen am ganzen Objekt vor.' },
    { key: 'share_percent', label: 'Anteil (%)', type: 'number', required: true, step: '0.0001',
      hint: 'Je Einheit oder Objekt zusammen höchstens 100 %. Ein Rest gehört „ohne Eigentümer“.' },
    { key: 'valid_from', label: 'Gilt ab', type: 'date', hint: 'Leer: seit jeher.' },
    { key: 'valid_to', label: 'Gilt bis', type: 'date', hint: 'Leer: bis auf Weiteres. Beide Tage zählen mit.' },
    { key: 'note', label: 'Notiz', type: 'textarea' },
  ];
  const save = async data => {
    const body = { ...data, property_id: propertyId, unit_id: data.unit_id || null, share_percent: Number(data.share_percent),
      valid_from: data.valid_from || null, valid_to: data.valid_to || null };
    if (modal === 'create') await api.post('/ownership-shares', body);
    else await api.put(`/ownership-shares/${encodeURIComponent(modal.id)}`, body);
    refresh();
  };
  const changeFields = [
    { key: 'kind', label: 'Art des Wechsels', type: 'select', required: true, default: 'purchase', options: KINDS.map(([value, label]) => ({ value, label })) },
    { key: 'effective_date', label: 'Wirksam ab', type: 'date', required: true,
      hint: 'Der erste Tag der neuen Eigentümer (Übergang von Nutzen und Lasten). Bisherige Anteile enden am Vortag.' },
    { key: 'from_owner_contact_id', label: 'Bisheriger Eigentümer (gibt ab)', type: 'select', required: true,
      options: owners.map(owner => ({ value: owner.id, label: owner.name })) },
    { key: 'place', label: 'Gilt für', type: 'select', default: '',
      options: [{ value: '', label: 'Ganzes Objekt (Anteile am Objekt)' }, ...units.map(unit => ({ value: unit.id, label: unit.label })),
        { value: ALL, label: 'Alles, was er an diesem Objekt hält (Objekt und Einheiten)' }] },
    { key: 'fraction_percent', label: 'Übertragener Teil seines Anteils (%)', type: 'number', step: '0.0001', default: 100, required: true,
      hint: '100: der ganze Anteil (Verkauf, Erbschaft). 50: die Hälfte, z. B. wenn ein Alleineigentümer mit einem neuen Miteigentümer teilt.' },
    { key: 'receivers', label: 'Neue Eigentümer (erhalten)', full: true, component: receiversField(owners), default: [{ owner_contact_id: '', percent: 100 }],
      hint: 'Ihre Prozente beziehen sich auf den übertragenen Teil und ergeben zusammen 100 %. Wer schon einen Anteil hält, erhält einen gemeinsamen Anteil. Bei „Verkauf an Dritte“ bleibt die Liste leer: dieser Teil gehört dann „ohne Eigentümer“.' },
    { key: 'note', label: 'Notiz (z. B. Urkunde, Erbschein)', type: 'textarea' },
  ];
  const saveChange = async data => {
    const all = data.place === ALL;
    await api.post('/ownership-shares/transfers', {
      property_id: propertyId, unit_id: all ? null : data.place || null, scope: all ? 'all' : 'object',
      effective_date: data.effective_date, from_owner_contact_id: data.from_owner_contact_id, kind: data.kind || 'purchase',
      fraction_percent: Number(data.fraction_percent ?? 100), note: data.note || null,
      receivers: data.kind === 'sale_external' ? [] : (data.receivers || []).filter(row => row.owner_contact_id)
        .map(row => ({ owner_contact_id: row.owner_contact_id, percent: Number(row.percent) })),
    });
    refresh();
  };
  const undo = async change => {
    if (!await confirm(`${change.kind_label} vom ${formatDate(change.effective_date)} rückgängig machen? Die Anteile werden wie vor dem Wechsel; der Wechsel bleibt im Verlauf vermerkt.`)) return;
    try {
      await api.post(`/ownership-shares/transfers/${encodeURIComponent(change.id)}/revert`, {});
      refresh();
    } catch (error) {
      setState(current => ({ ...current, error: error.message }));
    }
  };
  const remove = async share => {
    if (!await confirm(`Anteil von ${ownerName(share.owner_contact_id)} an „${unitLabel(share.unit_id)}“ löschen?`, { action: 'delete' })) return;
    await api.del(`/ownership-shares/${encodeURIComponent(share.id)}`);
    refresh();
  };

  if (state.loading) return <p role="status">Eigentumsanteile werden geladen …</p>;
  if (state.error) return <div className="alert alert-error" role="alert">{state.error} <button type="button" className="btn btn-sm btn-secondary" onClick={() => setRevision(value => value + 1)}>Erneut laden</button></div>;
  return <div className="panel">
    <div className="panel-header">Eigentümer und Anteile</div>
    <div className="panel-body">
      <p className="text-muted">Berichte, Budgets und Steuerauswertung teilen jeden Betrag nach diesen Anteilen: Geld einer Einheit nach deren Eigentümern, Geld des ganzen Objekts nach den Objektanteilen (sonst nach Wohnfläche der Einheiten). Eine Buchung kann auch einem Eigentümer allein gehören, etwa eine Entnahme.</p>
      <label className="form-inline" style={{ display: 'inline-flex', gap: '0.5rem', alignItems: 'center' }}>Stand am
        <input type="date" aria-label="Stand am" value={asOf} onChange={e => setAsOf(e.target.value)} />
        {asOf && <button type="button" className="btn btn-sm btn-ghost" onClick={() => setAsOf('')}>Heute</button>}</label>
      {overview && <>
        <p><strong>{asOf ? `Am ${formatDate(asOf)}` : 'Heute'}, ganzes Objekt:</strong> {owned(overview.common)} <span className="text-muted">({BASIS[overview.common_basis]})</span></p>
        {overview.units.length > 0 && <div className="dossier-table-scroll" role="region" aria-label="Eigentümer je Einheit" tabIndex={0}>
          <table className="simple-table"><caption className="sr-only">Eigentümer je Einheit heute</caption>
            <thead><tr><th scope="col">Einheit</th><th scope="col">{asOf ? `Eigentümer am ${formatDate(asOf)}` : 'Eigentümer heute'}</th><th scope="col">Grundlage</th></tr></thead>
            <tbody>{overview.units.map(unit => <tr key={unit.unit_id}><th scope="row"><Link to={`/units/${encodeURIComponent(unit.unit_id)}`}>{unit.label}</Link></th>
              <td>{owned(unit.owners)}</td><td>{BASIS[unit.basis]}</td></tr>)}</tbody></table></div>}
      </>}
      <h3>Erfasste Anteile</h3>
      {shares.length === 0 ? <p>Noch keine Anteile erfasst: alles gehört „ohne Eigentümer“.</p> :
        <div className="dossier-table-scroll" role="region" aria-label="Erfasste Anteile" tabIndex={0}>
          <table className="simple-table"><caption className="sr-only">Erfasste Eigentumsanteile</caption>
            <thead><tr><th scope="col">Eigentümer</th><th scope="col">Gilt für</th><th scope="col" className="num">Anteil</th><th scope="col">Gültig</th><th scope="col">Notiz</th>{canEdit && <th scope="col"><span className="sr-only">Aktionen</span></th>}</tr></thead>
            <tbody>{shares.map(share => <tr key={share.id}>
              <th scope="row">{ownerName(share.owner_contact_id)}</th><td>{unitLabel(share.unit_id)}</td><td className="num">{percent(share.share_percent)}</td>
              <td>{share.valid_from ? `ab ${formatDate(share.valid_from)}` : 'seit jeher'}{share.valid_to ? ` bis ${formatDate(share.valid_to)}` : ''}</td><td>{share.note || '—'}</td>
              {canEdit && <td><button type="button" className="btn btn-sm btn-ghost" onClick={() => setModal(share)}>Bearbeiten</button>
                <button type="button" className="btn btn-sm btn-ghost" onClick={() => remove(share)}>Löschen</button></td>}
            </tr>)}</tbody></table></div>}
      {canEdit && <div className="dossier-actions"><button type="button" className="btn btn-primary" onClick={() => setModal('create')}>Anteil erfassen</button>
        {shares.length > 0 && <button type="button" className="btn btn-secondary" onClick={() => setChanging(true)}>Eigentümerwechsel erfassen</button>}
        {owners.length === 0 && <Link className="btn btn-secondary" to="/contacts">Eigentümer im Adressbuch anlegen</Link>}</div>}
      {history && (history.transfers.length > 0 || history.objects.some(object => object.periods.length > 1)) && <>
        <h3>Verlauf</h3>
        {history.objects.filter(object => object.periods.length > 1 || object.periods[0]?.owners.some(o => o.owner_contact_id)).map(object =>
          <div key={object.unit_id || 'property'} className="dossier-table-scroll" role="region" aria-label={`Verlauf ${object.label}`} tabIndex={0}>
            <table className="simple-table"><caption>{object.label}</caption>
              <thead><tr><th scope="col">Zeitraum</th><th scope="col">Eigentümer</th></tr></thead>
              <tbody>{object.periods.map(row => <tr key={row.from || 'start'}><th scope="row">{period(row)}</th><td>{owned(row.owners)}</td></tr>)}</tbody></table></div>)}
        {history.transfers.length > 0 && <ul aria-label="Eigentümerwechsel">{history.transfers.map(change => <li key={change.id} className={change.reverted_at ? 'text-muted' : undefined}>
          {change.reverted_at ? <del>{formatDate(change.effective_date)} · {change.kind_label}</del> : <>{formatDate(change.effective_date)} · {change.kind_label}</>}: {change.from_name} → {change.receivers.length ? change.receivers.map(r => `${r.name} (${percent(r.percent)})`).join(', ') : 'Dritte'}
          {' '}({percent(change.fraction_percent)} des Anteils{change.scope === 'all' ? ' am ganzen Bestand im Objekt' : change.unit_label ? ` an ${change.unit_label}` : ' am Objekt'}){change.note ? ` – ${change.note}` : ''}
          {change.reverted_at && ` – rückgängig gemacht am ${formatDate(change.reverted_at)}`}
          {canEdit && change.revertible && <>{' '}<button type="button" className="btn btn-sm btn-ghost" onClick={() => undo(change)}>Rückgängig machen</button></>}</li>)}</ul>}
      </>}
    </div>
    {changing && <FormModal title="Eigentümerwechsel erfassen" fields={changeFields} initial={null} onSave={saveChange}
      onClose={() => setChanging(false)} autosave={false} />}
    {modal && <FormModal title={modal === 'create' ? 'Eigentumsanteil erfassen' : 'Eigentumsanteil bearbeiten'} fields={fields}
      initial={modal === 'create' ? null : { ...modal, unit_id: modal.unit_id || '' }} onSave={save} onClose={() => setModal(null)} autosave={false} />}
  </div>;
}
