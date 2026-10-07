import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import FileViewer from '../components/FileViewer';

const engine = vi.hoisted(() => ({ getDocument: vi.fn(), GlobalWorkerOptions: {} }));
vi.mock('pdfjs-dist', () => engine);
vi.mock('../api', () => ({ api: { get: vi.fn().mockResolvedValue({ has_ocr: false }) } }));

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const makePage = (number, extra = {}) => ({
  getViewport: vi.fn(({ scale }) => ({ width: 600 * scale, height: 800 * scale })),
  render: vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() })),
  getTextContent: vi.fn().mockResolvedValue({ items: [{ str: `Vertragstext Seite ${number}`, hasEOL: true }] }),
  cleanup: vi.fn(), ...extra,
});
const makeDocument = (count = 4) => ({ numPages: count, getPage: vi.fn(number => Promise.resolve(makePage(number))) });
const taskFor = pdf => ({ promise: Promise.resolve(pdf), destroy: vi.fn().mockResolvedValue() });
const mount = (url = '/uploads/contract.pdf') => render(<FileViewer fileUrl={url} title="Mietvertrag" onClose={() => {}} />);
let pdf;
let loadingTask;

beforeEach(() => {
  vi.clearAllMocks();
  pdf = makeDocument();
  loadingTask = taskFor(pdf);
  engine.getDocument.mockReturnValue(loadingTask);
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({});
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe('PDF preview lifecycle', () => {
  it('renders the signed original and navigates to any page with zoom and available text', async () => {
    pdf.numPages = 1000;
    mount('https://storage.example/contract.pdf?signature=exact');
    await screen.findByRole('img', { name: /Mietvertrag.*Seite 1/ });
    expect(engine.getDocument).toHaveBeenCalledWith(expect.objectContaining({ url: 'https://storage.example/contract.pdf?signature=exact', disableAutoFetch: true, disableStream: true }));
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Seite' }), { target: { value: '1000' } });
    fireEvent.click(screen.getByRole('button', { name: 'Seite anzeigen' }));
    await screen.findByRole('img', { name: /Seite 1000/ });
    expect(pdf.getPage).toHaveBeenCalledWith(1000);
    expect(screen.getByRole('button', { name: 'Nächste Seite' })).toBeDisabled();
    fireEvent.change(screen.getByRole('combobox', { name: 'Zoom' }), { target: { value: '150' } });
    await waitFor(() => expect(screen.getByRole('img', { name: /Seite 1000/ }).style.width).toBe('900px'));
    fireEvent.change(screen.getByRole('combobox', { name: 'Zoom' }), { target: { value: 'fit' } });
    await waitFor(() => expect(parseFloat(screen.getByRole('img', { name: /Seite 1000/ }).style.width)).toBeLessThanOrEqual(600));
    fireEvent.click(screen.getByRole('button', { name: 'PDF-Text' }));
    expect(await screen.findByText('Vertragstext Seite 1000')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Herunterladen' })).toBeEnabled();
  });

  it('shows load failure with original actions and recovers on retry', async () => {
    engine.getDocument.mockImplementationOnce(() => ({ promise: Promise.reject(new Error('Failed to fetch')), destroy: vi.fn().mockResolvedValue() }));
    mount();
    expect(await screen.findByRole('alert')).toHaveTextContent('PDF');
    expect(screen.getByRole('link', { name: 'Öffnen' })).toHaveAttribute('href', expect.stringContaining('/uploads/contract.pdf'));
    fireEvent.click(screen.getByRole('button', { name: 'Erneut versuchen' }));
    expect(await screen.findByRole('img', { name: /Seite 1/ })).toBeInTheDocument();
  });

  it('shows a password hint and destroys the pending load instead of waiting forever', async () => {
    const pending = deferred();
    loadingTask.promise = pending.promise;
    mount();
    await waitFor(() => expect(loadingTask.onPassword).toBeTypeOf('function'));
    act(() => loadingTask.onPassword(() => {}, 1));
    expect(await screen.findByRole('alert')).toHaveTextContent('passwortgeschützt');
    expect(loadingTask.destroy).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Herunterladen' })).toBeEnabled();
  });

  it('discards an old document answer after source replacement and destroys both loads on cleanup', async () => {
    const old = deferred();
    const oldTask = { promise: old.promise, destroy: vi.fn().mockResolvedValue() };
    engine.getDocument.mockReturnValueOnce(oldTask);
    const view = mount('/uploads/old.pdf');
    await waitFor(() => expect(engine.getDocument).toHaveBeenCalled());
    view.rerender(<FileViewer fileUrl="/uploads/new.pdf" title="Neuer Vertrag" onClose={() => {}} />);
    await screen.findByRole('img', { name: /Neuer Vertrag/ });
    const oldDocument = makeDocument();
    await act(async () => { old.resolve(oldDocument); });
    expect(oldDocument.getPage).not.toHaveBeenCalled();
    expect(oldTask.destroy).toHaveBeenCalled();
    view.unmount();
    expect(loadingTask.destroy).toHaveBeenCalled();
  });

  it('cancels the previous render when changing page and ignores a late render rejection', async () => {
    const pending = deferred();
    const oldRender = { promise: pending.promise, cancel: vi.fn() };
    pdf.getPage.mockImplementation(number => Promise.resolve(makePage(number, number === 1 ? { render: vi.fn(() => oldRender) } : {})));
    mount();
    await screen.findByRole('button', { name: 'Nächste Seite' });
    await waitFor(() => expect(pdf.getPage).toHaveBeenCalledWith(1));
    fireEvent.click(screen.getByRole('button', { name: 'Nächste Seite' }));
    await screen.findByRole('img', { name: /Seite 2/ });
    expect(oldRender.cancel).toHaveBeenCalled();
    await act(async () => { pending.reject(new Error('Rendering cancelled')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows drawing failures and releases a pending render on unmount', async () => {
    const drawing = deferred();
    const renderTask = { promise: drawing.promise, cancel: vi.fn() };
    pdf.getPage.mockResolvedValue(makePage(1, { render: vi.fn(() => renderTask) }));
    const view = mount();
    await waitFor(() => expect(pdf.getPage).toHaveBeenCalled());
    await act(async () => { drawing.reject(new Error('Invalid drawing')); });
    expect(await screen.findByRole('alert')).toHaveTextContent('PDF');
    view.unmount();
    expect(loadingTask.destroy).toHaveBeenCalled();
  });

  it('bounds canvas allocation for huge pages without restricting page count', async () => {
    const page = makePage(1, { getViewport: ({ scale }) => ({ width: 100000 * scale, height: 200000 * scale }) });
    pdf.getPage.mockResolvedValue(page);
    mount();
    await screen.findByRole('img', { name: /Seite 1/ });
    fireEvent.change(screen.getByRole('combobox', { name: 'Zoom' }), { target: { value: '200' } });
    await waitFor(() => expect(page.render).toHaveBeenCalledTimes(2));
    const canvas = screen.getByRole('img', { name: /Seite 1/ });
    expect(canvas.width * canvas.height).toBeLessThanOrEqual(16_777_216);
    expect(Math.max(canvas.width, canvas.height)).toBeLessThanOrEqual(8192);
  });

  it('discards an old getPage answer when the source changes before drawing', async () => {
    const pending = deferred();
    pdf.getPage.mockReturnValue(pending.promise);
    const view = mount('/uploads/old.pdf');
    await waitFor(() => expect(pdf.getPage).toHaveBeenCalledWith(1));
    engine.getDocument.mockReturnValue(taskFor(makeDocument()));
    view.rerender(<FileViewer fileUrl="/uploads/new.pdf" title="Neuer Vertrag" onClose={() => {}} />);
    await screen.findByRole('img', { name: /Neuer Vertrag/ });
    const oldPage = makePage(1);
    await act(async () => { pending.resolve(oldPage); });
    expect(oldPage.render).not.toHaveBeenCalled();
    expect(oldPage.cleanup).toHaveBeenCalled();
    expect(screen.queryByRole('img', { name: /Mietvertrag/ })).not.toBeInTheDocument();
  });

  it('cancels drawing immediately when the dialog unmounts', async () => {
    const pending = deferred();
    const renderTask = { promise: pending.promise, cancel: vi.fn() };
    const page = makePage(1, { render: vi.fn(() => renderTask) });
    pdf.getPage.mockResolvedValue(page);
    const view = mount();
    await waitFor(() => expect(page.render).toHaveBeenCalled());
    view.unmount();
    expect(renderTask.cancel).toHaveBeenCalledTimes(1);
    expect(loadingTask.destroy).toHaveBeenCalledTimes(1);
    await act(async () => { pending.reject(new Error('Cancelled after unmount')); });
  });

  it('ends an indefinitely pending load with an actionable timeout', async () => {
    const pending = deferred();
    loadingTask.promise = pending.promise;
    mount();
    await waitFor(() => expect(engine.getDocument).toHaveBeenCalled());
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    // Restart so the actual application deadline uses the fake clock.
    cleanup();
    mount();
    await act(async () => { await Promise.resolve(); });
    await act(async () => { vi.advanceTimersByTime(30_001); });
    expect(screen.getByRole('alert')).toHaveTextContent('dauert zu lange');
    expect(loadingTask.destroy).toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Erneut versuchen' })).toBeEnabled();
  });
});
