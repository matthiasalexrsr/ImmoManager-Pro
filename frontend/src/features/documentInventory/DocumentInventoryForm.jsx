import { useState } from 'react';
import FormModal from '../../components/FormModal';
import ReferenceChoice from '../unitInventory/ReferenceChoice';

export default function DocumentInventoryForm({ initial, fields, principal, onSave, onClose, title, uploadedUrl, onFileChange, uploading }) {
  const [refs, setRefs] = useState({ property_id: initial?.property_id || '', unit_id: initial?.unit_id || '', contract_id: initial?.contract_id || '' });
  const changeProperty = value => setRefs({ property_id: value, unit_id: '', contract_id: '' });
  const changeUnit = (value, row) => setRefs(current => ({ property_id: row?.property_id || current.property_id, unit_id: value, contract_id: '' }));
  const changeContract = (value, row) => setRefs(current => ({ property_id: row?.property_id || current.property_id, unit_id: row?.unit_id || current.unit_id, contract_id: value }));
  return <FormModal initial={initial} fields={fields} title={title} onClose={onClose} saveDisabled={uploading}
    onSave={payload => onSave({ ...payload, ...Object.fromEntries(Object.entries(refs).map(([key, value]) => [key, value || null])) })}>
    {!initial && <div className="inventory-reference"><label>Datei auswählen<input type="file" disabled={uploading}
      onChange={event => onFileChange?.(event.target.files?.[0])} /></label>
      <p role="status">{uploading ? 'Datei wird verarbeitet …' : uploadedUrl ? 'Die hochgeladene Originaldatei ist für dieses Dokument vorgemerkt.' : 'Bitte eine Originaldatei auswählen. Angaben bleiben bei einem Uploadfehler erhalten.'}</p></div>}
    <ReferenceChoice kind="properties" label="Immobilie" value={refs.property_id} onChange={changeProperty} principal={principal} />
    <ReferenceChoice key={`units:${refs.property_id}`} kind="units" label="Einheit" value={refs.unit_id} onChange={changeUnit}
      principal={principal} filters={{ property_id: refs.property_id }} />
    <ReferenceChoice key={`contracts:${refs.property_id}:${refs.unit_id}`} kind="contracts" label="Vertrag" value={refs.contract_id}
      onChange={changeContract} principal={principal} filters={{ property_id: refs.property_id, unit_id: refs.unit_id }} />
  </FormModal>;
}
