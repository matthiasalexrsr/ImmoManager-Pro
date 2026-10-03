import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';
import { checkedPage, queryString, usePrivateRead } from '../unitInventory/read';

const defaults = { search: '', document_type: '', view: 'all', property_id: '', date_from: '', date_to: '', sort_by: 'title', sort_order: 'asc' };

export function useDocumentInventory(principal) {
  const [filters, setFilters] = useState(defaults);
  const [pages, setPages] = useState({ source: '', trail: [null] });
  const [generation, setGeneration] = useState(0);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);
  const request = useRef(null);
  useEffect(() => () => request.current?.abort(), []);
  const query = queryString({ ...filters, page_size: 25 });
  const trail = pages.source === query ? pages.trail : [null];
  const state = usePrivateRead(`/documents/inventory/page?${query}${trail.at(-1) ? `&cursor=${encodeURIComponent(trail.at(-1))}` : ''}`, principal, generation);
  const summary = usePrivateRead(`/documents/inventory/summary?${query}`, principal, generation);
  const page = checkedPage(state.data) ? state.data : null;
  const failure = state.error || (!state.loading && !page ? new Error('Die Dokumentenliste konnte nicht geprüft werden.') : null);
  const stats = summary.data && ['total', 'with_file', 'analyzed', 'no_assignment'].every(key => Number.isInteger(summary.data[key]) && summary.data[key] >= 0) ? summary.data : null;
  const change = (key, value) => { request.current?.abort(); setExporting(false); setExportError(null); setFilters(current => ({ ...current, [key]: value })); };
  const refresh = () => { setPages({ source: query, trail: [null] }); setGeneration(current => current + 1); };
  const reset = () => { request.current?.abort(); setExporting(false); setExportError(null); setFilters(defaults); };
  const download = async () => {
    request.current?.abort(); const controller = new AbortController(); request.current = controller;
    setExporting(true); setExportError(null);
    try {
      const blob = await api.getBlob(`/documents/inventory/export?${query}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob); const anchor = document.createElement('a');
      anchor.href = url; anchor.download = 'dokumente.csv'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { if (!controller.signal.aborted) setExportError(error); }
    finally { if (!controller.signal.aborted) setExporting(false); }
  };
  return { filters, change, reset, refresh, state, summary, stats, page, failure, exporting, exportError, download,
    pageNumber: trail.length, previous: () => setPages({ source: query, trail: trail.slice(0, -1) }),
    next: () => setPages({ source: query, trail: [...trail, page.next_cursor] }) };
}

