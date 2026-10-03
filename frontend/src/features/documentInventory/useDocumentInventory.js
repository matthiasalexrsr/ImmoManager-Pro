import { useInventory } from '../inventory/useInventory';

const configuration = {
  defaults: { search: '', document_type: '', view: 'all', property_id: '', date_from: '', date_to: '', sort_by: 'title', sort_order: 'asc' },
  resource: 'documents', filename: 'dokumente.csv',
  countFields: ['total', 'with_file', 'analyzed', 'no_assignment'],
  invalidMessage: 'Die Dokumentenliste konnte nicht geprüft werden.',
};

export function useDocumentInventory(principal) {
  return useInventory(principal, configuration);
}
