import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import PlatformSection from '../pages/settings/PlatformSection';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn(), captureSession: vi.fn() } }));
const STATUS = { storage: { backend: 'local', origin: 'default' },
  portable_export: { passphrase_configured: true }, plugins: [{ name: 'fixture', version: '2.0.0',
    installed_version: '1.0.0', revision: 1, enabled: true, backup_revisions: [], declaration: { schema_version: 2 } }] };

describe('PlatformSection', () => {
  beforeEach(() => {
    vi.resetAllMocks();
    api.captureSession.mockReturnValue(() => {});
    api.get.mockResolvedValue(STATUS);
  });
  it('shows actual storage, trust boundary and distinct restore readiness', async () => {
    render(<PlatformSection />);
    expect(await screen.findByText('Lokaler Speicher')).toBeInTheDocument();
    expect(screen.getByText(/Sie sind nicht isoliert/)).toBeInTheDocument();
    expect(screen.getByText(/noch keine erfolgreiche Anmeldung oder Browserprüfung/)).toBeInTheDocument();
    expect(api.get).toHaveBeenCalledWith('/admin/operations/platform');
  });
  it('keeps the exact command for retry after a lost response', async () => {
    api.post.mockRejectedValueOnce(new Error('Antwort verloren')).mockResolvedValueOnce({ revision: 2 });
    render(<PlatformSection />);
    fireEvent.click(await screen.findByRole('button', { name: 'Paket geprüft übernehmen' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Antwort verloren');
    fireEvent.click(screen.getByRole('button', { name: 'Paket geprüft übernehmen' }));
    await screen.findByRole('status');
    expect(api.post.mock.calls[0]).toEqual(api.post.mock.calls[1]);
    expect(api.post.mock.calls[0][1]).toMatchObject({ operation: 'upgrade', expected_revision: 1 });
  });
  it('discards a late reply after the account changes', async () => {
    let complete;
    let active = true;
    api.captureSession.mockReturnValue(() => { if (!active) throw Error('Sitzung geändert'); });
    api.get.mockReturnValue(new Promise(resolve => { complete = resolve; }));
    render(<PlatformSection />);
    active = false;
    complete(STATUS);
    await waitFor(() => expect(screen.queryByText('Lokaler Speicher')).not.toBeInTheDocument());
    expect(screen.queryByText('fixture')).not.toBeInTheDocument();
  });
});
