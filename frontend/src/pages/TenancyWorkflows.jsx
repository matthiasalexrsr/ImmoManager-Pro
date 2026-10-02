import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { useTranslation } from '../i18n';
import CursorReferencePicker from '../components/CursorReferencePicker';
import { createCommand, isReviewRequired, isUnknownOutcome, tenancyWorkflowApi } from '../tenancyWorkflowApi';
import { workflowText } from '../tenancyWorkflowText';
import './TenancyWorkflows.css';

const ROLES = ['eigentuemer', 'verwalter', 'techniker', 'buchhaltung'];
const EVIDENCE = ['none', 'document_original', 'handover_protocol', 'meter_reading'];
const ANCHORS = ['previous_contract_end', 'next_contract_start', 'move_out_handover', 'move_in_handover'];

function legacyLoader(path, filter = () => true, labelFilter = () => true) {
  return async ({ after, limit = 25, signal }) => {
    const skip = Number(after || 0);
    const separator = path.includes('?') ? '&' : '?';
    const rows = await api.get(`${path}${separator}skip=${skip}&limit=${limit}`, { signal });
    const items = (Array.isArray(rows) ? rows : []).filter(filter).filter(labelFilter);
    return { items, next_cursor: rows?.length === limit ? String(skip + limit) : null, has_more: rows?.length === limit };
  };
}

function CursorCards({ items, empty, hasMore, loading, onMore, children, moreLabel }) {
  return <>{items.length ? <div className="workflow-card-grid">{items.map(children)}</div>
    : !loading && <div className="workflow-empty">{empty}</div>}
    {hasMore && <button className="btn btn-secondary" type="button" onClick={onMore} disabled={loading}>{moreLabel}</button>}</>;
}

function Status({ value, text }) {
  return <span className={`workflow-status workflow-status-${value || 'unknown'}`}>{text[value] || value || '—'}</span>;
}

function allows(actions, key) {
  return Array.isArray(actions) ? actions.includes(key) : Boolean(actions?.[key]);
}

function EvidenceControls({ step, text, documentLoader, onTask, onEvidence }) {
  const [kind, setKind] = useState('document_version');
  const [documentId, setDocumentId] = useState(null);
  const [versionId, setVersionId] = useState('');
  const [referenceId, setReferenceId] = useState('');
  const versionLoader = useCallback(async ({ after, limit = 25, signal }) => {
    if (!documentId) return { items: [], next_cursor: null, has_more: false };
    const before = after ? `&before=${encodeURIComponent(after)}` : '';
    const result = await api.get(`/documents/${documentId}/versions?limit=${limit}${before}`, { signal });
    return { items: result?.items || [], next_cursor: result?.next_before ? String(result.next_before) : null, has_more: Boolean(result?.next_before) };
  }, [documentId]);
  const submit = () => {
    if (kind === 'document_version') {
      if (documentId && versionId.trim()) onEvidence(step, { kind, document_id: documentId, document_version_id: versionId.trim() });
      return;
    }
    if (referenceId.trim()) onEvidence(step, { kind, [kind === 'handover_protocol' ? 'handover_protocol_id' : 'meter_reading_id']: referenceId.trim() });
  };
  return <div className="workflow-evidence-controls">
    {allows(step.actions, 'link_task') && !step.task_id && <button type="button" className="btn btn-secondary btn-sm" onClick={() => onTask(step)}>+ {text.task}</button>}
    {allows(step.actions, 'link_document') && <>
      <select aria-label="Belegart" value={kind} onChange={e => setKind(e.target.value)}>
        <option value="document_version">Dokumentoriginal</option><option value="handover_protocol">Übergabeprotokoll</option><option value="meter_reading">Zählerstand</option>
      </select>
      {kind === 'document_version' ? <>
        <CursorReferencePicker label="Dokument" value={documentId} onChange={value => { setDocumentId(value); setVersionId(''); }} loadPage={documentLoader} getLabel={doc => doc.title || doc.id} />
        <CursorReferencePicker label="Originalfassung" value={versionId} onChange={setVersionId} loadPage={versionLoader}
          getLabel={version => `v${version.number || '?'} · ${version.filename || version.id}`} disabled={!documentId} />
      </> : <label className="workflow-field"><span>{kind === 'handover_protocol' ? 'handover_protocol_id' : 'meter_reading_id'}</span><input value={referenceId} onChange={e => setReferenceId(e.target.value)} /></label>}
      <button type="button" className="btn btn-secondary btn-sm" onClick={submit}>Beleg verknüpfen</button>
    </>}
  </div>;
}

function StepEditor({ step, index, onChange, onRemove, text, userLoader }) {
  const update = patch => onChange(index, { ...step, ...patch });
  const dependencies = (step.depends_on_step_keys || []).join(', ');
  return <article className="workflow-step-editor">
    <div className="workflow-step-editor-head"><strong>{index + 1}. {step.title || '—'}</strong>
      <button type="button" className="btn btn-ghost btn-sm" onClick={() => onRemove(index)}>×</button></div>
    <div className="workflow-form-grid">
      <label className="workflow-field"><span>Stable key *</span><input value={step.stable_key || ''} onChange={e => update({ stable_key: e.target.value })} /></label>
      <label className="workflow-field"><span>Titel *</span><input value={step.title || ''} onChange={e => update({ title: e.target.value })} /></label>
      <label className="workflow-field"><span>{text.state}</span><select value={step.default_requirement || 'required'} onChange={e => update({ default_requirement: e.target.value })}>
        <option value="required">{text.required}</option><option value="optional">{text.optional}</option></select></label>
      <label className="workflow-field"><span>Terminanker</span><select value={step.anchor || 'move_in_handover'} onChange={e => update({ anchor: e.target.value })}>
        {ANCHORS.map(anchor => <option key={anchor} value={anchor}>{text.anchors[anchor]}</option>)}</select></label>
      <label className="workflow-field"><span>Versatz (Tage)</span><input type="number" value={step.offset_days ?? 0} onChange={e => update({ offset_days: Number(e.target.value) })} /></label>
      <label className="workflow-field"><span>Rolle</span><select value={step.assignee_role || ''} onChange={e => update({ assignee_role: e.target.value || null, assignee_user_id: e.target.value ? null : step.assignee_user_id })}>
        <option value="">—</option>{ROLES.map(role => <option key={role} value={role}>{role}</option>)}</select></label>
      <CursorReferencePicker label="Konkreter Benutzer" value={step.assignee_user_id} onChange={value => update({ assignee_user_id: value, assignee_role: value ? null : step.assignee_role })}
        loadPage={userLoader} getLabel={u => u.full_name || u.username || u.id} emptyLabel="—" />
      <label className="workflow-field"><span>Belegregel</span><select value={step.evidence_requirement || 'none'} onChange={e => update({ evidence_requirement: e.target.value })}>
        {EVIDENCE.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <label className="workflow-field workflow-field-wide"><span>Abhängigkeiten (stable keys)</span><input value={dependencies}
        onChange={e => update({ depends_on_step_keys: e.target.value.split(',').map(v => v.trim()).filter(Boolean) })} /></label>
      <label className="workflow-field workflow-field-wide"><span>Beschreibung</span><textarea value={step.description || ''} onChange={e => update({ description: e.target.value || null })} /></label>
    </div>
  </article>;
}

export default function TenancyWorkflows() {
  const { locale } = useTranslation();
  const text = workflowText(locale);
  const [tab, setTab] = useState('changes');
  const [templates, setTemplates] = useState([]);
  const [templateCursor, setTemplateCursor] = useState(null);
  const [templateMore, setTemplateMore] = useState(false);
  const [changes, setChanges] = useState([]);
  const [changeCursor, setChangeCursor] = useState(null);
  const [changeMore, setChangeMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState(null);
  const [unknown, setUnknown] = useState(null);
  const [selectedChange, setSelectedChange] = useState(null);
  const [selectedTemplate, setSelectedTemplate] = useState(null);
  const [versions, setVersions] = useState([]);
  const [versionEditor, setVersionEditor] = useState(null);
  const [preview, setPreview] = useState(null);
  const [reanchorDraft, setReanchorDraft] = useState({});
  const [reanchorPreview, setReanchorPreview] = useState(null);
  const [changeDraft, setChangeDraft] = useState({ mode: 'turnover' });
  const [templateDraft, setTemplateDraft] = useState({ direction: 'move_in' });

  const propertyLoader = useMemo(() => legacyLoader('/properties'), []);
  const unitLoader = useMemo(() => legacyLoader('/units', u => !templateDraft.property_id || u.property_id === templateDraft.property_id), [templateDraft.property_id]);
  const changeUnitLoader = useMemo(() => legacyLoader('/units', u => !changeDraft.property_id || u.property_id === changeDraft.property_id), [changeDraft.property_id]);
  const previousContractLoader = useMemo(() => legacyLoader('/contracts', c => !changeDraft.unit_id || c.unit_id === changeDraft.unit_id), [changeDraft.unit_id]);
  const nextContractLoader = previousContractLoader;
  const userLoader = useMemo(() => legacyLoader('/users', u => u.is_active !== false), []);
  const documentLoader = useMemo(() => legacyLoader('/documents', d => !selectedChange || (!d.property_id || d.property_id === selectedChange.property_id) && (!d.unit_id || d.unit_id === selectedChange.unit_id)), [selectedChange]);

  const loadTemplates = useCallback(async (after = null, append = false) => {
    setLoading(true);
    try {
      const page = await tenancyWorkflowApi.listTemplates({ after, limit: 25 });
      setTemplates(current => append ? [...current, ...page.items] : page.items);
      setTemplateCursor(page.next_cursor || null); setTemplateMore(Boolean(page.has_more));
    } catch (error) { setNotice({ kind: 'error', message: error.message }); }
    finally { setLoading(false); }
  }, []);

  const loadChanges = useCallback(async (after = null, append = false) => {
    setLoading(true);
    try {
      const page = await tenancyWorkflowApi.listChanges({ after, limit: 25 });
      setChanges(current => append ? [...current, ...page.items] : page.items);
      setChangeCursor(page.next_cursor || null); setChangeMore(Boolean(page.has_more));
    } catch (error) { setNotice({ kind: 'error', message: error.message }); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { loadTemplates(); loadChanges(); }, [loadTemplates, loadChanges]);

  const runMutation = async (label, execute, payload, onSuccess) => {
    setNotice(null);
    try {
      const result = await execute(payload);
      setUnknown(null); await onSuccess?.(result);
      return result;
    } catch (error) {
      if (isUnknownOutcome(error)) {
        setUnknown({ label, execute, payload, onSuccess });
        setNotice({ kind: 'warning', message: text.unknown });
      } else if (isReviewRequired(error)) {
        setNotice({ kind: 'warning', message: text.review });
      } else setNotice({ kind: 'error', message: error.message });
      return null;
    }
  };

  const retryUnknown = () => unknown && runMutation(unknown.label, unknown.execute, unknown.payload, unknown.onSuccess);

  const openTemplate = async template => {
    setSelectedTemplate(template); setVersionEditor(null); setNotice(null);
    try {
      const page = await tenancyWorkflowApi.listTemplateVersions(template.id, { limit: 25 });
      setVersions(page.items || []);
    } catch (error) { setNotice({ kind: 'error', message: error.message }); }
  };

  const openChange = async change => {
    setNotice(null); setReanchorPreview(null);
    try {
      const detail = await tenancyWorkflowApi.getChange(change.id);
      setSelectedChange(detail);
      setReanchorDraft({ move_out_handover_date: detail.move_out_handover_date || null, move_in_handover_date: detail.move_in_handover_date || null });
    } catch (error) { setNotice({ kind: 'error', message: error.message }); }
  };

  const saveVersion = async () => {
    if (!versionEditor) return;
    const invalid = versionEditor.steps?.find(step => step.assignee_user_id && step.assignee_role);
    if (invalid) { setNotice({ kind: 'error', message: 'Verantwortung muss Benutzer ODER Rolle sein.' }); return; }
    const payload = createCommand({ steps: versionEditor.steps }, versionEditor.revision);
    await runMutation('save-version', p => tenancyWorkflowApi.updateTemplateVersion(versionEditor.id, p), payload, result => {
      setVersionEditor(result); setVersions(current => current.map(v => v.id === result.id ? result : v));
    });
  };

  const publishVersion = async () => {
    if (!versionEditor) return;
    const payload = createCommand({}, versionEditor.revision);
    await runMutation('publish-version', p => tenancyWorkflowApi.publishTemplateVersion(versionEditor.id, p), payload, async result => {
      setVersionEditor(result); await openTemplate(selectedTemplate);
    });
  };

  const createTemplate = async event => {
    event.preventDefault();
    const payload = createCommand({ property_id: templateDraft.property_id, unit_id: templateDraft.unit_id || null, direction: templateDraft.direction }, null);
    await runMutation('create-template', p => tenancyWorkflowApi.createTemplate(p), payload, async result => {
      setTemplateDraft({ direction: 'move_in' }); await loadTemplates(); await openTemplate(result);
    });
  };

  const requestPreview = async event => {
    event.preventDefault(); setNotice(null); setPreview(null);
    try { setPreview(await tenancyWorkflowApi.previewChange(changeDraft)); }
    catch (error) { setNotice({ kind: 'error', message: error.message }); }
  };

  const confirmStart = async () => {
    if (!preview) return;
    const payload = createCommand({ ...changeDraft, preview_hash: preview.preview_hash,
      source_etags: preview.source_etags || preview.original_source_etags || null }, preview.expected_revision ?? null);
    await runMutation('create-change', p => tenancyWorkflowApi.createChange(p), payload, async result => {
      setPreview(null); setSelectedChange(result); await loadChanges();
    });
  };

  const patchStep = async (step, patch) => {
    const payload = createCommand(patch, step.revision);
    await runMutation('patch-step', p => tenancyWorkflowApi.patchStep(selectedChange.id, step.id, p), payload,
      async () => setSelectedChange(await tenancyWorkflowApi.getChange(selectedChange.id)));
  };

  const requestReanchorPreview = async event => {
    event.preventDefault(); setNotice(null); setReanchorPreview(null);
    try { setReanchorPreview(await tenancyWorkflowApi.previewReanchor(selectedChange.id, reanchorDraft)); }
    catch (error) { setNotice({ kind: 'error', message: error.message }); }
  };

  const confirmReanchor = async () => {
    if (!reanchorPreview) return;
    const payload = createCommand({ ...reanchorDraft, preview_hash: reanchorPreview.preview_hash,
      source_etags: reanchorPreview.source_etags || reanchorPreview.original_source_etags || null }, selectedChange.revision);
    await runMutation('reanchor', p => tenancyWorkflowApi.reanchor(selectedChange.id, p), payload, result => {
      setSelectedChange(result); setReanchorPreview(null);
      setReanchorDraft({ move_out_handover_date: result.move_out_handover_date || null, move_in_handover_date: result.move_in_handover_date || null });
      loadChanges();
    });
  };

  const linkTask = async step => {
    const payload = createCommand({}, step.revision);
    await runMutation('link-task', p => tenancyWorkflowApi.linkTask(selectedChange.id, step.id, p), payload,
      async () => setSelectedChange(await tenancyWorkflowApi.getChange(selectedChange.id)));
  };

  const linkEvidence = async (step, evidence) => {
    const payload = createCommand({ evidence }, step.revision);
    await runMutation('link-evidence', p => tenancyWorkflowApi.linkEvidence(selectedChange.id, step.id, p), payload,
      async () => setSelectedChange(await tenancyWorkflowApi.getChange(selectedChange.id)));
  };

  const completeChange = async () => {
    const payload = createCommand({}, selectedChange.revision);
    await runMutation('complete-change', p => tenancyWorkflowApi.completeChange(selectedChange.id, p), payload, result => {
      setSelectedChange(result); loadChanges();
    });
  };

  const addStep = () => setVersionEditor(current => ({ ...current, steps: [...(current.steps || []), {
    id: crypto.randomUUID(), stable_key: '', position: (current.steps?.length || 0) + 1, title: '',
    description: null, default_requirement: 'required', anchor: 'move_in_handover', offset_days: 0,
    assignee_user_id: null, assignee_role: null, depends_on_step_keys: [], evidence_requirement: 'none',
  }] }));

  return <div className="page tenancy-workflow-page">
    <header className="workflow-hero"><div><span className="workflow-eyebrow">P1 / P2</span><h1>{text.title}</h1>
      <p>{text.templateHint}</p></div><div className="workflow-tabs" role="tablist">
      <button role="tab" aria-selected={tab === 'changes'} onClick={() => setTab('changes')}>{text.changes}</button>
      <button role="tab" aria-selected={tab === 'templates'} onClick={() => setTab('templates')}>{text.templates}</button></div></header>

    {notice && <div className={`workflow-notice workflow-notice-${notice.kind}`} role="alert"><span>{notice.message}</span>
      {unknown && <button type="button" className="btn btn-secondary btn-sm" onClick={retryUnknown}>{text.retryExact}</button>}</div>}

    {tab === 'templates' && <div className="workflow-layout">
      <section className="workflow-pane"><h2>{text.templates}</h2>
        <CursorCards items={templates} empty={text.empty} hasMore={templateMore} loading={loading}
          onMore={() => loadTemplates(templateCursor, true)} moreLabel={text.loadMore}>
          {template => <button type="button" key={template.id} className="workflow-card" onClick={() => openTemplate(template)}>
            <div><strong>{text[template.direction] || template.direction}</strong><span>{template.property_name || template.property_id}</span></div>
            <Status value={template.state || template.latest_state} text={text} /></button>}
        </CursorCards>
        <form className="workflow-create-form" onSubmit={createTemplate}><h3>{text.createTemplate}</h3>
          <CursorReferencePicker label={text.property} value={templateDraft.property_id} onChange={value => setTemplateDraft(d => ({ ...d, property_id: value, unit_id: null }))}
            loadPage={propertyLoader} getLabel={p => p.name || p.id} required />
          <CursorReferencePicker label={text.unit} value={templateDraft.unit_id} onChange={value => setTemplateDraft(d => ({ ...d, unit_id: value }))}
            loadPage={unitLoader} getLabel={u => u.label || u.id} />
          <label className="workflow-field"><span>{text.direction}</span><select value={templateDraft.direction} onChange={e => setTemplateDraft(d => ({ ...d, direction: e.target.value }))}>
            <option value="move_in">{text.move_in}</option><option value="move_out">{text.move_out}</option></select></label>
          <button className="btn btn-primary" disabled={!templateDraft.property_id}>{text.createTemplate}</button>
        </form>
      </section>
      <section className="workflow-pane workflow-detail-pane">
        {!selectedTemplate ? <div className="workflow-empty">Vorlage auswählen.</div> : <>
          <div className="workflow-section-head"><div><span className="workflow-eyebrow">{selectedTemplate.id}</span><h2>{text.versions}</h2></div></div>
          <div className="workflow-version-list">{versions.map(version => <button type="button" key={version.id} onClick={() => setVersionEditor(structuredClone(version))}>
            <span>v{version.version}</span><Status value={version.state} text={text} /></button>)}</div>
          {versionEditor && <div className="workflow-version-editor">
            <div className="workflow-section-head"><h3>v{versionEditor.version} · {text[versionEditor.state] || versionEditor.state}</h3>
              <div><button type="button" className="btn btn-secondary btn-sm" onClick={addStep} disabled={versionEditor.state !== 'draft'}>+ Schritt</button>
                <button type="button" className="btn btn-primary btn-sm" onClick={saveVersion} disabled={versionEditor.state !== 'draft'}>Speichern</button>
                {allows(versionEditor.actions, 'publish_template') && <button type="button" className="btn btn-primary btn-sm" onClick={publishVersion}>Veröffentlichen</button>}</div></div>
            {(versionEditor.steps || []).map((step, index) => <StepEditor key={step.id || step.stable_key || index} step={step} index={index} text={text} userLoader={userLoader}
              onChange={(i, next) => setVersionEditor(current => ({ ...current, steps: current.steps.map((item, idx) => idx === i ? next : item) }))}
              onRemove={i => setVersionEditor(current => ({ ...current, steps: current.steps.filter((_, idx) => idx !== i) }))} />)}
          </div>}
        </>}
      </section>
    </div>}

    {tab === 'changes' && <div className="workflow-layout">
      <section className="workflow-pane"><h2>{text.changes}</h2>
        <CursorCards items={changes} empty={text.empty} hasMore={changeMore} loading={loading}
          onMore={() => loadChanges(changeCursor, true)} moreLabel={text.loadMore}>
          {change => <button type="button" key={change.id} className="workflow-card" onClick={() => openChange(change)}>
            <div><strong>{text[change.mode] || change.mode}</strong><span>{change.property_name || change.property_id} · {change.unit_label || change.unit_id}</span></div>
            <Status value={change.state} text={text} /></button>}
        </CursorCards>
        <form className="workflow-create-form" onSubmit={requestPreview}><h3>{text.createChange}</h3>
          <CursorReferencePicker label={text.property} value={changeDraft.property_id} onChange={value => setChangeDraft(d => ({ ...d, property_id: value, unit_id: null, previous_contract_id: null, next_contract_id: null }))}
            loadPage={propertyLoader} getLabel={p => p.name || p.id} required />
          <CursorReferencePicker label={text.unit} value={changeDraft.unit_id} onChange={value => setChangeDraft(d => ({ ...d, unit_id: value, previous_contract_id: null, next_contract_id: null }))}
            loadPage={changeUnitLoader} getLabel={u => u.label || u.id} required />
          <label className="workflow-field"><span>{text.direction}</span><select value={changeDraft.mode} onChange={e => setChangeDraft(d => ({ ...d, mode: e.target.value }))}>
            <option value="move_out">{text.move_out}</option><option value="move_in">{text.move_in}</option><option value="turnover">{text.turnover}</option></select></label>
          {changeDraft.mode !== 'move_in' && <CursorReferencePicker label={text.previousContract} value={changeDraft.previous_contract_id}
            onChange={value => setChangeDraft(d => ({ ...d, previous_contract_id: value }))} loadPage={previousContractLoader} getLabel={c => c.contract_number || c.id} required />}
          {changeDraft.mode !== 'move_out' && <CursorReferencePicker label={text.nextContract} value={changeDraft.next_contract_id}
            onChange={value => setChangeDraft(d => ({ ...d, next_contract_id: value }))} loadPage={nextContractLoader} getLabel={c => c.contract_number || c.id} required />}
          <label className="workflow-field"><span>{text.outDate}</span><input type="date" value={changeDraft.move_out_handover_date || ''} onChange={e => setChangeDraft(d => ({ ...d, move_out_handover_date: e.target.value || null }))} /></label>
          <label className="workflow-field"><span>{text.inDate}</span><input type="date" value={changeDraft.move_in_handover_date || ''} onChange={e => setChangeDraft(d => ({ ...d, move_in_handover_date: e.target.value || null }))} /></label>
          <button className="btn btn-primary" disabled={!changeDraft.property_id || !changeDraft.unit_id}>{text.preview}</button>
        </form>
        {preview && <div className="workflow-preview"><h3>{text.preview}</h3><code>{preview.preview_hash}</code>
          <dl>{Object.entries(preview.anchors || {}).map(([key, value]) => <div key={key}><dt>{text.anchors[key] || key}</dt><dd>{value || '—'}</dd></div>)}</dl>
          <p>{Array.isArray(preview.affected_steps) ? `${preview.affected_steps.length} Schritte` : ''}</p>
          <button type="button" className="btn btn-primary" onClick={confirmStart}>{text.confirmStart}</button></div>}
      </section>
      <section className="workflow-pane workflow-detail-pane">
        {!selectedChange ? <div className="workflow-empty">Wechselakte auswählen.</div> : <>
          <div className="workflow-section-head"><div><span className="workflow-eyebrow">{selectedChange.id}</span><h2>{text[selectedChange.mode] || selectedChange.mode}</h2></div>
            <Status value={selectedChange.state} text={text} /></div>
          <div className="workflow-anchor-grid">
            <div><span>{text.outDate}</span><strong>{selectedChange.move_out_handover_date || '—'}</strong></div>
            <div><span>{text.inDate}</span><strong>{selectedChange.move_in_handover_date || '—'}</strong></div>
          </div>
          {allows(selectedChange.actions, 'reanchor') && <form className="workflow-reanchor" onSubmit={requestReanchorPreview}>
            <div className="workflow-form-grid">
              <label className="workflow-field"><span>{text.outDate}</span><input type="date" value={reanchorDraft.move_out_handover_date || ''} onChange={e => setReanchorDraft(d => ({ ...d, move_out_handover_date: e.target.value || null }))} /></label>
              <label className="workflow-field"><span>{text.inDate}</span><input type="date" value={reanchorDraft.move_in_handover_date || ''} onChange={e => setReanchorDraft(d => ({ ...d, move_in_handover_date: e.target.value || null }))} /></label>
            </div>
            <button type="submit" className="btn btn-secondary btn-sm">Terminänderung prüfen</button>
            {reanchorPreview && <div className="workflow-preview"><code>{reanchorPreview.preview_hash}</code>
              <p>{Array.isArray(reanchorPreview.affected_steps) ? `${reanchorPreview.affected_steps.length} offene Schritte betroffen` : ''}</p>
              <button type="button" className="btn btn-primary btn-sm" onClick={confirmReanchor}>Terminänderung bestätigen</button></div>}
          </form>}
          <h3>{text.steps}</h3>
          <div className="workflow-checklist">{(selectedChange.steps || []).map(step => <article key={step.id} className={`workflow-step workflow-step-${step.state}`}>
            <div className="workflow-step-main"><div><span className="workflow-step-requirement">{text[step.requirement] || step.requirement}</span>
              <h4>{step.title_snapshot}</h4><p>{step.description_snapshot}</p></div><Status value={step.state} text={text} /></div>
            <div className="workflow-step-meta"><span>{text.due}: <strong>{step.due_date || '—'}</strong></span>
              {step.original_due_date !== step.due_date && <span>{text.originalDue}: {step.original_due_date}</span>}
              <span>{text.task}: {step.task_id || '—'}</span><span>{text.evidence}: {step.evidence_links?.length || 0}</span></div>
            {step.blocked_by_step_ids?.length > 0 && <p className="workflow-blocked">↳ {text.blocked}: {step.blocked_by_step_ids.join(', ')}</p>}
            <div className="workflow-step-actions">
              {allows(step.actions, 'complete_step') && <button type="button" className="btn btn-primary btn-sm" onClick={() => patchStep(step, { state: 'completed' })}>{text.completed}</button>}
              {allows(step.actions, 'complete_step') && step.requirement === 'optional' && <button type="button" className="btn btn-secondary btn-sm" onClick={() => {
                const reason = window.prompt('Grund für unzutreffend'); if (reason?.trim()) patchStep(step, { state: 'not_applicable', not_applicable_reason: reason.trim() });
              }}>{text.not_applicable}</button>}
            </div>
            <EvidenceControls step={step} text={text} documentLoader={documentLoader} onTask={linkTask} onEvidence={linkEvidence} />
          </article>)}</div>
          {allows(selectedChange.actions, 'complete_change') && <button type="button" className="btn btn-primary workflow-complete" onClick={completeChange}>{text.completeChange}</button>}
        </>}
      </section>
    </div>}
  </div>;
}
