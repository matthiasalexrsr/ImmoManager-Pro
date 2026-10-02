import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api';
import FileViewer from '../components/FileViewer';
import useProtectedFile, { storageKey } from '../hooks/useProtectedFile';

vi.mock('../api', () => ({ api: { getBlob: vi.fn(), get: vi.fn() } }));
const createUrl = vi.fn();
const revokeUrl = vi.fn();
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const png = () => new Blob([new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10])], { type: 'image/png' });

beforeEach(() => {
  vi.clearAllMocks();
  URL.createObjectURL = createUrl.mockReturnValue('blob:protected-file');
  URL.revokeObjectURL = revokeUrl;
  api.get.mockResolvedValue({ has_ocr: false });
});
afterEach(() => vi.restoreAllMocks());

describe('private file references and lifecycle', () => {
  it('normalizes local, same-origin and S3 keys while rejecting external and escaping references', () => {
    expect(storageKey('/uploads/documents/image%20one.png')).toBe('documents/image one.png');
    expect(storageKey(`${window.location.origin}/uploads/documents/file.pdf`)).toBe('documents/file.pdf');
    expect(storageKey('s3://private-bucket/documents/file.pdf')).toBe('documents/file.pdf');
    expect(storageKey('s3://private-bucket/uploads/file.pdf')).toBe('uploads/file.pdf');
    for (const reference of ['https://foreign.example/uploads/file.png', '//foreign.example/uploads/file.png', 'javascript:alert(1)', '/uploads/../secret.txt', '/uploads/%2e%2e/secret', 'C:\\secret.txt', '/uploads/a%5cb.png', '/uploads/file%00.png']) {
      expect(() => storageKey(reference)).toThrow('Ungültiger Dateiverweis');
    }
  });

  it('aborts replaced files, ignores late responses and revokes each created Blob URL', async () => {
    const old = pending();
    api.getBlob.mockReturnValueOnce(old.promise).mockResolvedValueOnce(png());
    const hook = renderHook(({ reference }) => useProtectedFile(reference), { initialProps: { reference: '/uploads/old.png' } });
    const oldSignal = api.getBlob.mock.calls[0][1].signal;
    hook.rerender({ reference: 's3://bucket/new.png' });
    expect(oldSignal.aborted).toBe(true);
    await waitFor(() => expect(hook.result.current.url).toBe('blob:protected-file'));
    await act(async () => old.resolve(new Blob(['old'])));
    expect(createUrl).toHaveBeenCalledTimes(1);
    expect(api.getBlob.mock.calls[1][0]).toBe('/files/download?key=new.png');
    hook.unmount();
    expect(revokeUrl).toHaveBeenCalledWith('blob:protected-file');
  });

  it('displays download failure and retries without exposing the private URL', async () => {
    api.getBlob.mockRejectedValueOnce(new Error('Datei nicht gefunden')).mockResolvedValueOnce(png());
    render(<FileViewer fileUrl="/uploads/documents/image.png" onClose={() => {}} />);
    await screen.findByText('Datei nicht gefunden');
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    await waitFor(() => expect(screen.getByAltText('Dokument').getAttribute('src')).toBe('blob:protected-file'));
    expect(screen.getByRole('link', { name: 'Herunterladen' })).toHaveAttribute('download', 'image.png');
  });

  it('clears stale OCR and does not show late text from the previous file', async () => {
    const oldOcr = pending();
    api.get.mockReturnValueOnce(oldOcr.promise).mockResolvedValueOnce({ has_ocr: false });
    api.getBlob.mockResolvedValue(png());
    const view = render(<FileViewer fileUrl="/uploads/old.png" onClose={() => {}} />);
    const signal = api.get.mock.calls[0][1].signal;
    view.rerender(<FileViewer fileUrl="/uploads/new.png" onClose={() => {}} />);
    await act(async () => oldOcr.resolve({ has_ocr: true, text: 'Private text from old file' }));
    expect(signal.aborted).toBe(true);
    expect(screen.queryByRole('button', { name: 'OCR-Text' })).not.toBeInTheDocument();
    expect(screen.queryByText('Private text from old file')).not.toBeInTheDocument();
  });

  it('downloads active HTML and spoofed PDFs, and previews only verified PDF bytes with a fixed MIME', async () => {
    api.getBlob.mockResolvedValue(new Blob(['<script>bad()</script>'], { type: 'text/html' }));
    const view = render(<FileViewer fileUrl="/uploads/document.html" onClose={() => {}} />);
    await screen.findByRole('link', { name: 'Datei herunterladen' });
    expect(document.querySelector('iframe')).toBeNull();
    expect(screen.getByRole('link', { name: 'Herunterladen' })).toHaveAttribute('download', 'document.html');
    expect(createUrl.mock.calls.at(-1)[0].type).toBe('application/octet-stream');
    view.rerender(<FileViewer fileUrl="/uploads/document.pdf" onClose={() => {}} />);
    await screen.findByText('Dateiinhalt passt nicht zum Dateityp. Die Datei kann nur heruntergeladen werden.');
    expect(document.querySelector('iframe')).toBeNull();
    expect(createUrl.mock.calls.at(-1)[0].type).toBe('application/octet-stream');
    api.getBlob.mockResolvedValueOnce(new Blob(['%PDF-1.4\nverified PDF'], { type: 'text/html' }));
    view.rerender(<FileViewer fileUrl="/uploads/verified.pdf" onClose={() => {}} />);
    const iframe = await screen.findByTitle('PDF Viewer');
    expect(iframe).not.toHaveAttribute('sandbox');
    expect(createUrl.mock.calls.at(-1)[0].type).toBe('application/pdf');
  });

  it('refuses active content disguised as an image and treats SVG as download only', async () => {
    api.getBlob.mockResolvedValue(new Blob(['<svg onload="bad()"></svg>'], { type: 'image/svg+xml' }));
    const view = render(<FileViewer fileUrl="/uploads/disguised.png" onClose={() => {}} />);
    await screen.findByText('Dateiinhalt passt nicht zum Dateityp. Die Datei kann nur heruntergeladen werden.');
    expect(screen.queryByAltText('Dokument')).not.toBeInTheDocument();
    view.rerender(<FileViewer fileUrl="/uploads/vector.svg" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByRole('link', { name: 'Herunterladen' })).toHaveAttribute('download', 'vector.svg'));
    expect(screen.queryByAltText('Dokument')).not.toBeInTheDocument();
    expect(document.querySelector('iframe')).toBeNull();
    expect(createUrl.mock.calls.at(-1)[0].type).toBe('application/octet-stream');
  });
});
