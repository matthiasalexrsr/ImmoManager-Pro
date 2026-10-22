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

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    const id = encodeURIComponent(propertyId);
    Promise.all([api.get(`/ownership-shares/overview?property_id=${id}`, options),
      api.list(`/ownership-shares?property_id=${id}`, options), api.list('/ownership-shares/owners', options)])
      .then(([overview, shares, owners]) => { if (!controller.signal.aborted) setState({ loading: false, error: null, overview, shares, owners }); })
      .catch(error => { if (!controller.signal.aborted) setState(current => ({ ...current, loading: false, error: error.message })); });
    return () => controller.abort();
  }, [propertyId, revision]);

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
      {overview && <>
        <p><strong>Heute, ganzes Objekt:</strong> {owned(overview.common)} <span className="text-muted">({BASIS[overview.common_basis]})</span></p>
        {overview.units.length > 0 && <div className="dossier-table-scroll" role="region" aria-label="Eigentümer je Einheit" tabIndex={0}>
          <table className="simple-table"><caption className="sr-only">Eigentümer je Einheit heute</caption>
            <thead><tr><th scope="col">Einheit</th><th scope="col">Eigentümer heute</th><th scope="col">Grundlage</th></tr></thead>
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
        {owners.length === 0 && <Link className="btn btn-secondary" to="/contacts">Eigentümer im Adressbuch anlegen</Link>}</div>}
    </div>
    {modal && <FormModal title={modal === 'create' ? 'Eigentumsanteil erfassen' : 'Eigentumsanteil bearbeiten'} fields={fields}
      initial={modal === 'create' ? null : { ...modal, unit_id: modal.unit_id || '' }} onSave={save} onClose={() => setModal(null)} autosave={false} />}
  </div>;
}
