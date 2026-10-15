import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { api } from '../api';
import BackupSection from '../pages/settings/BackupSection';

vi.mock('../api', () => ({ api: { get: vi.fn(() => Promise.resolve({})), post: vi.fn(), upload: vi.fn(), getBlob: vi.fn(), captureSession: () => () => {} } }));
const t = (key) => key;
vi.mock('../i18n', () => ({ useTranslation: () => ({ t }) }));
vi.mock('../components/Toast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

function importFile(container) {
  const input = container.querySelector('input[type=file]');
  const file = new File(['{}'], 'export.json', { type: 'application/json' });
  fireEvent.change(input, { target: { files: [file] } });
}

describe('BackupSection import', () => {
  beforeEach(() => { api.upload.mockReset(); });

  it('shows why an import was rejected', async () => {
    // Regression: a 400 response rendered nothing, so a failed import looked like success.
    api.upload.mockRejectedValue(new Error('Import abgebrochen – 1 Problem(e)'));
    const { container } = render(<BackupSection />);
    importFile(container);
    expect(await screen.findByRole('alert')).toHaveTextContent('Import abgebrochen');
  });

  it('reports records that already existed', async () => {
    api.upload.mockResolvedValue({ imported: {}, skipped_existing: { tenants: 3 } });
    const { container } = render(<BackupSection />);
    importFile(container);
    expect(await screen.findByText('tenants: 3 pages.settings.skippedExisting')).toBeInTheDocument();
    expect(screen.getByText('pages.settings.nothingNew')).toBeInTheDocument();
  });
});
