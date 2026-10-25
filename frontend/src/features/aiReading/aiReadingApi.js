import { api } from '../../api';
import { formatDate, formatMoney } from '../../utils/format';

const key = () => crypto.randomUUID();

export const aiReadingApi = {
  options: (surface, options) => api.get(`/ai/readings/options${surface ? `?surface=${encodeURIComponent(surface)}` : ''}`, options),
  start: body => api.post('/ai/readings', { ...body, idempotency_key: body.idempotency_key || key() }),
  get: id => api.get(`/ai/readings/${encodeURIComponent(id)}`),
  say: (reading, text, idempotency_key = key()) => api.post(`/ai/readings/${encodeURIComponent(reading.id)}/messages`,
    { text, expected_revision: reading.revision, idempotency_key }),
  decide: (reading, action, record) => api.post(`/ai/readings/${encodeURIComponent(reading.id)}/decision`,
    { action, record_kind: record?.kind || null, record_id: record?.id || null, expected_revision: reading.revision, idempotency_key: key() }),
  finish: (reading, outcome, record) => api.post(`/ai/readings/${encodeURIComponent(reading.id)}/finish`,
    { outcome, record_kind: record?.kind || null, record_id: record?.id || null, expected_revision: reading.revision, idempotency_key: key() }),
  upload: async (file, folder = 'documents') => {
    const form = new FormData();
    form.append('file', file);
    const uploaded = await api.upload(`/files/upload?folder=${encodeURIComponent(folder)}`, form);
    if (!uploaded?.file_url) throw new Error('Der Server hat keine Datei zurückgegeben.');
    return uploaded.file_url;
  },
};

export const CONFIDENCE_LABELS = { high: 'sicher', medium: 'wahrscheinlich', low: 'unsicher' };
export const READER_HINTS = {
  local: 'Lokale Regeln: das Dokument bleibt auf diesem Rechner. Für Scans, Fotos und das Gespräch Claude oder ChatGPT verbinden.',
  claude: 'Das Dokument wird zum Lesen an Claude (Ihr verbundenes Konto) gesendet.',
  codex: 'Das Dokument wird zum Lesen an ChatGPT (Ihr verbundenes Konto) gesendet.',
};

/** The reader to preselect: the person's default if it can read here, else the first connected AI, else the rules. */
export function preferredReader(options, needsAi = false) {
  const readers = options?.readers || [];
  const ready = readers.filter(item => item.ai && item.available).map(item => item.id);
  const preferred = options?.default_reader;
  if (preferred === 'local' && !needsAi) return 'local';
  if (['claude', 'codex'].includes(preferred) && ready.includes(preferred)) return preferred;
  if (ready.length && options?.ai_enabled !== false) return ready[0];
  return needsAi ? '' : 'local';
}

/** The value of a field as a form takes it: units and tenants become their id, everything else stays text. */
export function formValue(item) {
  const value = item?.value;
  if (value && typeof value === 'object' && 'id' in value) return value.id;
  return value ?? '';
}

/**
 * Values of a reading for a form, and the marks the form shows: `mapping` names for each form field the
 * reading field it comes from (or a function of all values). Only fields with a value are returned.
 */
export function readingToForm(reading, mapping) {
  const values = reading?.values || {};
  const initial = {};
  const marks = {};
  for (const [formKey, source] of Object.entries(mapping)) {
    const item = typeof source === 'function' ? source(values) : values[source];
    if (item == null || item.value == null || item.value === '') continue;
    initial[formKey] = formValue(item);
    marks[formKey] = { value: String(formValue(item)), evidence: item.evidence || null, confidence: item.confidence || null,
      source: item.source || reading.reader };
  }
  return { initial, marks };
}

export const CHOICE_LABELS = {
  heating: 'Heizung', hot_water: 'Warmwasser', water: 'Wasser', sewage: 'Abwasser', electricity: 'Allgemeinstrom',
  waste: 'Müllabfuhr', street_cleaning: 'Straßenreinigung', cleaning: 'Gebäudereinigung', garden: 'Gartenpflege',
  caretaker: 'Hauswart', insurance: 'Versicherung', property_tax: 'Grundsteuer', elevator: 'Aufzug', chimney: 'Schornsteinfeger',
  cable_tv: 'Kabel/Antenne', lighting: 'Beleuchtung', maintenance: 'Instandhaltung', administration: 'Verwaltung', other: 'Sonstiges',
  invoice: 'Rechnung', credit_note: 'Gutschrift', true: 'Ja', false: 'Nein', cold_water: 'Kaltwasser', gas: 'Gas',
};

export function shownValue(field, value) {
  if (value == null || value === '') return '—';
  if (typeof value === 'object') return value.label || '—';
  if (field?.kind === 'money') return formatMoney(Number(value));
  if (field?.kind === 'date') return formatDate(value);
  if (field?.kind === 'percent') return `${String(value).replace('.', ',')}\u00a0%`;
  if (field?.kind === 'number') return String(value).replace('.', ',');
  if (field?.kind === 'choice') return CHOICE_LABELS[value] || value;
  return String(value);
}
