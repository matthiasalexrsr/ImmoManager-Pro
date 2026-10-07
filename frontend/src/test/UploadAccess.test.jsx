import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import FileViewer from '../components/FileViewer';
import { api } from '../api';
import { downloadFile } from '../features/partyWorkspace/files';

vi.mock('../api', () => ({ api: { get: vi.fn() } }));
const engine = vi.hoisted(() => ({ getDocument: vi.fn(), GlobalWorkerOptions: {} }));
vi.mock('pdfjs-dist', () => engine);
const deferred = () => { let resolve; let reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.setItem('access_token', 'session-a');
  api.get.mockResolvedValue({ has_ocr: false });
  engine.getDocument.mockReturnValue({ promise: new Promise(() => {}), destroy: vi.fn().mockResolvedValue() });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); localStorage.clear(); });

describe('protected upload consumers', () => {
  it('does not start an own image before session preparation succeeds', async () => {
    const access = deferred();
    api.get.mockImplementation(path => path === '/auth/me' ? access.promise : Promise.resolve({ has_ocr: false }));
    render(<FileViewer fileUrl="/uploads/image.png" title="Foto" onClose={() => {}} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    await act(async () => { access.resolve({ id: 'reader' }); });
    expect(await screen.findByRole('img', { name: 'Foto' })).toHaveAttribute('src', `${window.location.origin}/uploads/image.png`);
  });

  it('prepares the session before starting a PDF and again after a failed render retry', async () => {
    const access = deferred();
    api.get.mockImplementation(path => path === '/auth/me' ? access.promise : Promise.resolve({ has_ocr: false }));
    engine.getDocument.mockImplementation(() => ({ promise: Promise.reject(new Error('expired file access')), destroy: vi.fn().mockResolvedValue() }));
    render(<FileViewer fileUrl="/uploads/lease.pdf" title="Vertrag" onClose={() => {}} />);
    await waitFor(() => expect(api.get.mock.calls.some(([path]) => path === '/auth/me')).toBe(true));
    expect(engine.getDocument).not.toHaveBeenCalled();
    await act(async () => { access.resolve({ id: 'reader' }); });
    await screen.findByRole('alert');
    const before = api.get.mock.calls.filter(([path]) => path === '/auth/me').length;
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    await waitFor(() => expect(api.get.mock.calls.filter(([path]) => path === '/auth/me')).toHaveLength(before + 1));
  });

  it('keeps failed own-image access actionable and allows retry without requesting a broken image', async () => {
    let calls = 0;
    api.get.mockImplementation(path => path === '/auth/me' && calls++ === 0 ? Promise.reject(new Error('Server offline')) : Promise.resolve({ has_ocr: false }));
    render(<FileViewer fileUrl="/uploads/image.png" title="Foto" onClose={() => {}} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Server offline');
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    expect(await screen.findByRole('img', { name: 'Foto' })).toBeInTheDocument();
  });

  it('does not prepare or add credentials for an unrelated storage host', async () => {
    render(<FileViewer fileUrl="https://outside.example/uploads/photo.png?sig=x" title="Extern" onClose={() => {}} />);
    expect(await screen.findByRole('img', { name: 'Extern' })).toHaveAttribute('src', 'https://outside.example/uploads/photo.png?sig=x');
    expect(api.get).not.toHaveBeenCalled();
  });

  it('does not fetch a download if session preparation fails', async () => {
    api.get.mockRejectedValue(new Error('Sitzung nicht verfügbar'));
    const fileFetch = vi.fn();
    vi.stubGlobal('fetch', fileFetch);
    await expect(downloadFile('/uploads/lease.pdf', 'Vertrag')).rejects.toThrow('Sitzung nicht verfügbar');
    expect(fileFetch).not.toHaveBeenCalled();
  });

  it('navigates a reserved original-file tab only after preparation and closes it on file change', async () => {
    const access = deferred();
    api.get.mockImplementation(path => path === '/auth/me' ? access.promise : Promise.resolve({ has_ocr: false }));
    const popup = { opener: window, location: { replace: vi.fn() }, close: vi.fn() };
    vi.spyOn(window, 'open').mockReturnValue(popup);
    const view = render(<FileViewer fileUrl="/uploads/one.png" title="Eins" onClose={() => {}} />);
    fireEvent.click(screen.getByRole('link', { name: 'Öffnen' }));
    expect(popup.opener).toBeNull();
    expect(popup.location.replace).not.toHaveBeenCalled();
    await act(async () => { access.resolve({}); });
    expect(popup.location.replace).toHaveBeenCalledWith(`${window.location.origin}/uploads/one.png`);

    const next = deferred();
    api.get.mockImplementation(path => path === '/auth/me' ? next.promise : Promise.resolve({ has_ocr: false }));
    fireEvent.click(screen.getByRole('link', { name: 'Öffnen' }));
    view.rerender(<FileViewer fileUrl="/uploads/two.png" title="Zwei" onClose={() => {}} />);
    expect(popup.close).toHaveBeenCalledTimes(1);
    await act(async () => { next.resolve({}); });
    expect(popup.location.replace).toHaveBeenCalledTimes(1);
  });

  it('preserves a signed foreign download URL without authorization or cross-origin credentials', async () => {
    const fileFetch = vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(['file']) });
    vi.stubGlobal('fetch', fileFetch);
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:download'), revokeObjectURL: vi.fn() }));
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    const url = 'https://outside.example/uploads/a.pdf?sig=unchanged';
    await downloadFile(url, 'Beleg');
    expect(fileFetch).toHaveBeenCalledWith(url, { signal: undefined, credentials: 'same-origin' });
    expect(api.get).not.toHaveBeenCalled();
  });
});
