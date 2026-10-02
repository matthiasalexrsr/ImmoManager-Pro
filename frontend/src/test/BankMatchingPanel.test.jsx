import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import BankMatchingPanel from '../components/BankMatchingPanel';
import PaymentHistoryPanel from '../components/PaymentHistoryPanel';
import { exactAmount } from '../utils/bankMatching';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), confirm: vi.fn(), invalidateRelated: vi.fn(), role: 'buchhaltung', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'synthetic-user', role: mocks.role } }) }));
vi.mock('../contexts/DataStoreContext', () => ({ useDataStore: () => mocks }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: (key, params = {}) => (key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key)
    .replace(/\{\{(\w+)\}\}/g, (match, name) => params[name] ?? match) }) }));
const labels = de.bankMatching;
const booking = { id: 'bank-source', amount: '-100.30', allocated_amount: '0', booking_date: '2026-09-05', payment_text: 'Synthetic INV-AX' };
const candidate = (changes = {}) => ({ kind: 'invoice', id: 'invoice-1', label: 'Synthetic supplier', reference: 'INV-AX',
  property_label: 'Synthetic property', due_date: '2026-09-01', open_cents: 10030, suggested_cents: 10030,
  score: 12, reasons: ['reference', 'amount_exact', 'same_portfolio'], review_token: 'signed-reviewed-source', ...changes });
const page = (items = [candidate()], changes = {}) => ({ booking_id: booking.id, available_cents: 10030, items, ambiguous: false,
  has_more: false, next_cursor: null, ...changes });
const receipt = (changes = {}) => ({ id: 'receipt-1', entity_type: 'invoice', entity_id: 'invoice-1', booking_id: booking.id,
  amount: '40.10', payment_date: '2026-09-05', reversal: null, note: null, ...changes });
const history = (items = [], changes = {}) => ({ items, has_more: false, next_cursor: null, ...changes });
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const view = props => <BankMatchingPanel booking={booking} onClose={vi.fn()} {...props} />;
const select = async () => fireEvent.click(await screen.findByRole('radio', { name: /Synthetic supplier/ }));
beforeEach(() => {
  mocks.role = 'buchhaltung'; mocks.locale = 'de-DE'; mocks.confirm.mockReset().mockResolvedValue(true);
  mocks.invalidateRelated.mockReset(); mocks.post.mockReset().mockImplementation(async (_, request) => receipt({ idempotency_key: request.idempotency_key }));
  mocks.get.mockReset().mockImplementation(async path => path.includes('/suggestions?') ? page()
    : path.includes('/allocations?') || path.includes('/payments?') ? history() : booking);
});

describe('deliberate bank allocation', () => {
  it('never chooses or posts automatically, respects cancellation and retries the same exact command after a network failure', async () => {
    const approval = deferred(); mocks.confirm.mockReturnValueOnce(approval.promise);
    mocks.post.mockRejectedValueOnce(new Error('Synthetic network interruption'));
    render(view()); await screen.findByRole('radio');
    expect(screen.getByRole('radio')).not.toBeChecked(); expect(mocks.post).not.toHaveBeenCalled();
    await select(); fireEvent.change(screen.getByLabelText(labels.amount), { target: { value: '40,10' } });
    fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalledWith(labels.confirmQuestion));
    await act(async () => approval.resolve(false));
    await waitFor(() => expect(screen.getByRole('button', { name: labels.confirm })).toBeEnabled());
    expect(mocks.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Synthetic network interruption');
    expect(mocks.post.mock.calls[0][1]).toMatchObject({ review_token: 'signed-reviewed-source', amount: '40.10', note: null });
    fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    await screen.findByText(labels.completed, { exact: false });
    expect(mocks.post.mock.calls[1][1]).toEqual(mocks.post.mock.calls[0][1]);
    expect(mocks.invalidateRelated).toHaveBeenCalledWith('bookings', 'accounts', 'invoices', 'rent-charges', 'receivables', 'contracts');
  });

  it('requires renewed review after a stale source and does not retain an actionable selection', async () => {
    mocks.post.mockRejectedValue(Object.assign(new Error('Booking changed during review'), { statusCode: 409 }));
    render(view()); await select(); fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Booking changed');
    expect(screen.queryByRole('button', { name: labels.confirm })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: labels.renew }));
    await waitFor(() => expect(screen.getByRole('radio')).not.toBeChecked());
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('keeps the exact matching command after an unverified success response', async () => {
    mocks.post.mockResolvedValueOnce({ id: 'unknown' }).mockImplementationOnce(async (_, request) => receipt({ idempotency_key: request.idempotency_key }));
    render(view()); await select(); fireEvent.change(screen.getByLabelText(labels.amount), { target: { value: '40.10' } });
    fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.getByLabelText(labels.amount)).toHaveValue('40.10');
    fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    await screen.findByText(labels.completed, { exact: false });
    expect(mocks.post.mock.calls[1][1]).toEqual(mocks.post.mock.calls[0][1]);
  });

  it('ignores late search results, sends bounded cursor queries and renders unsafe text as text', async () => {
    const late = deferred();
    const regular = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(path => {
      if (path.includes('/suggestions?')) return path.includes('search=late') ? late.promise : Promise.resolve(path.includes('cursor=next')
        ? page([candidate({ label: '<script>synthetic()</script>' })]) : page([candidate()], { has_more: true, next_cursor: 'next' }));
      return regular(path);
    });
    const { container } = render(view()); await screen.findByRole('radio');
    const search = screen.getByRole('searchbox', { name: labels.search });
    fireEvent.change(search, { target: { value: 'late' } }); fireEvent.submit(search.closest('form'));
    fireEvent.change(search, { target: { value: 'current' } }); fireEvent.submit(search.closest('form'));
    await screen.findByRole('radio');
    await act(async () => late.resolve(page([candidate({ label: 'Obsolete result' })])));
    expect(screen.queryByText('Obsolete result')).not.toBeInTheDocument();
    const paging = screen.getByRole('navigation', { name: labels.candidatePages });
    fireEvent.click(within(paging).getByRole('button', { name: de.bookingPages.next }));
    await screen.findByText('<script>synthetic()</script>'); expect(container.querySelector('script')).toBeNull();
    expect(mocks.get.mock.calls.some(([path]) => path.includes('page_size=25') && path.includes('search=current') && path.includes('cursor=next'))).toBe(true);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('makes ambiguity explicit and rejects malformed foreign-source responses', async () => {
    mocks.get.mockImplementation(async path => path.includes('/suggestions?') ? page([candidate(), candidate({ id: 'invoice-2' })], { ambiguous: true })
      : path.includes('/allocations?') ? history() : booking);
    const viewResult = render(view());
    await screen.findByText(labels.ambiguous); expect(screen.getAllByRole('radio').every(element => !element.checked)).toBe(true);
    viewResult.unmount();
    mocks.get.mockImplementation(async path => path.includes('/suggestions?') ? page([candidate()], { booking_id: 'foreign-source' })
      : path.includes('/allocations?') ? history() : booking);
    render(view()); expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.queryByRole('radio')).not.toBeInTheDocument(); expect(mocks.post).not.toHaveBeenCalled();
  });

  it('invalidates a pending confirmation across loss and regain of a grant', async () => {
    const pending = deferred(); mocks.confirm.mockReturnValue(pending.promise);
    const rendered = render(view()); await select();
    fireEvent.click(screen.getByRole('button', { name: labels.confirm }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    mocks.role = 'readonly'; rendered.rerender(view());
    mocks.role = 'buchhaltung'; rendered.rerender(view());
    await act(async () => pending.resolve(true));
    expect(mocks.post).not.toHaveBeenCalled(); expect(screen.queryByLabelText(labels.amount)).not.toBeInTheDocument();
  });

  it.each(['de-DE', 'en-US', 'es-ES'])('allows readonly review with translated controls in %s', async locale => {
    mocks.role = 'readonly'; mocks.locale = locale;
    const text = { 'de-DE': de, 'en-US': en, 'es-ES': es }[locale].bankMatching;
    render(view()); expect(await screen.findByRole('radio')).toBeDisabled();
    expect(screen.getByText(text.readonly)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: text.confirm })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('pages receipt history and reverses through the actual target API with explicit confirmation', async () => {
    let reversed = false;
    mocks.get.mockImplementation(async path => path.includes('cursor=next') ? history([receipt({ id: 'receipt-2', reversal: reversed
      ? { id: 'reversal-2', payment_id: 'receipt-2', amount: '40.10', reversal_date: '2026-09-06', reason: 'Reviewed correction' } : null })])
      : history([receipt()], { has_more: true, next_cursor: 'next' }));
    mocks.post.mockImplementation(async (_, request) => { reversed = true; return { ...request, id: 'reversal-2', payment_id: 'receipt-2', amount: '40.10' }; });
    render(<PaymentHistoryPanel path="/invoices/invoice-1/payments" />);
    await screen.findByText('receipt-1');
    const paging = screen.getByRole('navigation', { name: labels.historyPages });
    fireEvent.click(within(paging).getByRole('button', { name: de.bookingPages.next }));
    await screen.findByText('receipt-2');
    fireEvent.click(screen.getByRole('button', { name: labels.reverse }));
    fireEvent.change(screen.getByLabelText(labels.reversalDate, { exact: false }), { target: { value: '2026-09-06' } });
    fireEvent.change(screen.getByLabelText(labels.reason, { exact: false }), { target: { value: 'Reviewed correction' } });
    const dialog = screen.getByRole('dialog');
    fireEvent.submit(within(dialog).getByRole('button', { name: labels.reverse, exact: true }).closest('form'));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/invoices/invoice-1/payments/receipt-2/reversal',
      expect.objectContaining({ reason: 'Reviewed correction', reversal_date: '2026-09-06', idempotency_key: expect.any(String) }), expect.any(Object)));
    expect(mocks.confirm).toHaveBeenCalledWith(labels.reverseConfirm);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('validates cents without floating arithmetic or rounding away excess precision', () => {
    expect(exactAmount('0,10', 10)).toBe('0.10'); expect(exactAmount('100.30', 10030)).toBe('100.30');
    for (const value of ['0', '-1', '1.001', '1e2', 'Infinity', '100.31']) expect(exactAmount(value, 10030)).toBeNull();
  });

  it('keeps a malformed reversal response recoverable with the same form and idempotency key, and locks close during the request', async () => {
    mocks.get.mockResolvedValue(history([receipt()]));
    const pending = deferred(); mocks.post.mockReturnValueOnce(pending.promise).mockResolvedValueOnce({});
    render(<PaymentHistoryPanel path="/invoices/invoice-1/payments" onClose={vi.fn()} />);
    await screen.findByText('receipt-1');
    fireEvent.click(screen.getByRole('button', { name: labels.reverse }));
    fireEvent.change(screen.getByLabelText(labels.reversalDate, { exact: false }), { target: { value: '2026-09-06' } });
    fireEvent.change(screen.getByLabelText(labels.reason, { exact: false }), { target: { value: 'Keep reviewed reason' } });
    const dialog = screen.getByRole('dialog');
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledOnce());
    expect(within(screen.getByRole('heading', { name: labels.history }).parentElement).getByRole('button', { name: de.ui.buttons.close })).toBeDisabled();
    await act(async () => pending.resolve({ id: 'foreign', payment_id: 'other-receipt' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.getByLabelText(labels.reason, { exact: false })).toHaveValue('Keep reviewed reason');
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(2));
    expect(mocks.post.mock.calls[1][1]).toEqual(mocks.post.mock.calls[0][1]);
  });

  it('invalidates a reversal confirmation when the receipt source path changes', async () => {
    mocks.get.mockResolvedValue(history([receipt()])); const pending = deferred(); mocks.confirm.mockReturnValue(pending.promise);
    const result = render(<PaymentHistoryPanel path="/invoices/invoice-1/payments" />);
    await screen.findByText('receipt-1'); fireEvent.click(screen.getByRole('button', { name: labels.reverse }));
    fireEvent.change(screen.getByLabelText(labels.reason, { exact: false }), { target: { value: 'Original selected invoice' } });
    fireEvent.submit(screen.getByRole('dialog').querySelector('form'));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    result.rerender(<PaymentHistoryPanel path="/invoices/invoice-2/payments" />);
    await act(async () => pending.resolve(true)); expect(mocks.post).not.toHaveBeenCalled();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
