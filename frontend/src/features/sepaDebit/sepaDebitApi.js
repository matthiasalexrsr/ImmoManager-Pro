import { api } from '../../api';

export const sepaDebitService = {
  accounts: options => api.list('/accounts', options),
  preview: (params, options) => api.get(`/receivables/sepa-debits/preview?${new URLSearchParams(params)}`, options),
  create: body => api.post('/receivables/sepa-debits/files', body),
};

/** The month after `today` as YYYY-MM (rents are usually collected for the coming month). */
export function nextMonth(today = new Date()) {
  const next = new Date(today.getFullYear(), today.getMonth() + 1, 1);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}`;
}

/** Contracts preselected in the file: ready ones that were not written to a file before. */
export function preselected(lines) {
  return new Set((lines || []).filter(line => line.ready && !line.repeated).map(line => line.contract_id));
}

export function totalOf(lines, chosen) {
  const cents = (lines || []).filter(line => chosen.has(line.contract_id))
    .reduce((sum, line) => sum + Math.round(Number(line.amount) * 100), 0);
  return cents / 100;
}

export function saveXml(result) {
  const url = URL.createObjectURL(new Blob([result.xml], { type: 'application/xml' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = result.filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
