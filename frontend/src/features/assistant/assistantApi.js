import { api } from '../../api';

const root = '/assistant';
const id = encodeURIComponent;
const page = cursor => `?limit=50${cursor ? `&cursor=${id(cursor)}` : ''}`;
export const assistantApi = {
  capabilities: options => api.get(`${root}/capabilities`, options),
  conversations: (cursor, options) => api.get(`${root}/conversations${page(cursor)}`, options),
  create: body => api.post(`${root}/conversations`, body),
  conversation: (value, options) => api.get(`${root}/conversations/${id(value)}`, options),
  edit: (value, body) => api.patch(`${root}/conversations/${id(value)}`, body),
  messages: (value, cursor, options) => api.get(`${root}/conversations/${id(value)}/messages${page(cursor)}`, options),
  attachments: (value, options, cursor) => api.get(`${root}/conversations/${id(value)}/attachments${page(cursor)}`, options),
  upload: (value, file, options) => { const body = new FormData(); body.append('file', file); return api.upload(`${root}/conversations/${id(value)}/attachments`, body, options); },
  download: (value, options) => api.getBlob(`${root}/attachments/${id(value)}/download`, options),
  runs: (value, cursor, options) => api.get(`${root}/conversations/${id(value)}/runs${page(cursor)}`, options),
  submit: (value, body) => api.post(`${root}/conversations/${id(value)}/runs`, body),
  run: (value, options) => api.get(`${root}/runs/${id(value)}`, options),
  cancel: (value, body) => api.post(`${root}/runs/${id(value)}/cancel`, body),
  retry: (value, body) => api.post(`${root}/runs/${id(value)}/retry`, body),
  connection: (provider, options) => api.get(`${root}/connections/${id(provider)}`, options),
  login: provider => api.post(`${root}/connections/${id(provider)}/login`, {}),
  cancelLogin: (provider, loginId) => api.post(`${root}/connections/${id(provider)}/login/cancel`, { login_id: loginId }),
  completeLogin: (provider, loginId, code) => api.post(`${root}/connections/${id(provider)}/login/${id(loginId)}/complete`, { code }),
  disconnect: provider => api.post(`${root}/connections/${id(provider)}/disconnect`, {}),
  probeConnection: provider => api.post(`${root}/connections/${id(provider)}/probe`, {}),
  previewContext: (selection, report, options) => api.post(`${root}/context/preview`, { selection, report: report || null, extract_documents: true }, options),
  proposals: (value, options, cursor) => api.get(`${root}/conversations/${id(value)}/proposals${page(cursor)}`, options),
  previewProposal: (value, body) => api.post(`${root}/proposals/${id(value)}/preview`, body),
  getProposal: (value, options) => api.get(`${root}/proposals/${id(value)}`, options),
  saveProposal: (value, body) => api.post(`${root}/proposals/${id(value)}/save`, body),
  applyProposal: (value, body) => api.post(`${root}/proposals/${id(value)}/apply`, body),
  rejectProposal: (value, body) => api.post(`${root}/proposals/${id(value)}/reject`, body),
};

export const contextSelection = cards => Object.fromEntries(['property', 'unit', 'tenant', 'contact', 'document', ...['contract', 'booking', 'receivable', 'invoice', 'task', 'maintenance', 'meter', 'standalone_reading', 'calendar', 'utility_statement', 'billing_period', 'service_contract', 'portfolio'].filter(kind => cards.some(card => card.kind === kind))]
  .map(kind => [`${kind}_ids`, [...new Set(cards.filter(card => card.kind === kind).map(card => card.id))]]));
export const activeRun = run => run && ['queued', 'running'].includes(run.state);
export const runText = run => run?.response || (run?.events || []).filter(event => event.type === 'delta' || event.type === 'text').map(event => event.text || '').join('');
