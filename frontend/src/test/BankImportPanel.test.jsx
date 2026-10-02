import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import BankImportPanel from '../components/BankImportPanel';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getBlob: vi.fn(), saveBlob: vi.fn(), postForm: vi.fn(), post: vi.fn(), confirm: vi.fn(), invalidateRelated: vi.fn(), role: 'buchhaltung', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-user', role: mocks.role } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => mocks }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../utils/bookingCsv', () => ({ saveBlob: mocks.saveBlob }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: (key, params = {}) => (key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key)
    .replace(/\{\{(\w+)\}\}/g, (match, name) => params[name] ?? match) }) }));

const labels = de.bankImport;
const job = (changes = {}) => ({ id: 'saved-import', account_id: 'account', portfolio_id: 'portfolio', filename: 'synthetic.csv',
  state: 'ready', revision: 0, mapping: { version: 1, format: 'csv' }, source_sha256: 'a'.repeat(64), mapping_hash: 'b'.repeat(64), preview_hash: 'c'.repeat(64),
  source_bytes: 99, row_count: 2, error_count: 0, duplicate_count: 0, published_count: 0, persistent: true, maximum_page_size: 500, ...changes });
const row = (ordinal = 1, changes = {}) => ({ ordinal, source_line: ordinal + 1, booking_date: '2026-01-01', value_date: '2026-01-01',
  amount_cents: 101, payment_text: 'Synthetic transaction', bank_reference: null, error_code: null, error_message: null, duplicate_booking_id: null, ...changes });
const preview = (items = [row()], changes = {}) => ({ import_id: 'saved-import', preview_hash: 'c'.repeat(64), items, has_more: false, next_cursor: null, ...changes });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = props => <BankImportPanel initialAccount="account" onClose={vi.fn()} {...props} />;
async function upload() {
  const input = await screen.findByLabelText(labels.file, { exact: true });
  await screen.findByRole('option', { name: 'Synthetic bank' });
  fireEvent.change(input, { target: { files: [new File(['date;amount;text\n2026-01-01;1.01;Synthetic'], 'synthetic.csv', { type: 'text/csv' })] } });
  fireEvent.submit(screen.getByLabelText(labels.file, { exact: true }).closest('form'));
  await screen.findByRole('button', { name: labels.approve });
  await screen.findByText('Synthetic transaction');
}
beforeEach(() => {
  mocks.locale = 'de-DE'; mocks.role = 'buchhaltung'; mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.invalidateRelated.mockReset(); mocks.post.mockReset().mockResolvedValue(job({ state: 'committed', revision: 1, published_count: 2 }));
  mocks.postForm.mockReset().mockResolvedValue(job());
  mocks.getBlob.mockReset().mockResolvedValue(new Blob(['synthetic original'])); mocks.saveBlob.mockReset();
  mocks.get.mockReset().mockImplementation(async path => {
    if (path.startsWith('/bookings/lookup/accounts')) return { items: [{ id: 'account', label: 'Synthetic bank' }], selected: null, has_more: false, next_cursor: null };
    if (path.startsWith('/bookings/imports?')) return { items: [job()], has_more: false, next_cursor: null };
    if (path.includes('/preview?')) return preview();
    return job();
  });
});

describe('reviewed bank import', () => {
  it('uploads explicit mapping without publishing, then requires confirmation and preserves replay payload on failure', async () => {
    const approval = deferred(); mocks.confirm.mockReturnValueOnce(approval.promise);
    mocks.post.mockRejectedValueOnce(new Error('Permission changed before publication'));
    render(view()); await upload();
    const form = mocks.postForm.mock.calls[0][1];
    expect(form).toBeInstanceOf(FormData);
    expect(form.get('account_id')).toBe('account');
    expect(JSON.parse(form.get('mapping'))).toMatchObject({ format: 'csv', date_column: 'date', decimal_separator: 'legacy', reference_column: null });
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: labels.approve }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(labels.confirmQuestion));
    expect(mocks.post).not.toHaveBeenCalled();
    await act(async () => approval.resolve(false));
    await waitFor(() => expect(screen.getByRole('button', { name: labels.approve })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: labels.approve }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Permission changed');
    expect(mocks.post.mock.calls[0][1]).toEqual({ revision: 0, preview_hash: 'c'.repeat(64) });
    fireEvent.click(screen.getByRole('button', { name: de.ui.buttons.retry }));
    await waitFor(() => expect(screen.getByRole('button', { name: labels.approve })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: labels.approve }));
    await screen.findByText(`${labels.published}: 2`);
    expect(mocks.post.mock.calls[1][1]).toEqual(mocks.post.mock.calls[0][1]);
    expect(mocks.invalidateRelated).toHaveBeenCalledWith('bookings', 'accounts');
  });

  it('retains stored row errors and never offers approval for an invalid file', async () => {
    mocks.postForm.mockResolvedValue(job({ state: 'invalid', error_count: 1 }));
    mocks.get.mockImplementation(async path => {
      if (path.startsWith('/bookings/lookup/accounts')) return { items: [{ id: 'account', label: 'Synthetic bank' }], selected: null, has_more: false, next_cursor: null };
      if (path.startsWith('/bookings/imports?')) return { items: [], has_more: false, next_cursor: null };
      return preview([row(1, { amount_cents: null, error_code: 'DATE_INVALID', error_message: 'Explicit date format is incorrect' })]);
    });
    render(view());
    await screen.findByRole('option', { name: 'Synthetic bank' });
    fireEvent.change(screen.getByLabelText(labels.file, { exact: true }), { target: { files: [new File(['bad'], 'bad.csv')] } });
    fireEvent.submit(screen.getByLabelText(labels.file, { exact: true }).closest('form'));
    await screen.findByText('Explicit date format is incorrect');
    expect(screen.getByText(labels.invalidHint)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: labels.approve })).not.toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(labels.errorsOnly));
    await waitFor(() => expect(mocks.get.mock.calls.some(([path]) => path.includes('errors_only=true'))).toBe(true));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('loads saved previews and later pages without a full booking list or treating text as markup', async () => {
    const regular = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (path, options) => {
      if (path.includes('/preview?')) return path.includes('cursor=next-safe')
        ? preview([row(2, { payment_text: '<script>synthetic()</script>' })])
        : preview([row()], { has_more: true, next_cursor: 'next-safe' });
      return regular(path, options);
    });
    const { container } = render(view());
    const history = screen.getByText(labels.history).closest('details');
    history.open = true;
    fireEvent.click(await within(history).findByRole('button', { name: /synthetic.csv/ }));
    const region = await screen.findByRole('region', { name: labels.preview });
    const controls = region.parentElement.querySelector('.bank-import-paging');
    fireEvent.click(within(controls).getByRole('button', { name: de.bookingPages.next }));
    await screen.findByText('<script>synthetic()</script>');
    expect(container.querySelector('script')).toBeNull();
    expect(mocks.get.mock.calls.some(([path]) => path === '/bookings')).toBe(false);
    expect(mocks.postForm).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('ignores a delayed permission-confirmation result after role loss', async () => {
    const approval = deferred(); mocks.confirm.mockReturnValue(approval.promise);
    const page = render(view()); await upload();
    fireEvent.click(screen.getByRole('button', { name: labels.approve }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    mocks.role = 'readonly'; page.rerender(view());
    await act(async () => approval.resolve(true));
    expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('button', { name: labels.approve })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(labels.file, { exact: true })).not.toBeInTheDocument();
  });

  it('fails closed on a foreign-account upload response', async () => {
    mocks.postForm.mockResolvedValue(job({ account_id: 'foreign-account' }));
    render(view()); await screen.findByRole('option', { name: 'Synthetic bank' });
    fireEvent.change(screen.getByLabelText(labels.file, { exact: true }), { target: { files: [new File(['test'], 'test.csv')] } });
    fireEvent.submit(screen.getByLabelText(labels.file, { exact: true }).closest('form'));
    expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.queryByRole('button', { name: labels.approve })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('downloads the protected original for readonly without putting tokens in a URL', async () => {
    mocks.role = 'readonly';
    render(view());
    const history = screen.getByText(labels.history).closest('details'); history.open = true;
    fireEvent.click(await within(history).findByRole('button', { name: /synthetic.csv/ }));
    await waitFor(() => expect(screen.getByRole('button', { name: labels.downloadOriginal })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: labels.downloadOriginal }));
    await waitFor(() => expect(mocks.saveBlob).toHaveBeenCalledOnce());
    expect(mocks.getBlob).toHaveBeenCalledWith('/bookings/imports/saved-import/source', { signal: expect.any(AbortSignal) });
    expect(mocks.saveBlob.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(mocks.saveBlob.mock.calls[0][1]).toBe('synthetic.csv');
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('offers readable saved-history access without mutation in %s', async (locale, catalog) => {
    mocks.role = 'readonly'; mocks.locale = locale;
    const { container } = render(view());
    await screen.findByRole('option', { name: 'Synthetic bank' });
    expect(screen.getByText(catalog.bankImport.description)).toBeInTheDocument();
    expect(screen.queryByLabelText(catalog.bankImport.file, { exact: true })).not.toBeInTheDocument();
    expect(container.textContent).not.toContain('bankImport.');
    expect(mocks.postForm).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
