import { useState } from 'react';
import DisputeReferenceChoice from './DisputeReferenceChoice';
import { PAGE_SIZE, readVersionPage } from './disputeModel';
import { DisputeFailure } from './DisputeOriginals';
import useDisputeRead from './useDisputeRead';

function Versions({ documentId, principal, value, onChange, disabled, tr, onDenied }) {
  const [trail, setTrail] = useState([null]); const [retry, setRetry] = useState(0);
  const before = trail.at(-1);
  const state = useDisputeRead(`/documents/${encodeURIComponent(documentId)}/versions?limit=${PAGE_SIZE}${before ? `&before=${before}` : ''}`,
    principal, retry, row => readVersionPage(row, documentId), onDenied);
  return <section aria-label={tr('chooseVersion')}><h4>{tr('chooseVersion')}</h4>
    {state.loading && <p role="status">{tr('loading')}</p>}
    {state.error && <DisputeFailure error={state.error} tr={tr} onRetry={() => setRetry(count => count + 1)} />}
    {state.data && <>{!state.data.items.length ? <p>{tr('noVersions')}</p> : <ul className="dispute-version-list">{state.data.items.map(row => <li key={row.id}>
      <button type="button" className="btn btn-secondary" disabled={disabled || value.includes(row.id)} aria-pressed={value.includes(row.id)} onClick={() => onChange([...value, row.id])}>
        {tr('version')} {row.number} · {row.filename}</button><small>{row.created_at}</small>
      <details><summary>{tr('technical')}</summary><dl><dt>SHA-256</dt><dd>{row.sha256}</dd><dt>{tr('revision')}</dt><dd>{row.id}</dd></dl></details>
    </li>)}</ul>}
    <nav className="dispute-actions" aria-label={tr('chooseVersion')}><button type="button" className="btn btn-secondary" disabled={disabled || trail.length === 1} onClick={() => setTrail(trail.slice(0, -1))}>{tr('previous')}</button><span>{tr('page')} {trail.length}</span>
      <button type="button" className="btn btn-secondary" disabled={disabled || state.data.next_before === null} onClick={() => setTrail([...trail, state.data.next_before])}>{tr('next')}</button></nav></>}
  </section>;
}

/** Only immutable selected version IDs become command values; never file URLs. */
export default function OriginalEvidencePicker({ propertyId, principal, value = [], onChange, disabled = false, tr, onDenied }) {
  const [documentId, setDocumentId] = useState('');
  return <fieldset disabled={disabled} className="dispute-evidence-picker"><legend>{tr('evidence')}</legend>
    {value.length > 0 && <><p>{tr('selectedVersions')}: {value.length}. {tr('verifyVersions')}</p><ul>{value.map((id, index) => <li key={id}>
      <span>{tr('version')} {index + 1}</span><button className="btn btn-secondary" type="button" onClick={() => onChange(value.filter(item => item !== id))}>{tr('remove')}</button>
      <details><summary>{tr('technical')}</summary><code>{id}</code></details></li>)}</ul></>}
    <DisputeReferenceChoice kind="documents" label={tr('chooseDocument')} principal={principal} filters={{ property_id: propertyId }} value={documentId} onChange={setDocumentId} disabled={disabled} tr={tr} onDenied={onDenied} />
    {documentId && <Versions key={documentId} documentId={documentId} principal={principal} value={value} onChange={onChange} disabled={disabled} tr={tr} onDenied={onDenied} />}
  </fieldset>;
}
