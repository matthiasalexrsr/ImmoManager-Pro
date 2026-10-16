import { useEffect, useState } from 'react';
import { api } from '../../api';

// Documents for Aktenwerk (DMS): see docs/AKTENWERK_INTERFACE_20261014.md for the contract.
export const KINDS = [
  ['vertrag', 'Verträge'], ['rechnung', 'Rechnungen'], ['beleg', 'Belege'], ['abrechnung', 'Abrechnungen'],
  ['protokoll', 'Protokolle'], ['korrespondenz', 'Schreiben'], ['bescheid', 'Bescheide'], ['nachweis', 'Nachweise'],
  ['bescheinigung', 'Bescheinigungen'], ['sonstiges', 'Sonstiges'],
];
export const KIND_LABEL = Object.fromEntries(KINDS);

export const documentExchangeId = id => (id ? `immomanager:document:${id}` : null);
export const receiptExchangeId = id => (id ? `immomanager:booking-receipt:${id}` : null);

export function queryOf({ kinds = [], year = '', taxRelevant = false, deductible = false, propertyId = '' } = {}) {
  const params = new URLSearchParams();
  kinds.forEach(kind => params.append('kind', kind));
  if (year) params.set('year', year);
  if (propertyId) params.set('property_id', propertyId);
  if (taxRelevant) params.set('tax_relevant', 'true');
  if (deductible) params.set('deductible', 'true');
  const text = params.toString();
  return text ? `?${text}` : '';
}

export const aktenwerkApi = {
  manifest: (filters, options) => api.get(`/aktenwerk/manifest${queryOf(filters)}`, options),
  exportZip: (filters, options) => api.getBlob(`/aktenwerk/export${queryOf(filters)}`, options),
  send: exchangeIds => api.post('/aktenwerk/send', { exchange_ids: exchangeIds }),
  // not /integrations/aktenwerk: accounts limited to some portfolios may not read the settings
  status: options => api.get('/aktenwerk/status', options),
};

// The server takes at most this many documents per request.
export const SEND_BATCH = 200;

/** Hand over any number of documents in batches the server accepts; one result for all of them. */
export async function sendAll(exchangeIds, send = aktenwerkApi.send) {
  let sent = 0; let failed = 0; let unknown = 0; const results = [];
  const warnings = new Set();
  for (let start = 0; start < exchangeIds.length; start += SEND_BATCH) {
    let outcome;
    try {
      outcome = await send(exchangeIds.slice(start, start + SEND_BATCH));
    } catch {
      // A lost response may follow an accepted transfer. Keep completed batches
      // visible, stop sending and distinguish the unconfirmed batch from later ones.
      const attempted = Math.min(SEND_BATCH, exchangeIds.length - start);
      results.push(...exchangeIds.slice(start).map((id, offset) => ({
        exchange_id: id, status: offset < attempted ? 'unknown' : 'failed',
        reason: offset < attempted
          ? 'Übergabe unbestätigt: Antwort nicht erhalten. Vor erneutem Versand in Aktenwerk prüfen.'
          : 'Nach unterbrochener Übergabe nicht gesendet.',
      })));
      unknown += attempted;
      failed += exchangeIds.length - start - attempted;
      break;
    }
    const batch = exchangeIds.slice(start, start + SEND_BATCH);
    const received = Array.isArray(outcome?.results) ? outcome.results : [];
    const statuses = new Set(['sent', 'already_present', 'failed', 'conflict', 'unknown']);
    const byId = new Map();
    let inconsistent = !Array.isArray(outcome?.results);
    for (const item of received) {
      if (!item || !batch.includes(item.exchange_id) || !statuses.has(item.status) || byId.has(item.exchange_id)) {
        inconsistent = true;
      } else {
        byId.set(item.exchange_id, item);
      }
    }
    const verified = batch.map(id => byId.get(id));
    const successful = verified.filter(item => ['sent', 'already_present'].includes(item?.status)).length;
    const rejected = verified.filter(item => ['failed', 'conflict'].includes(item?.status)).length;
    const unresolved = verified.filter(item => item?.status === 'unknown').length;
    inconsistent ||= byId.size !== batch.length
      || (outcome?.sent != null && outcome.sent !== successful)
      || (outcome?.failed != null && outcome.failed !== rejected)
      || (outcome?.unknown != null && outcome.unknown !== unresolved);
    if (inconsistent) {
      // A broken/missing receipt is not proof that the remote write failed.
      // Do not silently lose IDs, miscount, or automatically resend this batch.
      results.push(...batch.map(exchange_id => ({ exchange_id, status: 'unknown',
        reason: 'Übertragungsantwort unvollständig oder widersprüchlich; externen Zustand prüfen.' })));
      unknown += batch.length;
    } else {
      results.push(...verified);
      sent += successful;
      failed += rejected;
      unknown += unresolved;
    }
    if (outcome?.history_warning) warnings.add(outcome.history_warning);
  }
  const summary = sent ? `${sent} an Aktenwerk übergeben` : 'Nichts übergeben';
  const message = summary + (failed ? (sent ? `, ${failed} fehlgeschlagen` : ` (${failed} fehlgeschlagen)`) : '')
    + (unknown ? ` · ${unknown} Ausgang unklar: in Aktenwerk abgleichen` : '');
  return { message, sent, failed, unknown, results, ...(warnings.size ? { history_warning: [...warnings].join(' ') } : {}) };
}

// Whether a transfer is possible: the integration is switched on and has a usable address.
// Fetched once per page view; lists only show "An Aktenwerk" when it is.
export function useAktenwerkReady() {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    aktenwerkApi.status({ signal: controller.signal })
      .then(status => setReady(Boolean(status?.enabled && status?.configured)))
      .catch(() => setReady(false));
    return () => controller.abort();
  }, []);
  return ready;
}

/** Bulk action for DataTable: each selected row with a document goes to Aktenwerk on its own. */
export function aktenwerkBulkAction(exchangeIdOf, label = 'An Aktenwerk übergeben') {
  return {
    key: 'aktenwerk',
    label,
    write: true,
    applies: row => Boolean(exchangeIdOf(row)),
    confirm: rows => `${rows.length} ${rows.length === 1 ? 'Dokument' : 'Dokumente'} an Aktenwerk übergeben? `
      + 'Nur Aktenwerk kann die Übernahme bestätigen. Unklaren Ausgang vor erneutem Versand prüfen.',
    run: async row => {
      const result = await aktenwerkApi.send([exchangeIdOf(row)]);
      const item = result?.results?.[0];
      if (!item || !['sent', 'already_present'].includes(item.status)) {
        throw new Error(item?.reason || result?.message || 'Übergabe nicht bestätigt');
      }
    },
  };
}
