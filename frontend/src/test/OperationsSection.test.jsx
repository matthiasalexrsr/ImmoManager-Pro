import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import OperationsSection from '../pages/settings/OperationsSection';
import { api } from '../api';
import { formatBytes } from '../utils/format';

vi.mock('../api', () => ({ api: { get: vi.fn(), post: vi.fn() } }));
const t = (key, params) => (params ? `${key} ${JSON.stringify(params)}` : key);
vi.mock('../i18n', () => ({ useTranslation: () => ({ t }) }));

const OVERVIEW = {
  backup: {
    enabled: true,
    schedule: { daily_at: '01:30', timezone: 'Europe/Berlin' },
    directory: '/data/backups/full',
    second_target: null,
    retention: { daily: 14, monthly: 6, pre_upgrade: 3 },
    passphrase_protected: false,
    last: { event: 'backup', ok: true, at: '2026-10-08T01:30:00+00:00', archive: 'immomanager-full-a.zip', size: 2048 },
    archives: [{ name: 'immomanager-full-a.zip', size_bytes: 2048 }],
    total_size_bytes: 2048,
  },
  restore_probe: {
    schedule: { day: 1, at: '03:30' },
    last: { event: 'restore_probe', ok: false, at: '2026-10-01T03:30:00+00:00', error: 'Archivprüfung fehlgeschlagen' },
  },
  secrets: { active_key_id: 'k20261008-abcd', sealed: 2, plaintext: 0 },
  warnings: [{ code: 'no_second_target' }, { code: 'backup_stale', hours: 40 }],
  failures: [],
};

describe('OperationsSection', () => {
  beforeEach(() => {
    api.get.mockReset();
    api.post.mockReset();
  });

  it('shows the last backup, the failed probe and the notices', async () => {
    api.get.mockResolvedValue(OVERVIEW);
    render(<OperationsSection />);
    expect(await screen.findByText(/immomanager-full-a.zip · 2.0 KB/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Archivprüfung fehlgeschlagen');
    const warnings = screen.getByTestId('operations-warnings');
    expect(warnings).toHaveTextContent('settings.operations.warnings.no_second_target');
    expect(warnings).toHaveTextContent('settings.operations.warnings.backup_stale {"hours":40}');
    expect(screen.getByText(/k20261008-abcd/)).toBeInTheDocument();
  });

  it('runs a backup on request and reloads the overview', async () => {
    api.get.mockResolvedValue(OVERVIEW);
    api.post.mockResolvedValue({ archive: 'immomanager-full-b.zip' });
    render(<OperationsSection />);
    await screen.findByText(/immomanager-full-a.zip/);
    fireEvent.click(screen.getByText('settings.operations.runBackup'));
    expect(await screen.findByRole('status')).toHaveTextContent('immomanager-full-b.zip');
    expect(api.post).toHaveBeenCalledWith('/admin/operations/backup');
    await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
  });

  it('shows why the overview is refused', async () => {
    api.get.mockRejectedValue(new Error('Diese Aktion verwaltet installationsweite Daten'));
    render(<OperationsSection />);
    expect(await screen.findByRole('alert')).toHaveTextContent('installationsweite Daten');
  });

  it('formats sizes', () => {
    expect(formatBytes(512)).toBe('512 B');
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB');
    expect(formatBytes(null)).toBe('—');
  });
});
