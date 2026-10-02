import { api } from './api';

export const workflowEndpoints = {
  templates: '/workflow-templates',
  template: id => `/workflow-templates/${id}`,
  templateVersions: id => `/workflow-templates/${id}/versions`,
  templateVersion: id => `/workflow-template-versions/${id}`,
  publishTemplateVersion: id => `/workflow-template-versions/${id}/publish`,
  changes: '/tenancy-changes',
  previewChange: '/tenancy-changes/preview',
  change: id => `/tenancy-changes/${id}`,
  reanchorPreview: id => `/tenancy-changes/${id}/reanchor-preview`,
  reanchor: id => `/tenancy-changes/${id}/reanchor`,
  step: (changeId, stepId) => `/tenancy-changes/${changeId}/steps/${stepId}`,
  task: (changeId, stepId) => `/tenancy-changes/${changeId}/steps/${stepId}/task`,
  evidence: (changeId, stepId) => `/tenancy-changes/${changeId}/steps/${stepId}/evidence`,
  evidenceLink: (changeId, stepId, linkId) => `/tenancy-changes/${changeId}/steps/${stepId}/evidence/${linkId}`,
  complete: id => `/tenancy-changes/${id}/complete`,
};

export function createCommand(data, revision, idempotencyKey = crypto.randomUUID()) {
  return { idempotency_key: idempotencyKey, expected_revision: revision, ...data };
}

export function isUnknownOutcome(error) {
  return Boolean(error?.isNetwork || !error?.statusCode || error.statusCode >= 500);
}

export function isReviewRequired(error) {
  return error?.statusCode === 409 || error?.statusCode === 412;
}

function query(path, params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') search.set(key, value);
  });
  const text = search.toString();
  return text ? `${path}?${text}` : path;
}

export const tenancyWorkflowApi = {
  listTemplates: (params, options) => api.get(query(workflowEndpoints.templates, params), options),
  createTemplate: (payload, options) => api.post(workflowEndpoints.templates, payload, options),
  getTemplate: (id, options) => api.get(workflowEndpoints.template(id), options),
  listTemplateVersions: (id, params, options) => api.get(query(workflowEndpoints.templateVersions(id), params), options),
  createTemplateVersion: (id, payload, options) => api.post(workflowEndpoints.templateVersions(id), payload, options),
  getTemplateVersion: (id, options) => api.get(workflowEndpoints.templateVersion(id), options),
  updateTemplateVersion: (id, payload, options) => api.put(workflowEndpoints.templateVersion(id), payload, options),
  publishTemplateVersion: (id, payload, options) => api.post(workflowEndpoints.publishTemplateVersion(id), payload, options),

  listChanges: (params, options) => api.get(query(workflowEndpoints.changes, params), options),
  previewChange: (payload, options) => api.post(workflowEndpoints.previewChange, payload, options),
  createChange: (payload, options) => api.post(workflowEndpoints.changes, payload, options),
  getChange: (id, options) => api.get(workflowEndpoints.change(id), options),
  patchChange: (id, payload, options) => api.patch(workflowEndpoints.change(id), payload, options),
  previewReanchor: (id, payload, options) => api.post(workflowEndpoints.reanchorPreview(id), payload, options),
  reanchor: (id, payload, options) => api.post(workflowEndpoints.reanchor(id), payload, options),
  patchStep: (changeId, stepId, payload, options) => api.patch(workflowEndpoints.step(changeId, stepId), payload, options),
  linkTask: (changeId, stepId, payload, options) => api.post(workflowEndpoints.task(changeId, stepId), payload, options),
  linkEvidence: (changeId, stepId, payload, options) => api.post(workflowEndpoints.evidence(changeId, stepId), payload, options),
  unlinkEvidence: (changeId, stepId, linkId, options) => api.del(workflowEndpoints.evidenceLink(changeId, stepId, linkId), options),
  completeChange: (id, payload, options) => api.post(workflowEndpoints.complete(id), payload, options),
};

export function assertPage(payload) {
  if (!payload || !Array.isArray(payload.items) || typeof payload.has_more !== 'boolean') {
    throw new Error('Ungültige Workflow-Listenantwort des Servers.');
  }
  return payload;
}

export async function collectCursorPages(loader, { signal, maxPages = 20 } = {}) {
  const items = [];
  let after;
  for (let page = 0; page < maxPages; page += 1) {
    const result = assertPage(await loader({ after, signal }));
    items.push(...result.items);
    if (!result.has_more) return items;
    if (!result.next_cursor || result.next_cursor === after) {
      throw new Error('Der Server lieferte keinen fortsetzbaren Cursor.');
    }
    after = result.next_cursor;
  }
  throw new Error('Die Referenzsuche wurde nach dem UI-Arbeitsbudget angehalten. Bitte Filter verfeinern.');
}
