import { webcrypto } from 'node:crypto';
import { Blob as NodeBlob } from 'node:buffer';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import DatevExport from '../pages/DatevExport';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), getBlob: vi.fn(), confirm: vi.fn(), role: 'buchhaltung', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-user', role: mocks.role } }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: key => key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key }) }));

const text = de.pages.datev;
const profile = () => ({ id: 'version-1', created_at: '2026-10-01', spec: { name: 'Synthetic reviewed profile',
  adviser: 12345, client: 42, gl_length: 4, chart: '03', freeze: 0, currency: 'EUR', calendar_year: true,
  document_reference: 'empty', reviewed_by: 'Synthetic review', review_confirmed: true,
  rules: [{ account_id: 'account', category_id: 'category', account_type: 'Girokonto', flow: 'income', bank_gl: '1200', counter_gl: '8200', counter_kind: 'general', no_vat_nonautomatic: true }] } });
const preview = () => ({ id: 'export-1', rows: 12_037, income: '750.00', expense: '25.00', files: [{ name: 'EXTF_Buchungsstapel.csv', rows: 12_037 }],
  samples: [{ id: 'booking-1', date: '2026-09-01', amount: '750.00', text: 'Synthetic Miete' }],
  profile_version_id: 'version-1', start_date: '2026-01-01', end_date: '2026-12-31', generated_at: '2026-10-01',
  sha256: 'a'.repeat(64), size: 4 });
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = () => render(<MemoryRouter><DatevExport /></MemoryRouter>);
const choosePortfolio = async (label = text) => {
  await screen.findByRole('option', { name: 'Synthetic portfolio' });
  fireEvent.change(screen.getByLabelText(label.portfolio, { exact: true }), { target: { value: 'portfolio' } });
  await screen.findByRole('option', { name: /Synthetic reviewed profile/ });
  fireEvent.change(screen.getByLabelText(label.version, { exact: true }), { target: { value: 'version-1' } });
  await waitFor(() => expect(screen.getByRole('button', { name: label.validate })).not.toBeDisabled());
};
const fillProfile = async () => {
  fireEvent.click(screen.getByRole('button', { name: text.newProfile }));
  const form = screen.getByRole('button', { name: text.saveVersion }).closest('form');
  fireEvent.change(within(form).getByLabelText(text.name), { target: { value: 'My reviewed draft' } });
  fireEvent.change(within(form).getByLabelText(text.adviser), { target: { value: '12345' } });
  fireEvent.change(within(form).getByLabelText(text.client), { target: { value: '42' } });
  fireEvent.change(within(form).getByLabelText(text.reviewedBy), { target: { value: 'Reviewed with synthetic adviser' } });
  fireEvent.change(within(form).getByLabelText(text.account), { target: { value: 'account' } });
  fireEvent.change(within(form).getByLabelText(text.category), { target: { value: 'category' } });
  fireEvent.change(within(form).getByLabelText(text.bankGl), { target: { value: '1200' } });
  fireEvent.change(within(form).getByLabelText(text.counterGl), { target: { value: '8200' } });
  fireEvent.click(within(form).getByLabelText(text.reviewConfirmation));
  return form;
};

beforeEach(() => {
  mocks.locale = 'de-DE'; mocks.role = 'buchhaltung';
  mocks.getAll.mockReset().mockResolvedValue([{ id: 'portfolio', name: 'Synthetic portfolio' }]);
  mocks.get.mockReset().mockImplementation(async path => path.includes('/options?')
    ? { accounts: [{ id: 'account', name: 'Synthetic Giro', account_type: 'Girokonto' }], categories: [{ id: 'category', name: 'Synthetic rent' }] }
    : path.includes('/profiles?') ? { total: 1, items: [profile()] } : { total: 0, items: [] });
  mocks.post.mockReset().mockResolvedValue(preview()); mocks.getBlob.mockReset();
  mocks.confirm.mockReset().mockResolvedValue(true);
  vi.stubGlobal('crypto', webcrypto);
  URL.createObjectURL = vi.fn().mockReturnValue('blob:synthetic'); URL.revokeObjectURL = vi.fn();
});
afterEach(() => vi.unstubAllGlobals());

describe('DATEV reviewed export workflow', () => {
  it('keeps a loaded older profile and period while paging the export journal', async () => {
    const defaultGet = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async path => {
      if (path.includes('/profiles?')) return path.includes('offset=1')
        ? { total: 2, items: [{ ...profile(), id: 'older-version', spec: { ...profile().spec, name: 'Older reviewed profile' } }] }
        : { total: 2, items: [profile()] };
      if (path.includes('/exports?')) return { total: 11, items: [] };
      return defaultGet(path);
    });
    view(); await choosePortfolio();
    fireEvent.click(screen.getByRole('button', { name: text.moreVersions }));
    await screen.findByRole('option', { name: /Older reviewed profile/ });
    fireEvent.change(screen.getByLabelText(text.version, { exact: true }), { target: { value: 'older-version' } });
    fireEvent.change(screen.getByLabelText(text.from), { target: { value: '2005-01-01' } });
    fireEvent.click(screen.getByRole('button', { name: text.next }));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('/exports?') && path.includes('offset=10'))).toBe(true));
    expect(screen.getByLabelText(text.version, { exact: true })).toHaveValue('older-version');
    expect(screen.getByLabelText(text.from)).toHaveValue('2005-01-01');
    expect(screen.getByRole('option', { name: /Older reviewed profile/ })).toBeInTheDocument();
    expect(mocks.get.mock.calls.filter(([path]) => path.includes('/profiles?'))).toHaveLength(2);
  });
  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('renders honest format boundaries and finance controls in %s', async (locale, catalog) => {
    mocks.locale = locale; const labels = catalog.pages.datev;
    const { container } = view(); await choosePortfolio(labels);
    expect(container).toHaveTextContent(labels.scope); expect(container).toHaveTextContent(labels.limits);
    expect(container.textContent).not.toMatch(/pages\.datev\./);
    expect(screen.getByRole('link', { name: labels.bookings })).toHaveAttribute('href', '/bookings');
    expect(screen.getByRole('button', { name: labels.newProfile })).toBeEnabled();
  });

  it('retains the reviewed draft and same retry reference after server rejection', async () => {
    view(); await choosePortfolio(); const form = await fillProfile();
    mocks.post.mockRejectedValueOnce(new Error('422: Gegenkonto ist für die Sachkontenlänge ungültig'));
    fireEvent.submit(form);
    expect(await screen.findByRole('alert')).toHaveTextContent('Gegenkonto');
    expect(within(form).getByLabelText(text.name)).toHaveValue('My reviewed draft');
    expect(within(form).getByLabelText(text.counterGl)).toHaveValue('8200');
    const first = mocks.post.mock.calls[0][1];
    mocks.post.mockResolvedValueOnce({ ...profile(), id: 'new-version' }); fireEvent.submit(form);
    await screen.findByRole('status');
    await waitFor(() => expect(screen.queryByRole('button', { name: text.saveVersion })).not.toBeInTheDocument());
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first.idempotency_key);
    expect(first.rules[0]).toMatchObject({ account_type: 'Girokonto', bank_gl: '1200', counter_gl: '8200', no_vat_nonautomatic: true });
    expect(first.rules[0]).not.toHaveProperty('key');
    expect(first.review_confirmed).toBe(true);
  });

  it('creates an explicit new version and requires a fresh review', async () => {
    view(); await choosePortfolio(); fireEvent.click(screen.getByRole('button', { name: text.newVersion }));
    const form = screen.getByRole('button', { name: text.saveVersion }).closest('form');
    expect(within(form).getByLabelText(text.name)).toHaveValue('Synthetic reviewed profile');
    expect(within(form).getByLabelText(text.reviewConfirmation)).not.toBeChecked();
    fireEvent.click(within(form).getByLabelText(text.reviewConfirmation));
    mocks.post.mockResolvedValueOnce({ ...profile(), id: 'version-2' }); fireEvent.submit(form);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith(`${'/reports/datev'}/profiles`, expect.objectContaining({ previous_version_id: 'version-1' })));
  });

  it('prevents duplicate preview requests and exposes only a fully validated manifest', async () => {
    view(); await choosePortfolio(); const operation = pending(); mocks.post.mockReturnValue(operation.promise);
    const form = screen.getByRole('button', { name: text.validate }).closest('form');
    fireEvent.submit(form); fireEvent.submit(form);
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: text.newProfile })).toBeDisabled();
    expect(screen.queryByRole('button', { name: text.download })).not.toBeInTheDocument();
    await act(async () => operation.resolve(preview()));
    expect(await screen.findByText(text.ready)).toBeInTheDocument();
    expect(screen.getByText('export-1')).toBeInTheDocument();
    expect(screen.getByText('booking-1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: text.download })).toBeEnabled();
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ profile_version_id: 'version-1' });
  });

  it('preserves period and retry reference after a late source validation failure', async () => {
    view(); await choosePortfolio();
    fireEvent.change(screen.getByLabelText(text.from), { target: { value: '2005-01-01' } });
    mocks.post.mockRejectedValueOnce(new Error('DATEV missing_rule: booking b-00012001; account account; category other'));
    const form = screen.getByRole('button', { name: text.validate }).closest('form'); fireEvent.submit(form);
    expect(await screen.findByRole('alert')).toHaveTextContent('b-00012001');
    expect(screen.getByLabelText(text.from)).toHaveValue('2005-01-01');
    expect(screen.queryByRole('button', { name: text.download })).not.toBeInTheDocument();
    const first = mocks.post.mock.calls[0][1]; fireEvent.submit(form);
    await screen.findByText(text.ready); expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first.idempotency_key);
  });

  it.each([401, 500])('does not download a rejected API response (%s)', async status => {
    view(); await choosePortfolio(); fireEvent.submit(screen.getByRole('button', { name: text.validate }).closest('form'));
    await screen.findByText(text.ready); mocks.getBlob.mockRejectedValue(new Error(`${status}: Synthetic server error`));
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    expect(await screen.findByRole('alert')).toHaveTextContent(String(status)); expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(screen.queryByText(/Datei heruntergeladen/)).not.toBeInTheDocument();
  });

  it('refuses malformed preview metadata and HTML masquerading as an export', async () => {
    view(); await choosePortfolio(); const form = screen.getByRole('button', { name: text.validate }).closest('form');
    mocks.post.mockResolvedValueOnce({ id: 'fake', rows: 12000 }); fireEvent.submit(form);
    expect(await screen.findByRole('alert')).toHaveTextContent(text.malformed);
    expect(screen.queryByRole('button', { name: text.download })).not.toBeInTheDocument();
    fireEvent.submit(form); await screen.findByText(text.ready);
    mocks.getBlob.mockResolvedValue(new NodeBlob(['HTML'], { type: 'text/html' }));
    fireEvent.click(screen.getByRole('button', { name: text.download }));
    expect(await screen.findByRole('alert')).toHaveTextContent(text.malformed); expect(URL.createObjectURL).not.toHaveBeenCalled();
  });

  it('verifies the exact complete file checksum before download and revokes the temporary URL', async () => {
    const content = new Uint8Array([80, 75, 3, 4]);
    const hash = [...new Uint8Array(await webcrypto.subtle.digest('SHA-256', content))].map(byte => byte.toString(16).padStart(2, '0')).join('');
    mocks.post.mockResolvedValueOnce({ ...preview(), sha256: hash });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    try {
      view(); await choosePortfolio(); fireEvent.submit(screen.getByRole('button', { name: text.validate }).closest('form'));
      await screen.findByText(text.ready);
      mocks.getBlob.mockResolvedValue(new NodeBlob([content], { type: 'application/zip' }));
      fireEvent.click(screen.getByRole('button', { name: text.download }));
      await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
      expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:synthetic');
      expect(screen.getByRole('status')).toHaveTextContent('export-1');
    } finally { click.mockRestore(); }
  });

  it('readonly cannot save profiles or create previews, including direct form submission', async () => {
    mocks.role = 'readonly'; view();
    await screen.findByRole('option', { name: 'Synthetic portfolio' });
    fireEvent.change(screen.getByLabelText(text.portfolio, { exact: true }), { target: { value: 'portfolio' } });
    await screen.findByRole('option', { name: /Synthetic reviewed profile/ });
    expect(screen.queryByRole('button', { name: text.newProfile })).not.toBeInTheDocument();
    const button = screen.getByRole('button', { name: text.validate }); expect(button).toBeDisabled();
    fireEvent.submit(button.closest('form')); await screen.findByRole('alert'); expect(mocks.post).not.toHaveBeenCalled();
  });
});
