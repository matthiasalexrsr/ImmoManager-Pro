import { api } from '../../api';
import {
  PAGE_SIZE,
  validateChangePreview,
  validateCursorPage,
  validateReanchorPreview,
  validateStepInstance,
  validateTemplateVersion,
  validateTenancyChange,
} from './tenancyWorkflowModel';

const encodeId = value => encodeURIComponent(String(value));

function queryString(values) {
  const params = new URLSearchParams();
  for (const [name, value] of Object.entries(values)) {
    if (value !== undefined && value !== null && value !== '') params.set(name, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

function pageQuery(filters = {}, after, limit = PAGE_SIZE) {
  return queryString({ ...filters, after, limit });
}

export const workflowApi = {
  async listTemplates(filters = {}, { after = null, limit = PAGE_SIZE, signal } = {}) {
    return validateCursorPage(
      await api.get(`/workflow-templates${pageQuery(filters, after, limit)}`, { signal }),
      validateTemplateVersion,
    );
  },

  async getTemplate(templateId, { signal } = {}) {
    return validateTemplateVersion(await api.get(`/workflow-templates/${encodeId(templateId)}`, { signal }));
  },

  async listTemplateVersions(templateId, { after = null, limit = PAGE_SIZE, signal } = {}) {
    return validateCursorPage(
      await api.get(
        `/workflow-templates/${encodeId(templateId)}/versions${pageQuery({}, after, limit)}`,
        { signal },
      ),
      validateTemplateVersion,
    );
  },

  async getTemplateVersion(versionId, { signal } = {}) {
    return validateTemplateVersion(
      await api.get(`/workflow-template-versions/${encodeId(versionId)}`, { signal }),
    );
  },

  async createTemplate(command, { signal } = {}) {
    return validateTemplateVersion(await api.post('/workflow-templates', command, { signal }));
  },

  async createTemplateVersion(templateId, command, { signal } = {}) {
    return validateTemplateVersion(
      await api.post(`/workflow-templates/${encodeId(templateId)}/versions`, command, { signal }),
    );
  },

  async updateTemplateVersion(versionId, command, { signal } = {}) {
    return validateTemplateVersion(
      await api.put(`/workflow-template-versions/${encodeId(versionId)}`, command, { signal }),
    );
  },

  async publishTemplateVersion(versionId, command, { signal } = {}) {
    return validateTemplateVersion(
      await api.post(`/workflow-template-versions/${encodeId(versionId)}/publish`, command, { signal }),
    );
  },

  async listChanges(filters = {}, { after = null, limit = PAGE_SIZE, signal } = {}) {
    return validateCursorPage(
      await api.get(`/tenancy-changes${pageQuery(filters, after, limit)}`, { signal }),
      validateTenancyChange,
    );
  },

  async previewChange(payload, { signal } = {}) {
    return validateChangePreview(await api.post('/tenancy-changes/preview', payload, { signal }));
  },

  async createChange(command, { signal } = {}) {
    return validateTenancyChange(await api.post('/tenancy-changes', command, { signal }));
  },

  async getChange(changeId, { signal } = {}) {
    return validateTenancyChange(await api.get(`/tenancy-changes/${encodeId(changeId)}`, { signal }));
  },

  async patchChange(changeId, command, { signal } = {}) {
    return validateTenancyChange(
      await api.patch(`/tenancy-changes/${encodeId(changeId)}`, command, { signal }),
    );
  },

  async reanchorPreview(change, payload, { signal } = {}) {
    return validateReanchorPreview(
      await api.post(`/tenancy-changes/${encodeId(change.id)}/reanchor-preview`, payload, { signal }),
      change.id,
      change.revision,
    );
  },

  async reanchor(changeId, command, { signal } = {}) {
    return validateTenancyChange(
      await api.post(`/tenancy-changes/${encodeId(changeId)}/reanchor`, command, { signal }),
    );
  },

  async patchStep(changeId, stepId, command, { signal } = {}) {
    return validateStepInstance(
      await api.patch(
        `/tenancy-changes/${encodeId(changeId)}/steps/${encodeId(stepId)}`,
        command,
        { signal },
      ),
      changeId,
    );
  },

  async linkTask(changeId, stepId, command, { signal } = {}) {
    return validateStepInstance(
      await api.post(
        `/tenancy-changes/${encodeId(changeId)}/steps/${encodeId(stepId)}/task`,
        command,
        { signal },
      ),
      changeId,
    );
  },

  async linkEvidence(changeId, stepId, command, { signal } = {}) {
    return validateStepInstance(
      await api.post(
        `/tenancy-changes/${encodeId(changeId)}/steps/${encodeId(stepId)}/evidence`,
        command,
        { signal },
      ),
      changeId,
    );
  },

  async unlinkEvidence(changeId, stepId, linkId, command, { signal } = {}) {
    return validateStepInstance(
      await api.delJson(
        `/tenancy-changes/${encodeId(changeId)}/steps/${encodeId(stepId)}/evidence/${encodeId(linkId)}`,
        command,
        { signal },
      ),
      changeId,
    );
  },

  async completeChange(changeId, command, { signal } = {}) {
    return validateTenancyChange(
      await api.post(`/tenancy-changes/${encodeId(changeId)}/complete`, command, { signal }),
    );
  },
};

export function legacyPageLoader(path, filters = {}, mapItem = item => item) {
  return async ({ offset = 0, limit = PAGE_SIZE, signal }) => {
    const page = await api.get(
      `${path}${queryString({ ...filters, skip: offset, limit })}`,
      { signal },
    );
    if (!Array.isArray(page)) throw new Error('invalid_reference_page');
    return page.map(mapItem);
  };
}

export async function loadDocumentVersionPage(documentId, { before = null, limit = PAGE_SIZE, signal } = {}) {
  const result = await api.get(
    `/documents/${encodeId(documentId)}/versions${queryString({ before, limit })}`,
    { signal },
  );
  if (!result || result.document_id !== documentId || !Array.isArray(result.items)
      || !(result.next_before == null || Number.isSafeInteger(result.next_before))) {
    throw new Error('invalid_document_version_page');
  }
  return result;
}
