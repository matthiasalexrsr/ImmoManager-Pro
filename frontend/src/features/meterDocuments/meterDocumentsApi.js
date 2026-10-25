import { api } from '../../api';

const base = id => `/billing/meter-documents/${encodeURIComponent(id)}`;

// Kinds of cost the import offers; the keys are the cost categories of the utility statement.
export const CATEGORY_OPTIONS = [
  ['heating', 'Heizkosten'], ['hot_water', 'Warmwasser'], ['water', 'Wasser und Abwasser'],
  ['electricity', 'Allgemeinstrom'], ['garbage', 'Müllabfuhr'], ['cleaning', 'Gebäudereinigung'],
  ['garden', 'Gartenpflege'], ['insurance', 'Versicherung'], ['property_tax', 'Grundsteuer'], ['other', 'Sonstige Kosten'],
];

export const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.csv,.txt,.xlsx,.docx';

/** "ista_Abrechnung-2025.pdf" -> "ista Abrechnung 2025" */
export function titleFrom(name) {
  const stem = String(name || 'Dokument').replace(/\.[a-z0-9]{1,5}$/i, '').replace(/[_-]+/g, ' ').trim();
  return stem || 'Dokument des Messdienstes';
}

export const meterDocumentsApi = {
  readers: options => api.get('/billing/meter-documents/readers', options),
  upload: (file, propertyId) => {
    const form = new FormData();
    form.append('file', file);
    form.append('title', titleFrom(file.name));
    form.append('document_type', 'Nebenkostenabrechnung');
    form.append('tags', 'Messdienst');
    form.append('property_id', propertyId);
    return api.upload('/documents/import', form);
  },
  analyse: (documentId, body) => api.post(`${base(documentId)}/analysis`, body),
  apply: (documentId, body) => api.post(`${base(documentId)}/apply`, body),
};

/** The rows a person can change, from the proposal: costs and readings with their choice. */
export function editableRows(proposal, { withCosts }) {
  return {
    costs: (proposal.costs || []).map(cost => ({ ...cost, checked: withCosts && Boolean(cost.allocation_key_id) })),
    readings: (proposal.readings || []).map(reading => ({ ...reading, checked: Boolean(reading.meter_id && reading.reading_date) })),
  };
}

/** The body of the take-over: only checked rows, only the fields the server accepts. */
export function applyBody(rows, { propertyId, periodId }) {
  return {
    property_id: propertyId || null,
    billing_period_id: periodId || null,
    costs: rows.costs.filter(row => row.checked).map(row => ({
      description: row.description.trim(), amount: Number(row.amount), cost_category: row.cost_category || null,
      allocation_key_id: row.allocation_key_id, is_recoverable: row.is_recoverable !== false,
      consumption_share: row.consumption_share === '' || row.consumption_share == null ? null : Number(row.consumption_share),
      fixed_key_id: row.consumption_share ? row.fixed_key_id || null : null,
    })),
    readings: rows.readings.filter(row => row.checked).map(row => ({
      meter_id: row.meter_id, reading_date: row.reading_date, value: Number(row.value),
    })),
  };
}

/** What still keeps a checked row from being taken over, or ''. */
export function rowProblem(rows, keys) {
  const consumption = new Set((keys || []).filter(key => key.key_type === 'consumption').map(key => key.id));
  for (const row of rows.costs.filter(item => item.checked)) {
    if (!row.description?.trim()) return 'Eine Kostenposition hat keine Bezeichnung.';
    if (!(Number(row.amount) > 0)) return `„${row.description}“: bitte einen Betrag über 0 angeben.`;
    if (!row.allocation_key_id) return `„${row.description}“: bitte einen Verteilerschlüssel wählen.`;
    const share = row.consumption_share === '' || row.consumption_share == null ? null : Number(row.consumption_share);
    if (share != null && (share < 50 || share > 70)) return `„${row.description}“: der Verbrauchsanteil liegt zwischen 50 und 70 %.`;
    if (share != null && !consumption.has(row.allocation_key_id)) return `„${row.description}“: ein Verbrauchsanteil braucht einen Verbrauchsschlüssel.`;
  }
  for (const row of rows.readings.filter(item => item.checked)) {
    if (!row.meter_id) return `Gerät ${row.serial}: bitte einen Zähler wählen oder die Zeile abwählen.`;
    if (!row.reading_date) return `Gerät ${row.serial}: bitte den Ablesetag angeben.`;
    if (!(Number(row.value) >= 0) || row.value === '') return `Gerät ${row.serial}: bitte den Zählerstand angeben.`;
  }
  return '';
}
