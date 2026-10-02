import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { useTranslation } from '../i18n';
import {
  BoundedReferencePicker,
  TenancyChangeFile,
  TenancyChangeStartForm,
  WorkflowCommandNotice,
  WorkflowTemplateCreateForm,
  WorkflowTemplateDesigner,
  activeUserReferenceLoader,
  addEvidenceCommand,
  cancelTenancyChangeCommand,
  completeTenancyChangeCommand,
  contractReferenceLoader,
  createStepTaskCommand,
  createTemplateCommand,
  createTemplateVersionCommand,
  documentReferenceLoader,
  documentVersionReferenceLoader,
  handoverReferenceLoader,
  meterReadingReferenceLoader,
  propertyReferenceLoader,
  publishTemplateVersionCommand,
  reanchorPreviewPayload,
  reanchorTenancyChangeCommand,
  removeEvidenceCommand,
  startTenancyChangeCommand,
  unitReferenceLoader,
  updateStepCommand,
  updateTemplateVersionCommand,
  useWorkflowCommand,
  workflowApi,
  workflowText,
} from '../features/tenancyWorkflows';
import './TenancyWorkflows.css';

function principal(user) {
  if (!user) return '';
  return JSON.stringify([
    user.id,
    user.role,
    user.portfolio_access,
    [...(user.portfolio_ids || [])].sort(),
    user.portfolio_access_origin,
  ]);
}

function mergeUnique(current, items) {
  const values = new Map(current.map(item => [item.id, item]));
  items.forEach(item => values.set(item.id, item));
  return [...values.values()];
}

function evidenceInput(selection) {
  if (selection?.kind === 'document_version') {
    return {
      kind: 'document_version',
      document_id: selection.document_id,
      document_version_id: selection.document_version_id,
    };
  }
  if (selection?.kind === 'handover_protocol' && selection.item?.id) {
    return { kind: 'handover_protocol', handover_protocol_id: selection.item.id };
  }
  if (selection?.kind === 'meter_reading' && selection.item?.id) {
    return { kind: 'meter_reading', meter_reading_id: selection.item.id };
  }
  throw new Error('invalid_evidence_input');
}

export default function TenancyWorkflows() {
  const { locale } = useTranslation();
  const auth = useAuth();
  const navigate = useNavigate();
  const user = auth?.user;
  const principalKey = principal(user);
  const manager = ['eigentuemer', 'verwalter'].includes(user?.role);
  const tr = useCallback((key, params) => workflowText(locale, key, params), [locale]);
  const [tab, setTab] = useState('changes');

  const [templates, setTemplates] = useState([]);
  const [templateCursor, setTemplateCursor] = useState(null);
  const [templateMore, setTemplateMore] = useState(false);
  const [templateError, setTemplateError] = useState(null);
  const [versions, setVersions] = useState([]);
  const [versionCursor, setVersionCursor] = useState(null);
  const [versionMore, setVersionMore] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState(null);

  const [changes, setChanges] = useState([]);
  const [changeCursor, setChangeCursor] = useState(null);
  const [changeMore, setChangeMore] = useState(false);
  const [changeError, setChangeError] = useState(null);
  const [selectedChange, setSelectedChange] = useState(null);

  const [contextProperty, setContextProperty] = useState(null);
  const [contextUnit, setContextUnit] = useState(null);
  const pageCommand = useWorkflowCommand(principalKey);

  const propertyLoader = useMemo(() => propertyReferenceLoader(), []);
  const userLoaderForProperty = useCallback(
    propertyId => activeUserReferenceLoader({ propertyId }),
    [],
  );
  const contextUnitLoader = useMemo(
    () => contextProperty ? unitReferenceLoader({ propertyId: contextProperty.id }) : null,
    [contextProperty],
  );
  const unitLoaderForProperty = useCallback(
    propertyId => unitReferenceLoader({ propertyId }),
    [],
  );
  const selectedVersionUserLoader = useMemo(
    () => selectedVersion ? activeUserReferenceLoader({ propertyId: selectedVersion.property_id }) : null,
    [selectedVersion],
  );

  const loadTemplates = useCallback(async (after = null, append = false, options = {}) => {
    if (!manager) return;
    setTemplateError(null);
    try {
      const page = await workflowApi.listTemplates({}, { after, limit: 25, signal: options.signal });
      setTemplates(current => append ? mergeUnique(current, page.items) : page.items);
      setTemplateCursor(page.next_cursor);
      setTemplateMore(page.has_more);
    } catch (error) {
      if (error?.name !== 'AbortError') setTemplateError(error.message);
    }
  }, [manager]);

  const loadVersions = useCallback(async (templateId, after = null, append = false, options = {}) => {
    setTemplateError(null);
    try {
      const page = await workflowApi.listTemplateVersions(templateId, { after, limit: 25, signal: options.signal });
      setVersions(current => append ? mergeUnique(current, page.items) : page.items);
      setVersionCursor(page.next_cursor);
      setVersionMore(page.has_more);
    } catch (error) {
      if (error?.name !== 'AbortError') setTemplateError(error.message);
    }
  }, []);

  const loadChanges = useCallback(async (after = null, append = false, options = {}) => {
    setChangeError(null);
    try {
      const page = await workflowApi.listChanges({}, { after, limit: 25, signal: options.signal });
      setChanges(current => append ? mergeUnique(current, page.items) : page.items);
      setChangeCursor(page.next_cursor);
      setChangeMore(page.has_more);
    } catch (error) {
      if (error?.name !== 'AbortError') setChangeError(error.message);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setSelectedVersion(null);
    setSelectedChange(null);
    setVersions([]);
    setTemplates([]);
    setChanges([]);
    loadChanges(null, false, { signal: controller.signal });
    if (manager) loadTemplates(null, false, { signal: controller.signal });
    else setTab('changes');
    return () => controller.abort();
  }, [loadChanges, loadTemplates, manager, principalKey]);

  const selectTemplateVersion = async version => {
    setSelectedVersion(version);
    await loadVersions(version.template_id);
  };

  const reviewTemplate = async ({ version }) => {
    try {
      setSelectedVersion(await workflowApi.getTemplateVersion(version.id));
    } catch (error) {
      setTemplateError(error.message);
    }
  };

  const createNextVersion = () => {
    if (!selectedVersion || !['published', 'retired'].includes(selectedVersion.state)) return;
    const payload = createTemplateVersionCommand(selectedVersion);
    pageCommand.execute({
      label: 'create-template-version',
      payload,
      send: (command, options) => workflowApi.createTemplateVersion(
        selectedVersion.template_id,
        command,
        options,
      ),
      onSuccess: async result => {
        setSelectedVersion(result);
        await Promise.all([loadTemplates(), loadVersions(result.template_id)]);
      },
    });
  };

  const contractLoader = useMemo(
    () => contextProperty && contextUnit
      ? contractReferenceLoader({ propertyId: contextProperty.id, unitId: contextUnit.id })
      : null,
    [contextProperty, contextUnit],
  );

  const publishedTemplateLoader = useCallback(
    ({ cursor, limit, signal, direction, propertyId }) => workflowApi.listTemplates(
      { property_id: propertyId, direction },
      { after: cursor, limit, signal },
    ),
    [],
  );

  const openChange = async change => {
    setChangeError(null);
    try {
      setSelectedChange(await workflowApi.getChange(change.id));
    } catch (error) {
      setChangeError(error.message);
    }
  };

  const refreshChange = useCallback(async changeId => {
    const current = await workflowApi.getChange(changeId);
    setSelectedChange(current);
    setChanges(items => items.map(item => item.id === current.id ? current : item));
    return current;
  }, []);

  const afterStep = useCallback(
    async (operation, changeId, options) => {
      await operation;
      return workflowApi.getChange(changeId, { signal: options?.signal });
    },
    [],
  );

  const documentLoader = useCallback(args => {
    const { propertyId, unitId, contractId, direction, ...pageArgs } = args;
    return documentReferenceLoader({ propertyId, unitId, contractId, direction })(pageArgs);
  }, []);
  const handoverLoader = useCallback(args => {
    const { propertyId, unitId, contractId, direction, ...pageArgs } = args;
    return handoverReferenceLoader({ propertyId, unitId, contractId, direction })(pageArgs);
  }, []);
  const meterReadingLoader = useCallback(args => {
    const { propertyId, unitId, contractId, direction, ...pageArgs } = args;
    return meterReadingReferenceLoader({ propertyId, unitId, contractId, direction })(pageArgs);
  }, []);

  const canSelectEvidence = useCallback((_kind, item) => Boolean(item?.id), []);

  const renderTemplateWorkspace = () => (
    <div className="tenancy-workflow-page__columns">
      <aside className="tenancy-workflow-page__rail">
        <WorkflowTemplateCreateForm
          locale={locale}
          principalKey={principalKey}
          propertyLoader={propertyLoader}
          unitLoaderForProperty={unitLoaderForProperty}
          userLoaderForProperty={userLoaderForProperty}
          prepareCreate={input => ({
            payload: createTemplateCommand(input),
            send: (payload, options) => workflowApi.createTemplate(payload, options),
          })}
          onCreated={async result => {
            setSelectedVersion(result);
            await Promise.all([loadTemplates(), loadVersions(result.template_id)]);
          }}
        />

        <section className="tenancy-workflow-page__list">
          <div className="tenancy-workflow-page__section-head">
            <h2>{tr('templatesTitle')}</h2>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadTemplates()}>
              {tr('refresh')}
            </button>
          </div>
          {templateError && <div className="workflow-inline-error" role="alert">{templateError}</div>}
          {templates.map(item => (
            <button type="button" key={item.id}
              className={selectedVersion?.template_id === item.template_id ? 'is-selected' : ''}
              onClick={() => selectTemplateVersion(item)}>
              <strong>{tr(item.direction)} · {tr('version', { version: item.version })}</strong>
              <span>{item.unit_id ? tr('unitOverride') : tr('objectDefault')} · {tr(item.state)}</span>
              <code>{item.property_id}</code>
            </button>
          ))}
          {templateMore && <button type="button" className="btn btn-secondary"
            onClick={() => loadTemplates(templateCursor, true)}>{tr('loadMore')}</button>}
        </section>
      </aside>

      <main className="tenancy-workflow-page__detail">
        <WorkflowCommandNotice state={pageCommand.state} locale={locale}
          onRetryExact={pageCommand.retryExact} onDismiss={pageCommand.reset} />
        {!selectedVersion ? (
          <div className="tenancy-workflow-page__empty">{tr('selectTemplate')}</div>
        ) : (
          <>
            <section className="tenancy-workflow-page__versionbar">
              <div>
                <strong>{tr('version', { version: selectedVersion.version })}</strong>
                <span>{selectedVersion.id}</span>
              </div>
              {['published', 'retired'].includes(selectedVersion.state) && (
                <button type="button" className="btn btn-secondary btn-sm"
                  disabled={pageCommand.busy || pageCommand.state.phase === 'unknown'}
                  onClick={createNextVersion}>{tr('newDraftVersion')}</button>
              )}
            </section>
            <div className="tenancy-workflow-page__versions">
              {versions.map(version => (
                <button type="button" key={version.id}
                  className={selectedVersion.id === version.id ? 'is-selected' : ''}
                  onClick={() => setSelectedVersion(version)}>
                  v{version.version} · {tr(version.state)}
                </button>
              ))}
              {versionMore && <button type="button" className="btn btn-secondary btn-sm"
                onClick={() => loadVersions(selectedVersion.template_id, versionCursor, true)}>
                {tr('loadMore')}
              </button>}
            </div>
            <WorkflowTemplateDesigner
              key={selectedVersion.id}
              version={selectedVersion}
              locale={locale}
              principalKey={principalKey}
              userLoader={selectedVersionUserLoader}
              prepareSave={({ version, steps }) => ({
                payload: updateTemplateVersionCommand(version, steps),
                send: (payload, options) => workflowApi.updateTemplateVersion(version.id, payload, options),
              })}
              preparePublish={({ version }) => ({
                payload: publishTemplateVersionCommand(version),
                send: (payload, options) => workflowApi.publishTemplateVersion(version.id, payload, options),
              })}
              onChanged={async result => {
                setSelectedVersion(result);
                await Promise.all([loadTemplates(), loadVersions(result.template_id)]);
              }}
              onReviewCurrent={reviewTemplate}
            />
          </>
        )}
      </main>
    </div>
  );

  const renderChangeWorkspace = () => (
    <div className="tenancy-workflow-page__columns">
      <aside className="tenancy-workflow-page__rail">
        {manager && (
          <section className="workflow-shell tenancy-workflow-page__context">
            <header className="workflow-shell__header">
              <div><span className="workflow-eyebrow">{tr('eyebrow')}</span><h2>{tr('startTitle')}</h2></div>
            </header>
            <BoundedReferencePicker label={tr('propertyScope')} locale={locale}
              value={contextProperty?.id || null} selectedItem={contextProperty}
              loadPage={propertyLoader} sourceKey="change-properties"
              getLabel={item => item.name || item.label || item.id}
              onChange={item => { setContextProperty(item); setContextUnit(null); }} required />
            <BoundedReferencePicker label={tr('unitScope')} locale={locale}
              value={contextUnit?.id || null} selectedItem={contextUnit}
              loadPage={contextUnitLoader} sourceKey={contextProperty?.id || 'no-property'}
              getLabel={item => item.label || item.name || item.id}
              disabled={!contextProperty} onChange={setContextUnit} required />
          </section>
        )}

        {manager && contextProperty && contextUnit && (
          <TenancyChangeStartForm
            propertyId={contextProperty.id}
            unitId={contextUnit.id}
            locale={locale}
            principalKey={principalKey}
            loadContracts={contractLoader}
            loadTemplates={publishedTemplateLoader}
            onPreview={(payload, options) => workflowApi.previewChange(payload, options)}
            prepareCreate={({ form, preview }) => ({
              payload: startTenancyChangeCommand(form, preview),
              send: (payload, options) => workflowApi.createChange(payload, options),
            })}
            onCreated={async result => {
              setSelectedChange(result);
              await loadChanges();
            }}
          />
        )}

        <section className="tenancy-workflow-page__list">
          <div className="tenancy-workflow-page__section-head">
            <h2>{tr('changeTitle')}</h2>
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => loadChanges()}>
              {tr('refresh')}
            </button>
          </div>
          {changeError && <div className="workflow-inline-error" role="alert">{changeError}</div>}
          {changes.map(item => (
            <button type="button" key={item.id}
              className={selectedChange?.id === item.id ? 'is-selected' : ''}
              onClick={() => openChange(item)}>
              <strong>{tr(item.mode)}</strong>
              <span>{item.property_id} · {item.unit_id}</span>
              <small>{tr(item.state)}</small>
            </button>
          ))}
          {changeMore && <button type="button" className="btn btn-secondary"
            onClick={() => loadChanges(changeCursor, true)}>{tr('loadMore')}</button>}
        </section>
      </aside>

      <main className="tenancy-workflow-page__detail">
        {!selectedChange ? (
          <div className="tenancy-workflow-page__empty">{tr('selectChange')}</div>
        ) : (
          <TenancyChangeFile
            key={selectedChange.id}
            change={selectedChange}
            locale={locale}
            principalKey={principalKey}
            prepareStepMutation={({ change, step, patch }) => ({
              payload: updateStepCommand(change, step, patch),
              send: (payload, options) => afterStep(
                workflowApi.patchStep(change.id, step.id, payload, options),
                change.id,
                options,
              ),
            })}
            prepareTaskLink={({ change, step }) => ({
              payload: createStepTaskCommand(change, step),
              send: (payload, options) => afterStep(
                workflowApi.linkTask(change.id, step.id, payload, options),
                change.id,
                options,
              ),
            })}
            prepareCancel={({ change, reason }) => ({
              payload: cancelTenancyChangeCommand(change, reason),
              send: (payload, options) => workflowApi.patchChange(change.id, payload, options),
            })}
            prepareComplete={({ change }) => ({
              payload: completeTenancyChangeCommand(change),
              send: (payload, options) => workflowApi.completeChange(change.id, payload, options),
            })}
            onReanchorPreview={({ change, dates }, options) => workflowApi.reanchorPreview(
              change,
              reanchorPreviewPayload(change, dates),
              options,
            )}
            prepareReanchor={({ change, dates, preview }) => ({
              payload: reanchorTenancyChangeCommand(change, dates, preview),
              send: (payload, options) => workflowApi.reanchor(change.id, payload, options),
            })}
            prepareEvidenceLink={({ change, step, selection }) => {
              const evidence = evidenceInput(selection);
              return {
                payload: addEvidenceCommand(change, step, evidence),
                send: (payload, options) => afterStep(
                  workflowApi.linkEvidence(change.id, step.id, payload, options),
                  change.id,
                  options,
                ),
              };
            }}
            prepareUnlinkEvidence={({ change, step, link }) => ({
              payload: removeEvidenceCommand(change, step),
              send: (payload, options) => afterStep(
                workflowApi.unlinkEvidence(change.id, step.id, link.id, payload, options),
                change.id,
                options,
              ),
            })}
            canLinkEvidence={() => true}
            canSelectEvidence={canSelectEvidence}
            loadDocuments={documentLoader}
            loadDocumentVersions={documentVersionReferenceLoader}
            loadHandoverProtocols={handoverLoader}
            loadMeterReadings={meterReadingLoader}
            onChanged={result => {
              setSelectedChange(result);
              setChanges(items => items.map(item => item.id === result.id ? result : item));
            }}
            onReviewCurrent={({ change }) => refreshChange(change.id)}
            onOpenTask={() => navigate('/tasks')}
          />
        )}
      </main>
    </div>
  );

  return (
    <div className="page tenancy-workflow-page">
      <header className="tenancy-workflow-page__hero">
        <div>
          <span className="workflow-eyebrow">P1 / P2</span>
          <h1>{tr('eyebrow')}</h1>
          <p>{tr('pageDescription')}</p>
        </div>
        <div className="tenancy-workflow-page__tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === 'changes'}
            onClick={() => setTab('changes')}>{tr('changeTitle')}</button>
          {manager && <button type="button" role="tab" aria-selected={tab === 'templates'}
            onClick={() => setTab('templates')}>{tr('templatesTitle')}</button>}
        </div>
      </header>
      {tab === 'templates' && manager ? renderTemplateWorkspace() : renderChangeWorkspace()}
    </div>
  );
}
