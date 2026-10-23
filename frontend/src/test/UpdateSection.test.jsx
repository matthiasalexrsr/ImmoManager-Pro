import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import UpdateSection from '../pages/settings/UpdateSection';
import { api } from '../api';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ error: vi.fn() }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => async () => true }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

const newer = { update_available: true, current_version: '2.0.0', latest_version: '2.1.0', error: null,
  release_url: 'https://github.com/o/r/releases/tag/v2.1.0', release_notes: 'Neu' };

describe('update check', () => {
  it('leads the Windows package to the download and says what happens to the data', async () => {
    api.get.mockResolvedValue({ ...newer, is_frozen: true, can_apply: false,
      download_hint: 'Neue Version herunterladen … Vollbackup …' });
    render(<UpdateSection versionInfo={{ version: '2.0.0' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Jetzt prüfen' }));
    const link = await screen.findByRole('link', { name: 'Neue Version herunterladen' });
    expect(link).toHaveAttribute('href', newer.release_url);
    expect(screen.getByText(/Vollbackup/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Jetzt installieren' })).not.toBeInTheDocument();
  });

  it('lets a git checkout install the update itself', async () => {
    api.get.mockResolvedValue({ ...newer, is_frozen: false, can_apply: true, download_hint: null });
    api.post.mockResolvedValue({ success: true, message: 'ok', steps: [] });
    render(<UpdateSection versionInfo={{ version: '2.0.0' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Jetzt prüfen' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Jetzt installieren' }));
    await screen.findByText('ok');
    expect(api.post).toHaveBeenCalledWith('/updates/apply', { target_version: '2.1.0' });
  });
});
