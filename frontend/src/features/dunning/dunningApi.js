// Dunning API (backend: /dunning). Command keys make a repeated click or a lost answer safe.
import { api } from '../../api';

const enc = value => encodeURIComponent(String(value));
const query = params => {
  const search = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''));
  return search.size ? `?${search}` : '';
};

export function commandKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

export const dunningService = {
  overview: (params = {}, opts) => api.get(`/dunning/overview${query(params)}`, opts),
  contractFile: (contractId, opts) => api.get(`/dunning/contracts/${enc(contractId)}`, opts),
  preview: scope => api.post('/dunning/preview', scope),
  createRun: (scope, previewHash, key = commandKey('run')) => api.post('/dunning/runs',
    { ...scope, preview_hash: previewHash, command_key: key }),
  letter: id => api.get(`/dunning/letters/${enc(id)}`),
  letterPdf: id => api.getBlob(`/dunning/letters/${enc(id)}/pdf`),
  finalize: (id, draftHash, channel, key = commandKey('finalize')) => api.post(`/dunning/letters/${enc(id)}/finalize`,
    { draft_hash: draftHash, channel, confirmed: true, command_key: key }),
  refresh: id => api.post(`/dunning/letters/${enc(id)}/refresh`, {}),
  cancel: (id, reason) => api.post(`/dunning/letters/${enc(id)}/cancel`, { reason }),
  addBlock: (contractId, body) => api.post(`/dunning/contracts/${enc(contractId)}/blocks`, body),
  liftBlock: (id, note) => api.post(`/dunning/blocks/${enc(id)}/lift`, { note: note || null }),
  addDispute: (contractId, body) => api.post(`/dunning/contracts/${enc(contractId)}/disputes`, body),
  decideDispute: (id, decision) => api.post(`/dunning/disputes/${enc(id)}/decide`, { decision }),
  result: (caseId, body) => api.post(`/dunning/cases/${enc(caseId)}/result`, body),
  timeline: (caseId, after) => api.get(`/dunning/cases/${enc(caseId)}/timeline${query({ after, limit: 50 })}`),
  addNote: (caseId, text) => api.post(`/dunning/cases/${enc(caseId)}/notes`, { text }),
  outbox: (params = {}) => api.get(`/dunning/outbox${query(params)}`),
  markSent: (id, body) => api.post(`/dunning/outbox/${enc(id)}/mark-sent`, body),
  eml: id => api.getBlob(`/dunning/outbox/${enc(id)}/eml`),
  replies: (params = {}) => api.get(`/dunning/replies${query(params)}`),
  recordReply: body => api.post('/dunning/replies', body),
  assignReply: (id, target) => api.post(`/dunning/replies/${enc(id)}/assign`, target),
  dismissReply: id => api.post(`/dunning/replies/${enc(id)}/dismiss`, {}),
  settings: () => api.get('/dunning/settings'),
  saveStages: stages => api.put('/dunning/settings/stages', { stages }),
  addRate: body => api.post('/dunning/settings/base-rates', body),
  removeRate: id => api.del(`/dunning/settings/base-rates/${enc(id)}`),
};

/** Save a blob under a file name (PDF, .eml) without opening a window. */
export function saveBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
