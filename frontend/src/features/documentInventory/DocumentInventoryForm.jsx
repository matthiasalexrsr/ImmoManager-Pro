import { useEffect, useRef } from 'react';
import FormModal from '../../components/FormModal';
import ReferenceChoice from '../unitInventory/ReferenceChoice';

function FileReference({ value, onChange, inputProps, uploadedUrl, onFileChange, uploading }) {
  const previousUpload = useRef(uploadedUrl);
  useEffect(() => {
    if (previousUpload.current === uploadedUrl) return;
    previousUpload.current = uploadedUrl;
    if (uploadedUrl) onChange(uploadedUrl);
  }, [uploadedUrl, onChange]);
  return <div className="inventory-reference"><label>Datei auswählen<input type="file" disabled={uploading || inputProps.disabled}
    onChange={event => onFileChange?.(event.target.files?.[0])} /></label>
    <input {...inputProps} type="hidden" value={value} />
    <p role="status">{uploading ? 'Datei wird verarbeitet …' : value ? 'Die hochgeladene Originaldatei ist für dieses Dokument vorgemerkt.' : 'Bitte eine Originaldatei auswählen. Angaben bleiben bei einem Uploadfehler erhalten.'}</p>
  </div>;
}

export default function DocumentInventoryForm({ initial, fields, principal, onSave, onClose, title, uploadedUrl, onFileChange, uploading }) {
  const referenceFields = [
    { key: 'property_id', label: 'Immobilie', type: 'select', onChange: () => ({ unit_id: '', contract_id: '' }),
      render: ({ value, onChange, inputProps }) => <ReferenceChoice kind="properties" label="Immobilie" value={value} onChange={onChange} principal={principal} disabled={inputProps.disabled} /> },
    { key: 'unit_id', label: 'Einheit', type: 'select', onChange: (value, values, row) => ({ property_id: row?.property_id || values.property_id, contract_id: '' }),
      render: ({ value, values, onChange, inputProps }) => <ReferenceChoice key={`units:${values.property_id}`} kind="units" label="Einheit" value={value} onChange={onChange} principal={principal} filters={{ property_id: values.property_id }} disabled={inputProps.disabled} /> },
    { key: 'contract_id', label: 'Vertrag', type: 'select', onChange: (value, values, row) => ({ property_id: row?.property_id || values.property_id, unit_id: row?.unit_id || values.unit_id }),
      render: ({ value, values, onChange, inputProps }) => <ReferenceChoice key={`contracts:${values.property_id}:${values.unit_id}`} kind="contracts" label="Vertrag" value={value} onChange={onChange} principal={principal} filters={{ property_id: values.property_id, unit_id: values.unit_id }} disabled={inputProps.disabled} /> },
  ];
  const formFields = [...referenceFields, ...fields.map(field => field.key === 'file_url' && !initial ? { ...field,
    render: props => <FileReference {...props} uploadedUrl={uploadedUrl} onFileChange={onFileChange} uploading={uploading} /> } : field)];
  return <FormModal initial={initial} fields={formFields} title={title} onClose={onClose} saveDisabled={uploading}
    draftConfig={{ collection: 'documents' }} onSave={onSave} />;
}
