import { api } from '../../api';

export const contentSearchService = {
  status: options => api.get('/documents/text-index', options),
  refresh: options => api.post('/documents/text-index', {}, options),
  search: (q, options) => api.get(`/documents/search?${new URLSearchParams({ q, limit: '25' })}`, options),
};
