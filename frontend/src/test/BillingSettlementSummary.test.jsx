import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { I18nProvider } from '../i18n';
import BillingSettlementSummary from '../components/BillingSettlementSummary';
import { emptySummary, mixedSummary } from './fixtures/settlements';
import de from '../../../i18n/de-DE.json';
import en from '../../../i18n/en-US.json';
import es from '../../../i18n/es-ES.json';

const mocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock('../api', () => ({ api: mocks }));
const catalogs = { 'de-DE': de, 'en-US': en, 'es-ES': es };
const period = { id: 'period', status: 'finalized', revision_number: 2,
  source_period_id: 'source-period', revision_notes: 'Corrected cleaning cost' };
const view = (selected = period, refreshKey = 0) => <I18nProvider>
  <BillingSettlementSummary period={selected} refreshKey={refreshKey}
    contracts={{ 'contract-debt': { contract_number: 'MV-1' } }} />
</I18nProvider>;
const pending = () => {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
};
beforeEach(() => {
  localStorage.clear();
  mocks.get.mockReset().mockResolvedValue(mixedSummary());
  mocks.post.mockReset();
  vi.stubGlobal('fetch', vi.fn(async url => ({ ok: true,
    json: async () => catalogs[String(url).split('/').at(-1)] || {} })));
});

describe.each(Object.entries(catalogs))('settlement summary in %s', (locale, messages) => {
  it('shows available credit, separate totals and statuses without claiming a payout', async () => {
    localStorage.setItem('locale', locale);
    const labels = messages.pages.statements.settlements;
    const { container } = render(view());
    await screen.findByText(labels.notPaidOut);
    const region = screen.getByRole('region', { name: labels.title });
    const currency = value => new Intl.NumberFormat(locale, { style: 'currency', currency: 'EUR' }).format(value);
    for (const [label, amount] of [[labels.debts, 360], [labels.credits, 75], [labels.net, 285]]) {
      expect(within(region).getByText(label).parentElement).toHaveTextContent(currency(amount).replace(/\u00a0/g, ' '));
    }
    for (const label of Object.values(labels.status)) expect(within(region).getByText(label)).toBeInTheDocument();
    expect(region).toHaveTextContent(labels.deltaHelp);
    expect(region).toHaveTextContent('MV-1');
    expect(region).toHaveTextContent('Corrected cleaning cost');
    expect(region).toHaveTextContent('source-period');
    expect(container.textContent).not.toMatch(/pages\.statements\./);
    expect(mocks.post).not.toHaveBeenCalled();
  });
});

describe('settlement read reliability', () => {
  it('shows errors instead of zero totals and retries only the GET', async () => {
    mocks.get.mockRejectedValueOnce(new Error('Settlement service unavailable'));
    const { container } = render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent('Settlement service unavailable');
    expect(container.querySelector('.stats-grid')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: de.ui.buttons.retry }));
    await screen.findByText(de.pages.statements.settlements.notPaidOut);
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(mocks.get).toHaveBeenLastCalledWith('/billing/periods/period/settlements', expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(mocks.post).not.toHaveBeenCalled();
  });
  it.each([null, {}, { ...emptySummary(), net_amount: 10 }, { ...mixedSummary(), period_id: 'other' }])('rejects malformed responses (%#)', async body => {
    mocks.get.mockResolvedValue(body);
    const { container } = render(view());
    expect(await screen.findByRole('alert')).toHaveTextContent(de.pages.statements.settlements.invalidResponse);
    expect(container.querySelector('.stats-grid')).toBeNull();
  });
  it('distinguishes a real empty ledger from a failed read', async () => {
    mocks.get.mockResolvedValue(emptySummary());
    render(view());
    await screen.findByText(de.pages.statements.settlements.empty);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('does not apply a late result to a different period', async () => {
    const first = pending(), second = pending();
    mocks.get.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const page = render(view());
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    page.rerender(view({ ...period, id: 'second' }));
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(2));
    expect(mocks.get.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => first.resolve(mixedSummary()));
    expect(screen.queryByText('MV-1')).not.toBeInTheDocument();
    await act(async () => second.resolve(emptySummary('second')));
    await screen.findByText(de.pages.statements.settlements.empty);
  });
  it('refreshes persisted totals when a posting attempt completes', async () => {
    mocks.get.mockResolvedValueOnce(emptySummary()).mockResolvedValueOnce(mixedSummary());
    const page = render(view());
    await screen.findByText(de.pages.statements.settlements.empty);
    page.rerender(view(period, 1));
    await screen.findByText('MV-1');
    expect(mocks.get).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(de.pages.statements.settlements.empty)).not.toBeInTheDocument();
  });
  it('aborts on unmount and ignores the eventual response', async () => {
    const deferred = pending();
    mocks.get.mockReturnValue(deferred.promise);
    const page = render(view());
    await waitFor(() => expect(mocks.get).toHaveBeenCalledTimes(1));
    const signal = mocks.get.mock.calls[0][1].signal;
    page.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => deferred.resolve(mixedSummary()));
  });
});

it('labels legacy credit references as historical evidence with no payment action', async () => {
  const summary = mixedSummary();
  summary.settlements[1].receivable_id = 'legacy-credit-evidence';
  mocks.get.mockResolvedValue(summary);
  render(view());
  const reference = await screen.findByText('Historische Belegreferenz: legacy-credit-evidence');
  const row = reference.closest('tr');
  expect(row).toHaveTextContent(de.pages.statements.settlements.status.credit_available);
  expect(within(row).getByRole('button', { name: de.pages.statements.credits.title })).toBeInTheDocument();
  expect(within(row).queryByRole('link')).not.toBeInTheDocument();
  expect(screen.getByText(de.pages.statements.settlements.credits).parentElement).toHaveTextContent('75,00');
  expect(mocks.post).not.toHaveBeenCalled();
});
