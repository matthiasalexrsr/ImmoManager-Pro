import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, ArrowLeft, Camera, CheckCircle2, Download, FileText, Plus, Trash2, X } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useTranslation } from '../../i18n';
import { mayWrite } from '../../utils/permissions';
import { prepareUploadAccess } from '../../utils/uploadAccess';
import PdfPreview from '../../components/PdfPreview';
import { resolveFileUrl } from '../partyWorkspace/files';
import { useModalDialog } from '../partyWorkspace/useModalDialog';
import { handoverProtocolService } from './handoverProtocolApi';
import {
  CONDITIONS,
  KEY_TYPES,
  METER_TYPES,
  RESPONSIBLE,
  contentPayload,
  formatDay,
  formErrors,
  formFromDetail,
  formSignature,
  missingKeys,
  newDefect,
  newFreeReading,
  newId,
  newKey,
  newRoom,
  photosOf,
  protocolState,
} from './handoverProtocolModel';
import { handoverText } from './handoverProtocolText';
import './HandoverProtocol.css';

function PhotoStrip({ photos, label, editable, busy, onAdd, onRemove, say }) {
  const inputId = useId();
  return <div className="handover__photos" aria-label={label} role="group">
    {photos.map((photo, index) => <figure key={photo.id} className="handover__photo">
      <img src={resolveFileUrl(photo.file_url)} alt={photo.caption || `${say('photo')} ${index + 1}`} loading="lazy" />
      {photo.caption && <figcaption>{photo.caption}</figcaption>}
      {editable && <button type="button" className="handover__icon-button handover__photo-remove" disabled={busy}
        aria-label={`${say('removePhoto')} ${index + 1}`} onClick={() => onRemove(photo)}>
        <Trash2 size={14} aria-hidden="true" /></button>}
    </figure>)}
    {editable && <label className="btn btn-secondary btn-sm handover__photo-add" htmlFor={inputId}
      aria-disabled={busy || undefined}>
      <Camera size={15} aria-hidden="true" />{say('addPhoto')}
      <input id={inputId} type="file" accept="image/*" capture="environment" disabled={busy} aria-label={label}
        onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; if (file) onAdd(file); }} />
    </label>}
  </div>;
}

/**
 * One handover protocol: draft it (rooms, defects, keys, meters, photos), check it, finalize it
 * into an immutable original; a finalized one is shown with its original and can be corrected.
 */
export default function HandoverProtocolEditor({ protocolId, onClose, onChanged, service = handoverProtocolService }) {
  const auth = useAuth();
  const write = auth?.write ?? null;
  const { locale } = useTranslation();
  const say = useCallback((key, params) => handoverText(locale, key, params), [locale]);
  const titleId = useId();
  const dialogRef = useRef(null);
  const [currentId, setCurrentId] = useState(protocolId);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState(null);
  const [baseline, setBaseline] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [preview, setPreview] = useState(null);
  const [confirmed, setConfirmed] = useState({ content: false, signatures: false });
  const [pending, setPending] = useState(null);
  const [unknown, setUnknown] = useState(false);
  const [followUps, setFollowUps] = useState({});
  const [pdf, setPdf] = useState(null);
  const [askDiscard, setAskDiscard] = useState(false);
  const objectUrl = useRef(null);
  const controllers = useRef(new Set());
  const mounted = useRef(true);
  const canEdit = mayWrite(write, '/handover-protocols');
  const canFinalize = canEdit && mayWrite(write, '/documents') && mayWrite(write, '/meters');

  useEffect(() => {
    mounted.current = true;      // StrictMode runs setup twice: mark mounted on every setup
    const running = controllers.current;
    return () => {
      mounted.current = false;
      for (const controller of running) controller.abort();
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    };
  }, []);

  const showPdf = useCallback(next => {
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = next?.revoke ? next.url : null;
    setPdf(next);
  }, []);

  const apply = useCallback(next => {
    const nextForm = formFromDetail(next);
    setDetail(next);
    setForm(nextForm);
    setBaseline(formSignature(nextForm));
    setFollowUps(Object.fromEntries(next.defects.map(defect => [defect.id, {
      resolved_at: defect.resolved_at || '', resolution_note: defect.resolution_note || '' }])));
    setConflict(false);
  }, []);

  /** Run one request; its error becomes the dialog's message, its result is returned (undefined on failure). */
  const run = useCallback(async (name, operation) => {
    const controller = new AbortController();
    controllers.current.add(controller);
    setBusy(name);
    setError(null);
    setNotice(null);
    try {
      return await operation(controller.signal);
    } catch (failure) {
      if (controller.signal.aborted || failure?.name === 'AbortError' || !mounted.current) return undefined;
      if (failure?.statusCode === 409 && name === 'save') setConflict(true);
      setError(failure?.message?.startsWith('invalid_') ? say('loadFailed') : failure?.message || say('loadFailed'));
      return undefined;
    } finally {
      controllers.current.delete(controller);
      if (mounted.current) setBusy(current => (current === name ? null : current));
    }
  }, [say]);

  const load = useCallback(async () => {
    const next = await run('load', async signal => {
      const loaded = await service.load(currentId, { signal });
      // the thumbnails are protected uploads: the session cookie first
      if (loaded.photos.length) await prepareUploadAccess(resolveFileUrl(loaded.photos[0].file_url), { signal });
      return loaded;
    });
    if (next && mounted.current) apply(next);
    if (mounted.current) setLoading(false);
  }, [apply, currentId, run, service]);

  useEffect(() => { void load(); }, [load]);

  const dirty = Boolean(form) && formSignature(form) !== baseline;
  const editable = Boolean(detail?.state.editable) && canEdit;
  const previewValid = Boolean(preview && detail && !dirty && preview.revision === detail.protocol.revision);
  const locked = Boolean(busy) || unknown;
  const type = detail?.protocol.protocol_type;

  const change = updater => {
    if (!editable || locked) return;
    setForm(current => updater(current));
    setNotice(null);
  };
  const setField = (name, value) => change(current => ({ ...current, [name]: value }));
  const setRow = (list, id, patch) => change(current => ({
    ...current, [list]: current[list].map(row => (row.id === id ? { ...row, ...patch } : row)) }));
  const addRow = (list, row) => change(current => ({ ...current, [list]: [...current[list], row] }));
  const removeRow = (list, id) => change(current => ({
    ...current,
    [list]: current[list].filter(row => row.id !== id),
    // a defect of a removed room stays, as a general one
    defects: list === 'rooms' ? current.defects.map(d => (d.room_id === id ? { ...d, room_id: '' } : d)) : current.defects,
  }));

  const save = async () => {
    const problems = formErrors(form);
    if (problems.length) {
      setError(problems.map(code => say(`error_${code}`)).join(' '));
      return null;
    }
    const saved = await run('save', signal => service.save(currentId, contentPayload(form, detail.protocol.revision),
      { signal }));
    if (!saved) return null;
    apply(saved);
    setNotice(say('saved'));
    onChanged?.();
    return saved;
  };
  const ensureSaved = async () => (dirty ? save() : detail);

  const reloadKeepingNothing = async () => {
    setPreview(null);
    await load();
  };

  const addPhoto = async (file, links) => {
    if (!(await ensureSaved())) return;
    const uploaded = await run('upload', signal => service.uploadPhoto(currentId, file, links, { signal }));
    if (uploaded) {
      setPreview(null);
      await load();
    }
  };
  const removePhoto = async photo => {
    const removed = await run('photo', signal => service.deletePhoto(currentId, photo.id, { signal }).then(() => true));
    if (removed) {
      setPreview(null);
      await load();
    }
  };

  const check = async () => {
    if (!(await ensureSaved())) return;
    const result = await run('check', signal => service.preview(currentId, { signal }));
    if (!result) return;
    setPreview(result);
    setConfirmed({ content: false, signatures: false });
    setPending(null);
  };

  const openPreviewPdf = async () => {
    const url = await run('pdf', signal => service.previewPdfUrl(currentId, preview, { signal }));
    if (url) {
      if (!mounted.current) { URL.revokeObjectURL(url); return; }
      showPdf({ url, revoke: true, title: say('previewPdfTitle') });
    }
  };

  const finalize = async () => {
    if (!canFinalize || (!pending && !(previewValid && preview.ready && confirmed.content && confirmed.signatures))) {
      return;
    }
    // the exact command is kept: after a lost answer it is sent again unchanged
    const command = pending || { idempotencyKey: `handover:${newId()}`, reviewHash: preview.review_hash };
    setPending(command);
    const controller = new AbortController();
    controllers.current.add(controller);
    setBusy('finalize');
    setError(null);
    try {
      const final = await service.finalize(currentId, command, { signal: controller.signal });
      if (!mounted.current) return;
      apply(final);
      setPending(null);
      setPreview(null);
      setUnknown(false);
      setNotice(say('finalized'));
      onChanged?.();
    } catch (failure) {
      if (controller.signal.aborted || failure?.name === 'AbortError' || !mounted.current) return;
      if (failure?.isNetwork || failure?.statusCode >= 500) {
        setUnknown(true);
      } else {
        setPending(null);
        setUnknown(false);
        setError(failure?.message || say('loadFailed'));
      }
    } finally {
      controllers.current.delete(controller);
      if (mounted.current) setBusy(null);
    }
  };

  const startCorrection = async () => {
    const draft = await run('correction', signal => service.startCorrection(currentId, { signal }));
    if (!draft) return;
    setPreview(null);
    setCurrentId(draft.protocol.id);
    apply(draft);
    onChanged?.();
  };

  const saveFollowUp = async defect => {
    const next = await run('followup', signal => service.followUp(currentId, defect.id, followUps[defect.id], { signal }));
    if (next) {
      apply(next);
      setNotice(say('saved'));
    }
  };

  const download = () => run('download', signal => service.downloadOriginal(detail, { signal }));

  const closeNow = useCallback(() => {
    for (const controller of controllers.current) controller.abort();
    onClose?.();
  }, [onClose]);

  const requestClose = useCallback(() => {
    if (busy === 'finalize') return;
    if (pdf) { showPdf(null); return; }
    if (askDiscard) { setAskDiscard(false); return; }
    if ((dirty && editable) || unknown) { setAskDiscard(true); return; }
    closeNow();
  }, [askDiscard, busy, closeNow, dirty, editable, pdf, showPdf, unknown]);

  useModalDialog(dialogRef, requestClose, Boolean(currentId));

  const photos = detail?.photos || [];
  const strip = (field, id, label) => <PhotoStrip photos={photosOf(photos, field, id)} label={label}
    editable={editable} busy={locked} say={say} onRemove={removePhoto}
    onAdd={file => addPhoto(file, field ? { [{ room_id: 'roomId', defect_id: 'defectId',
      meter_reading_id: 'meterReadingId' }[field]]: id } : {})} />;
  const state = detail ? protocolState(detail.protocol) : null;
  const roomName = id => form?.rooms.find(room => room.id === id)?.name;

  return createPortal(
    <div className="handover__overlay" role="presentation"
      onMouseDown={event => { if (event.target === event.currentTarget) requestClose(); }}>
      <section className="handover" ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby={titleId}
        tabIndex={-1} aria-busy={Boolean(busy)}>
        <header className="handover__header">
          <div>
            <p className="handover__eyebrow">{say('eyebrow')}</p>
            <h2 id={titleId}>{pdf ? pdf.title : `${say('title')}${type ? ` – ${say(`type_${type}`)}` : ''}`}</h2>
            {detail && <p>{detail.source.contract.contract_number} · {detail.source.property.name} · {detail.source.unit.label}</p>}
          </div>
          <button type="button" className="handover__icon-button" aria-label={say('close')}
            disabled={busy === 'finalize'} onClick={requestClose}><X size={20} aria-hidden="true" /></button>
        </header>

        {pdf ? <div className="handover__pdf">
          <div><button type="button" className="btn btn-secondary btn-sm" onClick={() => showPdf(null)}>
            <ArrowLeft size={16} aria-hidden="true" />{say('back')}</button></div>
          <PdfPreview key={pdf.url} url={pdf.url} title={pdf.title} />
        </div> : <div className="handover__body">
          {askDiscard && <div className="handover__notice handover__notice--warning" role="alertdialog"
            aria-label={say('discardTitle')}>
            <AlertTriangle size={18} aria-hidden="true" />
            <div><strong>{say('discardTitle')}</strong><p>{say('discardPrompt')}</p></div>
            <div className="handover__actions">
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setAskDiscard(false)}>{say('keepEditing')}</button>
              <button type="button" className="btn btn-danger btn-sm" onClick={closeNow}>{say('discardConfirm')}</button>
            </div>
          </div>}
          {loading && <p role="status">{say('loading')}</p>}
          {error && <div className="handover__notice handover__notice--error" role="alert">
            <AlertTriangle size={18} aria-hidden="true" /><span>{error}</span>
            {!detail && <button type="button" className="btn btn-secondary btn-sm" onClick={() => void load()}>{say('retry')}</button>}
          </div>}
          {conflict && <div className="handover__notice handover__notice--warning" role="alert">
            <AlertTriangle size={18} aria-hidden="true" /><strong>{say('conflictTitle')}</strong>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => void reloadKeepingNothing()}>{say('reload')}</button>
          </div>}
          {unknown && <div className="handover__notice handover__notice--warning" role="alert">
            <AlertTriangle size={18} aria-hidden="true" />
            <div><strong>{say('unknownTitle')}</strong><p>{say('unknownBody')}</p></div>
            <button type="button" className="btn btn-primary btn-sm" disabled={busy === 'finalize'}
              onClick={() => void finalize()}>{say('retryExact')}</button>
          </div>}
          {notice && <div className="handover__notice handover__notice--success" role="status">
            <CheckCircle2 size={18} aria-hidden="true" /><span>{notice}</span></div>}

          {detail && form && <>
            <section className="handover__summary" aria-label={say('general')}>
              <div><span>{say('status')}</span><strong>{detail.state.superseded ? say('state_superseded') : say(`state_${state}`)}</strong></div>
              <div><span>{say('tenant')}</span><strong>{detail.source.tenant.full_name}</strong></div>
              <div><span>{say('contract')}</span><strong>{formatDay(detail.source.contract.start_date, locale)} – {formatDay(detail.source.contract.end_date, locale)}</strong></div>
            </section>
            {!canEdit && <p className="handover__muted" role="note">{say('readOnly')}</p>}
            {detail.state.legacy_status_finalized && <p className="handover__muted" role="note">{say('legacyFinalized')}</p>}
            {detail.correction_of && <p className="handover__muted" role="note">
              {say('correctionOf', { date: formatDay(detail.correction_of.protocol_date, locale) })} · {say('correctionHint')}</p>}

            {detail.original && <section className="handover__original" aria-label={say('original')}>
              <div className="handover__original-title"><FileText size={18} aria-hidden="true" />
                <strong>{say('original')}</strong><small>SHA-256 {detail.original.pdf_sha256?.slice(0, 16)}…</small></div>
              {detail.original.content_matches === false && <p role="alert">{say('contentMismatch')}</p>}
              <div className="handover__actions">
                <button type="button" className="btn btn-secondary btn-sm" disabled={locked}
                  onClick={() => showPdf({ url: resolveFileUrl(detail.original.file_url), revoke: false, title: say('originalPdfTitle') })}>
                  <FileText size={15} aria-hidden="true" />{say('openOriginal')}</button>
                <button type="button" className="btn btn-secondary btn-sm" disabled={locked} onClick={() => void download()}>
                  <Download size={15} aria-hidden="true" />{say('download')}</button>
                {canEdit && !detail.state.superseded && <button type="button" className="btn btn-secondary btn-sm"
                  disabled={locked} onClick={() => void startCorrection()}>{say('correction')}</button>}
              </div>
            </section>}

            <fieldset className="handover__section handover__grid" disabled={!editable || locked}>
              <legend>{say('general')}</legend>
              <label>{say('protocolDate')}<input type="date" value={form.protocol_date}
                onChange={event => setField('protocol_date', event.target.value)} /></label>
              <label>{say('overallCondition')}<select value={form.overall_condition}
                onChange={event => setField('overall_condition', event.target.value)}>
                <option value="">{say('notAssessed')}</option>
                {CONDITIONS.map(value => <option key={value} value={value}>{say(`condition_${value}`)}</option>)}
              </select></label>
              <label className="handover__check"><input type="checkbox" checked={form.tenant_present}
                onChange={event => setField('tenant_present', event.target.checked)} /><span>{say('tenantPresent')}</span></label>
              <label className="handover__check"><input type="checkbox" checked={form.landlord_present}
                onChange={event => setField('landlord_present', event.target.checked)} /><span>{say('landlordPresent')}</span></label>
              <label>{say('tenantSigner')}<input value={form.tenant_signature} autoComplete="off"
                onChange={event => setField('tenant_signature', event.target.value)} /></label>
              <label>{say('landlordSigner')}<input value={form.landlord_signature} autoComplete="off"
                onChange={event => setField('landlord_signature', event.target.value)} /></label>
              <label className="handover__wide">{say('notes')}<textarea rows="2" value={form.notes}
                onChange={event => setField('notes', event.target.value)} /></label>
            </fieldset>

            <fieldset className="handover__section" disabled={!editable || locked}>
              <legend>{say('rooms')}</legend>
              {form.rooms.length === 0 && <p className="handover__muted">{say('noRooms')}</p>}
              {form.rooms.map((room, index) => <article className="handover__row" key={room.id}>
                <div className="handover__grid">
                  <label>{say('roomName')}<input value={room.name} aria-label={`${say('roomName')} ${index + 1}`}
                    onChange={event => setRow('rooms', room.id, { name: event.target.value })} /></label>
                  <label>{say('condition')}<select value={room.condition} aria-label={`${say('condition')} ${index + 1}`}
                    onChange={event => setRow('rooms', room.id, { condition: event.target.value })}>
                    <option value="">{say('notAssessed')}</option>
                    {CONDITIONS.map(value => <option key={value} value={value}>{say(`condition_${value}`)}</option>)}
                  </select></label>
                  <label className="handover__wide">{say('notes')}<textarea rows="1" value={room.notes}
                    aria-label={`${say('notes')} ${say('roomName')} ${index + 1}`}
                    onChange={event => setRow('rooms', room.id, { notes: event.target.value })} /></label>
                </div>
                {strip('room_id', room.id, `${say('photos')} ${room.name || index + 1}`)}
                {editable && <button type="button" className="btn btn-secondary btn-sm handover__remove"
                  onClick={() => removeRow('rooms', room.id)}><Trash2 size={15} aria-hidden="true" />{say('removeRoom')}</button>}
              </article>)}
              {editable && <button type="button" className="btn btn-secondary btn-sm" onClick={() => addRow('rooms', newRoom())}>
                <Plus size={15} aria-hidden="true" />{say('addRoom')}</button>}
            </fieldset>

            <fieldset className="handover__section" disabled={!editable || locked}>
              <legend>{say('defects')}</legend>
              {form.defects.length === 0 && <p className="handover__muted">{say('noDefects')}</p>}
              {form.defects.map((defect, index) => <article className="handover__row" key={defect.id}>
                <div className="handover__grid">
                  <label>{say('defectRoom')}<select value={defect.room_id} aria-label={`${say('defectRoom')} ${index + 1}`}
                    onChange={event => setRow('defects', defect.id, { room_id: event.target.value })}>
                    <option value="">{say('generalRoom')}</option>
                    {form.rooms.map(room => <option key={room.id} value={room.id}>{room.name || '—'}</option>)}
                  </select></label>
                  <label>{say('responsible')}<select value={defect.responsible}
                    aria-label={`${say('responsible')} ${index + 1}`}
                    onChange={event => setRow('defects', defect.id, { responsible: event.target.value })}>
                    {RESPONSIBLE.map(value => <option key={value} value={value}>{say(`responsible_${value}`)}</option>)}
                  </select></label>
                  <label className="handover__wide">{say('description')}<textarea rows="2" value={defect.description}
                    aria-label={`${say('description')} ${index + 1}`}
                    onChange={event => setRow('defects', defect.id, { description: event.target.value })} /></label>
                  <label>{say('remedy')}<input value={defect.remedy} aria-label={`${say('remedy')} ${index + 1}`}
                    onChange={event => setRow('defects', defect.id, { remedy: event.target.value })} /></label>
                  <label>{say('dueDate')}<input type="date" value={defect.due_date} aria-label={`${say('dueDate')} ${index + 1}`}
                    onChange={event => setRow('defects', defect.id, { due_date: event.target.value })} /></label>
                </div>
                {strip('defect_id', defect.id, `${say('photos')} ${say('defects')} ${index + 1}`)}
                {editable && <button type="button" className="btn btn-secondary btn-sm handover__remove"
                  onClick={() => removeRow('defects', defect.id)}><Trash2 size={15} aria-hidden="true" />{say('removeDefect')}</button>}
              </article>)}
              {editable && <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => addRow('defects', newDefect())}><Plus size={15} aria-hidden="true" />{say('addDefect')}</button>}
            </fieldset>

            {detail.state.finalized && detail.defects.length > 0 && <section className="handover__section" aria-label={say('followUp')}>
              <h3>{say('followUp')}</h3>
              <p className="handover__muted">{say('followUpHint')}</p>
              {detail.defects.map((defect, index) => <article className="handover__row handover__grid" key={defect.id}>
                <strong className="handover__wide">{index + 1}. {defect.description}{defect.room_id ? ` (${roomName(defect.room_id)})` : ''}</strong>
                <label>{say('resolvedAt')}<input type="date" disabled={!canEdit || locked}
                  aria-label={`${say('resolvedAt')} ${index + 1}`} value={followUps[defect.id]?.resolved_at || ''}
                  onChange={event => setFollowUps(current => ({ ...current, [defect.id]: { ...current[defect.id], resolved_at: event.target.value } }))} /></label>
                <label>{say('resolutionNote')}<input disabled={!canEdit || locked} value={followUps[defect.id]?.resolution_note || ''}
                  aria-label={`${say('resolutionNote')} ${index + 1}`}
                  onChange={event => setFollowUps(current => ({ ...current, [defect.id]: { ...current[defect.id], resolution_note: event.target.value } }))} /></label>
                {canEdit && <button type="button" className="btn btn-secondary btn-sm" disabled={locked}
                  onClick={() => void saveFollowUp(defect)}>{say('saveFollowUp')}</button>}
              </article>)}
            </section>}

            <fieldset className="handover__section" disabled={!editable || locked}>
              <legend>{say('keys')}</legend>
              {form.keys.length === 0 && <p className="handover__muted">{say('noKeys')}</p>}
              {form.keys.map((key, index) => {
                const missing = type === 'move_out' ? missingKeys(key) : null;
                return <article className="handover__row handover__grid handover__grid--keys" key={key.id}>
                  <label>{say('keyType')}<select value={key.key_type} aria-label={`${say('keyType')} ${index + 1}`}
                    onChange={event => setRow('keys', key.id, { key_type: event.target.value })}>
                    {KEY_TYPES.map(value => <option key={value} value={value}>{say(`key_${value}`)}</option>)}
                  </select></label>
                  <label>{say('keyLabel')}<input value={key.label} aria-label={`${say('keyLabel')} ${index + 1}`}
                    onChange={event => setRow('keys', key.id, { label: event.target.value })} /></label>
                  <label>{type === 'move_out' ? say('handedOverMoveOut') : say('handedOver')}<input inputMode="numeric"
                    value={key.handed_over} aria-label={`${say('handedOver')} ${index + 1}`}
                    onChange={event => setRow('keys', key.id, { handed_over: event.target.value })} /></label>
                  {type === 'move_out' && <label>{say('returned')}<input inputMode="numeric" value={key.returned}
                    aria-label={`${say('returned')} ${index + 1}`}
                    onChange={event => setRow('keys', key.id, { returned: event.target.value })} /></label>}
                  {missing > 0 && <p className="handover__missing" role="status">{say('missingKeys', { count: missing })}</p>}
                  {editable && <button type="button" className="btn btn-secondary btn-sm handover__remove"
                    aria-label={`${say('removeKey')} ${index + 1}`} onClick={() => removeRow('keys', key.id)}>
                    <Trash2 size={15} aria-hidden="true" /></button>}
                </article>;
              })}
              {editable && <button type="button" className="btn btn-secondary btn-sm" onClick={() => addRow('keys', newKey())}>
                <Plus size={15} aria-hidden="true" />{say('addKey')}</button>}
            </fieldset>

            <fieldset className="handover__section" disabled={!editable || locked}>
              <legend>{say('meters')}</legend>
              <p className="handover__muted">{say('meterHint')}</p>
              {form.meters.length === 0 && <p className="handover__muted">{say('noMeters')}</p>}
              {form.meters.map((row, index) => <article className="handover__row" key={row.id}>
                {row.meter_id ? <p className="handover__meter-name">
                  <strong>{say(`meter_${row.meter_type}`)}</strong> {row.meter_number}{row.unit ? ` · ${row.unit}` : ''}
                  {row.last_reading && <small>{say('lastReading', { value: row.last_reading.value,
                    date: formatDay(row.last_reading.reading_date, locale) })}</small>}
                </p> : <div className="handover__grid">
                  <label>{say('meterType')}<select value={row.meter_type} aria-label={`${say('meterType')} ${index + 1}`}
                    onChange={event => setRow('meters', row.id, { meter_type: event.target.value })}>
                    {[...new Set([...METER_TYPES, row.meter_type])].map(value => <option key={value} value={value}>{say(`meter_${value}`)}</option>)}
                  </select></label>
                  <label>{say('meterNumber')}<input value={row.meter_number} aria-label={`${say('meterNumber')} ${index + 1}`}
                    onChange={event => setRow('meters', row.id, { meter_number: event.target.value })} /></label>
                  <p className="handover__muted handover__wide">{say('notInBilling')}</p>
                </div>}
                <div className="handover__grid">
                  <label>{say('meterValue')}<input inputMode="decimal" value={row.value}
                    aria-label={`${say('meterValue')} ${row.meter_number || index + 1}`}
                    onChange={event => setRow('meters', row.id, { value: event.target.value })} /></label>
                  {!row.meter_id && <label>{say('meterUnit')}<input value={row.unit} aria-label={`${say('meterUnit')} ${index + 1}`}
                    onChange={event => setRow('meters', row.id, { unit: event.target.value })} /></label>}
                  <label className={row.meter_id ? '' : 'handover__wide'}>{say('notes')}<input value={row.notes}
                    aria-label={`${say('notes')} ${say('meters')} ${index + 1}`}
                    onChange={event => setRow('meters', row.id, { notes: event.target.value })} /></label>
                </div>
                {String(row.value).trim() !== '' && strip('meter_reading_id', row.id, `${say('photos')} ${say('meters')} ${index + 1}`)}
                {editable && !row.meter_id && <button type="button" className="btn btn-secondary btn-sm handover__remove"
                  onClick={() => removeRow('meters', row.id)}><Trash2 size={15} aria-hidden="true" />{say('removeReading')}</button>}
              </article>)}
              {editable && <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => addRow('meters', newFreeReading())}><Plus size={15} aria-hidden="true" />{say('addFreeReading')}</button>}
            </fieldset>

            <section className="handover__section" aria-label={say('protocolPhotos')}>
              <h3>{say('protocolPhotos')}</h3>
              <p className="handover__muted">{say('photoHint')}</p>
              {strip(null, null, say('protocolPhotos'))}
              {busy === 'upload' && <p role="status">{say('uploading')}</p>}
            </section>

            {editable && <section className="handover__finish" aria-label={say('checkTitle')}>
              <div className="handover__actions">
                <button type="button" className="btn btn-primary" disabled={locked || !dirty} onClick={() => void save()}>{say('save')}</button>
                <button type="button" className="btn btn-secondary" disabled={locked} onClick={() => void check()}>{say('check')}</button>
                {dirty && <span className="handover__muted" role="status">{say('dirty')}</span>}
              </div>
              {preview && !previewValid && <p role="status">{say('previewInvalidated')}</p>}
              {preview && previewValid && <div className="handover__preview">
                <div className="handover__preview-title">
                  {preview.ready ? <CheckCircle2 size={19} aria-hidden="true" /> : <AlertTriangle size={19} aria-hidden="true" />}
                  <strong>{preview.ready ? say('ready') : say('notReady')}</strong>
                </div>
                <p>{say('counts', { rooms: preview.counts.rooms, defects: preview.counts.defects, keys: preview.counts.keys,
                  readings: preview.counts.meter_readings, photos: preview.counts.photos })}</p>
                {preview.problems.length > 0 && <ul className="handover__problems" aria-label={say('hints')}>
                  {preview.problems.map(problem => <li key={`${problem.code}:${problem.message}`}
                    className={problem.blocking ? 'handover__problem--blocking' : ''}>
                    {locale === 'de-DE' ? problem.message : handoverText(locale, `problem_${problem.code}`)}</li>)}
                </ul>}
                <button type="button" className="btn btn-secondary" disabled={locked} onClick={() => void openPreviewPdf()}>
                  <FileText size={16} aria-hidden="true" />{say('openPreviewPdf')}</button>
                {preview.ready && canFinalize && <>
                  <label className="handover__check"><input type="checkbox" checked={confirmed.content} disabled={locked}
                    onChange={event => setConfirmed(current => ({ ...current, content: event.target.checked }))} />
                    <span>{say('confirmContent')}</span></label>
                  <label className="handover__check"><input type="checkbox" checked={confirmed.signatures} disabled={locked}
                    onChange={event => setConfirmed(current => ({ ...current, signatures: event.target.checked }))} />
                    <span>{say('confirmSignatures')}</span></label>
                  <button type="button" className="btn btn-primary" disabled={locked || !confirmed.content || !confirmed.signatures}
                    onClick={() => void finalize()}>{say('finalize')}</button>
                </>}
              </div>}
            </section>}
          </>}
        </div>}

        <footer className="handover__footer">
          <button type="button" className="btn btn-secondary" disabled={busy === 'finalize'} onClick={requestClose}>{say('close')}</button>
        </footer>
      </section>
    </div>,
    document.body,
  );
}
