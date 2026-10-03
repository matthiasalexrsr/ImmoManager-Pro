import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, expect, it, vi } from 'vitest';
import Documents from '../pages/Documents';
import de from '../../../i18n/de-DE.json';
import { ocrFailure } from '../utils/ocrFailure';

const mocks = vi.hoisted(() => ({ role: 'eigentuemer', get: vi.fn(), getAll: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), fetch: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'owner', role: mocks.role }, role: mocks.role }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => ({ invalidateRelated: vi.fn() }), useEntities: () => ({ items: [] }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => vi.fn() }));
vi.mock('../components/FileViewer', () => ({ default: () => null }));
const translate = key => key.split('.').reduce((value, part) => value?.[part], de) ?? key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: translate, locale: 'de-DE' }) }));
const original = '/uploads/documents/retained.png';
const ocrError = () => Object.assign(new Error('Bild hat 1200 Pixel; Budget ist 100. Auflösung reduzieren.'), { code: 'ocr_pixel_budget', statusCode: 422 });

beforeEach(() => {
  vi.clearAllMocks(); mocks.role = 'eigentuemer'; mocks.get.mockImplementation(path => Promise.resolve(path.startsWith('/auth/users/me/form-drafts') ? { draft: null } : path.includes('/summary?')
    ? { total: 0, with_file: 0, analyzed: 0, no_assignment: 0 } : { items: [], has_more: false, next_cursor: null, selected: null })); mocks.getAll.mockResolvedValue([]);
  mocks.post.mockRejectedValue(ocrError());
  mocks.put.mockResolvedValue({ revision: 'draft-a', updated_at: '2026-10-03T00:00:00Z', expires_at: '2026-10-10T00:00:00Z' });
  mocks.del.mockResolvedValue({ discarded: true });
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ file_url: original }) });
  vi.stubGlobal('fetch', mocks.fetch);
});
async function upload(ui) {
  await screen.findByRole('region', { name: 'Gefilterte Dokumente' });
  fireEvent.change(ui.container.querySelector('input[type=file]'), { target: { files: [new File(['original bytes'], 'invoice.png', { type: 'image/png' })] } });
}

it('shows typed numeric OCR failure and correction while retaining original and allowing explicit metadata save', async () => {
  const ui = render(<MemoryRouter><Documents /></MemoryRouter>);
  await upload(ui);
  expect(await screen.findByText(/Bild hat 1200 Pixel; Budget ist 100/)).toBeInTheDocument();
  expect(screen.getByText('HTTP 422 · ocr_pixel_budget')).toBeInTheDocument();
  expect(screen.getByText(de.documentsOCR.corrections.budget)).toBeInTheDocument();
  expect(screen.getByText(de.documentsOCR.originalSaved)).toBeInTheDocument();
  expect(mocks.post.mock.calls.map(([path]) => path)).toEqual(['/documents/ocr-analyze']);
  expect(screen.getByText(new RegExp(original))).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Dokument erstellen' }));
  await screen.findByText('Entwurfsschutz bereit');
  fireEvent.change(screen.getByLabelText(/^Titel/), { target: { value: 'Manual review original' } });
  mocks.post.mockResolvedValue({ id: 'document' });
  fireEvent.click(screen.getByRole('button', { name: de.ui.buttons.save }));
  await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/documents', expect.objectContaining({ title: 'Manual review original', file_url: original })));
});

it('retries OCR against the saved original without uploading or creating financial records again', async () => {
  const ui = render(<MemoryRouter><Documents /></MemoryRouter>);
  await upload(ui);
  const retry = await screen.findByRole('button', { name: de.documentsOCR.retry });
  mocks.post.mockResolvedValue({ success: true, extracted_text: 'Recognized 271828', guessedType: 'Rechnung' });
  fireEvent.click(retry);
  await screen.findByText(/Recognized 271828/);
  expect(mocks.fetch).toHaveBeenCalledTimes(1);
  expect(mocks.post.mock.calls).toEqual([
    ['/documents/ocr-analyze', { file_url: original }], ['/documents/ocr-analyze', { file_url: original }],
  ]);
});

it('displays a typed error already returned by successful upload without immediately rerunning the worker', async () => {
  mocks.fetch.mockResolvedValue({ ok: true, json: async () => ({ file_url: original,
    ocr_error: { code: 'ocr_language_missing', message: 'Sprachdaten fehlen: deu.' } }) });
  const ui = render(<MemoryRouter><Documents /></MemoryRouter>);
  await upload(ui);
  await screen.findByText(/Sprachdaten fehlen: deu/);
  expect(screen.getByText('ocr_language_missing')).toBeInTheDocument();
  expect(screen.getByText(de.documentsOCR.corrections.setup)).toBeInTheDocument();
  expect(screen.getByText(de.documentsOCR.originalSaved)).toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalled();
});

it('keeps upload failure distinct and offers no retry against an unuploaded file', async () => {
  mocks.fetch.mockResolvedValue({ ok: false });
  const ui = render(<MemoryRouter><Documents /></MemoryRouter>);
  await upload(ui);
  await screen.findByText(new RegExp(de.pages.documents.upload.failed));
  expect(screen.queryByText(de.documentsOCR.originalSaved)).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: de.documentsOCR.retry })).not.toBeInTheDocument();
  expect(mocks.post).not.toHaveBeenCalled();
});

it('ignores an OCR response after write permission is revoked', async () => {
  let resolve;
  mocks.post.mockReturnValue(new Promise(done => { resolve = done; }));
  const ui = render(<MemoryRouter><Documents /></MemoryRouter>);
  await upload(ui);
  await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
  mocks.role = 'readonly'; ui.rerender(<MemoryRouter><Documents /></MemoryRouter>);
  await act(async () => resolve({ success: true, extracted_text: 'Late private result' }));
  expect(screen.queryByText(/Late private result/)).not.toBeInTheDocument();
  expect(screen.queryByText(de.documentsOCR.originalSaved)).not.toBeInTheDocument();
  expect(ui.container.querySelector('input[type=file]')).toBeNull();
});

it('preserves timeout semantics and maps unknown failures without inventing an OCR code', () => {
  const timeout = ocrFailure(Object.assign(new Error('Zeitbudget 5 Sekunden überschritten.'), { code: 'ocr_timeout', statusCode: 504 }), translate);
  expect(timeout).toMatchObject({ code: 'ocr_timeout', httpStatus: 504, message: 'Zeitbudget 5 Sekunden überschritten.', correction: de.documentsOCR.corrections.timeout });
  expect(ocrFailure(new Error('Network unavailable'), translate).code).toBeNull();
});
