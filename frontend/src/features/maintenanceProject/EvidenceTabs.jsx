import { useCallback, useRef, useState } from 'react';
import FileViewer from '../../components/FileViewer';
import PhotoDropZone from '../../components/PhotoDropZone';
import { api } from '../../api';
import { commandKey, projectApi } from './projectApi';
import { choices, day } from './projectFormat';
import { Empty, Modal, PdfDialog, PickerDialog, Pill, Section } from './ProjectUi';
import { fill } from './text';

const BASE = import.meta.env.VITE_API_URL || '/api/v1';
const PROTOCOL_TYPES = ['acceptance', 'inspection', 'site_visit'];
const RESULTS = ['accepted', 'accepted_with_defects', 'refused'];
const SEVERITIES = ['minor', 'major', 'critical'];
const DOC_ROLES = ['damage_photo', 'quote', 'order', 'invoice', 'protocol', 'report', 'other'];
const emptyDefect = () => ({ title: '', location: '', severity: 'minor', due_date: '', description: '', photo_ids: [] });
const orNull = value => (value === '' || value === undefined ? null : value);

function ProtocolDialog({ ctx, protocol, onClose }) {
  const { project, caseId, tx } = ctx;
  const [values, setValues] = useState(() => ({
    protocol_type: protocol?.protocol_type || 'acceptance',
    protocol_date: protocol?.protocol_date || new Date().toISOString().slice(0, 10),
    title: protocol?.title || '', participants: protocol?.participants || '', result: protocol?.result || '',
    notes: protocol?.notes || '', work_package_id: protocol?.work_package_id || '', order_id: protocol?.order_id || '',
    photo_ids: protocol?.photo_ids || [],
    defects: (protocol?.defects || []).map(defect => ({ ...emptyDefect(), ...defect,
      location: defect.location || '', due_date: defect.due_date || '', description: defect.description || '' })),
  }));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const set = (key, value) => setValues(current => ({ ...current, [key]: value }));
  const setDefect = (index, key, value) => setValues(current => ({
    ...current, defects: current.defects.map((defect, i) => (i === index ? { ...defect, [key]: value } : defect)) }));
  const toggle = (list, id) => (list.includes(id) ? list.filter(item => item !== id) : [...list, id]);
  const photos = project.photos;
  const photoLabel = (photo, index) => photo.caption || `${tx.photos} ${index + 1}`;

  const submit = async event => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    const payload = {
      ...values, title: orNull(values.title), participants: orNull(values.participants), result: orNull(values.result),
      notes: orNull(values.notes), work_package_id: orNull(values.work_package_id), order_id: orNull(values.order_id),
      defects: values.defects.map(defect => ({ ...defect, location: orNull(defect.location), due_date: orNull(defect.due_date),
        description: orNull(defect.description) })),
    };
    try {
      if (protocol) await projectApi.updateProtocol(caseId, protocol.id, payload);
      else await projectApi.addProtocol(caseId, payload);
      onClose(true);
    } catch (failure) {
      setError(failure.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={protocol ? tx.editProtocol : tx.addProtocol} onClose={() => onClose(false)} wide>
      <form onSubmit={submit}>
        <div className="modal-body mp-protocol-form">
          {error && <div className="alert-error" role="alert">{error}</div>}
          <div className="mp-form-grid">
            <label className="form-group">{tx.protocolType}
              <select value={values.protocol_type} onChange={event => set('protocol_type', event.target.value)} required>
                {choices(tx, 'ptype_', PROTOCOL_TYPES).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="form-group">{tx.protocolDate}
              <input type="date" value={values.protocol_date} onChange={event => set('protocol_date', event.target.value)} required />
            </label>
            <label className="form-group">{tx.result}
              <select value={values.result} onChange={event => set('result', event.target.value)}>
                <option value="">{tx.noResult}</option>
                {choices(tx, 'result_', RESULTS).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </label>
            <label className="form-group">{tx.title}
              <input value={values.title} onChange={event => set('title', event.target.value)} />
            </label>
            <label className="form-group">{tx.workPackage}
              <select value={values.work_package_id} onChange={event => set('work_package_id', event.target.value)}>
                <option value="">—</option>
                {project.work_packages.map(wp => <option key={wp.id} value={wp.id}>{wp.title}</option>)}
              </select>
            </label>
            <label className="form-group">{tx.order}
              <select value={values.order_id} onChange={event => set('order_id', event.target.value)}>
                <option value="">—</option>
                {project.orders.filter(o => o.status !== 'cancelled').map(o => (
                  <option key={o.id} value={o.id}>{[o.order_number, o.supplier_name].filter(Boolean).join(' · ')}</option>
                ))}
              </select>
            </label>
            <label className="form-group form-group-full">{tx.participants}
              <input value={values.participants} onChange={event => set('participants', event.target.value)} />
            </label>
            <label className="form-group form-group-full">{tx.notes}
              <textarea rows={3} value={values.notes} onChange={event => set('notes', event.target.value)} />
            </label>
          </div>

          <fieldset className="mp-fieldset">
            <legend>{tx.defects}</legend>
            {values.defects.map((defect, index) => (
              <div key={index} className="mp-defect">
                <div className="mp-form-grid">
                  <label className="form-group">{tx.defectTitle} {index + 1}
                    <input value={defect.title} required onChange={event => setDefect(index, 'title', event.target.value)} />
                  </label>
                  <label className="form-group">{tx.location}
                    <input value={defect.location} onChange={event => setDefect(index, 'location', event.target.value)} />
                  </label>
                  <label className="form-group">{tx.severity}
                    <select value={defect.severity} onChange={event => setDefect(index, 'severity', event.target.value)}>
                      {choices(tx, 'severity_', SEVERITIES).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                  </label>
                  <label className="form-group">{tx.defectDue}
                    <input type="date" value={defect.due_date} onChange={event => setDefect(index, 'due_date', event.target.value)} />
                  </label>
                </div>
                {photos.length > 0 && (
                  <div className="mp-photo-choice" role="group" aria-label={`${tx.photos}: ${tx.defectTitle} ${index + 1}`}>
                    {photos.map((photo, photoIndex) => (
                      <label key={photo.id} className="mp-check">
                        <input type="checkbox" checked={defect.photo_ids.includes(photo.id)}
                          onChange={() => setDefect(index, 'photo_ids', toggle(defect.photo_ids, photo.id))} />
                        {photoLabel(photo, photoIndex)}
                      </label>
                    ))}
                  </div>
                )}
                <button type="button" className="btn btn-ghost btn-sm"
                  onClick={() => set('defects', values.defects.filter((_, i) => i !== index))}>{tx.remove}</button>
              </div>
            ))}
            <button type="button" className="btn btn-secondary btn-sm"
              onClick={() => set('defects', [...values.defects, emptyDefect()])}>{tx.addDefect}</button>
          </fieldset>

          <fieldset className="mp-fieldset">
            <legend>{tx.photos}</legend>
            {photos.length === 0 ? <Empty>{tx.noPhotos}</Empty> : (
              <div className="mp-photo-choice">
                {photos.map((photo, index) => (
                  <label key={photo.id} className="mp-check">
                    <input type="checkbox" checked={values.photo_ids.includes(photo.id)}
                      onChange={() => set('photo_ids', toggle(values.photo_ids, photo.id))} />
                    {photoLabel(photo, index)}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
        </div>
        <div className="modal-footer">
          <button type="button" className="btn btn-secondary" onClick={() => onClose(false)}>{tx.cancel}</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>{tx.save}</button>
        </div>
      </form>
    </Modal>
  );
}

export function ProtocolsTab({ ctx }) {
  const { project, caseId, tx, can, act, busy, reload } = ctx;
  const [editing, setEditing] = useState(null);
  const [pdf, setPdf] = useState(null);
  const keys = useRef({});     // a retried finalize (lost answer) repeats the same command
  const loadPdf = useCallback(options => projectApi.protocolPdf(caseId, pdf?.id, options), [caseId, pdf?.id]);

  const finalize = protocol => {
    if (!keys.current[protocol.id]) keys.current[protocol.id] = commandKey(`protocol-${protocol.id.slice(0, 8)}`);
    act(async () => {
      await projectApi.finalizeProtocol(caseId, protocol.id, keys.current[protocol.id]);
      delete keys.current[protocol.id];
    }, tx.finalized, tx.finalizeConfirm);
  };

  return (
    <Section id="mp-protocols" title={tx.tabProtocols}
      actions={can.write_protocols && <button type="button" className="btn btn-primary btn-sm" onClick={() => setEditing({})}>{tx.addProtocol}</button>}>
      {project.protocols.length === 0 ? <Empty>{tx.noProtocols}</Empty> : (
        <ul className="mp-cards">
          {project.protocols.map(protocol => (
            <li key={protocol.id} className="mp-card">
              <div className="mp-card-head">
                <div className="mp-row-main">
                  <strong>{tx[`ptype_${protocol.protocol_type}`]} · {day(protocol.protocol_date)}</strong>
                  <span className="text-muted">
                    {[protocol.title, protocol.result ? tx[`result_${protocol.result}`] : null,
                      fill(tx.defectCount, { count: protocol.defects.length }), protocol.participants].filter(Boolean).join(' · ')}
                  </span>
                </div>
                <Pill tone={protocol.status === 'final' ? 'green' : 'gray'}>{protocol.status === 'final' ? tx.final : tx.draft}</Pill>
              </div>
              {protocol.status === 'final' && (
                <p className="mp-meta">
                  <Pill tone={protocol.integrity === 'verified' ? 'green' : 'red'}>{tx[`integrity_${protocol.integrity}`]}</Pill>
                </p>
              )}
              <div className="mp-actions">
                <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPdf(protocol)}>
                  {protocol.status === 'final' ? tx.showPdf : tx.preview}
                </button>
                {protocol.status === 'draft' && can.write_protocols && (
                  <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(protocol)}>{tx.edit}</button>
                )}
                {protocol.status === 'draft' && can.finalize_protocols && (
                  <button type="button" className="btn btn-primary btn-sm" disabled={busy} onClick={() => finalize(protocol)}>{tx.finalize}</button>
                )}
                {protocol.status === 'draft' && can.write_protocols && (
                  <button type="button" className="btn btn-ghost btn-sm"
                    onClick={() => act(() => projectApi.deleteProtocol(caseId, protocol.id), null, tx.confirmDeleteProtocol)}>{tx.delete}</button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
      {editing && (
        <ProtocolDialog ctx={ctx} protocol={editing.id ? editing : null}
          onClose={saved => { setEditing(null); if (saved) reload(); }} />
      )}
      {pdf && <PdfDialog title={tx.pdfTitle} load={loadPdf} onClose={() => setPdf(null)} />}
    </Section>
  );
}

async function uploadFile(file) {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${BASE}/files/upload?folder=documents`, {
    method: 'POST', body: formData, credentials: 'include',
    headers: { Authorization: `Bearer ${localStorage.getItem('access_token')}` },
  });
  if (!response.ok) {
    const failure = await response.json().catch(() => ({}));
    throw new Error(failure?.error?.message || failure?.detail || 'Upload');
  }
  const data = await response.json();
  if (!data.file_url) throw new Error('Upload');
  return data.file_url;
}

export function DocumentsTab({ ctx }) {
  const { project, caseId, tx, can, act, reload } = ctx;
  const record = project.case;
  const [viewer, setViewer] = useState(null);
  const [picker, setPicker] = useState(false);
  const [role, setRole] = useState('other');
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState(null);
  const fileRef = useRef(null);
  const loadDocuments = useCallback(async (params, options) => {
    const rows = await api.get(`/documents?property_id=${encodeURIComponent(record.property_id)}&skip=${params.skip}`
      + `&limit=${params.limit + 1}&sort_by=created_at&sort_order=desc`, options);
    const linked = new Set(project.documents.map(entry => entry.document.id));
    const q = (params.q || '').toLocaleLowerCase();
    const page = (rows || []).slice(0, params.limit);
    return {
      items: page.filter(doc => !linked.has(doc.id) && (!q || `${doc.title} ${doc.document_type || ''}`.toLocaleLowerCase().includes(q))),
      has_more: (rows || []).length > params.limit,
    };
  }, [record.property_id, project.documents]);

  const upload = async file => {
    if (!file) return;
    setUploading(true);
    setUploadError(null);
    try {
      const fileUrl = await uploadFile(file);
      const document = await api.post('/documents', {
        title: file.name, file_url: fileUrl, property_id: record.property_id, unit_id: record.unit_id || null,
        document_type: 'maintenance', description: record.title,
      });
      await projectApi.linkDocument(caseId, { document_id: document.id, role });
      reload();
    } catch (failure) {
      setUploadError(`${tx.uploadFailed}: ${failure.message}`);
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  return (
    <div className="mp-stack">
      <Section id="mp-documents" title={tx.documents} actions={can.documents && (
        <>
          <label className="mp-inline">{tx.docRole}
            <select value={role} onChange={event => setRole(event.target.value)}>
              {choices(tx, 'docRole_', DOC_ROLES).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>
          <button type="button" className="btn btn-primary btn-sm" disabled={uploading} onClick={() => fileRef.current?.click()}>
            {uploading ? tx.uploading : tx.uploadDocument}
          </button>
          <input ref={fileRef} type="file" hidden aria-label={tx.file} onChange={event => upload(event.target.files?.[0])} />
          <button type="button" className="btn btn-secondary btn-sm" onClick={() => setPicker(true)}>{tx.linkDocument}</button>
        </>
      )}>
        {uploadError && <div className="alert-error" role="alert">{uploadError}</div>}
        {project.documents.length === 0 ? <Empty>{tx.noDocuments}</Empty> : (
          <ul className="mp-list">
            {project.documents.map(entry => (
              <li key={entry.document.id} className="mp-row">
                <div className="mp-row-main">
                  <button type="button" className="dossier-document-link" onClick={() => setViewer(entry.document)}>{entry.document.title}</button>
                  <span className="text-muted">
                    {[tx[`docRole_${entry.role}`] || entry.role, day(entry.document.document_date || entry.document.created_at)].join(' · ')}
                  </span>
                </div>
                {entry.link_id && can.documents && (
                  <button type="button" className="btn btn-ghost btn-sm"
                    onClick={() => act(() => projectApi.unlinkDocument(caseId, entry.link_id), null, tx.confirmUnlinkDocument)}>{tx.unlink}</button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section id="mp-photos" title={tx.damagePhotos}>
        <PhotoDropZone entityType="maintenance" entityId={caseId} onChange={reload} />
      </Section>
      {picker && (
        <PickerDialog title={tx.linkDocument} load={loadDocuments} onClose={() => setPicker(false)}
          onPick={document => { setPicker(false); act(() => projectApi.linkDocument(caseId, { document_id: document.id, role })); }}
          renderItem={document => (
            <>
              <strong>{document.title}</strong>
              <span className="text-muted">{[document.document_type, day(document.document_date)].filter(Boolean).join(' · ')}</span>
            </>
          )} />
      )}
      {viewer && <FileViewer key={viewer.id} fileUrl={viewer.file_url} title={viewer.title} onClose={() => setViewer(null)} />}
    </div>
  );
}
