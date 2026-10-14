import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../../api';
import FileViewer from '../../components/FileViewer';

vi.mock('../../api', () => ({ api: { get: vi.fn() } }));
const pdfSources = vi.hoisted(() => []);
vi.mock('pdfjs-dist/legacy/build/pdf.mjs', () => ({ GlobalWorkerOptions: {}, getDocument: options => {
  pdfSources.push(options.url);
  return { promise: new Promise(() => {}), destroy: async () => {} };
} }));
afterEach(() => { cleanup(); vi.clearAllMocks(); pdfSources.length = 0; });

describe('FileViewer', () => {
  it('previews a signed PDF URL with the document title and safe download action', async () => {
    api.get.mockResolvedValue({ has_ocr: false });
    render(<FileViewer fileUrl="https://storage.example/lease.pdf?signature=abc" title="Mietvertrag" onClose={() => {}} />);
    expect(screen.getByRole('dialog', { name: 'Mietvertrag' })).toBeInTheDocument();
    await waitFor(() => expect(pdfSources).toContain('https://storage.example/lease.pdf?signature=abc'));
    expect(screen.getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', 'https://storage.example/lease.pdf?signature=abc');
    expect(screen.getByRole('button', { name: 'Herunterladen' })).toBeInTheDocument();
  });

  it('blocks unsafe file URLs from all preview and open surfaces', () => {
    render(<FileViewer fileUrl="javascript:alert(1)" onClose={() => {}} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.queryByTitle('PDF Viewer')).not.toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalled();
  });

  it('drops old OCR results when the file changes', async () => {
    let resolveOld;
    const old = new Promise(resolve => { resolveOld = resolve; });
    api.get.mockImplementation(path => path.includes('old.pdf') ? old : Promise.resolve({ has_ocr: false }));
    const view = render(<FileViewer fileUrl="/uploads/old.pdf" onClose={() => {}} />);
    await waitFor(() => expect(pdfSources).toContain(`${window.location.origin}/uploads/old.pdf`));
    view.rerender(<FileViewer fileUrl="/uploads/new.pdf" onClose={() => {}} />);
    await act(async () => resolveOld({ has_ocr: true, text: 'Veralteter Text' }));
    await waitFor(() => expect(pdfSources).toContain(`${window.location.origin}/uploads/new.pdf`));
    expect(screen.queryByRole('button', { name: 'OCR-Text' })).not.toBeInTheDocument();
    expect(screen.queryByText('Veralteter Text')).not.toBeInTheDocument();
  });
});
