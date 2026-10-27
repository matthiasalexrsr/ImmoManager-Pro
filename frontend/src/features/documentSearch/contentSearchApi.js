import { api } from '../../api';

const parameters = scope => Object.fromEntries(['property_id', 'unit_id', 'contract_id']
  .filter(key => typeof scope[key] === 'string' && scope[key]).map(key => [key, scope[key]]));
const suffix = scope => { const query = new URLSearchParams(parameters(scope)).toString(); return query ? `?${query}` : ''; };
export const contentSearchService = {
  status: ({ scope = {}, ...options } = {}) => api.get(`/documents/text-index${suffix(scope)}`, options),
  refresh: ({ scope = {}, ...options } = {}) => api.post(`/documents/text-index${suffix(scope)}`, {}, options),
  search: (q, { scope = {}, skip = 0, ...options } = {}) => api.get(`/documents/search?${new URLSearchParams({ q, limit: '25', skip: String(skip), ...parameters(scope) })}`, options),
};
