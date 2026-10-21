import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CurrentDocumentViewer from '../features/documentDetail/CurrentDocumentViewer';

vi.mock('../components/FileViewer', () => ({ default: ({ fileUrl }) => <div data-testid="upload">{fileUrl}</div> }));
vi.mock('../components/PdfPreview', () => ({ default: ({ url }) => <output data-testid="pdf">{url}</output> }));
const record = { id: 'd1', title: 'Beleg', file_url: '/uploads/old.pdf' };
const head = { id: 'v2', number: 2, filename: 'korrigiert.pdf', media_type: 'application/pdf', size_bytes: 100 };
const mount = service => render(<MemoryRouter><CurrentDocumentViewer document={record} service={service} onClose={() => {}} /></MemoryRouter>);
beforeEach(() => { URL.createObjectURL = vi.fn(() => 'blob:aktuell'); URL.revokeObjectURL = vi.fn(); });
afterEach(cleanup);

describe('current document preview', () => {
  it('opens the archived current version instead of the superseded upload', async () => {
    const service = { load: vi.fn().mockResolvedValue({ document: record, versions: { items: [head] } }),
      versionBlob: vi.fn().mockResolvedValue(new Blob(['new'])) };
    mount(service);
    expect(await screen.findByTestId('pdf')).toHaveTextContent('blob:aktuell');
    expect(service.versionBlob).toHaveBeenCalledWith('d1', 'v2', expect.anything());
    expect(screen.getByText(/Aktuelle Fassung 2/)).toBeInTheDocument();
    expect(screen.queryByTestId('upload')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Dokumentakte öffnen' })).toHaveAttribute('href', '/documents/d1');
  });
  it('uses the current upload only after verifying that no archive version exists', async () => {
    const service = { load: vi.fn().mockResolvedValue({ document: { ...record, file_url: '/uploads/current.pdf' }, versions: { items: [] } }) };
    mount(service);
    expect(await screen.findByTestId('upload')).toHaveTextContent('/uploads/current.pdf');
  });
  it('does not silently show an old file when loading the archive failed', async () => {
    const service = { load: vi.fn().mockRejectedValueOnce(new Error('Verbindung unterbrochen'))
      .mockResolvedValue({ document: record, versions: { items: [] } }) };
    mount(service);
    expect(await screen.findByRole('alert')).toHaveTextContent('Verbindung unterbrochen');
    expect(screen.queryByTestId('upload')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Erneut laden' }));
    expect(await screen.findByTestId('upload')).toBeInTheDocument();
  });
  it('retries a failed preview and releases the archived blob when closed', async () => {
    const service = { load: vi.fn().mockResolvedValue({ document: record, versions: { items: [head] } }),
      versionBlob: vi.fn().mockRejectedValueOnce(new Error('Download unterbrochen')).mockResolvedValue(new Blob(['new'])) };
    const view = mount(service);
    expect(await screen.findByRole('alert')).toHaveTextContent('Download unterbrochen');
    fireEvent.click(screen.getByRole('button', { name: 'Vorschau erneut laden' }));
    expect(await screen.findByTestId('pdf')).toHaveTextContent('blob:aktuell');
    view.unmount();
    await waitFor(() => expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:aktuell'));
  });
});
