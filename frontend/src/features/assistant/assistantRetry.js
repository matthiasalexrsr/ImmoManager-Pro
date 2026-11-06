import { contextSelection } from './assistantApi';

export const scopeLabels = { authorized: 'Berechtigte Verwaltungsdaten', selected: 'Nur ausgewählte Akten', none: 'Keine Verwaltungsdaten' };
const plainObject = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const sortedIds = value => Array.isArray(value) && value.every(id => typeof id === 'string' && id.length > 0)
  ? [...new Set(value)].sort() : null;
const canonical = value => Array.isArray(value) ? value.map(canonical) : plainObject(value)
  ? Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])])) : value;

function selection(value) {
  if (!plainObject(value)) return null;
  const entries = [];
  for (const [key, values] of Object.entries(value)) {
    const ids = sortedIds(values);
    if (!key.endsWith('_ids') || !ids) return null;
    if (ids.length) entries.push([key, ids]);
  }
  return Object.fromEntries(entries.sort(([a], [b]) => a.localeCompare(b)));
}

function decimal(value) {
  const text = String(value);
  if (!/^\d+(?:\.\d+)?$/.test(text)) return text;
  const [whole, fraction = ''] = text.split('.');
  const normalized = fraction.replace(/0+$/, '');
  return `${whole.replace(/^0+(?=\d)/, '')}${normalized ? `.${normalized}` : ''}`;
}

function report(value) {
  if (value == null) return null;
  if (!plainObject(value)) return undefined;
  // ReportDefinition adds these defaults to the server's public run. Compare
  // equivalent submitted forms without converting monetary values to floats.
  const normalized = { version: 2, months: 12, date_from: null, date_to: null, portfolio_id: null,
    property_id: null, unit_id: null, owner_contact_id: null, rent_payment_day: 3,
    rent_collection_percent: '100', arrears_collection_percent: '0', vacant_unit_ids: [], planned_flows: [], ...value };
  normalized.rent_collection_percent = decimal(normalized.rent_collection_percent);
  normalized.arrears_collection_percent = decimal(normalized.arrears_collection_percent);
  return canonical(normalized);
}

export function workingAttachmentIds(record, run, draft) {
  return [...new Set([...(record?.attachment_ids || run?.effective_attachment_ids || []), ...(draft.attachments || []).map(item => item.id)])]
    .filter(id => !(draft.excluded_attachment_ids || []).includes(id));
}

/** A retry creates a new inference for the old request, rather than sending the composer. */
export function originalRetryReview(run, { scope, context, attachmentIds, webResearch, report: currentReport }) {
  const originalSelection = selection(run?.context);
  const originalFiles = sortedIds(run?.effective_attachment_ids ?? run?.attachment_ids);
  const complete = Boolean(scopeLabels[run?.data_scope] && originalSelection && originalFiles && typeof run?.web_research === 'boolean'
    && Object.hasOwn(run, 'report') && report(run.report) !== undefined);
  const summary = { complete, scopeLabel: scopeLabels[run?.data_scope] || 'Nicht vollständig übermittelt',
    selectedCount: originalSelection ? Object.values(originalSelection).reduce((sum, ids) => sum + ids.length, 0) : null,
    fileCount: originalFiles?.length ?? null, webResearch: typeof run?.web_research === 'boolean' ? run.web_research : null,
    hasReport: run?.report != null };
  if (!complete) return { ...summary, allowed: false, reason: 'Der ursprüngliche Datenumfang ist nicht vollständig dokumentiert. Senden Sie eine neue Anfrage mit der aktuellen Auswahl.' };
  if (run.verification_status === 'stale') return { ...summary, allowed: false, reason: 'Die Quellen der Originalanfrage wurden inzwischen geändert. Senden Sie eine neue Anfrage, um den aktuellen Stand zu prüfen.' };
  const currentSelection = scope === 'none' ? {} : selection(contextSelection(context || []));
  const currentFiles = sortedIds(attachmentIds);
  const same = run.data_scope === scope && currentFiles && currentSelection
    && JSON.stringify(originalSelection) === JSON.stringify(currentSelection)
    && JSON.stringify(originalFiles) === JSON.stringify(currentFiles)
    && run.web_research === webResearch
    && JSON.stringify(report(run.report)) === JSON.stringify(report(scope === 'none' ? null : currentReport));
  return { ...summary, allowed: Boolean(same), reason: same ? ''
    : 'Die aktuelle Datenfreigabe oder Arbeitsauswahl weicht von der Originalanfrage ab. Prüfen Sie Ihre Eingabe und senden Sie eine neue Anfrage mit der aktuellen Auswahl.' };
}
