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

  it('uses the verified package route even when an older server advertises source updates', async () => {
    api.get.mockResolvedValue({ ...newer, is_frozen: false, can_apply: true, download_hint: null });
    render(<UpdateSection versionInfo={{ version: '2.0.0' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'Jetzt prüfen' }));
    expect(await screen.findByRole('link', { name: 'Neue Version herunterladen' })).toHaveAttribute('href',newer.release_url);
    expect(screen.queryByRole('button', { name: 'Jetzt installieren' })).not.toBeInTheDocument();
    expect(screen.getByText(/Vollbackup/)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();
  });

  it.each(['javascript:alert(1)','http://github.com/o/r/releases/tag/v2.1.0',
    'https://github.com.evil.invalid/o/r/releases/tag/v2.1.0','https://github.com@evil.invalid/o/r/releases/tag/v2.1.0',
    'https://github.com/o/r/releases/tag/v2.1.0?next=https://evil.invalid','https://github.com/o/r/issues/1',null])(
    'does not offer an unsafe or missing release link (%s)',async release_url=>{
      api.get.mockResolvedValue({...newer,release_url});
      render(<UpdateSection versionInfo={{version:'2.0.0'}}/>);
      fireEvent.click(screen.getByRole('button',{name:'Jetzt prüfen'}));
      expect(await screen.findByRole('alert')).toHaveTextContent('keine gültige Downloadadresse');
      expect(screen.queryByRole('link',{name:'Neue Version herunterladen'})).not.toBeInTheDocument();
      expect(api.post).not.toHaveBeenCalled();
    });

  it('shows a failed history request as an error and permits a successful retry',async()=>{
    api.get.mockRejectedValueOnce(new Error('Verlauf offline')).mockResolvedValueOnce({history:[]});
    render(<UpdateSection versionInfo={{version:'2.0.0'}}/>);
    fireEvent.click(screen.getByRole('button',{name:'Anzeigen'}));
    expect(await screen.findByRole('alert')).toHaveTextContent('Verlauf offline');
    expect(screen.queryByText('Noch keine Updates durchgeführt')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button',{name:'Anzeigen'}));
    expect(await screen.findByText('Noch keine Updates durchgeführt')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
