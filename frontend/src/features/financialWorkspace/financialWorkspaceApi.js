import { api } from '../../api';
import { saveBlob } from '../../utils/bookingCsv';
import {
  cashFilterQuery,
  validateCashReport,
  validateCashSources,
} from './financialWorkspaceModel';

export const financialWorkspaceApi = {
  async report(filters, { signal } = {}) {
    const result = await api.get(`/reports/cash?${cashFilterQuery(filters)}`, { signal });
    return validateCashReport(result, filters);
  },

  async sources(filters, { sourceHash, after = null, limit = 50, signal } = {}) {
    const query = cashFilterQuery(filters, {
      source_hash: sourceHash,
      after,
      limit,
    });
    const result = await api.get(`/reports/cash/sources?${query}`, { signal });
    return validateCashSources(result, sourceHash, filters);
  },

  async exportCsv(filters, { signal } = {}) {
    const blob = await api.getBlob(`/reports/cash/export.csv?${cashFilterQuery(filters)}`, { signal });
    if (!(blob instanceof Blob) || blob.size === 0) throw new Error('invalid_cash_export');
    saveBlob(blob, 'zahlungsquellen.csv');
  },
};
