import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ReportProvenance, SourceEvidence } from '../features/reportEvidence/ReportProvenance';
import { api } from '../api';

vi.mock('../api', () => ({ api: { getBlob: vi.fn(), captureSession: vi.fn() } }));
const proof = { kind: 'record', source_sha256: 'source-sha', original: { status: 'verified_original', document_id: 'doc-1',
  version_id: 'version-2', version_number: 2, title: 'Rechnung', sha256: 'original-sha', filename: 'rechnung.pdf',
  message: 'Geprüfte Originalfassung zum Rechnungseingang.' } };
beforeEach(() => { vi.resetAllMocks(); api.captureSession.mockReturnValue(() => {}); });
afterEach(() => { vi.restoreAllMocks(); });

it('zeigt Datenabruf, fachlichen Stichtag und fehlende Belege getrennt', () => {
  render(<ReportProvenance result={{ generated_at: '2026-01-31T10:00:00Z', provenance: { as_of: '2026-01-15', source_records: 3,
    verified_originals: 1, invoices_without_verified_original: 2, unresolved_sources: 0, warning_count: 1,
    completeness: 'review_required', coverage: 'Nur erfasste Daten.', assumptions: 2 } }} />);
  expect(screen.getByLabelText('Datenstand und Vollständigkeit')).toHaveTextContent('fachlicher Stichtag 2026-01-15');
  expect(screen.getByRole('status')).toHaveTextContent('2 Rechnungen ohne geprüfte Originalfassung');
  expect(screen.getByText(/ausdrücklichen Planungsannahmen/)).toBeInTheDocument();
});

it('ruft genau die angezeigte Originalversion mit erneuter Sitzungsprüfung ab', async () => {
  const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  URL.createObjectURL = vi.fn(() => 'blob:report-evidence'); URL.revokeObjectURL = vi.fn();
  api.getBlob.mockResolvedValue(new Blob(['original']));
  const current = vi.fn(); api.captureSession.mockReturnValue(current);
  render(<SourceEvidence provenance={proof} />);
  fireEvent.click(screen.getByRole('button', { name: 'Originalbeleg Rechnung, Version 2 herunterladen' }));
  await waitFor(() => expect(clicked).toHaveBeenCalledTimes(1));
  expect(api.getBlob).toHaveBeenCalledWith('/documents/doc-1/work/versions/version-2/download', { signal: expect.any(AbortSignal) });
  expect(current).toHaveBeenCalledTimes(1);
});

it('zeigt Rechteentzug und liefert nach einem Kontowechsel keine Datei aus', async () => {
  const clicked = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  api.getBlob.mockResolvedValue(new Blob(['original']));
  api.captureSession.mockReturnValue(() => { throw new Error('Sitzung geändert'); });
  render(<SourceEvidence provenance={proof} />);
  fireEvent.click(screen.getByRole('button'));
  expect(await screen.findByRole('alert')).toHaveTextContent('Sitzung geändert');
  expect(clicked).not.toHaveBeenCalled();
});

it('bietet bei gesperrtem Beleg keinen Download an', () => {
  render(<SourceEvidence provenance={{ kind: 'record', original: { status: 'unavailable', message: 'Original nicht freigegeben.' } }} />);
  expect(screen.queryByRole('button')).toBeNull();
  expect(screen.getByText('Original nicht freigegeben.')).toBeInTheDocument();
});

