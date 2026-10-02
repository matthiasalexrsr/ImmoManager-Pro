import { beforeEach, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import UpdateSection from '../pages/settings/UpdateSection';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), confirm: vi.fn() }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ role: 'eigentuemer' }) }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ t: key => key }) }));
beforeEach(() => {
  mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.get.mockReset().mockResolvedValue({ update_available: true, latest_version: '2.0.0' });
  mocks.post.mockReset();
});
async function update() {
  render(<UpdateSection versionInfo={{ version: '1.0.0' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Jetzt prüfen' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Jetzt installieren' }));
}

it('shows manual restart instructions returned by the server', async () => {
  mocks.post.mockResolvedValueOnce({ success: true, message: 'Update bereit', restart_required: true })
    .mockResolvedValueOnce({ restart_signaled: false, manual_restart_required: true, message: 'Bitte mit start.bat neu starten.' });
  await update();
  expect(await screen.findByText('Bitte mit start.bat neu starten.')).toBeInTheDocument();
  expect(mocks.post).toHaveBeenLastCalledWith('/updates/restart');
});

it('disables live installation and shows offline maintenance instructions', async () => {
  mocks.get.mockResolvedValue({ update_available: true, latest_version: '2.0.0', live_apply_supported: false, maintenance_hint: 'Anwendung stoppen und Wartungsbefehl ausführen.' });
  render(<UpdateSection versionInfo={{ version: '1.0.0' }} />);
  fireEvent.click(screen.getByRole('button', { name: 'Jetzt prüfen' }));
  expect(await screen.findByRole('button', { name: 'Jetzt installieren' })).toBeDisabled();
  expect(screen.getByRole('status')).toHaveTextContent('Anwendung stoppen');
  expect(mocks.post).not.toHaveBeenCalled();
});

it('shows incomplete recovery and does not restart a failed update', async () => {
  mocks.post.mockResolvedValue({ success: false, message: 'Migration fehlgeschlagen', rollback_performed: true, manual_recovery_required: true, restart_required: true });
  await update();
  expect(await screen.findByRole('alert')).toHaveTextContent('Wiederherstellung ist unvollständig');
  expect(screen.queryByText(/Daten sind unverändert/)).not.toBeInTheDocument();
  expect(mocks.post).toHaveBeenCalledTimes(1);
});

it('retains update result and restart guidance when the restart status request fails', async () => {
  mocks.post.mockResolvedValueOnce({ success: true, message: 'Update bereit', restart_required: true })
    .mockRejectedValueOnce(new Error('Status nicht erreichbar; manuell starten'));
  await update();
  expect(await screen.findByText('Status nicht erreichbar; manuell starten')).toBeInTheDocument();
  expect(screen.getByText('Update bereit')).toBeInTheDocument();
});
