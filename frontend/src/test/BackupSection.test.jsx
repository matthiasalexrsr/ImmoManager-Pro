import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import BackupSection from '../pages/settings/BackupSection';

vi.mock('../api', () => ({ api: { get: vi.fn(() => Promise.resolve({})), post: vi.fn() } }));
const t = (key) => key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

function importFile(container) {
  const input = container.querySelector('input[type=file]');
  const file = new File(['{}'], 'export.json', { type: 'application/json' });
  fireEvent.change(input, { target: { files: [file] } });
}

describe('BackupSection import', () => {
  beforeEach(() => { global.fetch = vi.fn(); });
  afterEach(() => { delete global.fetch; });

  it('shows why an import was rejected', async () => {
    // Regression: a 400 response rendered nothing, so a failed import looked like success.
    global.fetch.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ error: { message: 'Import abgebrochen – 1 Problem(e)' } }),
    });
    const { container } = render(<BackupSection />);
    importFile(container);
    expect(await screen.findByRole('alert')).toHaveTextContent('Import abgebrochen');
  });

  it('reports records that already existed', async () => {
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ imported: {}, skipped_existing: { tenants: 3 } }),
    });
    const { container } = render(<BackupSection />);
    importFile(container);
    expect(await screen.findByText('tenants: 3 pages.settings.skippedExisting')).toBeInTheDocument();
    expect(screen.getByText('pages.settings.nothingNew')).toBeInTheDocument();
  });
});
