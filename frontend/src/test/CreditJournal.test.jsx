import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import CreditJournal from '../components/CreditJournal';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), getAll: vi.fn(), post: vi.fn(), confirm: vi.fn(), role: 'buchhaltung', locale: 'de-DE' }));
vi.mock('../api', () => ({ api: mocks }));
vi.mock('../contexts/AuthContext', () => ({ useAuth: () => ({ user: { id: 'user', role: mocks.role } }) }));
vi.mock('../components/ConfirmDialog', () => ({ useConfirm: () => mocks.confirm }));
vi.mock('../i18n', () => ({ useTranslation: () => ({ locale: mocks.locale,
  t: (key, params = {}) => (key.split('.').reduce((value, part) => value?.[part], { 'de-DE': de, 'en-US': en, 'es-ES': es }[mocks.locale]) || key)
    .replace(/\{\{(\w+)\}\}/g, (match, name) => params[name] ?? match) }) }));

const labels = de.pages.statements.credits;
const summary = () => ({ contract_id: 'contract', remaining_amount: '100.00', reserved_amount: '40.00', available_amount: '60.00',
  sources: [{ id: 'source', root_statement_id: 'root', remaining_amount: '100.00', available_amount: '60.00', reserved_claims: [{ target_type: 'receivable', target_id: 'claim', amount: '40.00' }] }] });
const journal = () => ({ contract_id: 'contract', total: 0, receipts: [] });
const view = () => <CreditJournal contractId="contract" sourceId="source" onClose={vi.fn()} />;
const pending = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const openPayout = async () => {
  fireEvent.click(await screen.findByRole('button', { name: labels.payout }));
  const dialog = await screen.findByRole('dialog');
  fireEvent.change(within(dialog).getByLabelText(labels.amount, { exact: false }), { target: { value: '60.00' } });
  fireEvent.change(within(dialog).getByLabelText(labels.completedPayment, { exact: false }), { target: { value: 'confirmed' } });
  return dialog;
};
beforeEach(() => {
  mocks.role = 'buchhaltung'; mocks.locale = 'de-DE';
  mocks.get.mockReset().mockImplementation(async path => {
    if (path.includes('credit-choices/')) {
      const kind = path.includes('/booking?') ? 'booking' : path.includes('/rent_charge?') ? 'rent_charge' : 'receivable';
      return { contract_id: 'contract', items: kind === 'receivable' ? [
        { id: 'claim', kind, date: '2026-09-01', text: 'Synthetic claim', available_amount: '40.00' }] : [],
        selected: null, has_more: false, next_cursor: null };
    }
    return path.includes('credit-receipts?') ? journal() : summary();
  });
  mocks.getAll.mockReset().mockImplementation(async path => path === '/receivables' ? [{ id: 'claim', contract_id: 'contract', due_date: '2026-09-01', amount_due: 40, amount_paid: 0, status: 'open' }] : []);
  mocks.post.mockReset().mockImplementation(async (_, body) => ({ id: 'receipt', contract_id: 'contract', ...body }));
  mocks.confirm.mockReset().mockResolvedValue(true);
});

describe('credit receipt workflow', () => {
  it.each([['de-DE', de], ['en-US', en], ['es-ES', es]])('shows honest persisted balances and receipts in %s', async (locale, catalog) => {
    mocks.locale = locale; mocks.role = 'readonly';
    mocks.get.mockImplementation(async path => path.includes('credit-receipts?') ? { ...journal(), total: 1, receipts: [{ id: 'existing', transaction_date: '2026-09-02', method: 'cash', amount: '100.00', reversal: null }] } : summary());
    const { container } = render(view());
    await screen.findByText('existing');
    expect(container).toHaveTextContent(catalog.pages.statements.credits.payoutHint);
    expect(screen.queryByRole('button', { name: catalog.pages.statements.credits.payout })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: catalog.pages.statements.credits.offset })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: catalog.pages.statements.credits.reverse })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
    expect(container.textContent).not.toMatch(/pages\.statements\.credits\./);
  });

  it('keeps the edited draft and same idempotency reference after a server rejection', async () => {
    mocks.post.mockRejectedValueOnce(new Error('409: Bankbudget inzwischen verbraucht'));
    render(view());
    const dialog = await openPayout();
    fireEvent.click(within(dialog).getByRole('button', { name: labels.record }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Bankbudget inzwischen verbraucht');
    expect(within(dialog).getByLabelText(labels.amount, { exact: false })).toHaveValue('60.00');
    const first = mocks.post.mock.calls[0][1];
    fireEvent.click(within(dialog).getByRole('button', { name: labels.record }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocks.post.mock.calls[1][1].idempotency_key).toBe(first.idempotency_key);
    expect(first).toMatchObject({ source_settlement_id: 'source', amount: '60.00', method: 'cash', booking_id: null, confirmed_payment: true });
    expect(mocks.confirm).toHaveBeenCalledWith(labels.confirmPayout);
  });

  it('prevents duplicate submission and does not reopen a completed receipt after refresh failure', async () => {
    const request = pending(); mocks.post.mockReturnValue(request.promise);
    render(view());
    const dialog = await openPayout();
    fireEvent.submit(dialog.querySelector('form'));
    fireEvent.submit(dialog.querySelector('form'));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledTimes(1));
    screen.getAllByRole('button', { name: de.ui.buttons.close, exact: true }).forEach(button => expect(button).toBeDisabled());
    mocks.get.mockRejectedValue(new Error('Reload unavailable'));
    await act(async () => request.resolve({ id: 'completed', contract_id: 'contract', ...mocks.post.mock.calls[0][1] }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('Reload unavailable');
    expect(screen.getByRole('status')).toHaveTextContent('completed');
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('creates an offset using the actual chosen receivable and requires explicit confirmation', async () => {
    render(view());
    fireEvent.click(await screen.findByRole('button', { name: labels.offset }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(labels.amount, { exact: false }), { target: { value: '40' } });
    await within(dialog).findByRole('option', { name: /Synthetic claim/ });
    fireEvent.change(within(dialog).getByLabelText(labels.target, { exact: false, selector: 'select' }), { target: { value: 'receivable:claim' } });
    await waitFor(() => expect(within(dialog).getByRole('button', { name: labels.record })).toBeEnabled());
    const approval = pending();
    mocks.confirm.mockReturnValueOnce(approval.promise);
    fireEvent.click(within(dialog).getByRole('button', { name: labels.record }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    await act(async () => approval.resolve(false));
    await waitFor(() => expect(within(dialog).getByRole('button', { name: labels.record })).toBeEnabled());
    expect(mocks.post).not.toHaveBeenCalled();
    expect(within(dialog).getByLabelText(labels.amount, { exact: false })).toHaveValue('40');
    fireEvent.click(within(dialog).getByRole('button', { name: labels.record }));
    await waitFor(() => expect(mocks.post).toHaveBeenCalledWith('/billing/credit-offsets', expect.objectContaining({ amount: '40', target_type: 'receivable', target_id: 'claim' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(screen.getByRole('status')).toHaveTextContent('receipt');
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it('preserves a draft when translated field labels change', async () => {
    const page = render(view());
    await openPayout();
    mocks.locale = 'en-US'; page.rerender(view());
    expect(screen.getByLabelText(en.pages.statements.credits.amount, { exact: false })).toHaveValue('60.00');
    expect(screen.getByLabelText(en.pages.statements.credits.completedPayment, { exact: false, selector: 'select' })).toHaveValue('confirmed');
  });

  it('rechecks permissions after an asynchronous confirmation', async () => {
    const approval = pending(); mocks.confirm.mockReturnValue(approval.promise);
    const page = render(view());
    const dialog = await openPayout();
    fireEvent.click(within(dialog).getByRole('button', { name: labels.record }));
    await waitFor(() => expect(mocks.confirm).toHaveBeenCalled());
    mocks.role = 'readonly'; page.rerender(view());
    await act(async () => approval.resolve(true));
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('fails closed on malformed credit metadata', async () => {
    mocks.get.mockResolvedValue({ contract_id: 'other', sources: [] });
    render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(screen.queryByRole('button', { name: labels.payout })).not.toBeInTheDocument();
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it('uses bounded live choices and preserves the draft while loading later pages', async () => {
    const regular = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (path, options) => {
      if (!path.includes('credit-choices/')) return regular(path, options);
      const url = new URL(path, 'https://synthetic.invalid');
      const selected = url.searchParams.has('selected_id') ? { id: 'first', kind: 'receivable', date: '2026-09-01', text: 'First page claim', available_amount: '40.00' } : null;
      const later = url.searchParams.has('cursor');
      return { contract_id: 'contract', items: [later ? { id: 'later', kind: 'receivable', date: '2026-10-01', text: 'Later page claim', available_amount: '20.00' }
        : { id: 'first', kind: 'receivable', date: '2026-09-01', text: 'First page claim', available_amount: '40.00' }],
        selected, has_more: !later, next_cursor: later ? null : 'verified-cursor' };
    });
    render(view());
    fireEvent.click(await screen.findByRole('button', { name: labels.offset }));
    const dialog = await screen.findByRole('dialog');
    await within(dialog).findByRole('option', { name: /First page claim/ });
    fireEvent.change(within(dialog).getByLabelText(labels.amount, { exact: false }), { target: { value: '40' } });
    fireEvent.change(within(dialog).getByLabelText(labels.target, { exact: false, selector: 'select' }), { target: { value: 'receivable:first' } });
    const nextLabel = de.bookingPages.nextChoices.replace('{{label}}', labels.target);
    await waitFor(() => expect(within(dialog).getByRole('button', { name: nextLabel })).toBeEnabled());
    fireEvent.click(within(dialog).getByRole('button', { name: nextLabel }));
    await within(dialog).findByRole('option', { name: /Later page claim/ });
    expect(within(dialog).getByLabelText(labels.target, { exact: false, selector: 'select' })).toHaveValue('receivable:first');
    expect(within(dialog).getByLabelText(labels.amount, { exact: false })).toHaveValue('40');
    expect(mocks.get.mock.calls.some(([path]) => path.includes('page_size=25') && path.includes('cursor=verified-cursor'))).toBe(true);
    expect(mocks.getAll).not.toHaveBeenCalled();
  });

  it('loads bank choices only for bank payouts and fails closed on malformed choices', async () => {
    const regular = mocks.get.getMockImplementation();
    mocks.get.mockImplementation(async (path, options) => path.includes('credit-choices/') ? { contract_id: 'foreign', items: [] } : regular(path, options));
    render(view());
    const dialog = await openPayout();
    expect(mocks.get.mock.calls.some(([path]) => path.includes('credit-choices/'))).toBe(false);
    fireEvent.change(within(dialog).getByLabelText(labels.method, { exact: false, selector: 'select' }), { target: { value: 'bank' } });
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(labels.invalidResponse);
    expect(within(dialog).getByRole('button', { name: labels.record })).toBeDisabled();
    expect(mocks.getAll).not.toHaveBeenCalled();
    expect(mocks.post).not.toHaveBeenCalled();
  });
});
