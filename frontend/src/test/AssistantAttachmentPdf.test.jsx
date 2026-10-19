import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import AssistantAttachment from '../features/assistant/AssistantAttachment';
import { api } from '../api';

const engine = vi.hoisted(() => ({ getDocument: vi.fn(), GlobalWorkerOptions: {} }));
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => engine);
vi.mock('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url', () => ({ default: '/pdf-worker-test.mjs' }));
vi.mock('../api', () => ({ api: { captureSession: vi.fn(() => () => {}), getBlob: vi.fn() } }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('renders private PDF bytes with the existing safe paginated PDF.js viewer and releases them on close', async () => {
  const cleanupPage = vi.fn(); const destroy = vi.fn().mockResolvedValue();
  const getPage = vi.fn(async number => ({ getViewport: ({ scale }) => ({ width: 595 * scale, height: 842 * scale }), render: () => ({ promise: Promise.resolve(), cancel: vi.fn() }), getTextContent: async () => ({ items: [{ str: `Beleg Seite ${number}` }] }), cleanup: cleanupPage }));
  engine.getDocument.mockReturnValue({ promise: Promise.resolve({ numPages: 2, getPage }), destroy });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({}); vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
  URL.createObjectURL = vi.fn(() => 'blob:private-pdf'); URL.revokeObjectURL = vi.fn(); api.getBlob.mockResolvedValue(new Blob(['%PDF-test'], { type: 'application/pdf' }));
  render(<AssistantAttachment attachment={{ id: 'private-pdf', mime: 'application/pdf', name: 'Beleg.pdf', byte_length: 200 }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Datei ansehen: Beleg.pdf' }));
  await screen.findByRole('img', { name: /Beleg.pdf.*Seite 1 von 2/ }); expect(api.getBlob).toHaveBeenCalledWith('/assistant/attachments/private-pdf/download', expect.objectContaining({ signal: expect.any(AbortSignal) }));
  expect(engine.getDocument).toHaveBeenCalledWith(expect.objectContaining({ url: 'blob:private-pdf', withCredentials: false })); expect(document.querySelector('iframe')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'Nächste Seite' })); await screen.findByRole('img', { name: /Seite 2 von 2/ });
  expect(screen.getByRole('link', { name: 'Original herunterladen' })).toHaveAttribute('download', 'Beleg.pdf');
  fireEvent.click(screen.getByRole('button', { name: 'Dateivorschau schließen' }));
  await waitFor(() => expect(destroy).toHaveBeenCalled()); expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:private-pdf');
});
